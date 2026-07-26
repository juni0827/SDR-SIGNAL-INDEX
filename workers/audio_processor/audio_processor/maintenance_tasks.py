from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from celery import Task
from signal_index.config import get_settings
from signal_index.database import SessionLocal
from signal_index.models import (
    AudioSegment,
    CaptureJob,
    Embedding,
    ExtractedEntity,
    Provenance,
    Recording,
    Source,
    Transcript,
    TransmissionSession,
)
from signal_index.storage import ObjectStorage
from sqlalchemy import String, or_, select

from .celery_app import celery


def retention_days_for_recording(
    recording: Recording,
    capture: CaptureJob | None,
    source: Source | None,
    default_days: int,
) -> int:
    values: list[Any] = []
    if capture:
        values.append(capture.retention_policy.get("days"))
    if source:
        values.append(source.config.get("retention_days"))
    for value in values:
        if isinstance(value, int) and value > 0:
            return value
    return default_days


@celery.task(
    bind=True,
    max_retries=3,
    name="audio_processor.maintenance_tasks.apply_retention",
)
def apply_retention(self: Task) -> dict[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    storage = ObjectStorage(settings)
    expired = 0
    derived_deleted = 0
    originals_deleted = 0
    try:
        with SessionLocal.begin() as db:
            recordings = list(
                db.scalars(
                    select(Recording).where(Recording.deleted_at.is_(None)).limit(100_000)
                )
            )
            for recording in recordings:
                capture = db.scalar(
                    select(CaptureJob)
                    .where(
                        CaptureJob.recording_id == recording.id,
                        CaptureJob.deleted_at.is_(None),
                    )
                    .order_by(CaptureJob.created_at.desc())
                )
                source = None
                provenance = db.scalar(
                    select(Provenance)
                    .where(
                        Provenance.record_type == "RECORDING",
                        Provenance.record_id == recording.id,
                        Provenance.deleted_at.is_(None),
                    )
                    .order_by(Provenance.created_at.desc())
                )
                source_id = (
                    capture.retention_policy.get("source_id")
                    if capture and isinstance(capture.retention_policy.get("source_id"), str)
                    else provenance.source_id if provenance else None
                )
                if source_id:
                    source = db.get(Source, source_id)
                days = retention_days_for_recording(
                    recording,
                    capture,
                    source,
                    settings.DEFAULT_RECORDING_RETENTION_DAYS,
                )
                if recording.ended_at_utc >= now - timedelta(days=days):
                    continue
                segments = list(
                    db.scalars(
                        select(AudioSegment).where(
                            AudioSegment.recording_id == recording.id,
                            AudioSegment.deleted_at.is_(None),
                        )
                    )
                )
                segment_ids = [segment.id for segment in segments]
                segment_id_set = set(segment_ids)
                if settings.RETENTION_DELETE_DERIVED_OBJECTS:
                    keys = [
                        recording.processed_object_key,
                        recording.preview_object_key,
                        *[
                            key
                            for segment in segments
                            for key in (
                                segment.processed_object_key,
                                segment.waveform_object_key,
                                segment.spectrogram_object_key,
                            )
                        ],
                    ]
                    for key in dict.fromkeys(value for value in keys if value):
                        storage.delete(key)
                        derived_deleted += 1
                delete_original = bool(
                    (capture and capture.retention_policy.get("delete_original") is True)
                    or (source and source.config.get("delete_original_after_retention") is True)
                )
                if delete_original:
                    storage.delete(recording.object_key)
                    originals_deleted += 1
                recording.deleted_at = now
                for segment in segments:
                    segment.deleted_at = now
                if segment_ids:
                    for transcript in db.scalars(
                        select(Transcript).where(
                            Transcript.segment_id.in_(segment_ids),
                            Transcript.deleted_at.is_(None),
                        )
                    ):
                        transcript.deleted_at = now
                    for entity in db.scalars(
                        select(ExtractedEntity).where(
                            ExtractedEntity.segment_id.in_(segment_ids),
                            ExtractedEntity.deleted_at.is_(None),
                        )
                    ):
                        entity.deleted_at = now
                    for embedding in db.scalars(
                        select(Embedding).where(
                            or_(
                                Embedding.source_id == recording.id,
                                Embedding.source_id.in_(segment_ids),
                            ),
                            Embedding.deleted_at.is_(None),
                        )
                    ):
                        embedding.deleted_at = now
                sessions = list(
                    db.scalars(
                        select(TransmissionSession).where(
                            TransmissionSession.recording_ids.cast(String).contains(recording.id),
                            TransmissionSession.deleted_at.is_(None),
                        )
                    )
                )
                for session in sessions:
                    session.recording_ids = [
                        value for value in session.recording_ids if value != recording.id
                    ]
                    session.segment_ids = [
                        value for value in session.segment_ids if value not in segment_id_set
                    ]
                    if not session.recording_ids:
                        session.deleted_at = now
                expired += 1
        return {
            "recordings_expired": expired,
            "derived_objects_deleted": derived_deleted,
            "original_objects_deleted": originals_deleted,
        }
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(3600, 60 * (2**self.request.retries))) from exc
