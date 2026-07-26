from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
from signal_index.config import Settings
from signal_index.models import Embedding, Recording, Revision, TransmissionSession
from signal_processing.session import MergeWeights, SessionFeatures, merge_score
from sqlalchemy import select
from sqlalchemy.orm import Session


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0 or left.shape != right.shape:
        return 0.0
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator == 0:
        return 0.0
    return max(0.0, min(1.0, float(np.dot(left, right) / denominator)))


def configured_weights(settings: Settings) -> MergeWeights:
    weights = MergeWeights(
        time=settings.SESSION_WEIGHT_TIME,
        frequency=settings.SESSION_WEIGHT_FREQUENCY,
        acoustic=settings.SESSION_WEIGHT_ACOUSTIC,
        callsign=settings.SESSION_WEIGHT_CALLSIGN,
        numbers=settings.SESSION_WEIGHT_NUMBERS,
        message=settings.SESSION_WEIGHT_MESSAGE,
    )
    total = sum(
        (
            weights.time,
            weights.frequency,
            weights.acoustic,
            weights.callsign,
            weights.numbers,
            weights.message,
        )
    )
    if total <= 0:
        raise ValueError("session merge weights must contain at least one positive value")
    return MergeWeights(
        time=weights.time / total,
        frequency=weights.frequency / total,
        acoustic=weights.acoustic / total,
        callsign=weights.callsign / total,
        numbers=weights.numbers / total,
        message=weights.message / total,
    )


def message_structure_similarity(
    left_callsigns: set[str],
    right_callsigns: set[str],
    left_numbers: set[str],
    right_numbers: set[str],
) -> float:
    left_shape = sorted(len(value) for value in left_numbers)
    right_shape = sorted(len(value) for value in right_numbers)
    shape_score = 1.0 if left_shape and left_shape == right_shape else 0.0
    callsign_score = 1.0 if left_callsigns and right_callsigns else 0.0
    return 0.7 * shape_score + 0.3 * callsign_score


def select_session(
    db: Session,
    *,
    recording: Recording,
    callsigns: set[str],
    number_groups: set[str],
    composite_vector: np.ndarray,
    settings: Settings,
) -> tuple[TransmissionSession | None, float, dict[str, float]]:
    earliest = recording.started_at_utc - timedelta(seconds=settings.SESSION_WINDOW_SEC)
    latest = recording.ended_at_utc + timedelta(seconds=settings.SESSION_WINDOW_SEC)
    candidates = list(
        db.scalars(
            select(TransmissionSession).where(
                TransmissionSession.deleted_at.is_(None),
                TransmissionSession.end_at_utc >= earliest,
                TransmissionSession.start_at_utc <= latest,
                TransmissionSession.primary_frequency_hz.between(
                    recording.frequency_hz - settings.SESSION_FREQUENCY_WINDOW_HZ,
                    recording.frequency_hz + settings.SESSION_FREQUENCY_WINDOW_HZ,
                ),
            )
        )
    )
    weights = configured_weights(settings)
    best: TransmissionSession | None = None
    best_score = 0.0
    best_evidence: dict[str, float] = {}
    for candidate in candidates:
        embedding = db.scalar(
            select(Embedding).where(
                Embedding.source_type == "SESSION",
                Embedding.source_id == candidate.id,
                Embedding.embedding_type == "SESSION_COMPOSITE",
                Embedding.deleted_at.is_(None),
            )
        )
        acoustic = (
            cosine_similarity(np.asarray(embedding.vector, dtype=np.float32), composite_vector)
            if embedding is not None
            else 0.0
        )
        structure = message_structure_similarity(
            set(candidate.callsigns), callsigns, set(candidate.number_groups), number_groups
        )
        existing = SessionFeatures(
            observed_at=candidate.start_at_utc,
            frequency_hz=candidate.primary_frequency_hz,
            receiver_id=candidate.receiver_ids[0] if candidate.receiver_ids else None,
            acoustic_similarity=0.0,
            callsigns=frozenset(candidate.callsigns),
            number_groups=frozenset(candidate.number_groups),
            message_structure_similarity=0.0,
        )
        incoming = SessionFeatures(
            observed_at=recording.started_at_utc,
            frequency_hz=recording.frequency_hz,
            receiver_id=recording.receiver_id,
            acoustic_similarity=acoustic,
            callsigns=frozenset(callsigns),
            number_groups=frozenset(number_groups),
            message_structure_similarity=structure,
        )
        score = merge_score(existing, incoming, weights)
        if score > best_score:
            best = candidate
            best_score = score
            best_evidence = {
                "merge_score": score,
                "acoustic_similarity": acoustic,
                "message_structure_similarity": structure,
            }
    if best_score < settings.SESSION_MERGE_THRESHOLD:
        return None, best_score, best_evidence
    return best, best_score, best_evidence


def merge_into_session(
    db: Session,
    *,
    session: TransmissionSession,
    recording: Recording,
    segment_ids: list[str],
    callsigns: set[str],
    number_groups: set[str],
    languages: set[str],
    merge_score_value: float,
    evidence: dict[str, float],
) -> TransmissionSession:
    before = {
        "start_at_utc": session.start_at_utc.isoformat(),
        "end_at_utc": session.end_at_utc.isoformat(),
        "recording_ids": list(session.recording_ids),
        "segment_ids": list(session.segment_ids),
    }
    session.start_at_utc = min(session.start_at_utc, recording.started_at_utc)
    session.end_at_utc = max(session.end_at_utc, recording.ended_at_utc)
    session.frequencies_hz = sorted(set(session.frequencies_hz) | {recording.frequency_hz})
    session.receiver_ids = sorted(
        set(session.receiver_ids) | ({recording.receiver_id} if recording.receiver_id else set())
    )
    session.recording_ids = list(dict.fromkeys([*session.recording_ids, recording.id]))
    session.segment_ids = list(dict.fromkeys([*session.segment_ids, *segment_ids]))
    session.callsigns = sorted(set(session.callsigns) | callsigns)
    session.number_groups = sorted(set(session.number_groups) | number_groups)
    session.languages = sorted(set(session.languages) | languages)
    session.confidence = min(1.0, max(session.confidence, merge_score_value))
    db.add(
        Revision(
            record_type="SESSION",
            record_id=session.id,
            actor_type="MACHINE",
            before=before,
            after={
                "recording_ids": list(session.recording_ids),
                "segment_ids": list(session.segment_ids),
                "merge_score": merge_score_value,
                **evidence,
            },
            reason="automatic rule-engine merge",
        )
    )
    return session


def replace_session_embedding(
    db: Session,
    *,
    session: TransmissionSession,
    vector: np.ndarray,
    model: str,
    model_version: str,
    preprocessing_version: str,
) -> Embedding:
    for previous in db.scalars(
        select(Embedding).where(
            Embedding.source_type == "SESSION",
            Embedding.source_id == session.id,
            Embedding.embedding_type == "SESSION_COMPOSITE",
            Embedding.deleted_at.is_(None),
        )
    ):
        previous.deleted_at = datetime.now(UTC)
    embedding = Embedding(
        embedding_type="SESSION_COMPOSITE",
        source_type="SESSION",
        source_id=session.id,
        model=model,
        model_version=model_version,
        dimension=int(vector.size),
        preprocessing_version=preprocessing_version,
        vector=vector.tolist(),
    )
    db.add(embedding)
    db.flush()
    session.session_embedding_id = embedding.id
    return embedding
