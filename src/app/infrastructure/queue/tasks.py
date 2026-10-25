from celery import Celery

from app.core.settings import Settings

settings = Settings()
celery_app = Celery("rag", broker=settings.redis_url)
celery_app.conf.update(task_ignore_result=True, task_serializer="json", accept_content=["json"],
                       broker_connection_retry_on_startup=True, worker_prefetch_multiplier=1,
                       task_soft_time_limit=25, task_time_limit=30)


@celery_app.task(name="platform.ping")  # type: ignore[misc]
def ping() -> str:
    return "pong"
