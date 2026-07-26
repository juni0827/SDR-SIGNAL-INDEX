from celery import Celery
from signal_index.config import get_settings

settings = get_settings()
celery = Celery(
    "signal-index",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["audio_processor.tasks", "audio_processor.source_tasks"],
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
    },
)
