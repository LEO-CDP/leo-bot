import json
import logging
import os
import io
from typing import Tuple, Optional, Dict
from PIL import Image
from leoai.ai_core import GeminiClient

from main_config import setup_logging

setup_logging()

# Configure logging
logger = logging.getLogger(__name__)


def read_file_to_text(file_path: str) -> str:
    """
    Read a text file and return its content as a clean UTF-8 string.
    Designed for loading Windy scraped output (file.txt).

    Args:
        file_path (str): Path to the input text file.

    Returns:
        str: Clean text content, or empty string on error.
    """
    if not file_path or not isinstance(file_path, str):
        logger.error("read_file_to_text received invalid file path.")
        return ""

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Normalize common scraping artifacts
        cleaned = content.replace("\ufeff", "").strip()

        if not cleaned:
            logger.warning(
                f"read_file_to_text loaded an empty file: {file_path}")

        return cleaned

    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return ""

    except UnicodeDecodeError:
        logger.warning(
            f"UTF-8 decoding failed, retrying with latin-1: {file_path}")
        try:
            with open(file_path, "r", encoding="latin-1") as f:
                return f.read().strip()
        except Exception as e:
            logger.error(f"read_file_to_text fallback decoding failed: {e}")
            return ""

    except Exception as e:
        logger.exception(f"Unexpected error in read_file_to_text: {e}")
        return ""


def prepare_image_bytes(input_file_path: str) -> Tuple[bytes, Dict]:
    """
    Load an image, convert to optimized JPEG bytes if needed.
    Returns:
        img_bytes (bytes): compressed/converted image binary
        metadata (dict): file info for testing
    """

    if not os.path.exists(input_file_path):
        raise FileNotFoundError(f"File not found: {input_file_path}")

    file_extension = os.path.splitext(input_file_path)[1].lower()
    metadata = {"extension": file_extension}

    # Case 1: JPEG → load raw bytes
    if file_extension in (".jpg", ".jpeg"):
        with open(input_file_path, "rb") as f:
            img_bytes = f.read()

        metadata["original_size_kb"] = os.path.getsize(input_file_path) / 1024
        metadata["converted"] = False
        return img_bytes, metadata

    # Case 2: Non-JPEG → convert to optimized JPEG
    img = Image.open(input_file_path)

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=95, optimize=True)
    img_bytes = buffer.getvalue()

    metadata["original_size_kb"] = os.path.getsize(input_file_path) / 1024
    metadata["converted"] = True
    metadata["converted_size_kb"] = len(img_bytes) / 1024

    return img_bytes, metadata


def extract_geolocation_from_image(
    input_file_path: str,
    prompt: str,
    client: Optional[GeminiClient] = None
) -> Dict:
    """
    High-level function that:
    1) Prepares image bytes
    2) Sends bytes to Gemini
    3) Returns structured JSON
    """

    if client is None:
        client = GeminiClient()

    img_bytes, meta = prepare_image_bytes(input_file_path)

    result = client.generate_geolocation_from_image(
        text_prompt=prompt,
        image_bytes=img_bytes,
    )

    if not result:
        raise RuntimeError("Gemini returned empty result")

    return {
        "metadata": meta,
        "result": result,
    }


def extract_weather_info_from_text(input_file_path: str, limit_days: int, client: Optional[GeminiClient] = None) -> Dict:
    """
    High-level function that:
    1) Prepares raw data from file or database
    2) Sends raw data to Gemini
    3) Returns structured JSON
    """

    if client is None:
        client = GeminiClient(model_name="gemini-2.5-flash-lite")

    raw_text = read_file_to_text(input_file_path)

    result = client.generate_weather_info_from_text(
        raw_weather_text=raw_text, temperature=0.1, limit_days=limit_days
    )

    if not result:
        raise RuntimeError("Gemini returned empty result")

    return result
