from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.orm import Session

from .models import (
    Annotation,
    AudioSegment,
    ExternalEvent,
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
    if request.receiver_id:
        filters.append(
            TransmissionSession.receiver_ids.cast(String).ilike(f"%{request.receiver_id}%")
        )
    if request.duration_min_sec is not None:
        filters.append(
            func.extract("epoch", TransmissionSession.end_at_utc - TransmissionSession.start_at_utc)
            >= request.duration_min_sec
        )
    if request.duration_max_sec is not None:
        filters.append(
            func.extract("epoch", TransmissionSession.end_at_utc - TransmissionSession.start_at_utc)
            <= request.duration_max_sec
        )
    if request.text:
        filters.append(
            or_(
                TransmissionSession.title.ilike(f"%{request.text}%"),
                TransmissionSession.callsigns.cast(String).ilike(
                    f"%{request.text.upper()}%"
                ),
                TransmissionSession.number_groups.cast(String).ilike(
                    f"%{request.text.replace(' ', '').replace('-', '')}%"
                ),
            )
        )
    if request.callsign:
        filters.append(TransmissionSession.callsigns.cast(String).ilike(f"%{request.callsign.upper()}%"))
    if request.number_group:
        normalized = request.number_group.replace(" ", "").replace("-", "")
        filters.append(TransmissionSession.number_groups.cast(String).ilike(f"%{normalized}%"))
    if request.tags:
        tagged = select(Annotation.target_id).where(
            Annotation.target_type == "SESSION",
            Annotation.deleted_at.is_(None),
            *[
                Annotation.tags.cast(String).ilike(f"%{tag}%")
                for tag in request.tags
            ],
        )
        filters.append(TransmissionSession.id.in_(tagged))
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
    if request.duration_min_sec is not None:
        filters.append(AudioSegment.duration_sec >= request.duration_min_sec)
    if request.duration_max_sec is not None:
        filters.append(AudioSegment.duration_sec <= request.duration_max_sec)
    if request.snr_min_db is not None:
        filters.append(AudioSegment.snr_db >= request.snr_min_db)
    if request.snr_max_db is not None:
        filters.append(AudioSegment.snr_db <= request.snr_max_db)
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
    if request.transcript_confidence_max is not None:
        low_confidence_matches = select(Transcript.segment_id).where(
            Transcript.confidence <= request.transcript_confidence_max,
            Transcript.deleted_at.is_(None),
        )
        filters.append(AudioSegment.id.in_(low_confidence_matches))
    recording_filter_required = any(
        value is not None
        for value in (
            request.frequency_min_hz,
            request.frequency_max_hz,
            request.receiver_id,
            request.mode,
            request.source,
            request.started_after,
            request.started_before,
        )
    )
    if recording_filter_required:
        filters.append(AudioSegment.recording_id == Recording.id)
        if request.frequency_min_hz is not None:
            filters.append(Recording.frequency_hz >= request.frequency_min_hz)
        if request.frequency_max_hz is not None:
            filters.append(Recording.frequency_hz <= request.frequency_max_hz)
        if request.receiver_id:
            filters.append(Recording.receiver_id == request.receiver_id)
        if request.mode:
            filters.append(Recording.mode == request.mode.upper())
        if request.source:
            filters.append(Recording.source_type == request.source.upper())
        if request.started_after:
            filters.append(Recording.started_at_utc >= request.started_after)
        if request.started_before:
            filters.append(Recording.started_at_utc <= request.started_before)
    if request.tags:
        tagged = select(Annotation.target_id).where(
            Annotation.target_type == "SEGMENT",
            Annotation.deleted_at.is_(None),
            *[
                Annotation.tags.cast(String).ilike(f"%{tag}%")
                for tag in request.tags
            ],
        )
        filters.append(AudioSegment.id.in_(tagged))
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
        match_mode = request.number_match or ("exact" if request.exact_number else "normalized")
        if match_mode == "exact":
            filters.append(ExtractedEntity.normalized_value == normalized)
        elif match_mode == "fuzzy":
            filters.append(func.similarity(ExtractedEntity.normalized_value, normalized) >= 0.3)
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
            item["preferred_transcripts"] = [
                {
                    "id": value.id,
                    "segment_id": value.segment_id,
                    "language": value.language,
                    "text": value.text[:4_000],
                    "confidence": value.confidence,
                    "permalink": f"{app_url}/segments/{value.segment_id}",
                }
                for value in transcripts
            ]
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
        if "audio_feature_summary" in include:
            segments = list(
                db.scalars(
                    select(AudioSegment).where(
                        AudioSegment.id.in_(session.segment_ids),
                        AudioSegment.deleted_at.is_(None),
                    )
                )
            )
            item["audio_feature_summary"] = {
                "segment_count": len(segments),
                "duration_sec": sum(value.duration_sec for value in segments),
                "mean_snr_db": (
                    sum(value.snr_db for value in segments if value.snr_db is not None)
                    / max(1, sum(value.snr_db is not None for value in segments))
                ),
                "signal_classes": sorted({value.segment_type for value in segments}),
                "feature_records": [
                    {
                        "segment_id": value.id,
                        "snr_db": value.snr_db,
                        "rms_energy": value.rms_energy,
                        "spectral_centroid": value.spectral_centroid,
                        "spectral_flatness": value.spectral_flatness,
                        "bandwidth_hz": value.bandwidth_hz,
                        "zero_crossing_rate": value.zero_crossing_rate,
                        "permalink": f"{app_url}/segments/{value.id}",
                    }
                    for value in segments[:50]
                ],
            }
        if "external_events" in include:
            event_relations = list(
                db.scalars(
                    select(Relation).where(
                        Relation.subject_type == "SESSION",
                        Relation.subject_id == session.id,
                        Relation.object_type == "EVENT",
                        Relation.deleted_at.is_(None),
                    )
                )
            )
            event_ids = [relation.object_id for relation in event_relations]
            events = list(
                db.scalars(
                    select(ExternalEvent).where(
                        ExternalEvent.id.in_(event_ids),
                        ExternalEvent.deleted_at.is_(None),
                    )
                )
            )
            item["external_events"] = [
                {
                    **model_dict(event),
                    "permalink": f"{app_url}/events/{event.id}",
                }
                for event in events
            ]
        if "provenance" in include:
            provenance_types = [
                ("SESSION", [session.id]),
                ("RECORDING", list(session.recording_ids)),
                ("SEGMENT", list(session.segment_ids)),
            ]
            provenance: list[dict[str, Any]] = []
            for record_type, record_ids in provenance_types:
                provenance.extend(
                    model_dict(value)
                    for value in db.scalars(
                        select(Provenance).where(
                            Provenance.record_type == record_type,
                            Provenance.record_id.in_(record_ids),
                            Provenance.deleted_at.is_(None),
                        )
                    )
                )
            item["provenance"] = provenance
        output.append(item)
    payload = {
        "task": request.task,
        "sessions": output,
        "raw_audio_included": False,
        "record_count": len(output),
    }
    encoded = json.dumps(payload, default=str, separators=(",", ":"))
    approximate_tokens = max(1, len(encoded) // 4)
    truncated = False
    while approximate_tokens > request.token_budget and len(output) > 1:
        output.pop()
        truncated = True
        encoded = json.dumps(payload, default=str, separators=(",", ":"))
        approximate_tokens = max(1, len(encoded) // 4)
    if approximate_tokens > request.token_budget:
        for item in output:
            if "preferred_transcripts" in item:
                item["preferred_transcripts"] = [
                    {**transcript, "text": str(transcript["text"])[:500]}
                    for transcript in item["preferred_transcripts"]
                ]
            if "provenance" in item:
                item["provenance"] = item["provenance"][:20]
            if "entities" in item:
                item["entities"] = item["entities"][:50]
            if "relations" in item:
                item["relations"] = item["relations"][:50]
        truncated = True
        encoded = json.dumps(payload, default=str, separators=(",", ":"))
        approximate_tokens = max(1, len(encoded) // 4)
    payload["estimated_tokens"] = approximate_tokens
    payload["truncated_to_token_budget"] = truncated
    if approximate_tokens > request.token_budget:
        payload["budget_warning"] = (
            "Subject metadata alone exceeds the requested budget; IDs and permalinks were preserved."
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
