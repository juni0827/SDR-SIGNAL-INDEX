from typing import Any

import structlog
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready, worker_shutdown
from signal_index.config import get_settings
from signal_index.event_bus import publish_event

settings = get_settings()
log = structlog.get_logger()
celery = Celery(
    "signal-index",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "audio_processor.tasks",
        "audio_processor.source_tasks",
        "audio_processor.maintenance_tasks",
    ],
)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_connection_retry_on_startup=True,
    task_routes={
        "audio_processor.tasks.process_recording": {"queue": "audio"},
        "audio_processor.tasks.capture_receiver": {"queue": "capture"},
        "audio_processor.source_tasks.fetch_source": {"queue": "sources"},
        "audio_processor.source_tasks.check_receivers": {"queue": "sources"},
        "audio_processor.maintenance_tasks.apply_retention": {"queue": "maintenance"},
    },
    beat_schedule={
        "dispatch-due-captures": {
            "task": "audio_processor.tasks.dispatch_due_captures",
            "schedule": 30.0,
        },
        "dispatch-due-sources": {
            "task": "audio_processor.source_tasks.dispatch_due_sources",
            "schedule": 60.0,
        },
        "apply-retention-daily": {
            "task": "audio_processor.maintenance_tasks.apply_retention",
            "schedule": crontab(hour=3, minute=15),
        },
        "check-receiver-status": {
            "task": "audio_processor.source_tasks.check_receivers",
            "schedule": 600.0,
        },
    },
)


def announce_worker_ready(sender: Any = None, **_: Any) -> None:
    publish_worker_status("ONLINE", sender)


def announce_worker_shutdown(sender: Any = None, **_: Any) -> None:
    publish_worker_status("OFFLINE", sender)


def publish_worker_status(status: str, sender: Any) -> None:
    try:
        publish_event(
            "worker_status",
            {
                "status": status,
                "worker": str(getattr(sender, "hostname", "unknown")),
            },
            settings,
        )
    except Exception as exc:
        log.warning(
            "worker_status_publish_failed",
            status=status,
            error_type=type(exc).__name__,
        )


worker_ready.connect(announce_worker_ready, weak=False)
worker_shutdown.connect(announce_worker_shutdown, weak=False)
