import asyncio
import pytest
import json
import redis.asyncio as redis
import structlog

from leocdp.profile_payload import ProfilePayload
from leocdp.profile_queue import LEOCDP_PROFILE_QUEUE_NAME, ProfileJobProducer
from main_config import REDIS_HOST, REDIS_PORT

logger = structlog.get_logger(__name__)

REDIS_URL = f"redis://{REDIS_HOST}:{int(REDIS_PORT)}/0"


@pytest.mark.asyncio
async def test_profile_enqueue():
    redis_url = REDIS_URL
    queue_name = LEOCDP_PROFILE_QUEUE_NAME

    client = redis.from_url(redis_url)
    logger.info("test_profile_enqueue", redis_url=redis_url)

    # reset queue
    await client.delete(queue_name)

    profile = ProfilePayload(
        journeyMapIds="id_default_journey; ",
        dataLabels="CRM;test",
        crmRefId="1232",
        primaryEmail="tantrieuf32@gmail.com",
        primaryPhone="0903122290",
        firstName="trieu 2",
        lastName="nguyen",
        gender="male",
        extAttributes={"facebook-friend": 100, "facebook-short-bio": "#Dataism #LEOCDP"},
        incomeHistory={"2022-2023": 2000000, "2023-2024": 3000000},
        applicationIDs=["kiotviet-KH412555", "zalo-123"],
        socialMediaProfiles={"zalo": "123456789", "facebook": "123456789"},
        loyaltyIDs=["kiotviet-KH410273", "dpoint-1234"],
        fintechSystemIDs=["bank-123", "bank-456"],
        governmentIssuedIDs=["cccd-123", "cccd-456"],
        notes="this is a test 3"
    )

    producer = ProfileJobProducer(redis_url=redis_url, queue_name=queue_name)

    # enqueue
    await producer.enqueue_profile(profile.to_dict())

    # verify
    await asyncio.sleep(3)
    item = await client.lpop(queue_name)
    assert item is None, "Queue should empty after 3 seconds"


    # cleanup
    await producer.close()
    await client.aclose()
