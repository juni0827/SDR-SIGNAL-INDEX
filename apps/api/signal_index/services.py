from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.orm import Session

from .models import (
    AudioSegment,
    ExtractedEntity,
    Provenance,
    Recording,
    Relation,
    Transcript,
    TransmissionSession,
)
from .schemas import ContextBundleRequest, SearchRequest
from .serialization import model_dict


def encode_cursor(created_at: datetime, record_id: str) -> str:
    raw = json.dumps([created_at.astimezone(UTC).isoformat(), record_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, record_id = json.loads(raw)
        return datetime.fromisoformat(stamp), str(record_id)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="invalid cursor") from exc


def cursor_page(
    db: Session, model: Any, filters: list[Any], request: SearchRequest
) -> tuple[list[Any], str | None]:
    statement = select(model).where(*filters)
    if request.cursor:
        stamp, record_id = decode_cursor(request.cursor)
        statement = statement.where(
            or_(model.created_at < stamp, and_(model.created_at == stamp, model.id < record_id))
        )
    rows = list(
        db.scalars(statement.order_by(model.created_at.desc(), model.id.desc()).limit(request.limit + 1))
    )
    next_cursor = None
    if len(rows) > request.limit:
        rows = rows[: request.limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, last.id)
    return rows, next_cursor


def search_sessions(db: Session, request: SearchRequest) -> tuple[list[dict[str, Any]], str | None]:
    filters: list[Any] = [TransmissionSession.deleted_at.is_(None)]
    if request.frequency_min_hz is not None:
        filters.append(TransmissionSession.primary_frequency_hz >= request.frequency_min_hz)
    if request.frequency_max_hz is not None:
        filters.append(TransmissionSession.primary_frequency_hz <= request.frequency_max_hz)
    if request.started_after:
        filters.append(TransmissionSession.start_at_utc >= request.started_after)
    if request.started_before:
        filters.append(TransmissionSession.start_at_utc <= request.started_before)
    if request.confidence_min is not None:
        filters.append(TransmissionSession.confidence >= request.confidence_min)
    if request.status:
        filters.append(TransmissionSession.status == request.status)
    if request.category:
        filters.append(TransmissionSession.category == request.category)
    if request.text:
        filters.append(TransmissionSession.title.ilike(f"%{request.text}%"))
    if request.callsign:
        filters.append(TransmissionSession.callsigns.cast(String).ilike(f"%{request.callsign.upper()}%"))
    if request.number_group:
        normalized = request.number_group.replace(" ", "").replace("-", "")
        filters.append(TransmissionSession.number_groups.cast(String).ilike(f"%{normalized}%"))
    rows, next_cursor = cursor_page(db, TransmissionSession, filters, request)
    return [model_dict(row) for row in rows], next_cursor


def search_segments(db: Session, request: SearchRequest) -> tuple[list[dict[str, Any]], str | None]:
    filters: list[Any] = [AudioSegment.deleted_at.is_(None)]
    if request.signal_class:
        filters.append(AudioSegment.segment_type == request.signal_class.upper())
    if request.confidence_min is not None:
        filters.append(AudioSegment.class_confidence >= request.confidence_min)
    if request.reviewed is not None:
        filters.append(AudioSegment.reviewed.is_(request.reviewed))
    if request.text:
        transcript_matches = select(Transcript.segment_id).where(
            func.to_tsvector("simple", func.coalesce(Transcript.normalized_text, "")).op("@@")(
                func.plainto_tsquery("simple", request.text)
            ),
            Transcript.deleted_at.is_(None),
        )
        filters.append(AudioSegment.id.in_(transcript_matches))
    if request.language:
        language_matches = select(Transcript.segment_id).where(
            Transcript.language == request.language,
            Transcript.deleted_at.is_(None),
        )
        filters.append(AudioSegment.id.in_(language_matches))
    if request.frequency_min_hz is not None or request.frequency_max_hz is not None:
        filters.append(AudioSegment.recording_id == Recording.id)
        if request.frequency_min_hz is not None:
            filters.append(Recording.frequency_hz >= request.frequency_min_hz)
        if request.frequency_max_hz is not None:
            filters.append(Recording.frequency_hz <= request.frequency_max_hz)
    rows, next_cursor = cursor_page(db, AudioSegment, filters, request)
    results: list[dict[str, Any]] = []
    for row in rows:
        item = model_dict(row)
        transcript = db.scalar(
            select(Transcript).where(
                Transcript.segment_id == row.id,
                Transcript.deleted_at.is_(None),
                Transcript.is_preferred.is_(True),
            )
        )
        item["preferred_transcript"] = model_dict(transcript) if transcript else None
        results.append(item)
    return results, next_cursor


def search_entities(db: Session, request: SearchRequest) -> tuple[list[dict[str, Any]], str | None]:
    filters: list[Any] = [ExtractedEntity.deleted_at.is_(None)]
    if request.text:
        filters.append(
            or_(
                ExtractedEntity.raw_value.ilike(f"%{request.text}%"),
                ExtractedEntity.normalized_value.ilike(f"%{request.text}%"),
                func.similarity(ExtractedEntity.normalized_value, request.text) >= 0.3,
            )
        )
    if request.callsign:
        filters.extend(
            [
                ExtractedEntity.entity_type == "CALLSIGN",
                ExtractedEntity.normalized_value.ilike(f"%{request.callsign.upper()}%"),
            ]
        )
    if request.number_group:
        normalized = request.number_group.replace(" ", "").replace("-", "")
        filters.append(ExtractedEntity.entity_type == "NUMBER_GROUP")
        if request.exact_number:
            filters.append(ExtractedEntity.normalized_value == normalized)
        else:
            filters.append(ExtractedEntity.normalized_value.ilike(f"%{normalized}%"))
    if request.confidence_min is not None:
        filters.append(ExtractedEntity.confidence >= request.confidence_min)
    rows, next_cursor = cursor_page(db, ExtractedEntity, filters, request)
    return [model_dict(row) for row in rows], next_cursor


def context_bundle(db: Session, request: ContextBundleRequest, app_url: str) -> dict[str, Any]:
    ids = [item for item in [request.subject_session_id, *request.comparison_session_ids] if item]
    sessions = list(
        db.scalars(
            select(TransmissionSession).where(
                TransmissionSession.id.in_(ids), TransmissionSession.deleted_at.is_(None)
            )
        )
    )
    include = set(request.include)
    output: list[dict[str, Any]] = []
    for session in sessions:
        item: dict[str, Any] = {
            "id": session.id,
            "permalink": f"{app_url}/sessions/{session.id}",
            "metadata": model_dict(session),
        }
        if "preferred_transcripts" in include:
            transcripts = list(
                db.scalars(
                    select(Transcript).where(
                        Transcript.segment_id.in_(session.segment_ids),
                        Transcript.is_preferred.is_(True),
                        Transcript.deleted_at.is_(None),
                    )
                )
            )
            item["preferred_transcripts"] = [model_dict(value) for value in transcripts]
        if "entities" in include:
            entities = list(
                db.scalars(
                    select(ExtractedEntity).where(
                        or_(
                            ExtractedEntity.session_id == session.id,
                            ExtractedEntity.segment_id.in_(session.segment_ids),
                        ),
                        ExtractedEntity.deleted_at.is_(None),
                    )
                )
            )
            item["entities"] = [model_dict(value) for value in entities]
        if "relations" in include:
            relations = list(
                db.scalars(
                    select(Relation).where(
                        or_(
                            and_(Relation.subject_type == "SESSION", Relation.subject_id == session.id),
                            and_(Relation.object_type == "SESSION", Relation.object_id == session.id),
                        ),
                        Relation.deleted_at.is_(None),
                    )
                )
            )
            item["relations"] = [model_dict(value) for value in relations]
        output.append(item)
    payload = {
        "task": request.task,
        "sessions": output,
        "raw_audio_included": False,
        "record_count": len(output),
    }
    encoded = json.dumps(payload, default=str, separators=(",", ":"))
    approximate_tokens = max(1, len(encoded) // 4)
    if approximate_tokens > request.token_budget:
        raise HTTPException(
            status_code=413,
            detail={"message": "context bundle exceeds token budget", "estimated_tokens": approximate_tokens},
        )
    return payload


def record_provenance(db: Session, record_type: str, record_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Provenance).where(
            Provenance.record_type == record_type,
            Provenance.record_id == record_id,
            Provenance.deleted_at.is_(None),
        )
    )
    return [model_dict(row) for row in rows]
