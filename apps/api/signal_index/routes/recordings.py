from __future__ import annotations

import hashlib
import mimetypes
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..dependencies import CurrentUser
from ..malware import scanner
from ..models import ProcessingJob, Provenance, Recording
from ..schemas import Envelope
from ..serialization import model_dict
from ..storage import ObjectStorage

router = APIRouter(prefix="/recordings", tags=["recordings"])

ALLOWED_AUDIO_SIGNATURES = (
    b"RIFF",
    b"RF64",
    b"fLaC",
    b"OggS",
    b"ID3",
)


def validate_audio_signature(header: bytes) -> None:
    is_mp3_frame = len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
    if not any(header.startswith(signature) for signature in ALLOWED_AUDIO_SIGNATURES) and not is_mp3_frame:
        raise HTTPException(status_code=415, detail="unsupported or invalid audio content")


@router.post("/upload", response_model=Envelope[dict[str, object]], status_code=202)
def upload_recording(
    user: CurrentUser,
    file: UploadFile = File(...),
    frequency_hz: int = Form(..., ge=0, le=100_000_000_000),
    mode: str | None = Form(default=None, max_length=20),
    receiver_id: str | None = Form(default=None),
    started_at_utc: datetime = Form(...),
    source_type: str = Form(default="MANUAL_UPLOAD"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, object]]:
    digest = hashlib.sha256()
    size = 0
    first = b""
    with tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024, mode="w+b") as spool:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="upload exceeds configured size limit")
            if not first:
                first = chunk[:16]
            digest.update(chunk)
            spool.write(chunk)
        validate_audio_signature(first)
        try:
            scanner(settings).scan(spool)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail="malware scanner is unavailable") from exc
        sha256 = digest.hexdigest()
        duplicate = db.scalar(select(Recording).where(Recording.sha256 == sha256))
        if duplicate:
            return Envelope(
                data={"recording": model_dict(duplicate), "deduplicated": True},
                warnings=["identical immutable original already exists"],
            )
        safe_name = Path(file.filename or "upload.audio").name
        object_key = f"originals/{sha256[:2]}/{sha256}/{safe_name}"
        spool.seek(0)
        mime_type = file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        ObjectStorage(settings).upload(object_key, spool, mime_type)
    if started_at_utc.tzinfo is None:
        raise HTTPException(status_code=422, detail="started_at_utc must include a timezone")
    started = started_at_utc.astimezone(UTC)
    recording = Recording(
        object_key=object_key,
        original_filename=safe_name,
        sha256=sha256,
        receiver_id=receiver_id,
        frequency_hz=frequency_hz,
        mode=mode.upper() if mode else None,
        started_at_utc=started,
        ended_at_utc=started,
        duration_sec=0.0,
        sample_rate=0,
        channels=0,
        mime_type=mime_type,
        source_type=source_type,
        processing_status="PENDING",
    )
    db.add(recording)
    db.flush()
    job = ProcessingJob(recording_id=recording.id, status="PENDING", stage="INGEST")
    db.add(job)
    db.add(
        Provenance(
            record_type="RECORDING",
            record_id=recording.id,
            first_observed_at=started,
            raw_hash=sha256,
            confidence=1.0,
            manually_corrected=False,
            raw_object_key=object_key,
        )
    )
    db.commit()
    try:
        from audio_processor.tasks import process_recording

        process_recording.delay(recording.id, job.id)
    except Exception as exc:
        job.status = "FAILED"
        job.error_code = "QUEUE_UNAVAILABLE"
        job.error_stderr = str(exc)
        recording.processing_status = "FAILED"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "recording preserved but processing queue is unavailable", "recording_id": recording.id},
        ) from exc
    return Envelope(data={"recording": model_dict(recording), "job": model_dict(job), "deduplicated": False})


@router.get("/{recording_id}/media", response_model=Envelope[dict[str, str | None]])
def recording_media(
    recording_id: str,
    _user: CurrentUser,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, str | None]]:
    recording = db.get(Recording, recording_id)
    if recording is None or recording.deleted_at is not None:
        raise HTTPException(status_code=404, detail="recording not found")
    storage = ObjectStorage(settings)
    return Envelope(
        data={
            "original_url": storage.signed_get_url(recording.object_key),
            "processed_url": storage.signed_get_url(recording.processed_object_key)
            if recording.processed_object_key
            else None,
            "preview_url": storage.signed_get_url(recording.preview_object_key)
            if recording.preview_object_key
            else None,
        }
    )
