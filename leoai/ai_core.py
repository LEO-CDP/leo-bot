import os

from functools import lru_cache
import logging
from dotenv import load_dotenv
# Imports from the Google AI SDK
from google import genai
from google.genai import types
from google.genai.types import GenerationConfig, Schema
from google.api_core.exceptions import GoogleAPIError
import json
from typing import Dict, Any
import torch
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer

from leoai.ai_data_schema import WEATHER_FORECAST_SCHEMA, GEOLOCATION_SCHEMA
from leoai.domain.report_utils import generate_pie_chart
from leoai.domain.weather_utils import build_weather_prompt, enrich_weather_forecast

# Load environment variables from .env file
load_dotenv(override=True)

# Configure logging
logger = logging.getLogger(__name__)

# Default fallback values
DEFAULT_MODEL_ID = os.getenv("GEMINI_TEXT_MODEL_ID", "gemini-2.5-flash-lite")
DEFAULT_EMBEDDING_MODEL_ID = os.getenv(
    "DEFAULT_EMBEDDING_MODEL_ID", "intfloat/multilingual-e5-base")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Error message used when required config is missing
INIT_FAIL_MSG = "Both `model_name` and `api_key` must be provided or set in the environment."
JSON_TYPE = "application/json"

# --- Device Configuration ---
device = "cpu"
if torch.cuda.is_available():
    device = "cuda"
elif torch.backends.mps.is_available():
    device = "mps"

# default embedding_model


@lru_cache(maxsize=1)
def get_embedding_model():
    """Lazy-Loading SentenceTransformer model once."""
    logger.info(
        f"Loading SentenceTransformer model '{DEFAULT_EMBEDDING_MODEL_ID}' on device: {device}...")
    embedding_model = SentenceTransformer(
        DEFAULT_EMBEDDING_MODEL_ID, device=device)
    return embedding_model


@lru_cache(maxsize=1)
def get_tokenizer():
    """Lazy-Loading AutoTokenizer model once."""
    tokenizer = AutoTokenizer.from_pretrained(DEFAULT_EMBEDDING_MODEL_ID)
    return tokenizer


# the helper function for default embedding_model
def get_embed_texts(texts):
    """
    Embed a list of texts using the SentenceTransformer model.

    Args:
        texts (list[str]): List of text strings to embed.

    Returns:
        list[list[float]]: List of vector embeddings.
    """
    if not texts:
        logger.warning("embed_texts called with empty input list.")
        return []

    try:
        model = get_embedding_model()
        # Ensure input is a list of strings
        if isinstance(texts, str):
            texts = [texts]

        # Normalize whitespace and remove empty entries
        texts = [t.strip() for t in texts if t and t.strip()]
        if not texts:
            logger.warning("All input texts were empty or whitespace.")
            return []

        logger.info(f"Embedding {len(texts)} texts on device: {model.device}")
        embeddings = model.encode(
            texts,
            batch_size=16,
            show_progress_bar=False,
            normalize_embeddings=True,  # ensures cosine similarity compatibility
            convert_to_numpy=True
        )
        return embeddings.tolist()

    except Exception as e:
        logger.exception(f"Failed to embed texts: {e}")
        return []


# check and init Google AI
def is_gemini_model_ready():
    isReady = isinstance(GEMINI_API_KEY, str)
    if isReady:
        return True
    else:
        return False


class GeminiClient:
    """
    A wrapper class for interacting with Google Gemini API.
    Handles text generation via a specified model.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL_ID, api_key: str = GEMINI_API_KEY):
        if not model_name or not api_key:
            logger.critical(INIT_FAIL_MSG)
            raise ValueError(INIT_FAIL_MSG)

        self.model_name = model_name
        self.api_key = api_key

        try:
            self.client = genai.Client(api_key=self.api_key)
            logger.info(
                f"Gemini client initialized with model '{self.model_name}'")
        except Exception as e:
            logger.exception("Failed to initialize Gemini client.")
            raise

    # text to text
    def generate_content(self, prompt: str, temperature: float = 0.6, on_error: str = '') -> str:
        """
        Generates text content from a given prompt using the Gemini API.

        Args:
            prompt (str): The input prompt to send to the model.
            temperature (float): Sampling temperature for creativity.
            on_error (str): Fallback string if generation fails.

        Returns:
            str: Generated content or fallback string.
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature
                ),
            )
            if response.candidates and response.candidates[0].content.parts:
                text = response.candidates[0].content.parts[0].text.strip()
                return text
            else:
                logger.warning("Empty response received from Gemini API.")
                return on_error

        except GoogleAPIError as e:
            logger.error(f"Google API error during content generation: {e}")
            return on_error
        except Exception as e:
            logger.exception("Unexpected error during content generation.")
            return on_error

    # text to JSON
    def generate_json(self, prompt: str, json_schema: Schema) -> Dict[str, Any]:
        """
        Generates a structured JSON object from a prompt based on a provided schema.

        Args:
            prompt: The input prompt for the model.
            json_schema: The google.generativeai.types.Schema defining the desired JSON output.

        Returns:
            A dictionary parsed from the model's JSON response, or an empty dict on error.
        """
        try:
            # Configure the model for JSON output mode with the specified schema

            generation_config = GenerationConfig(
                response_mime_type=JSON_TYPE,
                response_schema=json_schema
            )

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=generation_config,
            )

            response_text = response.text.strip()
            return json.loads(response_text)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from model response: {e}")
            logger.debug(
                f"Raw model response: {response.text if 'response' in locals() else 'N/A'}")
            return {}
        except GoogleAPIError as e:
            logger.error(f"A Google API error occurred: {e}")
            return {}
        except Exception as e:
            logger.exception(
                f"An unexpected error occurred in generate_json: {e}")
            return {}

    def generate_geolocation_from_image(
        self,
        text_prompt: str,
        image_bytes: bytes,
        json_schema: Schema = None,
        temperature: float = 0.25,
        on_error: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Generate structured geolocation JSON using text + image input.

        Args:
            text_prompt (str): Natural language prompt describing what to extract.
            image_bytes (bytes): Raw image file content.
            json_schema (Schema): Output schema (GEOLOCATION_SCHEMA schema).
            temperature (float): Model creativity level.
            on_error (dict): Fallback dict if generation fails.

        Returns:
            dict: Parsed JSON adhering to GEOLOCATION_SCHEMA schema.
        """
        # Nếu on_error là None, khởi tạo nó là một dictionary rỗng
        if on_error is None:
            on_error = {}

        # Kiểm tra và sử dụng schema mặc định nếu chưa được cung cấp
        if json_schema is None:
            # Giả định GEOLOCATION_SCHEMA đã được import và là một object Schema hợp lệ
            json_schema = GEOLOCATION_SCHEMA
            logger.debug("Using default GEOLOCATION_SCHEMA.")

        try:
            # 1. Tạo Part cho hình ảnh
            image_part = types.Part.from_bytes(
                data=image_bytes,
                # Cố gắng suy luận MIME type, nhưng giữ mặc định nếu không có thông tin tốt hơn
                mime_type="image/jpeg"
            )

            # 2. Cấu hình GenerationConfig cho đầu ra JSON có cấu trúc
            generation_config = types.GenerateContentConfig(
                temperature=temperature,
                # Chỉ định đầu ra là JSON
                response_mime_type=JSON_TYPE,
                # Chỉ định Schema cho JSON
                response_schema=json_schema,
            )

            # 3. Multimodal: text + image
            # Contents là list chứa các phần: [image_part, text_prompt]
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[image_part, text_prompt],
                config=generation_config,
            )

            # 4. Xử lý phản hồi
            response_text = response.text.strip()

            # Kiểm tra xem có phản hồi không
            if not response_text:
                logger.warning(
                    "Empty response received from Gemini API in JSON mode.")
                return on_error

            return json.loads(response_text)

        except GoogleAPIError as e:
            logger.error(f"Google API error in generate_weather_forecast: {e}")
            return on_error

        except json.JSONDecodeError as e:
            logger.error(
                f"JSON decode failed. Model response was not valid JSON: {e}")
            logger.debug(
                f"Raw model response: {response.text if 'response' in locals() else 'N/A'}")
            return on_error

        except Exception as e:
            logger.exception(
                f"Unexpected error in generate_weather_forecast: {e}")
            return on_error

    def generate_weather_info_from_text(
        self,
        raw_weather_text: str,
        json_schema: Schema = None,
        temperature: float = 0.2,
        limit_days: int = 0,
        on_error: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Convert raw Windy.com scraped text into structured JSON weather info.

        Args:
            raw_weather_text (str): The extracted innerText from Windy (file.txt).
            model (GeminiClient): Optional injected Gemini client. Auto-created if None.
            json_schema (Schema): Output schema for structured weather forecasting.
            temperature (float): Model creativity level.
            on_error (dict): Fallback dictionary.

        Returns:
            dict: Weather forecast JSON following WEATHER_FORECAST_SCHEMA.
        """
        if on_error is None:
            on_error = {}

        # Use default weather schema if not provided
        if json_schema is None:
            json_schema = WEATHER_FORECAST_SCHEMA

        # Clean & normalize the raw text
        if not isinstance(raw_weather_text, str) or not raw_weather_text.strip():
            logger.warning(
                "generate_weather_info_from_text received empty input text.")
            return on_error

        cleaned_text = raw_weather_text.strip()

        # Prompt for the LLM
        prompt = build_weather_prompt(json_schema, cleaned_text, limit_days)
        try:
            # Use Gemini JSON mode

            generation_config = types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type=JSON_TYPE,
                response_schema=json_schema,
            )

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=generation_config,
            )

            text = response.text.strip()
            if not text:
                logger.error(
                    "Empty JSON response in generate_weather_info_from_text.")
                return on_error

            weather_info = enrich_weather_forecast(text)
            return weather_info

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode failed from model response: {e}")
            logger.debug(
                f"Raw response: {response.text if 'response' in locals() else 'N/A'}")
            return on_error

        except GoogleAPIError as e:
            logger.error(f"Google API error: {e}")
            return on_error

        except Exception as e:
            logger.exception(
                f"Unexpected error in generate_weather_info_from_text: {e}")
            return on_error

    def get_embedding(self, text: str) -> list[float]:
        """ get embedding of text

        Args:
            text (str): input text

        Returns:
            list[float]: embedding of text
        """
        model = get_embedding_model()
        embeddings = model.encode(
            text,
            batch_size=16,
            show_progress_bar=False,
            normalize_embeddings=True,  # ensures cosine similarity compatibility
            convert_to_numpy=True
        )
        return embeddings.tolist()

    def generate_report(self, prompt: str, temperature: float = 0.6, on_error: str = '') -> str:
        return generate_pie_chart()
