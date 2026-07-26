from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from signal_processing.scheduling import next_schedule
from source_adapters.adapters import CSVAdapter, JSONAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..dependencies import CurrentUser
from ..file_security import detect_file, scan_payload, validate_declared_type
from ..ingestion import materialize_record
from ..models import (
    AuditLog,
    CaptureJob,
    ExternalEvent,
    FrequencyEntry,
    GraphLayout,
    Hypothesis,
    HypothesisHistory,
    InboxItem,
    Provenance,
    Receiver,
    ReceiverStatus,
    SavedQuery,
    SecretRecord,
    SettingRevision,
    Source,
)
from ..schemas import Envelope
from ..security import encrypt_secret, validate_external_url
from ..serialization import model_dict
from ..storage import ObjectStorage

router = APIRouter(tags=["catalog"])


class InboxCreate(BaseModel):
    item_type: Literal["audio", "text", "url", "image", "pdf", "csv", "json", "observation"]
    text_content: str | None = Field(default=None, max_length=1_000_000)
    source_url: str | None = Field(default=None, max_length=2_048)
    frequency_hz: int | None = Field(default=None, ge=0, le=100_000_000_000)
    mode: str | None = Field(default=None, max_length=20)
    observed_at_utc: datetime | None = None
    receiver_id: str | None = None
    note: str | None = Field(default=None, max_length=100_000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    client_id: str | None = Field(default=None, max_length=80)


class CaptureCreate(BaseModel):
    receiver_id: str
    frequency_hz: int = Field(ge=0, le=100_000_000_000)
    mode: str
    schedule_utc: str
    capture_duration_sec: int = Field(ge=1, le=86_400)
    repetition: str | None = None
    maximum_storage_bytes: int | None = Field(default=None, ge=1)
    enabled: bool = False
    retention_policy: dict[str, Any] = Field(default_factory=dict)


class SavedQueryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query_type: str = Field(min_length=1, max_length=60)
    query_json: dict[str, Any]


class SettingCreate(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: dict[str, Any]


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    adapter_type: Literal[
        "rss_atom",
        "generic_html_table",
        "user_defined_static",
        "manual_frequency_list",
        "manual_receiver_list",
    ]
    base_url: str | None = Field(default=None, max_length=2_048)
    enabled: bool = False
    parser_version: str = Field(default="1.0.0", max_length=80)
    license_notes: str | None = Field(default=None, max_length=10_000)
    config: dict[str, Any] = Field(default_factory=dict)


class SourcePatch(BaseModel):
    enabled: bool | None = None
    parser_version: str | None = Field(default=None, max_length=80)
    license_notes: str | None = Field(default=None, max_length=10_000)
    config: dict[str, Any] | None = None


class FrequencyPatch(BaseModel):
    favorite: bool | None = None
    watchlisted: bool | None = None
    notes: str | None = Field(default=None, max_length=100_000)


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=400)
    event_type: str = Field(min_length=1, max_length=100)
    started_at_utc: datetime | None = None
    ended_at_utc: datetime | None = None
    country_codes: list[str] = Field(default_factory=list, max_length=100)
    location: dict[str, Any] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=100_000)
    source_url: str | None = Field(default=None, max_length=2_048)
    source_name: str | None = Field(default=None, max_length=200)
    confidence: float = Field(default=0.5, ge=0, le=1)


class EventPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=400)
    event_type: str | None = Field(default=None, min_length=1, max_length=100)
    started_at_utc: datetime | None = None
    ended_at_utc: datetime | None = None
    country_codes: list[str] | None = Field(default=None, max_length=100)
    location: dict[str, Any] | None = None
    description: str | None = Field(default=None, max_length=100_000)
    source_url: str | None = Field(default=None, max_length=2_048)
    source_name: str | None = Field(default=None, max_length=200)
    confidence: float | None = Field(default=None, ge=0, le=1)


class GraphLayoutCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query_json: dict[str, Any] = Field(default_factory=dict)
    positions: dict[str, Any] = Field(default_factory=dict)
    viewport: dict[str, Any] = Field(default_factory=dict)


class SecretCreate(BaseModel):
    key: Literal["local_llm.api_key", "tool_api.key"]
    value: str = Field(min_length=1, max_length=100_000)


def list_model(db: Session, model: type[Any], limit: int) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(model)
        .where(model.deleted_at.is_(None))
        .order_by(model.created_at.desc())
        .limit(limit)
    )
    return [model_dict(row) for row in rows]


@router.get("/receivers", response_model=Envelope[list[dict[str, Any]]])
def receivers(
    _user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, Receiver, limit), pagination={"limit": limit})


@router.get("/receivers/{receiver_id}", response_model=Envelope[dict[str, Any]])
def receiver(receiver_id: str, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[dict[str, Any]]:
    item = db.get(Receiver, receiver_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="receiver not found")
    return Envelope(data=model_dict(item))


@router.get(
    "/receivers/{receiver_id}/status-history",
    response_model=Envelope[list[dict[str, Any]]],
)
def receiver_status_history(
    receiver_id: str,
    _user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=1_000),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    item = db.get(Receiver, receiver_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="receiver not found")
    rows = list(
        db.scalars(
            select(ReceiverStatus)
            .where(
                ReceiverStatus.receiver_id == receiver_id,
                ReceiverStatus.deleted_at.is_(None),
            )
            .order_by(ReceiverStatus.created_at.desc())
            .limit(limit)
        )
    )
    return Envelope(
        data=[model_dict(row) for row in rows],
        pagination={"limit": limit, "truncated": len(rows) == limit},
    )


@router.get("/frequencies", response_model=Envelope[list[dict[str, Any]]])
def frequencies(
    _user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, FrequencyEntry, limit), pagination={"limit": limit})


@router.patch(
    "/frequencies/{frequency_id}",
    response_model=Envelope[dict[str, Any]],
)
def patch_frequency(
    frequency_id: str,
    payload: FrequencyPatch,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    item = db.get(FrequencyEntry, frequency_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="frequency entry not found")
    before = {
        "favorite": item.favorite,
        "watchlisted": item.watchlisted,
        "notes": item.notes,
    }
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.add(
        AuditLog(
            user_id=user.id,
            action="FREQUENCY_UPDATED",
            target_type="FREQUENCY",
            target_id=item.id,
            detail={"before": before, "after": payload.model_dump(exclude_unset=True)},
        )
    )
    db.commit()
    return Envelope(data=model_dict(item))


@router.get("/events", response_model=Envelope[list[dict[str, Any]]])
def events(
    _user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, ExternalEvent, limit), pagination={"limit": limit})


@router.post("/events", response_model=Envelope[dict[str, Any]], status_code=201)
def create_event(
    payload: EventCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    if payload.started_at_utc and payload.ended_at_utc:
        if payload.started_at_utc > payload.ended_at_utc:
            raise HTTPException(status_code=422, detail="event start must be before end")
    if payload.source_url:
        try:
            validate_external_url(payload.source_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    item = ExternalEvent(**payload.model_dump())
    db.add(item)
    db.flush()
    db.add(
        Provenance(
            record_type="EVENT",
            record_id=item.id,
            source_url=item.source_url,
            first_observed_at=datetime.now(UTC),
            confidence=item.confidence,
            manually_corrected=True,
            parser_version="manual-entry",
        )
    )
    db.add(
        AuditLog(
            user_id=user.id,
            action="EVENT_CREATED",
            target_type="EVENT",
            target_id=item.id,
        )
    )
    db.commit()
    return Envelope(data=model_dict(item), provenance=[{"source": "manual user entry"}])


@router.get("/events/{event_id}", response_model=Envelope[dict[str, Any]])
def event(
    event_id: str,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    item = db.get(ExternalEvent, event_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="event not found")
    provenance = list(
        db.scalars(
            select(Provenance).where(
                Provenance.record_type == "EVENT",
                Provenance.record_id == item.id,
                Provenance.deleted_at.is_(None),
            )
        )
    )
    return Envelope(
        data=model_dict(item),
        provenance=[model_dict(row) for row in provenance],
    )


@router.patch("/events/{event_id}", response_model=Envelope[dict[str, Any]])
def patch_event(
    event_id: str,
    payload: EventPatch,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    item = db.get(ExternalEvent, event_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="event not found")
    changes = payload.model_dump(exclude_unset=True)
    start = changes.get("started_at_utc", item.started_at_utc)
    end = changes.get("ended_at_utc", item.ended_at_utc)
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="event start must be before end")
    if source_url := changes.get("source_url"):
        try:
            validate_external_url(source_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    before = model_dict(item)
    for key, value in changes.items():
        setattr(item, key, value)
    db.add(
        AuditLog(
            user_id=user.id,
            action="EVENT_UPDATED",
            target_type="EVENT",
            target_id=item.id,
            detail={"before": before, "after": changes},
        )
    )
    db.commit()
    return Envelope(data=model_dict(item))


@router.get("/sources", response_model=Envelope[list[dict[str, Any]]])
def sources(
    _user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, Source, limit), pagination={"limit": limit})


@router.post("/sources", response_model=Envelope[dict[str, Any]], status_code=201)
def create_source(
    payload: SourceCreate,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    if db.scalar(select(Source).where(Source.name == payload.name)):
        raise HTTPException(status_code=409, detail="source name already exists")
    remote = payload.adapter_type in {"rss_atom", "generic_html_table"}
    if remote and not payload.base_url:
        raise HTTPException(status_code=422, detail="remote adapter requires base_url")
    if payload.enabled and not remote:
        raise HTTPException(status_code=422, detail="only fetchable remote adapters can be enabled")
    if payload.base_url:
        allowed_hosts = {
            str(host).lower().rstrip(".")
            for host in payload.config.get("allowed_hosts", [])
            if isinstance(host, str)
        }
        if not allowed_hosts:
            from urllib.parse import urlparse

            host = urlparse(payload.base_url).hostname
            if host:
                allowed_hosts.add(host.lower().rstrip("."))
        try:
            validate_external_url(payload.base_url, allowed_hosts)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        config = {**payload.config, "allowed_hosts": sorted(allowed_hosts)}
    else:
        config = payload.config
    source = Source(**payload.model_dump(exclude={"config"}), config=config)
    db.add(source)
    db.commit()
    return Envelope(
        data=model_dict(source),
        warnings=[] if source.enabled else ["source is manually disabled"],
    )


@router.get("/sources/{source_id}", response_model=Envelope[dict[str, Any]])
def source(source_id: str, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[dict[str, Any]]:
    item = db.get(Source, source_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="source not found")
    return Envelope(data=model_dict(item))


@router.patch("/sources/{source_id}", response_model=Envelope[dict[str, Any]])
def patch_source(
    source_id: str,
    payload: SourcePatch,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    item = db.get(Source, source_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="source not found")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("enabled") and item.adapter_type not in {"rss_atom", "generic_html_table"}:
        raise HTTPException(status_code=422, detail="source adapter is not remotely fetchable")
    for key, value in changes.items():
        setattr(item, key, value)
    db.commit()
    return Envelope(data=model_dict(item))


@router.post("/sources/{source_id}/fetch", response_model=Envelope[dict[str, Any]], status_code=202)
def fetch_source_now(
    source_id: str,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    item = db.get(Source, source_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="source not found")
    if not item.enabled:
        raise HTTPException(status_code=409, detail="source is manually disabled")
    try:
        from audio_processor.source_tasks import fetch_source

        result = fetch_source.delay(source_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="source worker queue is unavailable") from exc
    return Envelope(data={"source_id": source_id, "task_id": result.id, "status": "QUEUED"})


@router.post("/sources/import", response_model=Envelope[dict[str, Any]], status_code=201)
def import_source(
    _user: CurrentUser,
    file: UploadFile = File(...),
    source_name: str = Form(..., min_length=1, max_length=200),
    adapter_type: Literal["csv", "json"] = Form(...),
    record_type: Literal["FREQUENCY", "RECEIVER", "EVENT"] = Form(...),
    license_notes: str | None = Form(default=None, max_length=10_000),
    archive_raw: bool = Form(default=True),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, Any]]:
    payload = file.file.read(50 * 1024 * 1024 + 1)
    if len(payload) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="source import exceeds 50 MiB")
    adapter = CSVAdapter(payload, record_type) if adapter_type == "csv" else JSONAdapter(payload, record_type)
    records = adapter.parse(payload)
    source = Source(
        name=source_name,
        adapter_type=adapter_type,
        enabled=False,
        parser_version=adapter.parser_version,
        license_notes=license_notes,
        config={"manual_import": True, "filename": file.filename},
    )
    db.add(source)
    db.flush()
    raw_hash = hashlib.sha256(payload).hexdigest()
    raw_key = None
    if archive_raw:
        raw_key = f"source-archive/{source.id}/{raw_hash}.bin"
        ObjectStorage(settings).upload(raw_key, payload, file.content_type or "application/octet-stream")
    created: list[str] = []
    duplicate_count = 0
    for record in records:
        record_id, was_created = materialize_record(
            db,
            source=source,
            record=record,
            fetched_at=None,
            raw_object_key=raw_key,
        )
        if was_created:
            created.append(record_id)
        else:
            duplicate_count += 1
    db.commit()
    return Envelope(
        data={
            "source": model_dict(source),
            "created_record_ids": created,
            "count": len(created),
            "duplicate_count": duplicate_count,
        },
        provenance=[{"raw_hash": raw_hash, "raw_object_key": raw_key}],
    )


@router.get("/hypotheses", response_model=Envelope[list[dict[str, Any]]])
def hypotheses(
    _user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, Hypothesis, limit), pagination={"limit": limit})


@router.get("/hypotheses/{hypothesis_id}", response_model=Envelope[dict[str, Any]])
def hypothesis(
    hypothesis_id: str,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    item = db.get(Hypothesis, hypothesis_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="hypothesis not found")
    history = list(
        db.scalars(
            select(HypothesisHistory)
            .where(
                HypothesisHistory.hypothesis_id == item.id,
                HypothesisHistory.deleted_at.is_(None),
            )
            .order_by(HypothesisHistory.created_at.desc())
        )
    )
    data = model_dict(item)
    data["history"] = [model_dict(row) for row in history]
    return Envelope(data=data)


@router.post("/inbox", response_model=Envelope[dict[str, Any]], status_code=201)
def inbox(payload: InboxCreate, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[dict[str, Any]]:
    if payload.client_id:
        existing = db.scalar(select(InboxItem).where(InboxItem.client_id == payload.client_id))
        if existing:
            return Envelope(data=model_dict(existing), warnings=["idempotent offline replay"])
    item = InboxItem(**payload.model_dump(), status="UNCLASSIFIED")
    db.add(item)
    db.commit()
    return Envelope(data=model_dict(item))


@router.post("/inbox/upload", response_model=Envelope[dict[str, Any]], status_code=201)
def inbox_upload(
    user: CurrentUser,
    file: UploadFile = File(...),
    item_type: Literal["image", "pdf", "csv", "json", "text", "observation"] = Form(...),
    frequency_hz: int | None = Form(default=None, ge=0, le=100_000_000_000),
    mode: str | None = Form(default=None, max_length=20),
    observed_at_utc: datetime | None = Form(default=None),
    receiver_id: str | None = Form(default=None),
    note: str | None = Form(default=None, max_length=100_000),
    tags: str = Form(default=""),
    client_id: str | None = Form(default=None, max_length=80),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, Any]]:
    if client_id:
        existing = db.scalar(select(InboxItem).where(InboxItem.client_id == client_id))
        if existing:
            return Envelope(data=model_dict(existing), warnings=["idempotent offline replay"])
    payload = file.file.read(settings.MAX_UPLOAD_BYTES + 1)
    if not payload:
        raise HTTPException(status_code=422, detail="uploaded file is empty")
    if len(payload) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="upload exceeds configured size limit")
    detected = detect_file(payload)
    validate_declared_type(detected, item_type)
    scan_payload(payload, settings)
    digest = hashlib.sha256(payload).hexdigest()
    key = f"inbox/{datetime.now(UTC):%Y/%m/%d}/{uuid.uuid4()}/{digest}"
    storage = ObjectStorage(settings)
    storage.upload(key, payload, detected.mime_type)
    item = InboxItem(
        item_type=item_type,
        object_key=key,
        frequency_hz=frequency_hz,
        mode=mode,
        observed_at_utc=observed_at_utc or datetime.now(UTC),
        receiver_id=receiver_id,
        note=note,
        tags=[value.strip() for value in tags.split(",") if value.strip()][:100],
        status="UNCLASSIFIED",
        client_id=client_id,
        original_filename=file.filename,
        mime_type=detected.mime_type,
        sha256=digest,
        size_bytes=len(payload),
    )
    db.add(item)
    db.flush()
    db.add(
        Provenance(
            record_type="INBOX_ITEM",
            record_id=item.id,
            first_observed_at=item.observed_at_utc,
            raw_hash=digest,
            raw_object_key=key,
            confidence=1.0,
            manually_corrected=False,
            parser_version="binary-upload",
            pipeline_version=settings.PIPELINE_VERSION,
        )
    )
    db.add(
        AuditLog(
            user_id=user.id,
            action="INBOX_BINARY_UPLOADED",
            target_type="INBOX_ITEM",
            target_id=item.id,
            detail={"mime_type": detected.mime_type, "size_bytes": len(payload)},
        )
    )
    db.commit()
    return Envelope(
        data=model_dict(item),
        provenance=[{"raw_hash": digest, "object_key": key}],
    )


@router.get("/inbox/{item_id}/media", response_model=Envelope[dict[str, Any]])
def inbox_media(
    item_id: str,
    _user: CurrentUser,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, Any]]:
    item = db.get(InboxItem, item_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="inbox item not found")
    if not item.object_key:
        raise HTTPException(status_code=409, detail="inbox item has no binary object")
    return Envelope(
        data={
            "url": ObjectStorage(settings).signed_get_url(item.object_key),
            "mime_type": item.mime_type,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
    )


@router.get("/inbox", response_model=Envelope[list[dict[str, Any]]])
def inbox_list(
    _user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, InboxItem, limit), pagination={"limit": limit})


@router.post("/capture", response_model=Envelope[dict[str, Any]], status_code=201)
def capture(payload: CaptureCreate, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[dict[str, Any]]:
    receiver = db.get(Receiver, payload.receiver_id)
    if receiver is None or receiver.deleted_at is not None:
        raise HTTPException(status_code=404, detail="receiver not found")
    if payload.enabled and not receiver.metadata_json.get("capture_url_template"):
        raise HTTPException(
            status_code=422,
            detail="enabled capture requires receiver.metadata.capture_url_template",
        )
    try:
        next_run_at = next_schedule(payload.schedule_utc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    lock_key = (
        f"capture:{payload.receiver_id}:{payload.frequency_hz}:{payload.schedule_utc}:"
        f"{payload.capture_duration_sec}"
    )
    existing = db.scalar(select(CaptureJob).where(CaptureJob.lock_key == lock_key))
    if existing:
        raise HTTPException(status_code=409, detail="duplicate capture schedule")
    item = CaptureJob(
        **payload.model_dump(),
        status="SCHEDULED",
        lock_key=lock_key,
        next_run_at=next_run_at,
    )
    db.add(item)
    db.commit()
    return Envelope(
        data=model_dict(item),
        warnings=[] if payload.enabled else ["capture is disabled until explicitly enabled"],
    )


@router.get("/capture", response_model=Envelope[list[dict[str, Any]]])
def captures(
    _user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, CaptureJob, limit), pagination={"limit": limit})


@router.post("/saved-queries", response_model=Envelope[dict[str, Any]], status_code=201)
def saved_query(
    payload: SavedQueryCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> Envelope[dict[str, Any]]:
    item = SavedQuery(**payload.model_dump(), created_by_type="USER", owner_id=user.id)
    db.add(item)
    db.commit()
    return Envelope(data=model_dict(item))


@router.get("/saved-queries", response_model=Envelope[list[dict[str, Any]]])
def saved_queries(
    _user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, SavedQuery, limit), pagination={"limit": limit})


@router.get("/graph-layouts", response_model=Envelope[list[dict[str, Any]]])
def graph_layouts(
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    rows = list(
        db.scalars(
            select(GraphLayout)
            .where(
                GraphLayout.owner_id == user.id,
                GraphLayout.deleted_at.is_(None),
            )
            .order_by(GraphLayout.updated_at.desc())
            .limit(limit)
        )
    )
    return Envelope(data=[model_dict(row) for row in rows], pagination={"limit": limit})


@router.post("/graph-layouts", response_model=Envelope[dict[str, Any]], status_code=201)
def create_graph_layout(
    payload: GraphLayoutCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    if len(payload.positions) > 500:
        raise HTTPException(status_code=422, detail="graph layout is limited to 500 nodes")
    item = GraphLayout(**payload.model_dump(), owner_id=user.id)
    db.add(item)
    db.commit()
    return Envelope(data=model_dict(item))


@router.patch("/graph-layouts/{layout_id}", response_model=Envelope[dict[str, Any]])
def update_graph_layout(
    layout_id: str,
    payload: GraphLayoutCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    item = db.get(GraphLayout, layout_id)
    if item is None or item.deleted_at is not None or item.owner_id != user.id:
        raise HTTPException(status_code=404, detail="graph layout not found")
    if len(payload.positions) > 500:
        raise HTTPException(status_code=422, detail="graph layout is limited to 500 nodes")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    db.commit()
    return Envelope(data=model_dict(item))


@router.post("/settings", response_model=Envelope[dict[str, Any]], status_code=201)
def setting(
    payload: SettingCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> Envelope[dict[str, Any]]:
    previous = db.scalar(
        select(SettingRevision)
        .where(SettingRevision.key == payload.key)
        .order_by(SettingRevision.created_at.desc())
    )
    item = SettingRevision(
        key=payload.key,
        value=payload.value,
        previous_value=previous.value if previous else None,
        actor_id=user.id,
    )
    db.add(item)
    db.commit()
    return Envelope(data=model_dict(item))


@router.get("/settings", response_model=Envelope[list[dict[str, Any]]])
def settings(
    _user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, SettingRevision, limit), pagination={"limit": limit})


@router.get("/settings/active", response_model=Envelope[dict[str, Any]])
def active_settings(
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(SettingRevision)
            .where(SettingRevision.deleted_at.is_(None))
            .order_by(SettingRevision.created_at.desc())
        )
    )
    active: dict[str, Any] = {}
    revisions: dict[str, str] = {}
    for row in rows:
        if row.key not in active:
            active[row.key] = row.value
            revisions[row.key] = row.id
    return Envelope(data={"values": active, "revision_ids": revisions})


@router.get("/settings/secrets", response_model=Envelope[list[dict[str, Any]]])
def secret_status(
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    rows = list(
        db.scalars(
            select(SecretRecord)
            .where(SecretRecord.deleted_at.is_(None))
            .order_by(SecretRecord.updated_at.desc())
        )
    )
    return Envelope(
        data=[
            {
                "id": row.id,
                "key": row.key,
                "key_version": row.key_version,
                "updated_at": row.updated_at,
                "configured": True,
            }
            for row in rows
        ]
    )


@router.post("/settings/secrets", response_model=Envelope[dict[str, Any]])
def store_secret(
    payload: SecretCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, Any]]:
    item = db.scalar(
        select(SecretRecord).where(
            SecretRecord.key == payload.key,
            SecretRecord.deleted_at.is_(None),
        )
    )
    encrypted = encrypt_secret(
        payload.value, settings.SECRET_ENCRYPTION_KEY.get_secret_value()
    )
    if item is None:
        item = SecretRecord(
            key=payload.key,
            encrypted_value=encrypted,
            key_version=1,
            actor_id=user.id,
        )
        db.add(item)
    else:
        item.encrypted_value = encrypted
        item.key_version += 1
        item.actor_id = user.id
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action="SECRET_ROTATED",
            target_type="SECRET_RECORD",
            target_id=item.id,
            detail={"key": item.key, "key_version": item.key_version},
        )
    )
    db.commit()
    return Envelope(
        data={
            "id": item.id,
            "key": item.key,
            "key_version": item.key_version,
            "configured": True,
        }
    )
