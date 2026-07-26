from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from source_adapters.adapters import CSVAdapter, JSONAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..dependencies import CurrentUser
from ..models import (
    CaptureJob,
    ExternalEvent,
    FrequencyEntry,
    Hypothesis,
    InboxItem,
    Provenance,
    Receiver,
    SavedQuery,
    SettingRevision,
    Source,
)
from ..schemas import Envelope
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


@router.get("/frequencies", response_model=Envelope[list[dict[str, Any]]])
def frequencies(
    _user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, FrequencyEntry, limit), pagination={"limit": limit})


@router.get("/sources", response_model=Envelope[list[dict[str, Any]]])
def sources(
    _user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, Source, limit), pagination={"limit": limit})


@router.get("/sources/{source_id}", response_model=Envelope[dict[str, Any]])
def source(source_id: str, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[dict[str, Any]]:
    item = db.get(Source, source_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="source not found")
    return Envelope(data=model_dict(item))


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
    for record in records:
        data = record.data
        if record_type == "FREQUENCY":
            item: Any = FrequencyEntry(
                frequency_hz=int(data["frequency_hz"]),
                lower_frequency_hz=int(data["lower_frequency_hz"]) if data.get("lower_frequency_hz") else None,
                upper_frequency_hz=int(data["upper_frequency_hz"]) if data.get("upper_frequency_hz") else None,
                mode=str(data.get("mode") or "") or None,
                label=str(data.get("label") or data["frequency_hz"]),
                category=str(data.get("category") or "UNKNOWN").upper(),
                country_code=str(data.get("country_code") or "") or None,
                station_name=str(data.get("station_name") or "") or None,
                callsigns=[value.strip() for value in str(data.get("callsigns") or "").split(",") if value.strip()],
                schedule={},
                source_id=source.id,
                confidence=float(data.get("confidence") or record.confidence),
                notes=str(data.get("notes") or "") or None,
            )
        elif record_type == "RECEIVER":
            item = Receiver(
                name=str(data["name"]),
                receiver_type=str(data.get("receiver_type") or "OTHER").upper(),
                base_url=str(data["base_url"]),
                country_code=str(data.get("country_code") or "") or None,
                latitude=float(data["latitude"]) if data.get("latitude") else None,
                longitude=float(data["longitude"]) if data.get("longitude") else None,
                supported_modes=[
                    value.strip() for value in str(data.get("supported_modes") or "").split(",") if value.strip()
                ],
                status=str(data.get("status") or "UNKNOWN").upper(),
                metadata_json={"imported": True},
            )
        else:
            item = ExternalEvent(
                title=str(data["title"]),
                event_type=str(data.get("event_type") or "IMPORTED"),
                country_codes=[
                    value.strip() for value in str(data.get("country_codes") or "").split(",") if value.strip()
                ],
                location={"text": data.get("location")},
                description=str(data.get("description") or "") or None,
                source_url=str(data.get("source_url") or "") or None,
                source_name=source_name,
                confidence=float(data.get("confidence") or record.confidence),
            )
        db.add(item)
        db.flush()
        created.append(item.id)
        db.add(
            Provenance(
                record_type=record_type,
                record_id=item.id,
                source_id=source.id,
                source_url=record.source_url,
                parser_version=adapter.parser_version,
                raw_hash=adapter.deduplicate_key(record),
                confidence=record.confidence,
                license_notes=license_notes,
                raw_object_key=raw_key,
            )
        )
    db.commit()
    return Envelope(
        data={"source": model_dict(source), "created_record_ids": created, "count": len(created)},
        provenance=[{"raw_hash": raw_hash, "raw_object_key": raw_key}],
    )


@router.get("/hypotheses", response_model=Envelope[list[dict[str, Any]]])
def hypotheses(
    _user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, Hypothesis, limit), pagination={"limit": limit})


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


@router.get("/inbox", response_model=Envelope[list[dict[str, Any]]])
def inbox_list(
    _user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, InboxItem, limit), pagination={"limit": limit})


@router.post("/capture", response_model=Envelope[dict[str, Any]], status_code=201)
def capture(payload: CaptureCreate, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[dict[str, Any]]:
    lock_key = (
        f"capture:{payload.receiver_id}:{payload.frequency_hz}:{payload.schedule_utc}:"
        f"{payload.capture_duration_sec}"
    )
    existing = db.scalar(select(CaptureJob).where(CaptureJob.lock_key == lock_key))
    if existing:
        raise HTTPException(status_code=409, detail="duplicate capture schedule")
    item = CaptureJob(**payload.model_dump(), status="SCHEDULED", lock_key=lock_key)
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
