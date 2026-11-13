from celery import Celery

from .config import settings

celery = Celery(
    "ghost",
    broker=settings.redis_url or "memory://",
    backend=settings.redis_url or None,
    include=["app.tasks"],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_ignore_result=True,
    beat_schedule={
        "check-all-services": {
            "task": "ghost.check_all_services",
            "schedule": float(settings.health_interval),
        },
        "scan-ghosts": {"task": "ghost.scan_ghosts", "schedule": 300.0},
        "prune-health-history": {"task": "ghost.prune_health_history", "schedule": 86400.0},
    },
)
