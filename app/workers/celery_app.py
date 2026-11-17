import logging

from celery import Celery
from celery.signals import after_setup_logger, after_setup_task_logger

from app.config import settings
from app.observability.logging_config import JsonFormatter


def configure_celery_json_logging(logger, **kwargs):
    logger.setLevel(logging.INFO)

    # Replace existing handlers to avoid duplicate or plain-text output.
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    logger.propagate = False


@after_setup_logger.connect
def setup_celery_logger(logger, **kwargs):
    configure_celery_json_logging(logger, **kwargs)


@after_setup_task_logger.connect
def setup_celery_task_logger(logger, **kwargs):
    configure_celery_json_logging(logger, **kwargs)


celery_app = Celery(
    "webhook_delivery",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks",
        "app.workers.dispatcher",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="webhook-deliveries",
    beat_schedule={
        "dispatch-pending-deliveries-every-30-seconds": {
            "task": "app.workers.dispatcher.dispatch_pending_deliveries",
            "schedule": 30.0,
        },
    },
)