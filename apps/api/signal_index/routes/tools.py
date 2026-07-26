from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from signal_processing.analytics import ActivityPoint, summarize_activity
from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..dependencies import CurrentUser
from ..models import (
    Annotation,
    AudioSegment,
    CaptureJob,
    Embedding,
    ExternalEvent,
    ExtractedEntity,
    Hypothesis,
    HypothesisHistory,
    InboxItem,
    ProcessingJob,
    Provenance,
    Receiver,
    Recording,
    Relation,
    Revision,
    SavedQuery,
    Transcript,
    TransmissionSession,
)
from ..schemas import (
    AnnotationCreate,
    ContextBundleRequest,
    CorrelationRequest,
    Envelope,
    HypothesisCreate,
    HypothesisPatch,
    LocalLLMRequest,
    RelationCreate,
    SearchRequest,
    SegmentClassification,
    SegmentMerge,
    SegmentReview,
    SegmentSplit,
    TranscriptCorrection,
)
from ..secrets_store import resolved_secret
from ..serialization import model_dict
from ..services import (
    context_bundle,
    cursor_page,
    record_provenance,
    search_entities,
    search_segments,
    search_sessions,
)
from ..storage import ObjectStorage

router = APIRouter(tags=["local LLM tools"])


def missing(name: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{name} not found")


@router.post("/local-llm/chat", response_model=Envelope[dict[str, Any]])
def local_llm_chat(
    payload: LocalLLMRequest,
    _user: CurrentUser,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, Any]]:
    if not settings.LOCAL_LLM_ENABLED:
        raise HTTPException(status_code=409, detail="local LLM integration is disabled")
    if not settings.LOCAL_LLM_MODEL:
        raise HTTPException(status_code=503, detail="LOCAL_LLM_MODEL is not configured")
    api_key = resolved_secret(
        db,
        settings,
        "local_llm.api_key",
        settings.LOCAL_LLM_API_KEY.get_secret_value(),
    )
    body = {
        "model": settings.LOCAL_LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are analyzing Signal Index evidence. Distinguish observed facts, "
                    "machine results, user interpretation, and hypotheses. Do not infer causality "
                    "from temporal order."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": payload.task,
                        "prompt": payload.prompt,
                        "context": payload.context,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
        "max_tokens": payload.max_tokens,
        "temperature": payload.temperature,
    }
    try:
        response = httpx.post(
            f"{settings.LOCAL_LLM_BASE_URL.rstrip('/')}/chat/completions",
            headers={"authorization": f"Bearer {api_key}"},
            json=body,
            timeout=120,
        )
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="local LLM endpoint failed") from exc
    return Envelope(
        data={
            "task": payload.task,
            "content": content,
            "model": result.get("model", settings.LOCAL_LLM_MODEL),
            "layer": "LOCAL_LLM_HYPOTHESIS",
        },
        query={"task": payload.task, "max_tokens": payload.max_tokens},
        warnings=[
            "This is local-LLM generated analysis, not an observed fact. It does not overwrite source records."
        ],
    )


@router.post("/search/sessions", response_model=Envelope[list[dict[str, Any]]])
def sessions_search(payload: SearchRequest, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[list[dict[str, Any]]]:
    data, cursor = search_sessions(db, payload)
    return Envelope(data=data, query=payload.model_dump(mode="json"), pagination={"next_cursor": cursor})


@router.post("/search/segments", response_model=Envelope[list[dict[str, Any]]])
def segments_search(payload: SearchRequest, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[list[dict[str, Any]]]:
    data, cursor = search_segments(db, payload)
    return Envelope(data=data, query=payload.model_dump(mode="json"), pagination={"next_cursor": cursor})


@router.post("/search/entities", response_model=Envelope[list[dict[str, Any]]])
def entities_search(payload: SearchRequest, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[list[dict[str, Any]]]:
    data, cursor = search_entities(db, payload)
    return Envelope(data=data, query=payload.model_dump(mode="json"), pagination={"next_cursor": cursor})


@router.post("/search/relations", response_model=Envelope[list[dict[str, Any]]])
def relations_search(payload: SearchRequest, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[list[dict[str, Any]]]:
    filters: list[Any] = [Relation.deleted_at.is_(None)]
    if payload.text:
        filters.append(Relation.predicate.ilike(f"%{payload.text}%"))
    if payload.confidence_min is not None:
        filters.append(Relation.confidence >= payload.confidence_min)
    if payload.status:
        filters.append(Relation.relation_status == payload.status)
    rows, cursor = cursor_page(db, Relation, filters, payload)
    return Envelope(
        data=[model_dict(row) for row in rows],
        query=payload.model_dump(mode="json"),
        pagination={"next_cursor": cursor},
    )


@router.post("/search/events", response_model=Envelope[list[dict[str, Any]]])
def events_search(payload: SearchRequest, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[list[dict[str, Any]]]:
    filters: list[Any] = [ExternalEvent.deleted_at.is_(None)]
    if payload.text:
        filters.append(
            or_(
                ExternalEvent.title.ilike(f"%{payload.text}%"),
                ExternalEvent.description.ilike(f"%{payload.text}%"),
            )
        )
    if payload.started_after:
        filters.append(ExternalEvent.started_at_utc >= payload.started_after)
    if payload.started_before:
        filters.append(ExternalEvent.started_at_utc <= payload.started_before)
    if payload.confidence_min is not None:
        filters.append(ExternalEvent.confidence >= payload.confidence_min)
    rows, cursor = cursor_page(db, ExternalEvent, filters, payload)
    return Envelope(
        data=[model_dict(row) for row in rows],
        query=payload.model_dump(mode="json"),
        pagination={"next_cursor": cursor},
    )


@router.get("/sessions/{session_id}", response_model=Envelope[dict[str, Any]])
def session_detail(session_id: str, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[dict[str, Any]]:
    session = db.get(TransmissionSession, session_id)
    if session is None or session.deleted_at is not None:
        raise missing("session")
    transcripts = list(
        db.scalars(
            select(Transcript).where(
                Transcript.segment_id.in_(session.segment_ids), Transcript.deleted_at.is_(None)
            )
        )
    )
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
    data = model_dict(session)
    data.update(
        transcripts=[model_dict(row) for row in transcripts],
        entities=[model_dict(row) for row in entities],
        relations=[model_dict(row) for row in relations],
        permalink=f"/sessions/{session.id}",
    )
    return Envelope(data=data, provenance=record_provenance(db, "SESSION", session.id))


@router.get("/segments/{segment_id}", response_model=Envelope[dict[str, Any]])
def segment_detail(segment_id: str, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[dict[str, Any]]:
    segment = db.get(AudioSegment, segment_id)
    if segment is None or segment.deleted_at is not None:
        raise missing("segment")
    transcripts = list(
        db.scalars(
            select(Transcript).where(
                Transcript.segment_id == segment_id, Transcript.deleted_at.is_(None)
            )
        )
    )
    entities = list(
        db.scalars(
            select(ExtractedEntity).where(
                ExtractedEntity.segment_id == segment_id, ExtractedEntity.deleted_at.is_(None)
            )
        )
    )
    data = model_dict(segment)
    data["transcripts"] = [model_dict(row) for row in transcripts]
    data["entities"] = [model_dict(row) for row in entities]
    data["permalink"] = f"/segments/{segment.id}"
    return Envelope(data=data, provenance=record_provenance(db, "SEGMENT", segment.id))


@router.get("/segments/{segment_id}/media", response_model=Envelope[dict[str, str | None]])
def segment_media(
    segment_id: str,
    _user: CurrentUser,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, str | None]]:
    segment = db.get(AudioSegment, segment_id)
    if segment is None or segment.deleted_at is not None:
        raise missing("segment")
    storage = ObjectStorage(settings)
    return Envelope(
        data={
            "processed_url": (
                storage.signed_get_url(segment.processed_object_key)
                if segment.processed_object_key
                else None
            ),
            "waveform_url": (
                storage.signed_get_url(segment.waveform_object_key)
                if segment.waveform_object_key
                else None
            ),
            "spectrogram_url": (
                storage.signed_get_url(segment.spectrogram_object_key)
                if segment.spectrogram_object_key
                else None
            ),
        }
    )


@router.patch("/segments/{segment_id}/review", response_model=Envelope[dict[str, Any]])
def review_segment(
    segment_id: str,
    payload: SegmentReview,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    segment = db.get(AudioSegment, segment_id)
    if segment is None or segment.deleted_at is not None:
        raise missing("segment")
    before = {"reviewed": segment.reviewed}
    segment.reviewed = payload.reviewed
    db.add(
        Revision(
            record_type="SEGMENT",
            record_id=segment.id,
            actor_type="USER",
            actor_id=user.id,
            before=before,
            after={"reviewed": segment.reviewed},
            reason="manual review state",
        )
    )
    db.commit()
    return Envelope(data=model_dict(segment))


@router.patch("/segments/{segment_id}/classification", response_model=Envelope[dict[str, Any]])
def classify_segment(
    segment_id: str,
    payload: SegmentClassification,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    segment = db.get(AudioSegment, segment_id)
    if segment is None or segment.deleted_at is not None:
        raise missing("segment")
    before = {
        "segment_type": segment.segment_type,
        "class_confidence": segment.class_confidence,
    }
    segment.segment_type = payload.segment_type
    segment.class_confidence = 1.0
    segment.manually_adjusted = True
    segment.class_features = {
        **segment.class_features,
        "manual_override": True,
        "manual_reason": payload.reason,
    }
    db.add(
        Revision(
            record_type="SEGMENT",
            record_id=segment.id,
            actor_type="USER",
            actor_id=user.id,
            before=before,
            after={
                "segment_type": segment.segment_type,
                "class_confidence": segment.class_confidence,
            },
            reason=payload.reason or "manual signal classification",
        )
    )
    db.commit()
    return Envelope(data=model_dict(segment))


@router.post("/segments/{segment_id}/transcripts", response_model=Envelope[dict[str, Any]])
def correct_transcript(
    segment_id: str,
    payload: TranscriptCorrection,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    segment = db.get(AudioSegment, segment_id)
    if segment is None or segment.deleted_at is not None:
        raise missing("segment")
    previous = db.scalar(
        select(Transcript).where(
            Transcript.segment_id == segment_id,
            Transcript.is_preferred.is_(True),
            Transcript.deleted_at.is_(None),
        )
    )
    if payload.mark_preferred:
        for candidate in db.scalars(
            select(Transcript).where(Transcript.segment_id == segment_id)
        ):
            candidate.is_preferred = False
    transcript = Transcript(
        segment_id=segment_id,
        transcript_type="MANUAL_CORRECTED",
        language=payload.language or (previous.language if previous else None),
        text=payload.text,
        normalized_text=payload.text.casefold().strip(),
        confidence=1.0,
        is_preferred=payload.mark_preferred,
        created_by=user.id,
        parent_transcript_id=previous.id if previous else None,
    )
    db.add(transcript)
    db.flush()
    db.add(
        Provenance(
            record_type="TRANSCRIPT",
            record_id=transcript.id,
            first_observed_at=transcript.created_at,
            confidence=1.0,
            manually_corrected=True,
        )
    )
    db.commit()
    return Envelope(
        data=model_dict(transcript),
        warnings=["machine candidates were preserved and were not overwritten"],
    )


@router.patch("/transcripts/{transcript_id}/preferred", response_model=Envelope[dict[str, Any]])
def prefer_transcript(
    transcript_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    transcript = db.get(Transcript, transcript_id)
    if transcript is None or transcript.deleted_at is not None:
        raise missing("transcript")
    candidates = list(
        db.scalars(
            select(Transcript).where(
                Transcript.segment_id == transcript.segment_id,
                Transcript.deleted_at.is_(None),
            )
        )
    )
    previous = next((row.id for row in candidates if row.is_preferred), None)
    for candidate in candidates:
        candidate.is_preferred = candidate.id == transcript.id
    db.add(
        Revision(
            record_type="SEGMENT",
            record_id=transcript.segment_id,
            actor_type="USER",
            actor_id=user.id,
            before={"preferred_transcript_id": previous},
            after={"preferred_transcript_id": transcript.id},
            reason="preferred transcript candidate selected",
        )
    )
    db.commit()
    return Envelope(data=model_dict(transcript))


def replace_session_segment_ids(
    db: Session,
    *,
    removed_ids: list[str],
    replacement_ids: list[str],
    user_id: str,
    reason: str,
) -> None:
    sessions = list(
        db.scalars(
            select(TransmissionSession).where(
                TransmissionSession.deleted_at.is_(None),
                or_(
                    *[
                        TransmissionSession.segment_ids.contains([segment_id])
                        for segment_id in removed_ids
                    ]
                ),
            )
        )
    )
    removed = set(removed_ids)
    for session in sessions:
        before = list(session.segment_ids)
        updated: list[str] = []
        inserted = False
        for segment_id in before:
            if segment_id in removed:
                if not inserted:
                    updated.extend(replacement_ids)
                    inserted = True
            else:
                updated.append(segment_id)
        session.segment_ids = list(dict.fromkeys(updated))
        db.add(
            Revision(
                record_type="SESSION",
                record_id=session.id,
                actor_type="USER",
                actor_id=user_id,
                before={"segment_ids": before},
                after={"segment_ids": session.segment_ids},
                reason=reason,
            )
        )


@router.post("/segments/{segment_id}/split", response_model=Envelope[list[dict[str, Any]]])
def split_segment(
    segment_id: str,
    payload: SegmentSplit,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    segment = db.get(AudioSegment, segment_id)
    if segment is None or segment.deleted_at is not None:
        raise missing("segment")
    if not segment.start_sec < payload.at_sec < segment.end_sec:
        raise HTTPException(status_code=422, detail="split point must be inside the segment")
    values = {
        "recording_id": segment.recording_id,
        "segment_type": segment.segment_type,
        "class_confidence": segment.class_confidence,
        "class_features": segment.class_features,
        "snr_db": segment.snr_db,
        "rms_energy": segment.rms_energy,
        "spectral_centroid": segment.spectral_centroid,
        "spectral_flatness": segment.spectral_flatness,
        "bandwidth_hz": segment.bandwidth_hz,
        "zero_crossing_rate": segment.zero_crossing_rate,
        "manually_adjusted": True,
    }
    left = AudioSegment(
        **values,
        start_sec=segment.start_sec,
        end_sec=payload.at_sec,
        duration_sec=payload.at_sec - segment.start_sec,
    )
    right = AudioSegment(
        **values,
        start_sec=payload.at_sec,
        end_sec=segment.end_sec,
        duration_sec=segment.end_sec - payload.at_sec,
    )
    segment.deleted_at = datetime.now(UTC)
    db.add_all([left, right])
    db.flush()
    source_transcripts = list(
        db.scalars(
            select(Transcript).where(
                Transcript.segment_id == segment.id,
                Transcript.deleted_at.is_(None),
            )
        )
    )
    for child in (left, right):
        for source_transcript in source_transcripts:
            db.add(
                Transcript(
                    segment_id=child.id,
                    transcript_type="ALTERNATIVE",
                    language=source_transcript.language,
                    text=source_transcript.text,
                    normalized_text=source_transcript.normalized_text,
                    model_name=source_transcript.model_name,
                    model_version=f"{source_transcript.model_version or 'manual'}:boundary-copy",
                    confidence=min(0.5, source_transcript.confidence or 0.5),
                    word_timestamps=[],
                    is_preferred=False,
                    parent_transcript_id=source_transcript.id,
                )
            )
        db.add(
            Relation(
                subject_type="SEGMENT",
                subject_id=child.id,
                predicate="DERIVED_FROM",
                object_type="SEGMENT",
                object_id=segment.id,
                confidence=1.0,
                relation_status="USER_ASSERTED",
                causal_claim=False,
                evidence_ids=[segment.id],
                created_by=user.id,
            )
        )
    replace_session_segment_ids(
        db,
        removed_ids=[segment.id],
        replacement_ids=[left.id, right.id],
        user_id=user.id,
        reason="manual segment split propagated to session",
    )
    db.add(
        Revision(
            record_type="SEGMENT",
            record_id=segment.id,
            actor_type="USER",
            actor_id=user.id,
            before={"segment_id": segment.id, "start_sec": segment.start_sec, "end_sec": segment.end_sec},
            after={"segment_ids": [left.id, right.id], "split_at_sec": payload.at_sec},
            reason="manual split",
        )
    )
    db.commit()
    return Envelope(
        data=[model_dict(left), model_dict(right)],
        warnings=["Derived media artifacts must be regenerated for the new boundaries."],
    )


@router.post("/segments/merge", response_model=Envelope[dict[str, Any]])
def merge_segments(
    payload: SegmentMerge,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    segments = list(
        db.scalars(
            select(AudioSegment)
            .where(
                AudioSegment.id.in_(payload.segment_ids), AudioSegment.deleted_at.is_(None)
            )
            .order_by(AudioSegment.start_sec)
        )
    )
    if len(segments) != len(set(payload.segment_ids)):
        raise HTTPException(status_code=404, detail="one or more segments were not found")
    if len({item.recording_id for item in segments}) != 1:
        raise HTTPException(status_code=422, detail="segments must belong to the same recording")
    for left, right in zip(segments, segments[1:], strict=False):
        if right.start_sec - left.end_sec > 1.0:
            raise HTTPException(status_code=422, detail="segments must be adjacent within one second")
    merged = AudioSegment(
        recording_id=segments[0].recording_id,
        start_sec=segments[0].start_sec,
        end_sec=segments[-1].end_sec,
        duration_sec=segments[-1].end_sec - segments[0].start_sec,
        segment_type=segments[0].segment_type
        if len({item.segment_type for item in segments}) == 1
        else "UNKNOWN",
        class_confidence=sum(item.class_confidence for item in segments) / len(segments),
        class_features={"manual_merge": True, "source_segment_ids": payload.segment_ids},
        snr_db=sum(item.snr_db or 0 for item in segments) / len(segments),
        manually_adjusted=True,
    )
    db.add(merged)
    db.flush()
    preferred_parts: list[Transcript] = []
    for source_segment in segments:
        preferred = db.scalar(
            select(Transcript).where(
                Transcript.segment_id == source_segment.id,
                Transcript.is_preferred.is_(True),
                Transcript.deleted_at.is_(None),
            )
        )
        if preferred:
            preferred_parts.append(preferred)
    if preferred_parts:
        db.add(
            Transcript(
                segment_id=merged.id,
                transcript_type="ALTERNATIVE",
                language=preferred_parts[0].language,
                text=" ".join(part.text for part in preferred_parts),
                normalized_text=" ".join(
                    part.normalized_text or part.text.casefold().strip()
                    for part in preferred_parts
                ),
                model_name="manual-boundary-merge",
                model_version="1.0.0",
                confidence=min(part.confidence or 0.5 for part in preferred_parts),
                word_timestamps=[],
                is_preferred=False,
                parent_transcript_id=preferred_parts[0].id,
            )
        )
    for segment in segments:
        segment.deleted_at = datetime.now(UTC)
        db.add(
            Relation(
                subject_type="SEGMENT",
                subject_id=merged.id,
                predicate="DERIVED_FROM",
                object_type="SEGMENT",
                object_id=segment.id,
                confidence=1.0,
                relation_status="USER_ASSERTED",
                causal_claim=False,
                evidence_ids=[segment.id],
                created_by=user.id,
            )
        )
    replace_session_segment_ids(
        db,
        removed_ids=[segment.id for segment in segments],
        replacement_ids=[merged.id],
        user_id=user.id,
        reason="manual segment merge propagated to session",
    )
    db.add(
        Revision(
            record_type="SEGMENT",
            record_id=merged.id,
            actor_type="USER",
            actor_id=user.id,
            before={"segment_ids": payload.segment_ids},
            after={"segment_id": merged.id, "start_sec": merged.start_sec, "end_sec": merged.end_sec},
            reason="manual merge",
        )
    )
    db.commit()
    return Envelope(
        data=model_dict(merged),
        warnings=[
            "Source segments and transcripts remain preserved; merged transcript is an unpreferred alternative pending review.",
            "Derived media artifacts must be regenerated for the merged boundary.",
        ],
    )


@router.get("/recordings/{recording_id}", response_model=Envelope[dict[str, Any]])
def recording_detail(recording_id: str, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[dict[str, Any]]:
    recording = db.get(Recording, recording_id)
    if recording is None or recording.deleted_at is not None:
        raise missing("recording")
    segments = list(
        db.scalars(
            select(AudioSegment)
            .where(AudioSegment.recording_id == recording_id, AudioSegment.deleted_at.is_(None))
            .order_by(AudioSegment.start_sec)
        )
    )
    data = model_dict(recording)
    data["segments"] = [model_dict(row) for row in segments]
    data["permalink"] = f"/recordings/{recording.id}"
    return Envelope(data=data, provenance=record_provenance(db, "RECORDING", recording.id))


@router.get("/frequencies/{frequency_hz}/activity", response_model=Envelope[dict[str, Any]])
def frequency_activity(
    frequency_hz: int,
    _user: CurrentUser,
    tolerance_hz: int = Query(default=0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    sessions = list(
        db.scalars(
            select(TransmissionSession)
            .where(
                TransmissionSession.primary_frequency_hz.between(
                    frequency_hz - tolerance_hz, frequency_hz + tolerance_hz
                ),
                TransmissionSession.deleted_at.is_(None),
            )
            .order_by(TransmissionSession.start_at_utc.desc())
            .limit(500)
        )
    )
    return Envelope(
        data={
            "frequency_hz": frequency_hz,
            "tolerance_hz": tolerance_hz,
            "session_count": len(sessions),
            "active_duration_sec": sum(
                (row.end_at_utc - row.start_at_utc).total_seconds() for row in sessions
            ),
            "sessions": [model_dict(row) for row in sessions],
        },
        query={"frequency_hz": frequency_hz, "tolerance_hz": tolerance_hz},
    )


@router.get("/entities/{entity_id}/relations", response_model=Envelope[list[dict[str, Any]]])
def entity_relations(entity_id: str, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[list[dict[str, Any]]]:
    entity = db.get(ExtractedEntity, entity_id)
    if entity is None or entity.deleted_at is not None:
        raise missing("entity")
    rows = list(
        db.scalars(
            select(Relation).where(
                or_(Relation.subject_id == entity_id, Relation.object_id == entity_id),
                Relation.deleted_at.is_(None),
            )
        )
    )
    return Envelope(data=[model_dict(row) for row in rows])


@router.get("/sessions/{session_id}/similar", response_model=Envelope[list[dict[str, Any]]])
def similar_sessions(
    session_id: str,
    _user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    subject = db.get(TransmissionSession, session_id)
    if subject is None or subject.deleted_at is not None:
        raise missing("session")
    subject_embedding = db.scalar(
        select(Embedding).where(
            Embedding.source_type == "SESSION",
            Embedding.source_id == session_id,
            Embedding.embedding_type == "SESSION_COMPOSITE",
        )
    )
    results: list[dict[str, Any]] = []
    if subject_embedding:
        nearest = db.execute(
            select(Embedding, Embedding.vector.cosine_distance(subject_embedding.vector).label("distance"))
            .where(
                Embedding.source_type == "SESSION",
                Embedding.source_id != session_id,
                Embedding.embedding_type == "SESSION_COMPOSITE",
            )
            .order_by("distance")
            .limit(limit)
        ).all()
        for embedding, distance in nearest:
            session = db.get(TransmissionSession, embedding.source_id)
            if session:
                results.append(
                    {
                        **model_dict(session),
                        "similarity": max(0.0, 1.0 - float(distance)),
                        "similarity_basis": "session_composite_embedding",
                    }
                )
    else:
        candidates = list(
            db.scalars(
                select(TransmissionSession)
                .where(
                    TransmissionSession.id != session_id,
                    TransmissionSession.deleted_at.is_(None),
                    TransmissionSession.primary_frequency_hz.between(
                        subject.primary_frequency_hz - 20_000,
                        subject.primary_frequency_hz + 20_000,
                    ),
                )
                .limit(200)
            )
        )
        for candidate in candidates:
            callsign_overlap = len(set(subject.callsigns) & set(candidate.callsigns))
            number_overlap = len(set(subject.number_groups) & set(candidate.number_groups))
            score = min(1.0, callsign_overlap * 0.35 + number_overlap * 0.25 + 0.1)
            results.append(
                {**model_dict(candidate), "similarity": score, "similarity_basis": "metadata_fallback"}
            )
        results.sort(key=lambda item: float(item["similarity"]), reverse=True)
        results = results[:limit]
    return Envelope(
        data=results,
        query={"session_id": session_id, "limit": limit},
        warnings=["Similarity indicates acoustic or structural resemblance, never speaker identity."],
    )


@router.post("/correlations/query", response_model=Envelope[dict[str, Any]])
def correlations(
    payload: CorrelationRequest,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    session = db.get(TransmissionSession, payload.subject_session_id)
    if session is None:
        raise missing("session")
    start = session.start_at_utc - timedelta(seconds=payload.event_window_before_sec)
    end = session.end_at_utc + timedelta(seconds=payload.event_window_after_sec)
    events = list(
        db.scalars(
            select(ExternalEvent).where(
                ExternalEvent.started_at_utc.between(start, end),
                ExternalEvent.confidence >= payload.minimum_confidence,
                ExternalEvent.deleted_at.is_(None),
            )
        )
    )
    candidates = [
        {
            **model_dict(event),
            "delta_seconds": (event.started_at_utc - session.end_at_utc).total_seconds()
            if event.started_at_utc
            else None,
            "relation": "temporally_follows"
            if event.started_at_utc and event.started_at_utc > session.end_at_utc
            else "co_occurs",
            "causal_claim": False,
        }
        for event in events
    ]
    return Envelope(
        data={"subject_session": model_dict(session), "candidate_events": candidates},
        query=payload.model_dump(mode="json"),
        warnings=["Temporal association is not evidence of causality."],
    )


@router.post("/relations", response_model=Envelope[dict[str, Any]], status_code=201)
def create_relation(
    payload: RelationCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    relation = Relation(**payload.model_dump(), created_by=user.id)
    db.add(relation)
    db.commit()
    return Envelope(data=model_dict(relation))


@router.post("/hypotheses", response_model=Envelope[dict[str, Any]], status_code=201)
def create_hypothesis(
    payload: HypothesisCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    hypothesis = Hypothesis(
        title=payload.title,
        statement=payload.statement,
        status="DRAFT" if payload.created_by == "LOCAL_LLM" else "ACTIVE",
        confidence=payload.confidence,
        supporting_evidence_ids=payload.supporting_evidence_ids,
        contradicting_evidence_ids=payload.contradicting_evidence_ids,
        unresolved_evidence_ids=payload.unresolved_evidence_ids,
        related_session_ids=payload.related_session_ids,
        related_event_ids=payload.related_event_ids,
        saved_query_ids=payload.saved_query_ids,
        created_by_type=payload.created_by,
        created_by_user_id=user.id if payload.created_by == "USER" else None,
        evaluation_notes=payload.evaluation_notes,
        user_notes=payload.user_notes,
        llm_notes=payload.llm_notes,
    )
    db.add(hypothesis)
    db.flush()
    db.add(
        HypothesisHistory(
            hypothesis_id=hypothesis.id,
            previous_status=None,
            new_status=hypothesis.status,
            actor_type=payload.created_by,
            actor_id=user.id if payload.created_by == "USER" else None,
            notes="created",
        )
    )
    db.commit()
    return Envelope(
        data=model_dict(hypothesis),
        warnings=["Local LLM hypotheses remain DRAFT until a user changes their status."]
        if payload.created_by == "LOCAL_LLM"
        else [],
    )


@router.patch("/hypotheses/{hypothesis_id}", response_model=Envelope[dict[str, Any]])
def patch_hypothesis(
    hypothesis_id: str,
    payload: HypothesisPatch,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    hypothesis = db.get(Hypothesis, hypothesis_id)
    if hypothesis is None or hypothesis.deleted_at is not None:
        raise missing("hypothesis")
    previous = hypothesis.status
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(hypothesis, key, value)
    if payload.status and payload.status != previous:
        db.add(
            HypothesisHistory(
                hypothesis_id=hypothesis.id,
                previous_status=previous,
                new_status=payload.status,
                actor_type="USER",
                actor_id=user.id,
                notes=payload.evaluation_notes,
            )
        )
    db.commit()
    return Envelope(data=model_dict(hypothesis))


@router.post("/annotations", response_model=Envelope[dict[str, Any]], status_code=201)
def create_annotation(
    payload: AnnotationCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    if payload.end_sec is not None and payload.start_sec is not None and payload.end_sec < payload.start_sec:
        raise HTTPException(status_code=422, detail="end_sec must be >= start_sec")
    if payload.client_id:
        existing = db.scalar(select(Annotation).where(Annotation.client_id == payload.client_id))
        if existing:
            if existing.sync_version != payload.sync_version or existing.body != payload.body:
                raise HTTPException(
                    status_code=409,
                    detail={"message": "offline sync conflict", "server": model_dict(existing)},
                )
            return Envelope(data=model_dict(existing), warnings=["idempotent offline replay"])
    annotation = Annotation(**payload.model_dump(), author_id=user.id)
    db.add(annotation)
    db.commit()
    return Envelope(data=model_dict(annotation))


@router.post("/export/context-bundle", response_model=Envelope[dict[str, Any]])
def export_context_bundle(
    payload: ContextBundleRequest,
    _user: CurrentUser,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, Any]]:
    return Envelope(
        data=context_bundle(db, payload, settings.APP_URL),
        query=payload.model_dump(mode="json"),
    )


@router.get("/export/context-bundle", response_model=Envelope[dict[str, Any]])
def export_context_bundle_get(
    _user: CurrentUser,
    subject_session_id: str,
    task: str = "inspect_session",
    token_budget: int = Query(default=24_000, ge=1_000, le=100_000),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, Any]]:
    payload = ContextBundleRequest(
        task=task,
        subject_session_id=subject_session_id,
        include=["metadata", "preferred_transcripts", "entities", "relations", "provenance"],
        token_budget=token_budget,
    )
    return Envelope(data=context_bundle(db, payload, settings.APP_URL), query=payload.model_dump())


@router.get("/export/evidence-bundle")
def evidence_bundle(
    _user: CurrentUser,
    session_id: str,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    session = db.get(TransmissionSession, session_id)
    if session is None or session.deleted_at is not None:
        raise missing("session")
    recordings = list(
        db.scalars(
            select(Recording).where(
                Recording.id.in_(session.recording_ids),
                Recording.deleted_at.is_(None),
            )
        )
    )
    annotations = list(
        db.scalars(
            select(Annotation).where(
                Annotation.target_id.in_([session.id, *session.segment_ids]),
                Annotation.deleted_at.is_(None),
            )
        )
    )
    data = {
        "query": {"session_id": session_id},
        "generated_at_utc": datetime.now(UTC),
        "selected_records": {
            "session": model_dict(session),
            "recordings": [model_dict(row) for row in recordings],
        },
        "provenance": record_provenance(db, "SESSION", session_id),
        "relations": [
            model_dict(row)
            for row in db.scalars(
                select(Relation).where(
                    or_(Relation.subject_id == session_id, Relation.object_id == session_id)
                )
            )
        ],
        "preferred_transcripts": [
            model_dict(row)
            for row in db.scalars(
                select(Transcript).where(
                    Transcript.segment_id.in_(session.segment_ids),
                    Transcript.is_preferred.is_(True),
                )
            )
        ],
        "notes": [model_dict(row) for row in annotations],
        "hashes": [{"recording_id": row.id, "sha256": row.sha256} for row in recordings],
        "app_version": "0.1.0",
        "schema_version": "0003",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("evidence.json", json.dumps(data, default=str, ensure_ascii=False, indent=2))
        archive.writestr(
            "README.md",
            "# Signal Index evidence bundle\n\nTemporal associations are not causal claims.\n",
        )
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="signal-index-{session_id}.zip"'},
    )


EXPORT_MODELS: dict[str, type[Any]] = {
    "sessions": TransmissionSession,
    "segments": AudioSegment,
    "recordings": Recording,
    "entities": ExtractedEntity,
    "relations": Relation,
    "events": ExternalEvent,
    "hypotheses": Hypothesis,
    "annotations": Annotation,
    "saved_queries": SavedQuery,
    "inbox": InboxItem,
    "receivers": Receiver,
}


@router.get("/export/data")
def export_data(
    _user: CurrentUser,
    record_type: str = Query(pattern="^[a-z_]+$"),
    format: str = Query(pattern="^(json|jsonl|csv|markdown)$"),  # noqa: A002
    ids: str | None = Query(default=None, max_length=20_000),
    limit: int = Query(default=10_000, ge=1, le=100_000),
    db: Session = Depends(get_db),
) -> Response:
    model = EXPORT_MODELS.get(record_type)
    if model is None:
        raise HTTPException(status_code=422, detail="unsupported export record_type")
    requested_ids = [value.strip() for value in (ids or "").split(",") if value.strip()]
    statement = select(model).where(model.deleted_at.is_(None))
    if requested_ids:
        if len(requested_ids) > 5_000:
            raise HTTPException(status_code=422, detail="selective export is limited to 5000 ids")
        statement = statement.where(model.id.in_(requested_ids))
    rows = list(db.scalars(statement.order_by(model.created_at).limit(limit)))
    data = [model_dict(row) for row in rows]
    meta = {
        "record_type": record_type,
        "ids": requested_ids,
        "limit": limit,
        "row_count": len(data),
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "schema_version": "0003",
    }
    filename = f"signal-index-{record_type}.{format if format != 'markdown' else 'md'}"
    if format == "json":
        body = json.dumps({"query": meta, "data": data}, default=str, ensure_ascii=False, indent=2)
        media_type = "application/json"
    elif format == "jsonl":
        body = "\n".join(json.dumps(row, default=str, ensure_ascii=False) for row in data) + "\n"
        media_type = "application/x-ndjson"
    elif format == "csv":
        columns = sorted({key for row in data for key in row})
        target = io.StringIO()
        writer = csv.DictWriter(target, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in data:
            writer.writerow(
                {
                    key: (
                        json.dumps(value, default=str, ensure_ascii=False)
                        if isinstance(value, dict | list)
                        else value
                    )
                    for key, value in row.items()
                }
            )
        body = target.getvalue()
        media_type = "text/csv"
    else:
        lines = [
            f"# Signal Index {record_type.replace('_', ' ').title()} Export",
            "",
            f"- Generated: {meta['generated_at_utc']}",
            f"- Records: {len(data)}",
            "- Statistical or temporal association does not imply causation.",
            "",
        ]
        for row in data:
            lines.extend(
                [
                    f"## {row.get('title') or row.get('name') or row.get('id')}",
                    "",
                    "```json",
                    json.dumps(row, default=str, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
        body = "\n".join(lines)
        media_type = "text/markdown"
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/hypotheses/{hypothesis_id}/report")
def hypothesis_report(
    hypothesis_id: str,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    hypothesis = db.get(Hypothesis, hypothesis_id)
    if hypothesis is None or hypothesis.deleted_at is not None:
        raise missing("hypothesis")
    history = list(
        db.scalars(
            select(HypothesisHistory)
            .where(
                HypothesisHistory.hypothesis_id == hypothesis.id,
                HypothesisHistory.deleted_at.is_(None),
            )
            .order_by(HypothesisHistory.created_at)
        )
    )
    lines = [
        f"# {hypothesis.title}",
        "",
        f"**Status:** {hypothesis.status}",
        f"**Confidence:** {hypothesis.confidence if hypothesis.confidence is not None else 'unscored'}",
        f"**Origin:** {hypothesis.created_by_type}",
        "",
        "## Statement",
        "",
        hypothesis.statement,
        "",
        "## Evidence",
        "",
        f"- Supporting: {', '.join(hypothesis.supporting_evidence_ids) or 'None'}",
        f"- Contradicting: {', '.join(hypothesis.contradicting_evidence_ids) or 'None'}",
        f"- Unresolved: {', '.join(hypothesis.unresolved_evidence_ids) or 'None'}",
        "",
        "## Evaluation history",
        "",
    ]
    lines.extend(
        f"- {row.created_at.isoformat()}: {row.previous_status or 'NEW'} → {row.new_status}"
        + (f" — {row.notes}" if row.notes else "")
        for row in history
    )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This report records a user interpretation or local-LLM draft. "
            "Temporal or statistical association is not a causal claim.",
        ]
    )
    return Response(
        "\n".join(lines),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="hypothesis-{hypothesis.id}.md"'
        },
    )


@router.get("/timeline", response_model=Envelope[dict[str, Any]])
def timeline_data(
    _user: CurrentUser,
    start_at_utc: datetime,
    end_at_utc: datetime,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    if start_at_utc >= end_at_utc:
        raise HTTPException(status_code=422, detail="timeline start must be before end")
    if end_at_utc - start_at_utc > timedelta(days=3660):
        raise HTTPException(status_code=422, detail="timeline range is limited to ten years")
    sessions = list(
        db.scalars(
            select(TransmissionSession)
            .where(
                TransmissionSession.start_at_utc <= end_at_utc,
                TransmissionSession.end_at_utc >= start_at_utc,
                TransmissionSession.deleted_at.is_(None),
            )
            .limit(500)
        )
    )
    events = list(
        db.scalars(
            select(ExternalEvent)
            .where(
                ExternalEvent.started_at_utc.between(start_at_utc, end_at_utc),
                ExternalEvent.deleted_at.is_(None),
            )
            .limit(500)
        )
    )
    session_ids = [row.id for row in sessions]
    segment_ids = [segment_id for row in sessions for segment_id in row.segment_ids]
    entities = list(
        db.scalars(
            select(ExtractedEntity).where(
                or_(
                    ExtractedEntity.session_id.in_(session_ids),
                    ExtractedEntity.segment_id.in_(segment_ids),
                ),
                ExtractedEntity.entity_type.in_(["CALLSIGN", "NUMBER_GROUP"]),
                ExtractedEntity.deleted_at.is_(None),
            )
        )
    )
    annotations = list(
        db.scalars(
            select(Annotation).where(
                or_(
                    and_(
                        Annotation.target_type == "SESSION",
                        Annotation.target_id.in_(session_ids),
                    ),
                    and_(
                        Annotation.target_type == "SEGMENT",
                        Annotation.target_id.in_(segment_ids),
                    ),
                ),
                Annotation.deleted_at.is_(None),
            )
        )
    )
    hypotheses = [
        value
        for value in db.scalars(
            select(Hypothesis).where(Hypothesis.deleted_at.is_(None)).limit(500)
        )
        if set(value.related_session_ids) & set(session_ids)
    ]
    return Envelope(
        data={
            "sessions": [model_dict(row) for row in sessions],
            "frequency_activity": [
                {
                    "session_id": row.id,
                    "frequency_hz": row.primary_frequency_hz,
                    "start_at_utc": row.start_at_utc,
                    "end_at_utc": row.end_at_utc,
                }
                for row in sessions
            ],
            "callsigns": [
                model_dict(row) for row in entities if row.entity_type == "CALLSIGN"
            ],
            "number_groups": [
                model_dict(row) for row in entities if row.entity_type == "NUMBER_GROUP"
            ],
            "receiver_observations": [
                {
                    "session_id": row.id,
                    "receiver_ids": row.receiver_ids,
                    "observed_at_utc": row.start_at_utc,
                }
                for row in sessions
            ],
            "external_events": [model_dict(row) for row in events],
            "annotations": [model_dict(row) for row in annotations],
            "hypotheses": [model_dict(row) for row in hypotheses],
            "resolution": "seconds",
            "display_timezone": "UTC",
        },
        query={"start_at_utc": start_at_utc, "end_at_utc": end_at_utc},
        warnings=["Receiver locations are not transmitter locations."],
    )


@router.get("/graph", response_model=Envelope[dict[str, Any]])
def graph_data(
    _user: CurrentUser,
    minimum_confidence: float = Query(default=0.0, ge=0, le=1),
    relation_status: str | None = None,
    predicate: str | None = None,
    node_types: str | None = None,
    focus_id: str | None = None,
    depth: int = Query(default=1, ge=1, le=3),
    start_at_utc: datetime | None = None,
    end_at_utc: datetime | None = None,
    limit: int = Query(default=500, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    filters: list[Any] = [
        Relation.deleted_at.is_(None),
        Relation.confidence >= minimum_confidence,
    ]
    if relation_status:
        filters.append(Relation.relation_status == relation_status)
    if predicate:
        filters.append(Relation.predicate == predicate)
    if start_at_utc:
        filters.append(Relation.created_at >= start_at_utc)
    if end_at_utc:
        filters.append(Relation.created_at <= end_at_utc)
    requested_types = {
        value.strip().upper() for value in (node_types or "").split(",") if value.strip()
    }
    if requested_types:
        filters.append(
            or_(
                Relation.subject_type.in_(requested_types),
                Relation.object_type.in_(requested_types),
            )
        )
    if focus_id:
        neighborhood = {focus_id}
        collected_ids: set[str] = set()
        for _ in range(depth):
            adjacent = list(
                db.scalars(
                    select(Relation).where(
                        Relation.deleted_at.is_(None),
                        or_(
                            Relation.subject_id.in_(neighborhood),
                            Relation.object_id.in_(neighborhood),
                        ),
                    )
                )
            )
            collected_ids.update(value.id for value in adjacent)
            neighborhood.update(value.subject_id for value in adjacent)
            neighborhood.update(value.object_id for value in adjacent)
        filters.append(Relation.id.in_(collected_ids or {"__none__"}))
    relations = list(
        db.scalars(
            select(Relation).where(*filters).order_by(Relation.confidence.desc()).limit(limit)
        )
    )
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for relation in relations:
        subject_key = f"{relation.subject_type}:{relation.subject_id}"
        object_key = f"{relation.object_type}:{relation.object_id}"
        nodes[subject_key] = {
            "id": subject_key,
            "record_id": relation.subject_id,
            "node_type": relation.subject_type,
            "label": f"{relation.subject_type} · {relation.subject_id[:8]}",
            "permalink": f"/{relation.subject_type.lower()}s/{relation.subject_id}",
        }
        nodes[object_key] = {
            "id": object_key,
            "record_id": relation.object_id,
            "node_type": relation.object_type,
            "label": f"{relation.object_type} · {relation.object_id[:8]}",
            "permalink": f"/{relation.object_type.lower()}s/{relation.object_id}",
        }
        edges.append(
            {
                **model_dict(relation),
                "source": subject_key,
                "target": object_key,
                "evidence_count": len(relation.evidence_ids),
            }
        )
    return Envelope(
        data={"nodes": list(nodes.values()), "edges": edges},
        query={
            "minimum_confidence": minimum_confidence,
            "relation_status": relation_status,
            "predicate": predicate,
            "node_types": sorted(requested_types),
            "focus_id": focus_id,
            "depth": depth,
            "start_at_utc": start_at_utc,
            "end_at_utc": end_at_utc,
            "limit": limit,
        },
        pagination={"limit": limit, "truncated": len(relations) == limit},
    )


@router.get("/analytics/summary", response_model=Envelope[dict[str, Any]])
def analytics_summary(
    _user: CurrentUser,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, Any]]:
    session_count = int(
        db.scalar(
            select(func.count()).select_from(TransmissionSession).where(
                TransmissionSession.deleted_at.is_(None)
            )
        )
        or 0
    )
    segment_count = int(
        db.scalar(
            select(func.count()).select_from(AudioSegment).where(AudioSegment.deleted_at.is_(None))
        )
        or 0
    )
    confidence_rows = list(
        db.scalars(
            select(TransmissionSession.confidence).where(
                TransmissionSession.deleted_at.is_(None)
            )
        )
    )
    active_duration_sec = float(
        db.scalar(
            select(func.coalesce(func.sum(AudioSegment.duration_sec), 0.0)).where(
                AudioSegment.deleted_at.is_(None)
            )
        )
        or 0.0
    )
    receiver_coverage = int(
        db.scalar(
            select(func.count(func.distinct(Recording.receiver_id))).where(
                Recording.receiver_id.is_not(None),
                Recording.deleted_at.is_(None),
            )
        )
        or 0
    )
    top_entities: dict[str, list[dict[str, Any]]] = {}
    for entity_type, key in (("CALLSIGN", "top_callsigns"), ("NUMBER_GROUP", "top_number_groups")):
        rows = db.execute(
            select(
                ExtractedEntity.normalized_value,
                func.count(ExtractedEntity.id).label("count"),
            )
            .where(
                ExtractedEntity.entity_type == entity_type,
                ExtractedEntity.deleted_at.is_(None),
            )
            .group_by(ExtractedEntity.normalized_value)
            .order_by(func.count(ExtractedEntity.id).desc())
            .limit(5)
        ).all()
        top_entities[key] = [{"value": value, "count": count} for value, count in rows]
    failed_jobs = list(
        db.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.status == "FAILED",
                ProcessingJob.deleted_at.is_(None),
            )
            .order_by(ProcessingJob.updated_at.desc())
            .limit(10)
        )
    )
    capture_status: dict[str, int] = {
        str(status): int(count)
        for status, count in db.execute(
            select(CaptureJob.status, func.count(CaptureJob.id))
            .where(CaptureJob.deleted_at.is_(None))
            .group_by(CaptureJob.status)
        ).all()
    }
    receiver_status: dict[str, int] = {
        str(status): int(count)
        for status, count in db.execute(
            select(Receiver.status, func.count(Receiver.id))
            .where(Receiver.deleted_at.is_(None))
            .group_by(Receiver.status)
        ).all()
    }
    storage: dict[str, Any]
    try:
        storage = {"status": "available", **ObjectStorage(settings).usage(maximum_objects=100_000)}
    except Exception as exc:
        storage = {"status": "unavailable", "error_type": type(exc).__name__}
    return Envelope(
        data={
            "session_count": session_count,
            "segment_count": segment_count,
            "active_duration_sec": active_duration_sec,
            "receiver_coverage": receiver_coverage,
            **top_entities,
            "failed_jobs": [model_dict(row) for row in failed_jobs],
            "capture_status": capture_status,
            "receiver_status": receiver_status,
            "storage": storage,
            "mean_session_confidence": (
                sum(confidence_rows) / len(confidence_rows) if confidence_rows else None
            ),
            "generated_for_window_ending_utc": datetime.now(UTC),
            "causal_claims_inferred": False,
        }
    )


@router.get("/analytics/activity", response_model=Envelope[dict[str, Any]])
def analytics_activity(
    _user: CurrentUser,
    start_at_utc: datetime,
    end_at_utc: datetime,
    frequency_min_hz: int | None = Query(default=None, ge=0),
    frequency_max_hz: int | None = Query(default=None, ge=0),
    receiver_id: str | None = None,
    mode: str | None = Query(default=None, max_length=20),
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    if start_at_utc >= end_at_utc:
        raise HTTPException(status_code=422, detail="analysis start must be before end")
    filters: list[Any] = [
        TransmissionSession.start_at_utc.between(start_at_utc, end_at_utc),
        TransmissionSession.deleted_at.is_(None),
    ]
    if frequency_min_hz is not None:
        filters.append(TransmissionSession.primary_frequency_hz >= frequency_min_hz)
    if frequency_max_hz is not None:
        filters.append(TransmissionSession.primary_frequency_hz <= frequency_max_hz)
    if receiver_id:
        filters.append(TransmissionSession.receiver_ids.cast(String).ilike(f"%{receiver_id}%"))
    if mode:
        matching_recording_ids = list(
            db.scalars(
                select(Recording.id)
                .where(
                    Recording.mode == mode.upper(),
                    Recording.deleted_at.is_(None),
                )
                .limit(5_000)
            )
        )
        filters.append(
            or_(
                *[
                    TransmissionSession.recording_ids.cast(String).ilike(f"%{recording_id}%")
                    for recording_id in matching_recording_ids
                ]
            )
            if matching_recording_ids
            else TransmissionSession.id == "__none__"
        )
    sessions = list(
        db.scalars(
            select(TransmissionSession)
            .where(*filters)
            .order_by(TransmissionSession.start_at_utc)
            .limit(100_000)
        )
    )
    points = [
        ActivityPoint(
            observed_at=session.start_at_utc,
            duration_sec=(session.end_at_utc - session.start_at_utc).total_seconds(),
            frequency_hz=session.primary_frequency_hz,
            receiver_ids=tuple(session.receiver_ids),
            callsigns=tuple(session.callsigns),
            number_groups=tuple(session.number_groups),
            confidence=session.confidence,
        )
        for session in sessions
    ]
    summary = summarize_activity(points)
    follow_up_delays = list(
        db.scalars(
            select(Relation.delta_seconds).where(
                Relation.predicate.in_(["PRECEDES", "FOLLOWS", "TEMPORALLY_PRECEDES"]),
                Relation.delta_seconds.is_not(None),
                Relation.deleted_at.is_(None),
                Relation.created_at.between(start_at_utc, end_at_utc),
            )
        )
    )
    multi_receiver = sum(len(set(session.receiver_ids)) > 1 for session in sessions)
    summary.update(
        {
            "follow_up_event_delay_distribution_sec": [
                float(value) for value in follow_up_delays if value is not None
            ],
            "source_agreement": {
                "multi_receiver_session_count": multi_receiver,
                "session_count": len(sessions),
                "ratio": multi_receiver / len(sessions) if sessions else None,
                "definition": "share of grouped sessions observed by more than one receiver",
            },
        }
    )
    return Envelope(
        data=summary,
        query={
            "start_at_utc": start_at_utc,
            "end_at_utc": end_at_utc,
            "frequency_min_hz": frequency_min_hz,
            "frequency_max_hz": frequency_max_hz,
            "receiver_id": receiver_id,
            "mode": mode,
        },
        pagination={"rows_analyzed": len(points), "truncated": len(points) == 100_000},
        warnings=["Statistical relationships and change candidates are not causal claims."],
    )
