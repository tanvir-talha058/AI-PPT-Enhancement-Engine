"""RQ worker for processing PPT enhancement jobs from Redis queue."""

from redis import Redis
from rq import Queue, Worker

from config import QUEUE_NAME, REDIS_URL, setup_logging

logger = setup_logging(__name__)

listen = [QUEUE_NAME]
redis_conn = Redis.from_url(REDIS_URL)


if __name__ == "__main__":
    logger.info(f"Starting RQ worker listening to queue(s): {listen}")
    worker = Worker([Queue(name, connection=redis_conn) for name in listen], connection=redis_conn)
    worker.work()
