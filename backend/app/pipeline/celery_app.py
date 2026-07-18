from celery import Celery

from app.core.config import settings

celery = Celery("crimescene", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_routes={
        "app.pipeline.stage2.*": {"queue": "gpu"},
    },
    task_default_queue="cpu",
    beat_schedule={
        "retention-purge-nightly": {
            "task": "app.pipeline.tasks.retention_purge",
            "schedule": 24 * 3600,
        },
        "audit-chain-verify-nightly": {
            "task": "app.pipeline.tasks.audit_chain_verify",
            "schedule": 24 * 3600,
        },
    },
)
celery.autodiscover_tasks(["app.pipeline"])

from app.pipeline import tasks  # noqa: E402,F401  (register tasks)
