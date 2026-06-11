import io
import os
import httpx
from urllib.parse import urlparse
from typing import Optional

# Ensure you are using the new Google GenAI SDK
from google import genai
from google.genai import types

# ---------------------------------------------------------------------
# Browser-like HTTP Fetcher
# Verified for httpx==0.28.1
# ---------------------------------------------------------------------


def fetch_with_browser_fingerprint(url: str, proxy: Optional[str] = None) -> httpx.Response:
    """
    Fetches a URL using browser headers to avoid 403 blocks.
    Compatible with httpx 0.28.1+ (uses 'proxies' in Client init).
    """

    # --- Browser Fingerprint Configuration ---

    headers_chrome = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not A(Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "DNT": "1"
    }

    headers_win = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": headers_chrome["Accept"],
        "Accept-Language": headers_chrome["Accept-Language"],
        "Referer": headers_chrome["Referer"],
        "Sec-Ch-Ua": '"Chromium";v="120", "Google Chrome";v="120", "Not A Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Ch-Ua-Mobile": "?0",
    }

    # --- Client Configuration , more at https://www.python-httpx.org/api/#client
    client_kwargs = {
        "follow_redirects": True,
        "timeout": 20.0
    }
    if proxy:
        client_kwargs['proxy'] = proxy

    # Attempt 1: Chrome on Mac
    try:
        with httpx.Client(**client_kwargs) as client:
            resp = client.get(url, headers=headers_chrome)
            resp.raise_for_status()
            return resp
    except Exception as e:
        print(
            f"⚠️ Fingerprint 1 failed for '{url}' ({type(e).__name__}). Retrying...")

    # Attempt 2: Chrome on Windows
    try:
        with httpx.Client(**client_kwargs) as client:
            resp = client.get(url, headers=headers_win)
            resp.raise_for_status()
            return resp
    except Exception as e:
        print(f"❌ All fingerprints failed for '{url}': {e}")
        raise

# ---------------------------------------------------------------------
# Manager (Download -> Upload -> Cache)
# ---------------------------------------------------------------------

class ContextCacheManager:
    """Handles downloading content, uploading to Gemini, and creating context cache."""

    def __init__(self, client: genai.Client, config, storage):
        self.client = client
        self.config = config
        self.storage = storage

    def _get_mime_type(self, url, content_type_header=None):
        if content_type_header:
            # Handle headers that include charset (e.g., "text/html; charset=utf-8")
            ct = content_type_header.split(';')[0].strip().lower()
            if ct in ['text/html', 'text/plain', 'application/pdf', 'text/md', 'text/csv']:
                return ct

        parsed = urlparse(url)
        path = parsed.path.lower()
        if path.endswith(('.html', '.htm')):
            return 'text/html'
        if path.endswith('.md'):
            return 'text/md'
        if path.endswith('.txt'):
            return 'text/plain'
        if path.endswith('.csv'):
            return 'text/csv'
        return 'application/pdf'  # Default fallback

    def get_or_create_cache(self, url: str) -> types.CachedContent | None:
        # Check existing cache
        entry = self.storage.get_entry(url)
        if entry:
            try:
                # Optional: Verify cache still exists in Gemini before returning
                # self.client.caches.get(name=entry["cache_name"])
                return types.CachedContent(name=entry["cache_name"])
            except Exception:
                print("⚠️ Cached content not found in Gemini, recreating...")

        print(f"⬇️ [Download] Fetching: {url}")

        # 1. Download
        try:
            response = fetch_with_browser_fingerprint(
                url,
                proxy=self.config.PROXY
            )
        except Exception as e:
            print(f"❌ Error downloading {url}: {e}")
            return None

        # 2. Determine MIME and Prepare File
        mime_type = self._get_mime_type(
            url, response.headers.get("content-type"))
        print(f"   Detected MIME: {mime_type}")

        doc_io = io.BytesIO(response.content)

        # 3. Upload to Gemini
        try:
            # Explicitly using types.UploadFileConfig ensures compatibility with newer SDKs
            upload_config = types.UploadFileConfig(
                mime_type=mime_type,
                display_name=url.split('/')[-1][:40] or "downloaded_content"
            )

            document = self.client.files.upload(
                file=doc_io,
                config=upload_config
            )
        except Exception as e:
            print(f"❌ Error uploading file to Gemini: {e}")
            return None

        # 4. Create Cache
        print(f"   Creating Cache (Model: {self.config.LLM_MODEL_NAME})...")

        system_instruction = (
            "You are a helpful research assistant.\n"
            f"SOURCE_METADATA: This content is loaded from: {url}\n"
            "INSTRUCTIONS: Use the provided content to answer questions. "
            "If the answer is found, quote the relevant section."
        )

        try:
            cache_config = types.CreateCachedContentConfig(
                system_instruction=system_instruction,
                contents=[document],
                ttl=f"{self.config.CACHE_TTL_SECONDS}s"
            )

            cache = self.client.caches.create(
                model=self.config.LLM_MODEL_NAME,
                config=cache_config
            )
        except Exception as e:
            print(f"❌ Error creating Gemini cache: {e}")
            return None

        # 5. Save and Return
        self.storage.save_new_entry(url, cache.name)
        return types.CachedContent(name=cache.name)
