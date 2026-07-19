from celery import Celery

from app.core.config import settings

# celery_eager=True (deploy/run_local.py's no-Redis path): tasks run synchronously in
# the calling process the instant .delay()/.apply_async() is called — no broker, no
# separate worker process. 'memory://' is Celery's own in-process transport, used only
# to satisfy Celery's config requirement; no actual message passing happens in eager mode.
broker = "memory://" if settings.celery_eager else settings.redis_url
backend = "cache+memory://" if settings.celery_eager else settings.redis_url

celery = Celery("crimescene", broker=broker, backend=backend)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_routes={
        "app.pipeline.stage2.*": {"queue": "gpu"},
    },
    task_default_queue="cpu",
    task_always_eager=settings.celery_eager,
    task_eager_propagates=settings.celery_eager,
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
