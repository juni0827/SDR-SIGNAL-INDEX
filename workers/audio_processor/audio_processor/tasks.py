from __future__ import annotations

import tempfile
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import structlog
from celery import Task
from signal_index.config import get_settings
from signal_index.database import SessionLocal
from signal_index.models import (
    AudioSegment,
    Embedding,
    ExtractedEntity,
    ProcessingJob,
    Provenance,
    Recording,
    Transcript,
    TransmissionSession,
)
from signal_index.storage import ObjectStorage
from signal_processing.config import PRESETS, VADPreset
from signal_processing.embeddings import MelStatisticsEmbedding
from signal_processing.entities import extract_entities
from signal_processing.features import RuleBasedClassifier, extract_features
from signal_processing.ffmpeg import MediaProcessError, create_preview, normalize_audio, probe
from signal_processing.vad import TimeRange, merge_and_split_ranges, silero_ranges
from sqlalchemy import select

from .artifacts import spectrogram_png, waveform_json
from .asr import transcribe
from .celery_app import celery

settings = get_settings()
log = structlog.get_logger()


def set_job(job_id: str, **values: Any) -> None:
    with SessionLocal.begin() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            raise RuntimeError(f"processing job {job_id} disappeared")
        for key, value in values.items():
            setattr(job, key, value)


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
        with tempfile.TemporaryDirectory(prefix="signal-index-") as temp_dir:
            root = Path(temp_dir)
            original = root / "original"
            original.write_bytes(storage.download(object_key))
            stage = "METADATA_EXTRACTION"
            set_job(job_id, stage=stage, progress=0.08)
            metadata = probe(original, settings.FFPROBE_PATH)
            processed = root / "processed.wav"
            stage = "NORMALIZE"
            normalize_audio(original, processed, PRESETS.get(mode, PRESETS["VOICE"]), settings.FFMPEG_PATH)
            preview = root / "preview.ogg"
            create_preview(processed, preview, settings.FFMPEG_PATH)
            processed_key = f"derived/{recording_id}/{settings.PIPELINE_VERSION}/processed.wav"
            preview_key = f"derived/{recording_id}/{settings.PIPELINE_VERSION}/preview.ogg"
            storage.upload(processed_key, processed.read_bytes(), "audio/wav")
            storage.upload(preview_key, preview.read_bytes(), "audio/ogg")
            samples, sample_rate = sf.read(processed, dtype="float32")
            samples = np.asarray(samples, dtype=np.float32)
            stage = "VAD"
            set_job(job_id, stage=stage, progress=0.25)
            vad_preset = VADPreset(threshold=settings.VAD_THRESHOLD)
            raw_ranges = silero_ranges(samples, sample_rate, vad_preset)
            if not raw_ranges:
                raw_ranges = energy_fallback(samples, sample_rate)
                log.warning("vad_energy_fallback", recording_id=recording_id)
            ranges = merge_and_split_ranges(raw_ranges, vad_preset, metadata.duration_sec)
            if not ranges:
                ranges = [TimeRange(0.0, metadata.duration_sec)]
            classifier = RuleBasedClassifier()
            embedder = MelStatisticsEmbedding()
            segment_ids: list[str] = []
            callsigns: set[str] = set()
            number_groups: set[str] = set()
            languages: set[str] = set()
            segment_vectors: list[np.ndarray] = []
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
                recording.processing_version = settings.PIPELINE_VERSION
                recording.processing_status = "PROCESSING"
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
                    base_key = f"derived/{recording_id}/{settings.PIPELINE_VERSION}/segments/{segment.id}"
                    segment_key = f"{base_key}.wav"
                    waveform_key = f"{base_key}.waveform.json"
                    spectrogram_key = f"{base_key}.spectrogram.png"
                    storage.upload(segment_key, segment_wav.read_bytes(), "audio/wav")
                    storage.upload(waveform_key, waveform_json(audio), "application/json")
                    storage.upload(spectrogram_key, spectrogram_png(audio, sample_rate), "image/png")
                    segment.processed_object_key = segment_key
                    segment.waveform_object_key = waveform_key
                    segment.spectrogram_object_key = spectrogram_key
                    vector = embedder.embed_audio(audio, sample_rate)
                    segment_vectors.append(vector)
                    db.add(
                        Embedding(
                            embedding_type="AUDIO",
                            source_type="SEGMENT",
                            source_id=segment.id,
                            model=embedder.name,
                            model_version=embedder.version,
                            dimension=embedder.dimension,
                            preprocessing_version=settings.PIPELINE_VERSION,
                            vector=vector.tolist(),
                        )
                    )
                    candidates = transcribe(segment_wav) if segment_type in {"VOICE", "UNKNOWN"} else []
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
                            pipeline_version=settings.PIPELINE_VERSION,
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
                    session_fingerprint=f"{recording.frequency_hz}:{recording.started_at_utc:%Y%m%d%H%M}",
                    confidence=0.68,
                    status="UNREVIEWED",
                )
                db.add(session)
                db.flush()
                for stored_entity in db.scalars(
                    select(ExtractedEntity).where(ExtractedEntity.segment_id.in_(segment_ids))
                ):
                    stored_entity.session_id = session.id
                if segment_vectors:
                    composite = np.mean(np.stack(segment_vectors), axis=0)
                    norm = float(np.linalg.norm(composite))
                    if norm:
                        composite /= norm
                    embedding = Embedding(
                        embedding_type="SESSION_COMPOSITE",
                        source_type="SESSION",
                        source_id=session.id,
                        model=embedder.name,
                        model_version=embedder.version,
                        dimension=embedder.dimension,
                        preprocessing_version=settings.PIPELINE_VERSION,
                        vector=composite.tolist(),
                    )
                    db.add(embedding)
                    db.flush()
                    session.session_embedding_id = embedding.id
                recording.processing_status = "COMPLETED"
                job = db.get(ProcessingJob, job_id)
                if job:
                    job.status = "COMPLETED"
                    job.stage = "INDEX_UPDATE"
                    job.progress = 1.0
                    job.finished_at = datetime.now(UTC)
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
        if self.request.retries >= self.max_retries:
            raise
        raise self.retry(
            exc=exc, countdown=min(300, 2 ** (self.request.retries + 1) * 10)
        ) from exc


@celery.task(name="audio_processor.tasks.capture_receiver")
def capture_receiver(capture_job_id: str) -> dict[str, str]:
    if not settings.CAPTURE_ENABLED:
        raise RuntimeError("capture is globally disabled")
    return {"capture_job_id": capture_job_id, "status": "scheduler acknowledged"}
