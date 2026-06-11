import json
import time
import os

from cache_manager import ContextCacheManager
from google import genai
from google.genai import types


# ---------------------------------------------------------------------
# Cấu Hình và Hằng Số
# ---------------------------------------------------------------------

class AppConfig:
    """Quản lý các hằng số cấu hình của ứng dụng."""
    
    # Model sử dụng
    LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gemini-2.5-flash-lite")

    # Persona of Agent
    AGENT_PERSONA = os.getenv("AGENT_PERSONA", "You are a Document Analyst")

    # Language
    TARGET_LANGUAGE = os.getenv("TARGET_LANGUAGE","Vietnamese")
    
    # Tệp cache tạm thời (sử dụng /tmp cho Cloud Run/Functions)
    CACHE_FILE_PATH = os.getenv("CACHE_FILE_PATH", "/tmp/url_cache_map.json")
    
    # Thời gian tồn tại của cache (10 phút)
    CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "600"))
    
    # Tiêu đề HTTP giả lập trình duyệt
    HTTP_HEADERS = {
        "User-Agent": os.getenv(
            "HTTP_HEADERS_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": os.getenv(
            "HTTP_HEADERS_ACCEPT",
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": os.getenv(
            "HTTP_HEADERS_ACCEPT_LANGUAGE",
            "en-US,en;q=0.5"
        )
    }
    
    # Proxy (optional)
    PROXY = os.getenv("HTTP_PROXY", None)


# ---------------------------------------------------------------------
# Quản lý API Key & Client (Lớp Tiện Ích)
# ---------------------------------------------------------------------

def get_gemini_client():
    """Lấy API Key từ biến môi trường (hoặc Colab userdata) và khởi tạo Client."""
    api_key = os.environ.get("GOOGLE_GEMINI_API_KEY")

    if not api_key:
        try:
            from google.colab import userdata
            api_key = userdata.get("GOOGLE_GEMINI_API_KEY")
        except ImportError:
            pass

    if not api_key:
        raise ValueError("GOOGLE_GEMINI_API_KEY environment variable is not set.")
    
    return genai.Client(api_key=api_key)

# ---------------------------------------------------------------------
# Quản lý Cache (JSON Metadata)
# ---------------------------------------------------------------------

class CacheStorage:
    """Quản lý việc đọc/ghi metadata cache vào tệp JSON."""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.cache_file = config.CACHE_FILE_PATH
        self.url_cache_map = self._load_cache_file()
        
    def _load_cache_file(self):
        if not os.path.exists(self.cache_file):
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading cache file {self.cache_file}: {e}")
            return {}

    def _save_cache_file(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.url_cache_map, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Failed saving cache file {self.cache_file}: {e}")

    def get_entry(self, url: str) -> dict | None:
        if url in self.url_cache_map:
            entry = self.url_cache_map[url]
            if time.time() < entry.get("expire_at", 0):
                return entry
            else:
                print(f"🗑️ [Expired] Cache expired for: {url}")
                self.url_cache_map.pop(url, None)
                self._save_cache_file()
        return None

    def save_new_entry(self, url: str, cache_name: str):
        self.url_cache_map[url] = {
            "cache_name": cache_name,
            "expire_at": time.time() + self.config.CACHE_TTL_SECONDS
        }
        self._save_cache_file()


# ---------------------------------------------------------------------
# Agent Chính
# ---------------------------------------------------------------------

class MultiSourceAgent:
    def __init__(self, client: genai.Client, config: AppConfig, cache_manager: ContextCacheManager):
        self.client = client
        self.config = config
        self.manager = cache_manager

    def ask(self, urls: list[str], question: str) -> str:
        findings = []

        print(f"\n🕵️‍♂️ AGENT: Analyzing {len(urls)} sources for: '{question}'...")

        for url in urls:
            cache_ref = self.manager.get_or_create_cache(url)
            if not cache_ref:
                continue

            # -----------------------------------------------------
            # 1. Map Phase – Query Cache
            #    Enhanced Prompt: thêm metadata để giảm skip sai
            # -----------------------------------------------------
            map_prompt = (
                f"You are analyzing a document from: {url}\n"
                f"Your task is to answer the question ONLY using the cached content.\n"
                f"If the answer does not exist in the cached content, return EXACTLY 'NO_RELEVANT_INFO'.\n\n"
                f"Question: {question}"
            )

            try:
                response = self.client.models.generate_content(
                    model=self.config.LLM_MODEL_NAME,
                    contents=map_prompt,
                    config=types.GenerateContentConfig(cached_content=cache_ref.name)
                )
                res_text = response.text.strip()

            except Exception as e:
                 print(f"   ⚠️ Error querying cache for {url}: {e}")
                 continue

            # -----------------------------------------------------
            # 2. Smart Skip Handling
            # -----------------------------------------------------

            def is_suspicious(txt: str) -> bool:
                """Heuristic: model trả lời quá ngắn hoặc mơ hồ."""
                if len(txt) < 20:
                    return True
                if "I cannot" in txt or "no information" in txt.lower():
                    return True
                return False

            if "NO_RELEVANT_INFO" in res_text or is_suspicious(res_text):
                # -----------------------------------------------------
                # 3. Retry logic (Relaxed Mode)
                # -----------------------------------------------------
                print(f"   (Retrying relaxed mode for {url})")

                relaxed_prompt = (
                    f"You are checking if ANY part of the document from: {url} "
                    f"contains information related to: '{question}'.\n"
                    f"If related information exists, extract it. "
                    f"If not, return EXACTLY 'NO_RELEVANT_INFO'."
                )

                try:
                    retry_resp = self.client.models.generate_content(
                        model=self.config.LLM_MODEL_NAME,
                        contents=relaxed_prompt,
                        config=types.GenerateContentConfig(cached_content=cache_ref.name)
                    )
                    retry_text = retry_resp.text.strip()

                    if "NO_RELEVANT_INFO" not in retry_text:
                        print(f"   ✓ Relaxed mode found relevant info for {url}")
                        findings.append(f"--- SOURCE: {url} ---\n{retry_text}\n")
                        continue
                    else:
                        print(f"   (Skipping {url} - No info found even after retry)")
                        continue

                except Exception as e:
                    print(f"   ⚠️ Retry error querying cache for {url}: {e}")
                    continue

            # -----------------------------------------------------
            # 4. Append valid result from first attempt
            # -----------------------------------------------------
            findings.append(f"--- SOURCE: {url} ---\n{res_text}\n")

        # -----------------------------------------------------
        # 5. If no data at all → return fallback
        # -----------------------------------------------------
        if not findings:
            return "❌ No information found in any of the provided documents regarding your question."

        print(f"\n🧠 AGENT: Synthesizing answer from {len(findings)} relevant sources...")

        synthesis_prompt = (
            f"{self.config.AGENT_PERSONA}. Please answer in {self.config.TARGET_LANGUAGE}\n"
            "CONTEXT: The user asked a question, and below are extracts from multiple different documents.\n"
            f"USER QUESTION: '{question}'\n\n"
            "EXTRACTED DATA:\n" + "\n".join(findings) + "\n\n"
            "INSTRUCTIONS:\n"
            "1. Combine the information to provide a comprehensive answer.\n"
            "2. Cite the specific Source URL for each key point.\n"
            "3. If sources conflict, mention the conflict."
        )

        final_response = self.client.models.generate_content(
            model=self.config.LLM_MODEL_NAME,
            contents=synthesis_prompt
        )

        return final_response.text
