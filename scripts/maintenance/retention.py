from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from signal_index.database import SessionLocal
from signal_index.models import (
    AudioSegment,
    Embedding,
    ExtractedEntity,
    ProcessingJob,
    Provenance,
    Recording,
    Relation,
    Transcript,
    TransmissionSession,
)
from signal_index.storage import ObjectStorage
from sqlalchemy import delete, or_, select


def apply_retention(days: int, hard: bool, delete_originals: bool) -> int:
    if days < 1:
        raise ValueError("retention days must be positive")
    cutoff = datetime.now(UTC) - timedelta(days=days)
    storage = ObjectStorage()
    count = 0
    with SessionLocal.begin() as db:
        recordings = list(
            db.scalars(
                select(Recording).where(
                    Recording.started_at_utc < cutoff,
                    Recording.deleted_at.is_(None),
                )
            )
        )
        for recording in recordings:
            recording.deleted_at = datetime.now(UTC)
            segments = list(
                db.scalars(
                select(AudioSegment).where(
                    AudioSegment.recording_id == recording.id,
                    AudioSegment.deleted_at.is_(None),
                )
                )
            )
            segment_ids = [segment.id for segment in segments]
            for segment in segments:
                segment.deleted_at = datetime.now(UTC)
                for key in (
                    segment.processed_object_key,
                    segment.waveform_object_key,
                    segment.spectrogram_object_key,
                ):
                    if key:
                        storage.delete(key)
            for key in (recording.processed_object_key, recording.preview_object_key):
                if key:
                    storage.delete(key)
            if hard and delete_originals:
                storage.delete(recording.object_key)
            if hard:
                if segment_ids:
                    db.execute(
                        delete(ExtractedEntity).where(ExtractedEntity.segment_id.in_(segment_ids))
                    )
                    db.execute(delete(Transcript).where(Transcript.segment_id.in_(segment_ids)))
                    db.execute(
                        delete(Embedding).where(
                            Embedding.source_type == "SEGMENT",
                            Embedding.source_id.in_(segment_ids),
                        )
                    )
                    db.execute(delete(AudioSegment).where(AudioSegment.id.in_(segment_ids)))
                db.execute(delete(ProcessingJob).where(ProcessingJob.recording_id == recording.id))
                db.execute(
                    delete(Provenance).where(
                        Provenance.record_type == "RECORDING",
                        Provenance.record_id == recording.id,
                    )
                )
                db.execute(
                    delete(Relation).where(
                        or_(
                            (Relation.subject_type == "RECORDING")
                            & (Relation.subject_id == recording.id),
                            (Relation.object_type == "RECORDING")
                            & (Relation.object_id == recording.id),
                        )
                    )
                )
                for session in db.scalars(
                    select(TransmissionSession).where(TransmissionSession.deleted_at.is_(None))
                ):
                    if recording.id in session.recording_ids:
                        session.deleted_at = datetime.now(UTC)
                db.delete(recording)
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply recording retention safely.")
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--hard", action="store_true")
    parser.add_argument("--delete-originals", action="store_true")
    arguments = parser.parse_args()
    if arguments.delete_originals and not arguments.hard:
        parser.error("--delete-originals requires --hard")
    affected = apply_retention(arguments.days, arguments.hard, arguments.delete_originals)
    print(f"Retention marked {affected} recording(s); hard={arguments.hard}.")


if __name__ == "__main__":
    main()
