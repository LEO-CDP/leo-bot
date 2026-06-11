import aiohttp
import json
import os

from tenacity import retry, stop_after_attempt, wait_exponential
import structlog
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

LEOCDP_HOST = os.getenv("LEOCDP_HOST")
LEOCDP_TOKEN_KEY = os.getenv("LEOCDP_TOKEN_KEY")
LEOCDP_TOKEN_VALUE = os.getenv("LEOCDP_TOKEN_VALUE")


logger = structlog.get_logger(__name__)


class CDPClient:
    def __init__(self):
        self.host = LEOCDP_HOST
        self.tokenkey = LEOCDP_TOKEN_KEY
        self.tokenvalue = LEOCDP_TOKEN_VALUE

        self.headers = {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "tokenkey": self.tokenkey,
            "tokenvalue": self.tokenvalue,
        }

        self.base_url = f"https://{self.host}"

    @retry(
        stop=stop_after_attempt(5),         # Retry tối đa 5 lần
        wait=wait_exponential(multiplier=1, min=1, max=20),  # Backoff tăng dần 1 → 20s
        reraise=True
    )
    async def save_profile(self, profile_data: dict):
        uri = "/api/profile/save"
        url = self.base_url + uri

        logger.info("cdp.request", url=url, payload=profile_data)

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=profile_data, headers=self.headers) as response:
                resp_text = await response.text()

                if response.status >= 500:
                    logger.warning(
                        "cdp.server_error",
                        http_status=response.status,
                        response=resp_text
                    )
                    raise Exception("Server error → Retry with backoff")

                try:
                    data = json.loads(resp_text)
                    logger.info("cdp.success", response=data)
                    return data
                except json.JSONDecodeError:
                    logger.error("cdp.invalid_json", raw=resp_text)
                    return {"raw": resp_text}
