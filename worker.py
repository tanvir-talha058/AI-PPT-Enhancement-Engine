from redis import Redis
from rq import Queue, Worker

from config import QUEUE_NAME, REDIS_URL


listen = [QUEUE_NAME]
redis_conn = Redis.from_url(REDIS_URL)


if __name__ == "__main__":
    worker = Worker([Queue(name, connection=redis_conn) for name in listen], connection=redis_conn)
    worker.work()
