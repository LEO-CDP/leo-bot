import json
import redis.asyncio as redis
import structlog
from main_config import REDIS_HOST, REDIS_PORT

logger = structlog.get_logger(__name__)

LEOCDP_PROFILE_QUEUE_NAME = "profile_queue"
class ProfileJobProducer:
    def __init__(self, redis_url=None, queue_name=LEOCDP_PROFILE_QUEUE_NAME):
        # Allow override redis_url in test
        if redis_url is None:
            redis_url = f"redis://{REDIS_HOST}:{int(REDIS_PORT)}/0"

        self.redis_url = redis_url
        self.queue_name = queue_name
        self.redis = redis.from_url(redis_url)

    async def enqueue_profile(self, profile_dict: dict):
        if not isinstance(profile_dict, dict):
            raise ValueError("profile_dict must be a dict")

        payload = json.dumps(profile_dict)
        await self.redis.lpush(self.queue_name, payload)

        logger.info(
            "profile.enqueue",
            queue=self.queue_name,
            redis=self.redis_url,
            size=len(payload),
        )

    async def close(self):
        await self.redis.aclose()
