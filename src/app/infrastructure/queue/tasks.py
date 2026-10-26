from celery import Celery

from app.core.settings import Settings

settings = Settings()
celery_app = Celery("rag", broker=settings.redis_url)
celery_app.conf.update(
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=25,
    task_time_limit=30,
)


@celery_app.task(name="platform.ping")  # type: ignore[misc]
def ping() -> str:
    return "pong"


celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": 600},
    beat_schedule={
        "process-document": {
            "task": "documents.process_next",
            "schedule": 5.0,
            "options": {"expires": 10},
        }
    },
)


@celery_app.task(name="documents.process_next", soft_time_limit=510, time_limit=540)  # type: ignore[misc]
def process_next_document() -> None:
    import asyncio
    from app.modules.documents.infrastructure.processing_worker import process_tick

    with asyncio.Runner() as runner:
        runner.run(process_tick(settings))
