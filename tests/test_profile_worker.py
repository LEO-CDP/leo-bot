import pytest
import json
import asyncio
import redis.asyncio as redis

from leocdp.profile_worker import ProfileJobWorker


class MockCDPClient:
    """Mock CDP client that simulates successful save_profile call."""
    async def save_profile(self, data: dict):
        return {"ok": True, "profile": data}


@pytest.mark.asyncio
async def test_process_job():
    """Test that a single job is processed correctly."""

    worker = ProfileJobWorker(
        redis_url="redis://localhost:6480/0",
        queue_name="test_profile_queue",
        client=MockCDPClient()
    )

    job = {"email": "test@example.com"}
    payload_raw = json.dumps(job).encode()

    result = await worker.process_job(payload_raw)

    assert result["ok"] is True
    assert result["profile"]["email"] == "test@example.com"

    await worker.shutdown()


@pytest.mark.asyncio
async def test_run_once_with_job():
    """Test run_once() processes exactly one job from Redis."""

    redis_url = "redis://localhost:6480/0"
    queue = "test_profile_queue"

    r = redis.from_url(redis_url)
    await r.delete(queue)

    # push a job into Redis
    job_data = {"name": "Alice"}
    await r.lpush(queue, json.dumps(job_data))

    worker = ProfileJobWorker(
        redis_url=redis_url,
        queue_name=queue,
        client=MockCDPClient()
    )

    result = await worker.run_once()

    assert result["ok"] is True
    assert result["profile"]["name"] == "Alice"

    await worker.shutdown()
    await r.aclose()


@pytest.mark.asyncio
async def test_run_once_timeout():
    """Test run_once returns None when queue is empty (timeout)."""

    redis_url = "redis://localhost:6480/0"
    queue = "empty_test_queue"

    r = redis.from_url(redis_url)
    await r.delete(queue)

    worker = ProfileJobWorker(
        redis_url=redis_url,
        queue_name=queue,
        client=MockCDPClient()
    )

    result = await worker.run_once()
    assert result is None  # Timeout should return None

    await worker.shutdown()
    await r.aclose()


@pytest.mark.asyncio
async def test_shutdown():
    """Test that shutting down the worker sets the correct flag and closes Redis."""

    worker = ProfileJobWorker(
        redis_url="redis://localhost:6480/0",
        queue_name="shutdown_test_queue",
        client=MockCDPClient()
    )

    await worker.shutdown()

    assert worker._shutdown is True
