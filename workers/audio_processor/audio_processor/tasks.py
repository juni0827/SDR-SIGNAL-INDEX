from __future__ import annotations

import hashlib
import tempfile
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np
import soundfile as sf
import structlog
from celery import Task
from signal_index.config import get_settings
from signal_index.database import SessionLocal
from signal_index.event_bus import publish_event
from signal_index.models import (
    AudioSegment,
    CaptureJob,
    Embedding,
    ExtractedEntity,
    ProcessingJob,
    Provenance,
    Receiver,
    Recording,
    Relation,
    Revision,
    Transcript,
    TransmissionSession,
)
from signal_index.security import validate_external_url
from signal_index.storage import ObjectStorage
from signal_processing.config import PRESETS, VADPreset
from signal_processing.embeddings import TorchHashTextEmbedding, TorchSpectralEmbedding
from signal_processing.entities import extract_entities
from signal_processing.features import RuleBasedClassifier, extract_features
from signal_processing.ffmpeg import MediaProcessError, create_preview, normalize_audio, probe, run
from signal_processing.scheduling import subsequent_schedule
from signal_processing.vad import TimeRange, merge_and_split_ranges, silero_ranges
from sqlalchemy import select

from .artifacts import spectrogram_png, waveform_json
from .asr import transcribe
from .celery_app import celery
from .grouping import merge_into_session, replace_session_embedding, select_session
from .runtime_config import active_setting_values, effective_worker_settings

settings = get_settings()
log = structlog.get_logger()


def emit_event(event_type: str, data: dict[str, Any]) -> None:
    try:
        publish_event(event_type, data, settings)
    except Exception as exc:
        log.warning(
            "realtime_publish_failed",
            event_type=event_type,
            error_type=type(exc).__name__,
        )


def set_job(job_id: str, **values: Any) -> None:
    with SessionLocal.begin() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            raise RuntimeError(f"processing job {job_id} disappeared")
        for key, value in values.items():
            setattr(job, key, value)
        event = {
            "job_id": job.id,
            "recording_id": job.recording_id,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
        }
    emit_event("processing_progress", event)


def energy_fallback(samples: np.ndarray, sample_rate: int) -> list[TimeRange]:
    frame = max(1, int(sample_rate * 0.25))
    ranges: list[TimeRange] = []
    active_start: float | None = None
    threshold = max(0.008, float(np.sqrt(np.mean(samples**2))) * 0.6)
    for offset in range(0, len(samples), frame):
        energy = float(np.sqrt(np.mean(samples[offset : offset + frame] ** 2)))
        if energy >= threshold and active_start is None:
            active_start = offset / sample_rate
        if energy < threshold and active_start is not None:
            ranges.append(TimeRange(active_start, offset / sample_rate))
            active_start = None
    if active_start is not None:
        ranges.append(TimeRange(active_start, len(samples) / sample_rate))
    return ranges


@celery.task(bind=True, max_retries=3, name="audio_processor.tasks.process_recording")
def process_recording(self: Task, recording_id: str, job_id: str) -> dict[str, Any]:
    stage = "INGEST"
    try:
        set_job(job_id, status="PROCESSING", stage=stage, progress=0.02, started_at=datetime.now(UTC))
        storage = ObjectStorage(settings)
        with SessionLocal() as db:
            recording = db.get(Recording, recording_id)
            if recording is None:
                raise RuntimeError(f"recording {recording_id} does not exist")
            object_key = recording.object_key
            mode = recording.mode or "VOICE"
            stored_job = db.get(ProcessingJob, job_id)
            if stored_job is None:
                raise RuntimeError(f"processing job {job_id} does not exist")
            job_parameters = dict(stored_job.parameters)
            active_values = active_setting_values(db)
            runtime_settings = effective_worker_settings(settings, active_values)
        with tempfile.TemporaryDirectory(prefix="signal-index-") as temp_dir:
            root = Path(temp_dir)
            original = root / "original"
            original.write_bytes(storage.download(object_key))
            stage = "METADATA_EXTRACTION"
            set_job(job_id, stage=stage, progress=0.08)
            metadata = probe(original, runtime_settings.FFPROBE_PATH)
            processed = root / "processed.wav"
            stage = "NORMALIZE"
            configured_preset = str(active_values.get("processing.preset", mode)).upper()
            normalize_audio(
                original,
                processed,
                PRESETS.get(configured_preset, PRESETS.get(mode, PRESETS["VOICE"])),
                runtime_settings.FFMPEG_PATH,
            )
            preview = root / "preview.ogg"
            create_preview(processed, preview, runtime_settings.FFMPEG_PATH)
            processed_key = (
                f"derived/{recording_id}/{runtime_settings.PIPELINE_VERSION}/processed.wav"
            )
            preview_key = (
                f"derived/{recording_id}/{runtime_settings.PIPELINE_VERSION}/preview.ogg"
            )
            storage.upload(processed_key, processed.read_bytes(), "audio/wav")
            storage.upload(preview_key, preview.read_bytes(), "audio/ogg")
            samples, sample_rate = sf.read(processed, dtype="float32")
            samples = np.asarray(samples, dtype=np.float32)
            stage = "VAD"
            set_job(job_id, stage=stage, progress=0.25)
            vad_preset = VADPreset(
                threshold=float(
                    job_parameters.get("threshold", runtime_settings.VAD_THRESHOLD)
                ),
                minimum_speech_ms=int(
                    job_parameters.get(
                        "minimum_speech_ms", runtime_settings.VAD_MINIMUM_SPEECH_MS
                    )
                ),
                minimum_silence_ms=int(
                    job_parameters.get(
                        "minimum_silence_ms", runtime_settings.VAD_MINIMUM_SILENCE_MS
                    )
                ),
                padding_ms=int(
                    job_parameters.get("padding_ms", runtime_settings.VAD_PADDING_MS)
                ),
                maximum_segment_sec=float(
                    job_parameters.get(
                        "maximum_segment_sec", runtime_settings.VAD_MAXIMUM_SEGMENT_SEC
                    )
                ),
                merge_shorter_than_ms=int(
                    job_parameters.get(
                        "merge_shorter_than_ms",
                        runtime_settings.VAD_MERGE_SHORTER_THAN_MS,
                    )
                ),
            )
            raw_ranges = (
                silero_ranges(samples, sample_rate, vad_preset)
                if runtime_settings.SILERO_VAD_ENABLED
                else []
            )
            if not raw_ranges:
                raw_ranges = energy_fallback(samples, sample_rate)
                log.warning("vad_energy_fallback", recording_id=recording_id)
            ranges = merge_and_split_ranges(raw_ranges, vad_preset, metadata.duration_sec)
            if not ranges:
                ranges = [TimeRange(0.0, metadata.duration_sec)]
            classifier = RuleBasedClassifier()
            audio_embedder = TorchSpectralEmbedding()
            text_embedder = TorchHashTextEmbedding()
            segment_ids: list[str] = []
            callsigns: set[str] = set()
            number_groups: set[str] = set()
            languages: set[str] = set()
            segment_vectors: list[np.ndarray] = []
            text_vectors: list[np.ndarray] = []
            with SessionLocal.begin() as db:
                recording = db.get(Recording, recording_id)
                if recording is None:
                    raise RuntimeError("recording deleted during processing")
                recording.duration_sec = metadata.duration_sec
                recording.sample_rate = metadata.sample_rate
                recording.channels = metadata.channels
                recording.ended_at_utc = recording.started_at_utc + timedelta(seconds=metadata.duration_sec)
                recording.processed_object_key = processed_key
                recording.preview_object_key = preview_key
                recording.processing_version = runtime_settings.PIPELINE_VERSION
                recording.processing_status = "PROCESSING"
                if job_parameters.get("replace_active_derivatives"):
                    now = datetime.now(UTC)
                    old_segments = list(
                        db.scalars(
                            select(AudioSegment).where(
                                AudioSegment.recording_id == recording_id,
                                AudioSegment.deleted_at.is_(None),
                            )
                        )
                    )
                    old_segment_ids = [value.id for value in old_segments]
                    for old_segment in old_segments:
                        old_segment.deleted_at = now
                    if old_segment_ids:
                        old_transcripts = list(
                            db.scalars(
                                select(Transcript).where(
                                    Transcript.segment_id.in_(old_segment_ids),
                                    Transcript.deleted_at.is_(None),
                                )
                            )
                        )
                        old_transcript_ids = [value.id for value in old_transcripts]
                        for old_transcript in old_transcripts:
                            old_transcript.deleted_at = now
                        for old_entity in db.scalars(
                            select(ExtractedEntity).where(
                                ExtractedEntity.segment_id.in_(old_segment_ids),
                                ExtractedEntity.deleted_at.is_(None),
                            )
                        ):
                            old_entity.deleted_at = now
                        for old_embedding in db.scalars(
                            select(Embedding).where(
                                Embedding.source_type.in_(["SEGMENT", "TRANSCRIPT"]),
                                Embedding.deleted_at.is_(None),
                            )
                        ):
                            if (
                                old_embedding.source_id in old_segment_ids
                                or old_embedding.source_id in old_transcript_ids
                            ):
                                old_embedding.deleted_at = now
                        for old_relation in db.scalars(
                            select(Relation).where(
                                Relation.deleted_at.is_(None),
                                (
                                    (Relation.subject_type == "SEGMENT")
                                    & Relation.subject_id.in_(old_segment_ids)
                                )
                                | (
                                    (Relation.object_type == "SEGMENT")
                                    & Relation.object_id.in_(old_segment_ids)
                                ),
                            )
                        ):
                            old_relation.deleted_at = now
                    for existing_session in db.scalars(
                        select(TransmissionSession).where(
                            TransmissionSession.deleted_at.is_(None)
                        )
                    ):
                        if recording_id not in existing_session.recording_ids:
                            continue
                        before = {
                            "recording_ids": list(existing_session.recording_ids),
                            "segment_ids": list(existing_session.segment_ids),
                        }
                        remaining_recordings = [
                            value
                            for value in existing_session.recording_ids
                            if value != recording_id
                        ]
                        if not remaining_recordings:
                            existing_session.deleted_at = now
                        else:
                            existing_session.recording_ids = remaining_recordings
                            existing_session.segment_ids = [
                                value
                                for value in existing_session.segment_ids
                                if value not in old_segment_ids
                            ]
                        db.add(
                            Revision(
                                record_type="SESSION",
                                record_id=existing_session.id,
                                actor_type="MACHINE",
                                before=before,
                                after={
                                    "recording_ids": list(existing_session.recording_ids),
                                    "segment_ids": list(existing_session.segment_ids),
                                    "soft_deleted": existing_session.deleted_at is not None,
                                },
                                reason="derived session invalidated by VAD rerun",
                            )
                        )
            for index, item in enumerate(ranges):
                stage = "SEGMENT_PROCESSING"
                set_job(job_id, stage=stage, progress=0.3 + 0.55 * index / max(1, len(ranges)))
                start = int(item.start_sec * sample_rate)
                end = int(item.end_sec * sample_rate)
                audio = samples[start:end]
                features = extract_features(audio, sample_rate)
                segment_type, confidence = classifier.classify(features)
                with SessionLocal.begin() as db:
                    segment = AudioSegment(
                        recording_id=recording_id,
                        start_sec=item.start_sec,
                        end_sec=item.end_sec,
                        duration_sec=item.duration_sec,
                        segment_type=segment_type,
                        class_confidence=confidence,
                        class_features={"classifier": classifier.name, **features.dict()},
                        snr_db=features.snr_db,
                        rms_energy=features.rms_energy,
                        spectral_centroid=features.spectral_centroid,
                        spectral_flatness=features.spectral_flatness,
                        bandwidth_hz=features.bandwidth_hz,
                        zero_crossing_rate=features.zero_crossing_rate,
                    )
                    db.add(segment)
                    db.flush()
                    segment_ids.append(segment.id)
                    segment_wav = root / f"{segment.id}.wav"
                    sf.write(segment_wav, audio, sample_rate, subtype="PCM_16")
                    base_key = (
                        f"derived/{recording_id}/{runtime_settings.PIPELINE_VERSION}"
                        f"/segments/{segment.id}"
                    )
                    segment_key = f"{base_key}.wav"
                    waveform_key = f"{base_key}.waveform.json"
                    spectrogram_key = f"{base_key}.spectrogram.png"
                    storage.upload(segment_key, segment_wav.read_bytes(), "audio/wav")
                    storage.upload(waveform_key, waveform_json(audio), "application/json")
                    storage.upload(spectrogram_key, spectrogram_png(audio, sample_rate), "image/png")
                    segment.processed_object_key = segment_key
                    segment.waveform_object_key = waveform_key
                    segment.spectrogram_object_key = spectrogram_key
                    vector = audio_embedder.embed_audio(audio, sample_rate)
                    segment_vectors.append(vector)
                    db.add(
                        Embedding(
                            embedding_type="AUDIO",
                            source_type="SEGMENT",
                            source_id=segment.id,
                            model=audio_embedder.name,
                            model_version=audio_embedder.version,
                            dimension=audio_embedder.dimension,
                            preprocessing_version=runtime_settings.PIPELINE_VERSION,
                            vector=vector.tolist(),
                        )
                    )
                    candidates = (
                        transcribe(segment_wav, runtime_settings)
                        if segment_type in {"VOICE", "UNKNOWN"}
                        else []
                    )
                    for candidate_index, candidate in enumerate(candidates):
                        transcript = Transcript(
                            segment_id=segment.id,
                            transcript_type="MACHINE" if candidate_index == 0 else "ALTERNATIVE",
                            language=candidate["language"],
                            text=candidate["text"],
                            normalized_text=candidate["text"].casefold().strip(),
                            model_name=candidate["model_name"],
                            model_version=candidate["model_version"],
                            confidence=candidate["confidence"],
                            word_timestamps=candidate["word_timestamps"],
                            is_preferred=candidate_index == 0,
                        )
                        db.add(transcript)
                        db.flush()
                        text_vector = text_embedder.embed_text(candidate["text"])
                        text_vectors.append(text_vector)
                        db.add(
                            Embedding(
                                embedding_type="TRANSCRIPT_TEXT",
                                source_type="TRANSCRIPT",
                                source_id=transcript.id,
                                model=text_embedder.name,
                                model_version=text_embedder.version,
                                dimension=text_embedder.dimension,
                                preprocessing_version=runtime_settings.PIPELINE_VERSION,
                                vector=text_vector.tolist(),
                            )
                        )
                        languages.add(candidate["language"])
                        for candidate_entity in extract_entities(candidate["text"]):
                            extracted = ExtractedEntity(
                                segment_id=segment.id,
                                entity_type=candidate_entity.entity_type,
                                raw_value=candidate_entity.raw_value,
                                normalized_value=candidate_entity.normalized_value,
                                confidence=candidate_entity.confidence,
                                source=candidate_entity.source,
                            )
                            db.add(extracted)
                            if candidate_entity.entity_type == "CALLSIGN":
                                callsigns.add(candidate_entity.normalized_value)
                            if candidate_entity.entity_type == "NUMBER_GROUP":
                                number_groups.add(candidate_entity.normalized_value)
                    db.add(
                        Provenance(
                            record_type="SEGMENT",
                            record_id=segment.id,
                            pipeline_version=runtime_settings.PIPELINE_VERSION,
                            confidence=confidence,
                            manually_corrected=False,
                        )
                    )
            stage = "SESSION_GROUPING"
            set_job(job_id, stage=stage, progress=0.9)
            with SessionLocal.begin() as db:
                recording = db.get(Recording, recording_id)
                if recording is None:
                    raise RuntimeError("recording deleted during session grouping")
                vectors = [*segment_vectors, *text_vectors]
                if vectors:
                    composite = np.mean(np.stack(vectors), axis=0)
                    norm = float(np.linalg.norm(composite))
                    if norm:
                        composite /= norm
                else:
                    composite = np.zeros(audio_embedder.dimension, dtype=np.float32)
                session_candidate, candidate_score, merge_evidence = select_session(
                    db,
                    recording=recording,
                    callsigns=callsigns,
                    number_groups=number_groups,
                    composite_vector=composite,
                    settings=runtime_settings,
                )
                if session_candidate is None:
                    session = TransmissionSession(
                        title=f"{recording.frequency_hz / 1000:g} kHz observation",
                        start_at_utc=recording.started_at_utc,
                        end_at_utc=recording.ended_at_utc,
                        primary_frequency_hz=recording.frequency_hz,
                        frequencies_hz=[recording.frequency_hz],
                        receiver_ids=[recording.receiver_id] if recording.receiver_id else [],
                        recording_ids=[recording.id],
                        segment_ids=segment_ids,
                        callsigns=sorted(callsigns),
                        number_groups=sorted(number_groups),
                        languages=sorted(languages),
                        category="UNKNOWN",
                        session_fingerprint=(
                            f"{recording.frequency_hz}:{recording.started_at_utc:%Y%m%d%H%M}"
                        ),
                        confidence=max(0.35, candidate_score),
                        status="UNREVIEWED",
                    )
                    db.add(session)
                    db.flush()
                else:
                    session = merge_into_session(
                        db,
                        session=session_candidate,
                        recording=recording,
                        segment_ids=segment_ids,
                        callsigns=callsigns,
                        number_groups=number_groups,
                        languages=languages,
                        merge_score_value=candidate_score,
                        evidence=merge_evidence,
                    )
                    previous_embedding = db.scalar(
                        select(Embedding).where(
                            Embedding.source_type == "SESSION",
                            Embedding.source_id == session.id,
                            Embedding.embedding_type == "SESSION_COMPOSITE",
                            Embedding.deleted_at.is_(None),
                        )
                    )
                    if previous_embedding is not None and vectors:
                        prior = np.asarray(previous_embedding.vector, dtype=np.float32)
                        if prior.shape == composite.shape:
                            composite = (prior + composite) / 2
                            composite_norm = float(np.linalg.norm(composite))
                            if composite_norm:
                                composite /= composite_norm
                for stored_entity in db.scalars(
                    select(ExtractedEntity).where(ExtractedEntity.segment_id.in_(segment_ids))
                ):
                    stored_entity.session_id = session.id
                if vectors:
                    replace_session_embedding(
                        db,
                        session=session,
                        vector=composite,
                        model="composite:torch-spectral+torch-hash-text",
                        model_version="2.0.0",
                        preprocessing_version=runtime_settings.PIPELINE_VERSION,
                    )
                recording.processing_status = "COMPLETED"
                job = db.get(ProcessingJob, job_id)
                if job:
                    job.status = "COMPLETED"
                    job.stage = "INDEX_UPDATE"
                    job.progress = 1.0
                    job.finished_at = datetime.now(UTC)
                capture_job = db.scalar(
                    select(CaptureJob).where(CaptureJob.recording_id == recording_id)
                )
                if capture_job:
                    capture_job.status = "COMPLETED"
                    capture_job.last_finished_at = datetime.now(UTC)
                    capture_job.next_run_at = subsequent_schedule(
                        capture_job.schedule_utc,
                        capture_job.repetition,
                        after=capture_job.last_finished_at,
                    )
                    if capture_job.next_run_at is not None:
                        capture_job.status = "SCHEDULED"
            emit_event(
                "transcript_completion",
                {"recording_id": recording_id, "segment_ids": segment_ids},
            )
            emit_event(
                "new_session",
                {"recording_id": recording_id, "session_id": session.id},
            )
            return {"recording_id": recording_id, "segment_count": len(segment_ids)}
    except Exception as exc:
        error_code = (
            f"FFMPEG_{exc.return_code}" if isinstance(exc, MediaProcessError) else type(exc).__name__.upper()
        )
        error_stderr = exc.stderr if isinstance(exc, MediaProcessError) else str(exc)
        with SessionLocal.begin() as db:
            job = db.get(ProcessingJob, job_id)
            recording = db.get(Recording, recording_id)
            if job:
                job.attempt = self.request.retries + 1
                job.status = "FAILED" if self.request.retries >= self.max_retries else "RETRYING"
                job.stage = stage
                job.error_code = error_code
                job.error_stderr = error_stderr[-20_000:]
                job.traceback = traceback.format_exc()[-40_000:]
            if recording:
                recording.processing_status = "FAILED" if self.request.retries >= self.max_retries else "PROCESSING"
            capture_job = db.scalar(
                select(CaptureJob).where(CaptureJob.recording_id == recording_id)
            )
            if capture_job:
                capture_job.status = "FAILED" if self.request.retries >= self.max_retries else "PROCESSING"
                capture_job.last_error = error_stderr[-20_000:]
        if self.request.retries >= self.max_retries:
            emit_event(
                "failed_job",
                {
                    "job_id": job_id,
                    "recording_id": recording_id,
                    "stage": stage,
                    "error_code": error_code,
                },
            )
            raise
        raise self.retry(
            exc=exc, countdown=min(300, 2 ** (self.request.retries + 1) * 10)
        ) from exc


@celery.task(bind=True, max_retries=2, name="audio_processor.tasks.capture_receiver")
def capture_receiver(self: Task, capture_job_id: str) -> dict[str, str]:
    if not settings.CAPTURE_ENABLED:
        raise RuntimeError("capture is globally disabled")
    from redis import Redis

    redis = Redis.from_url(settings.REDIS_URL)
    lock_name = f"capture-runtime:{capture_job_id}"
    lock_value = f"{self.request.id}:{datetime.now(UTC).isoformat()}"
    if not redis.set(lock_name, lock_value, nx=True, ex=86_400):
        raise RuntimeError("capture job is already locked")
    try:
        with SessionLocal.begin() as db:
            capture = db.get(CaptureJob, capture_job_id)
            if capture is None or capture.deleted_at is not None:
                raise RuntimeError("capture job does not exist")
            if not capture.enabled:
                raise RuntimeError("capture job is disabled")
            receiver = db.get(Receiver, capture.receiver_id)
            if receiver is None or receiver.deleted_at is not None:
                raise RuntimeError("capture receiver does not exist")
            template = str(receiver.metadata_json.get("capture_url_template") or "")
            if not template:
                raise RuntimeError("receiver has no explicit capture_url_template")
            capture.status = "STARTING"
            capture.last_started_at = datetime.now(UTC)
            rendered_url = template.format(
                frequency_hz=capture.frequency_hz,
                frequency_khz=capture.frequency_hz / 1_000,
                mode=capture.mode.lower(),
            )
            allowed_host = receiver.base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
            validated_url = validate_external_url(rendered_url, {allowed_host.lower()})
            duration = capture.capture_duration_sec
            maximum_storage_bytes = capture.maximum_storage_bytes
            frequency_hz = capture.frequency_hz
            mode = capture.mode
            receiver_id = receiver.id
            started_at = datetime.now(UTC)
            capture.status = "CAPTURING"
        emit_event(
            "capture_progress",
            {"capture_job_id": capture_job_id, "status": "CAPTURING", "progress": 0.05},
        )
        with tempfile.TemporaryDirectory(prefix="signal-index-capture-") as temp_dir:
            output = Path(temp_dir) / "capture.wav"
            run(
                [
                    settings.FFMPEG_PATH,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-t",
                    str(duration),
                    "-i",
                    validated_url,
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(output),
                ],
                "CAPTURE",
            )
            body = output.read_bytes()
            if maximum_storage_bytes is not None and len(body) > maximum_storage_bytes:
                raise RuntimeError(
                    f"capture size {len(body)} exceeds schedule limit {maximum_storage_bytes}"
                )
            digest = hashlib.sha256(body).hexdigest()
            object_key = f"originals/{digest[:2]}/{digest}/capture-{capture_job_id}.wav"
            storage = ObjectStorage(settings)
            storage.upload(object_key, body, "audio/wav")
            with SessionLocal.begin() as db:
                capture = db.get(CaptureJob, capture_job_id)
                if capture is None:
                    raise RuntimeError("capture job disappeared")
                existing = db.scalar(select(Recording).where(Recording.sha256 == digest))
                if existing is None:
                    recording = Recording(
                        object_key=object_key,
                        original_filename=f"capture-{capture_job_id}.wav",
                        sha256=digest,
                        receiver_id=receiver_id,
                        frequency_hz=frequency_hz,
                        mode=mode,
                        started_at_utc=started_at,
                        ended_at_utc=started_at + timedelta(seconds=duration),
                        duration_sec=float(duration),
                        sample_rate=16_000,
                        channels=1,
                        mime_type="audio/wav",
                        source_type="LIVE_CAPTURE",
                        source_url=validated_url,
                        processing_status="PENDING",
                    )
                    db.add(recording)
                    db.flush()
                    db.add(
                        Provenance(
                            record_type="RECORDING",
                            record_id=recording.id,
                            source_url=receiver.base_url,
                            first_observed_at=started_at,
                            raw_hash=digest,
                            confidence=1.0,
                            raw_object_key=object_key,
                        )
                    )
                else:
                    recording = existing
                processing_job = ProcessingJob(
                    recording_id=recording.id,
                    status="PENDING",
                    stage="INGEST",
                )
                db.add(processing_job)
                db.flush()
                capture.recording_id = recording.id
                capture.status = "PROCESSING"
                recording_id = recording.id
                processing_job_id = processing_job.id
            emit_event(
                "capture_progress",
                {
                    "capture_job_id": capture_job_id,
                    "recording_id": recording_id,
                    "status": "PROCESSING",
                    "progress": 1.0,
                },
            )
            process_recording.delay(recording_id, processing_job_id)
        return {"capture_job_id": capture_job_id, "recording_id": recording_id}
    except Exception as exc:
        with SessionLocal.begin() as db:
            capture = db.get(CaptureJob, capture_job_id)
            if capture:
                capture.status = "FAILED" if self.request.retries >= self.max_retries else "STARTING"
                capture.last_error = f"{type(exc).__name__}: {exc}"[-20_000:]
        if self.request.retries >= self.max_retries:
            emit_event(
                "failed_job",
                {
                    "capture_job_id": capture_job_id,
                    "stage": "CAPTURE",
                    "error_code": type(exc).__name__.upper(),
                },
            )
            raise
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries)) from exc
    finally:
        current = cast(bytes | None, redis.get(lock_name))
        if current is not None and current.decode() == lock_value:
            redis.delete(lock_name)


@celery.task(name="audio_processor.tasks.dispatch_due_captures")
def dispatch_due_captures() -> dict[str, int]:
    now = datetime.now(UTC)
    dispatched = 0
    with SessionLocal.begin() as db:
        jobs = list(
            db.scalars(
                select(CaptureJob).where(
                    CaptureJob.enabled.is_(True),
                    CaptureJob.status == "SCHEDULED",
                    CaptureJob.next_run_at.is_not(None),
                    CaptureJob.next_run_at <= now,
                    CaptureJob.deleted_at.is_(None),
                )
            )
        )
        for job in jobs:
            job.status = "STARTING"
            capture_receiver.delay(job.id)
            dispatched += 1
    return {"dispatched": dispatched}
