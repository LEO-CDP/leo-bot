import asyncio

import structlog
from leocdp.profile_worker import ProfileJobWorker
from main_config import setup_logging


logger = structlog.get_logger(__name__)


async def start_worker(worker_instance):
    """Wrapper để start một worker bất kỳ."""
    name = worker_instance.__class__.__name__
    logger.info("worker.starting", worker=name)

    try:
        await worker_instance.run()
    except Exception as ex:
        logger.error("worker.crashed", worker=name, error=str(ex))


async def main():
    setup_logging()
    logger.info("system.booting", message="Worker system initializing")

    # Add any worker classes here
    workers = [
        ProfileJobWorker(),
        # EventJobWorker(),
        # IdentityJobWorker(),
        # CustomerScoreWorker(),
        # EmailQueueWorker(),
        # v.v...
    ]

    tasks = [asyncio.create_task(start_worker(w)) for w in workers]

    logger.info("system.running", workers=[
                w.__class__.__name__ for w in workers])

    # loop forever
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
