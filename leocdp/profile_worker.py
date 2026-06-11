import asyncio
import json
import redis.asyncio as redis
import structlog

from leocdp.cdp_client import CDPClient
from leocdp.profile_queue import LEOCDP_PROFILE_QUEUE_NAME
from main_config import REDIS_HOST, REDIS_PORT

logger = structlog.get_logger(__name__)

REDIS_URL = f"redis://{REDIS_HOST}:{int(REDIS_PORT)}"


class ProfileJobWorker:
    """
    Worker that listens for profile jobs from Redis and processes them
    using CDPClient. Fully testable due to dependency injection.
    """

    def __init__(
        self,
        redis_url: str = REDIS_URL,
        queue_name: str = LEOCDP_PROFILE_QUEUE_NAME,
        client: CDPClient = None,
        brpop_timeout: int = 2
    ):
        logger.info("worker.init", object="ProfileJobWorker", redis_url=redis_url)

        self.redis_url = redis_url
        self.redis = redis.from_url(redis_url)

        self.queue_name = queue_name
        self.client = client or CDPClient()
        self.brpop_timeout = brpop_timeout

        self._shutdown = False

    async def shutdown(self):
        """Stop loop and close Redis connection."""
        self._shutdown = True
        await self.redis.aclose()
        logger.info("worker.shutdown")

    async def process_job(self, payload_raw: bytes):
        """Process one job. Testable in isolation."""
        job = json.loads(payload_raw)
        logger.info("worker.job_received", job=job)

        try:
            result = await self.client.save_profile(job)
            logger.info("worker.job_success", result=result)
            return result

        except Exception as ex:
            logger.error("worker.job_failed", error=str(ex), job=job)
            raise

    async def run_once(self):
        """Run one iteration (used in tests)."""
        try:
            msg = await self.redis.brpop(self.queue_name, timeout=self.brpop_timeout)
            if msg is None:
                return None

            _, payload_raw = msg
            return await self.process_job(payload_raw)

        except Exception as e:
            logger.error("worker.redis_error", error=str(e))
            await asyncio.sleep(0.2)
            return None

    async def run(self):
        """Infinite production loop."""
        logger.info("worker.start", queue=self.queue_name)

        while not self._shutdown:
            await self.run_once()
            await asyncio.sleep(0.01)
