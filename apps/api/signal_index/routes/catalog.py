from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
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
    ProcessingJob,
    Provenance,
    Receiver,
    ReceiverStatus,
    SavedQuery,
    SecretRecord,
    SettingRevision,
    Source,
    SourceFetchJob,
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


class CapturePatch(BaseModel):
    enabled: bool | None = None
    schedule_utc: str | None = Field(default=None, min_length=1, max_length=160)
    repetition: str | None = Field(default=None, max_length=160)
    capture_duration_sec: int | None = Field(default=None, ge=1, le=86_400)
    maximum_storage_bytes: int | None = Field(default=None, ge=1)
    retention_policy: dict[str, Any] | None = None


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
        "websdr_directory",
        "kiwisdr_directory",
        "priyom_schedule",
        "user_defined_static",
        "manual_frequency_list",
        "manual_receiver_list",
    ]
    base_url: str | None = Field(default=None, max_length=2_048)
    enabled: bool = False
    parser_version: str = Field(default="1.0.0", max_length=80)
    license_notes: str | None = Field(default=None, max_length=10_000)
    config: dict[str, Any] = Field(default_factory=dict)


REMOTE_ADAPTER_TYPES = {
    "rss_atom",
    "generic_html_table",
    "websdr_directory",
    "kiwisdr_directory",
    "priyom_schedule",
}


PUBLIC_SOURCE_PROFILES: dict[str, dict[str, Any]] = {
    "websdr-directory": {
        "id": "websdr-directory",
        "name": "WebSDR directory (permission required)",
        "adapter_type": "websdr_directory",
        "base_url": "http://websdr.ewi.utwente.nl/~~websdrlistk?v=1&fmt=2&chseq=0",
        "license_notes": "The official directory response states that reuse in another website or automated system requires prior permission. Do not enable this source without that permission.",
        "config": {
            "allowed_hosts": ["websdr.ewi.utwente.nl"],
            "interval_sec": 86_400,
            "archive_raw_response": True,
            "profile_id": "websdr-directory",
            "requires_terms_approval": True,
        },
        "description": "Adapter for the official WebSDR directory JSON. It is installed paused and requires the operator's documented permission before background collection.",
    },
    "kiwisdr-receiverbook": {
        "id": "kiwisdr-receiverbook",
        "name": "KiwiSDR public receiver directory (Receiverbook)",
        "adapter_type": "kiwisdr_directory",
        "base_url": "https://www.receiverbook.de/?page=1&type=kiwisdr",
        "license_notes": "Receiverbook listing metadata remains subject to the source site's terms. Signal Index stores provenance and checks robots.txt before every fetch.",
        "config": {
            "allowed_hosts": ["www.receiverbook.de"],
            "interval_sec": 86_400,
            "max_pages": 31,
            "archive_raw_response": True,
            "profile_id": "kiwisdr-receiverbook",
        },
        "description": "Refreshes the bounded public KiwiSDR directory once per day. It creates browser-tunable receiver catalogue records only.",
    },
    "priyom-number-station-schedule": {
        "id": "priyom-number-station-schedule",
        "name": "Priyom number-station schedule",
        "adapter_type": "priyom_schedule",
        "base_url": "https://calendar2.priyom.org/events",
        "license_notes": "Priyom schedule content is CC BY-NC-SA 4.0. Preserve source attribution and do not treat a published schedule as a confirmed observation.",
        "config": {
            "allowed_hosts": ["calendar2.priyom.org"],
            "interval_sec": 21_600,
            "archive_raw_response": True,
            "profile_id": "priyom-number-station-schedule",
        },
        "description": "Refreshes Priyom's public calendar every six hours and materializes attributed NUMBERS frequency index entries.",
    },
}


class SourcePatch(BaseModel):
    enabled: bool | None = None
    parser_version: str | None = Field(default=None, max_length=80)
    license_notes: str | None = Field(default=None, max_length=10_000)
    config: dict[str, Any] | None = None


class ReceiverCapturePatch(BaseModel):
    """Explicitly opt a receiver into unattended direct-audio capture.

    A tuning page is not an audio transport.  The template therefore has to be
    supplied by the owner for a receiver they are allowed to record from.  It
    is rendered only with the three documented values and must remain on the
    receiver's registered host.
    """

    capture_url_template: str | None = Field(default=None, max_length=2_048)
    capture_enabled: bool | None = None


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


def source_interval_sec(config: dict[str, Any]) -> int:
    """Validate the bounded polling interval shared by create and update paths."""
    try:
        interval_sec = int(config.get("interval_sec", 3_600))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="source interval_sec must be an integer") from exc
    if not 300 <= interval_sec <= 604_800:
        raise HTTPException(status_code=422, detail="source interval_sec must be between 300 and 604800")
    return interval_sec


@router.get("/receivers", response_model=Envelope[list[dict[str, Any]]])
def receivers(
    _user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, Receiver, limit), pagination={"limit": limit})


@router.get("/receivers/{receiver_id}/tune", response_model=Envelope[dict[str, str]])
def receiver_tune_link(
    receiver_id: str,
    _user: CurrentUser,
    frequency_hz: int = Query(ge=0, le=100_000_000_000),
    mode: str = Query(default="USB", min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$"),
    db: Session = Depends(get_db),
) -> Envelope[dict[str, str]]:
    """Render a receiver's catalogue tuning URL with SSRF-safe host pinning."""
    item = db.get(Receiver, receiver_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="receiver not found")
    template = item.tuning_url_template
    if not template:
        return Envelope(
            data={"url": item.base_url},
            warnings=["this receiver has no verified tuning template; opened its base page instead"],
        )
    try:
        rendered = template.format(
            frequency_hz=frequency_hz,
            frequency_khz=f"{frequency_hz / 1_000:g}",
            mode=mode.lower(),
        )
    except (KeyError, ValueError, IndexError) as exc:
        raise HTTPException(status_code=422, detail="receiver tuning template is invalid") from exc
    base_host = item.base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    try:
        url = validate_external_url(rendered, {base_host.lower()})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="receiver tuning URL failed host validation") from exc
    return Envelope(data={"url": url})


@router.get("/receivers/{receiver_id}", response_model=Envelope[dict[str, Any]])
def receiver(receiver_id: str, _user: CurrentUser, db: Session = Depends(get_db)) -> Envelope[dict[str, Any]]:
    item = db.get(Receiver, receiver_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="receiver not found")
    return Envelope(data=model_dict(item))


@router.patch("/receivers/{receiver_id}/capture", response_model=Envelope[dict[str, Any]])
def patch_receiver_capture(
    receiver_id: str,
    payload: ReceiverCapturePatch,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    """Configure a receiver-owned direct audio transport for the worker.

    This endpoint deliberately does not guess WebSDR/KiwiSDR stream URLs. A
    browser-tuning URL is often not a legal or usable recording stream. The
    owner must provide an authorised direct-audio URL template on the same
    host, then explicitly opt the receiver in.
    """
    item = db.get(Receiver, receiver_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="receiver not found")
    metadata = dict(item.metadata_json or {})
    before = {
        "capture_url_template": metadata.get("capture_url_template"),
        "capture_enabled": bool(metadata.get("capture_enabled", False)),
    }
    if payload.capture_url_template is not None:
        try:
            rendered = payload.capture_url_template.format(
                frequency_hz=4_625_000,
                frequency_khz=4_625.0,
                mode="usb",
            )
        except (KeyError, ValueError, IndexError) as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    "capture_url_template may use only {frequency_hz}, "
                    "{frequency_khz}, and {mode}"
                ),
            ) from exc
        base_host = item.base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        try:
            validate_external_url(rendered, {base_host.lower()})
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        metadata["capture_url_template"] = payload.capture_url_template
    if payload.capture_enabled is not None:
        if payload.capture_enabled and not metadata.get("capture_url_template"):
            raise HTTPException(
                status_code=422,
                detail="capture_enabled requires an authorised capture_url_template",
            )
        metadata["capture_enabled"] = payload.capture_enabled
    item.metadata_json = metadata
    db.add(
        AuditLog(
            user_id=user.id,
            action="RECEIVER_CAPTURE_CONFIGURATION_UPDATED",
            target_type="RECEIVER",
            target_id=item.id,
            detail={
                "before": before,
                "after": {
                    "capture_url_template_configured": bool(metadata.get("capture_url_template")),
                    "capture_enabled": bool(metadata.get("capture_enabled", False)),
                },
            },
        )
    )
    db.commit()
    data = model_dict(item)
    data["capture_configured"] = bool(metadata.get("capture_url_template"))
    data["capture_enabled"] = bool(metadata.get("capture_enabled", False))
    return Envelope(data=data)


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
    remote = payload.adapter_type in REMOTE_ADAPTER_TYPES
    if remote and not payload.base_url:
        raise HTTPException(status_code=422, detail="remote adapter requires base_url")
    if payload.enabled and not remote:
        raise HTTPException(status_code=422, detail="only fetchable remote adapters can be enabled")
    if (
        payload.enabled
        and payload.adapter_type == "websdr_directory"
        and not payload.config.get("terms_approved")
    ):
        raise HTTPException(
            status_code=422,
            detail="websdr_directory requires config.terms_approved=true after obtaining source permission",
        )
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
    interval_sec = source_interval_sec(config) if remote else 3_600
    source = Source(**payload.model_dump(exclude={"config"}), config=config)
    # An owner explicitly enabling a remote source expects the scheduler to
    # collect it on its next Beat tick rather than one interval later.
    if source.enabled:
        source.last_fetched_at = datetime.now(UTC) - timedelta(seconds=interval_sec)
    db.add(source)
    db.commit()
    return Envelope(
        data=model_dict(source),
        warnings=[] if source.enabled else ["source is manually disabled"],
    )


@router.get("/sources/profiles", response_model=Envelope[list[dict[str, Any]]])
def source_profiles(_user: CurrentUser) -> Envelope[list[dict[str, Any]]]:
    """List maintained public catalogue profiles without installing them."""
    return Envelope(data=list(PUBLIC_SOURCE_PROFILES.values()))


@router.post("/sources/profiles/{profile_id}/install", response_model=Envelope[dict[str, Any]], status_code=201)
def install_source_profile(
    profile_id: str,
    _user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    profile = PUBLIC_SOURCE_PROFILES.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="public source profile not found")
    existing = db.scalar(select(Source).where(Source.name == str(profile["name"])))
    if existing is not None:
        if existing.config.get("profile_id") != profile_id:
            raise HTTPException(status_code=409, detail="a different source already uses this profile name")
        requires_approval = bool(existing.config.get("requires_terms_approval", False))
        existing.enabled = not requires_approval
        if existing.enabled:
            existing.last_fetched_at = datetime.now(UTC) - timedelta(
                seconds=source_interval_sec(dict(existing.config))
            )
        db.commit()
        return Envelope(
            data=model_dict(existing),
            warnings=(
                ["existing profile enabled"]
                if existing.enabled
                else ["profile remains paused until its source terms are explicitly approved"]
            ),
        )
    source = Source(
        name=str(profile["name"]),
        adapter_type=str(profile["adapter_type"]),
        base_url=str(profile["base_url"]),
        enabled=not bool(dict(profile["config"]).get("requires_terms_approval", False)),
        parser_version="1.0.0",
        license_notes=str(profile["license_notes"]),
        config=dict(profile["config"]),
        last_fetched_at=datetime.now(UTC) - timedelta(
            seconds=source_interval_sec(dict(profile["config"]))
        ),
    )
    db.add(source)
    db.flush()
    db.add(
        AuditLog(
            user_id=_user.id,
            action="PUBLIC_SOURCE_PROFILE_INSTALLED",
            target_type="SOURCE",
            target_id=source.id,
            detail={"profile_id": profile_id, "adapter_type": source.adapter_type},
        )
    )
    db.commit()
    return Envelope(
        data=model_dict(source),
        warnings=(
            ["background collection enabled; first fetch is queued by Celery Beat"]
            if source.enabled
            else ["profile installed paused; source terms require operator approval before enablement"]
        ),
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
    if changes.get("enabled") and item.adapter_type not in REMOTE_ADAPTER_TYPES:
        raise HTTPException(status_code=422, detail="source adapter is not remotely fetchable")
    proposed_config_value = changes.get("config")
    proposed_config: dict[str, Any] = (
        proposed_config_value
        if isinstance(proposed_config_value, dict)
        else dict(item.config or {})
    )
    if (
        changes.get("enabled")
        and item.adapter_type == "websdr_directory"
        and not proposed_config.get("terms_approved")
    ):
        raise HTTPException(
            status_code=422,
            detail="websdr_directory remains paused until config.terms_approved=true is recorded",
        )
    if "config" in changes and changes["config"] is not None:
        config = dict(changes["config"])
        source_interval_sec(
            {"interval_sec": config.get("interval_sec", item.config.get("interval_sec", 3_600))}
        )
        allowed_hosts = config.get("allowed_hosts", item.config.get("allowed_hosts", []))
        if not isinstance(allowed_hosts, list) or not all(isinstance(host, str) for host in allowed_hosts):
            raise HTTPException(status_code=422, detail="allowed_hosts must be a string list")
        config["allowed_hosts"] = [host.lower().rstrip(".") for host in allowed_hosts]
        changes["config"] = config
    for key, value in changes.items():
        setattr(item, key, value)
    if changes.get("enabled") is True:
        interval_sec = source_interval_sec(item.config)
        item.last_fetched_at = datetime.now(UTC) - timedelta(seconds=max(300, interval_sec))
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
    if payload.enabled and (
        not receiver.metadata_json.get("capture_enabled")
        or not receiver.metadata_json.get("capture_url_template")
    ):
        raise HTTPException(
            status_code=422,
            detail="enabled capture requires an explicitly enabled receiver capture transport",
        )
    try:
        next_run_at = next_schedule(payload.schedule_utc)
        if payload.repetition:
            next_schedule(payload.repetition)
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


@router.patch("/capture/{capture_id}", response_model=Envelope[dict[str, Any]])
def patch_capture(
    capture_id: str,
    payload: CapturePatch,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    item = db.get(CaptureJob, capture_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="capture job not found")
    receiver = db.get(Receiver, item.receiver_id)
    if receiver is None or receiver.deleted_at is not None:
        raise HTTPException(status_code=409, detail="capture receiver is no longer available")
    changes = payload.model_dump(exclude_unset=True)
    prospective_enabled = bool(changes.get("enabled", item.enabled))
    if prospective_enabled and (
        not receiver.metadata_json.get("capture_enabled")
        or not receiver.metadata_json.get("capture_url_template")
    ):
        raise HTTPException(
            status_code=422,
            detail="enabled capture requires an explicitly enabled receiver capture transport",
        )
    schedule = str(changes.get("schedule_utc", item.schedule_utc))
    repetition = changes.get("repetition", item.repetition)
    try:
        next_run_at = next_schedule(schedule)
        if repetition:
            next_schedule(str(repetition))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    before = model_dict(item)
    for key, value in changes.items():
        setattr(item, key, value)
    if prospective_enabled:
        item.status = "SCHEDULED"
        item.last_error = None
        item.next_run_at = next_run_at
    else:
        item.status = "CANCELLED"
        item.next_run_at = None
    db.add(
        AuditLog(
            user_id=user.id,
            action="CAPTURE_SCHEDULE_UPDATED",
            target_type="CAPTURE_JOB",
            target_id=item.id,
            detail={"before": before, "after": model_dict(item)},
        )
    )
    db.commit()
    return Envelope(
        data=model_dict(item),
        warnings=[] if item.enabled else ["capture schedule paused"],
    )


@router.post("/capture/{capture_id}/run-now", response_model=Envelope[dict[str, Any]], status_code=202)
def run_capture_now(
    capture_id: str,
    _user: CurrentUser,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, Any]]:
    item = db.get(CaptureJob, capture_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="capture job not found")
    if not item.enabled:
        raise HTTPException(status_code=409, detail="enable the capture schedule before running it")
    if not settings.CAPTURE_ENABLED:
        raise HTTPException(status_code=409, detail="CAPTURE_ENABLED is false in the worker environment")
    if item.status in {"STARTING", "CAPTURING", "PROCESSING"}:
        raise HTTPException(status_code=409, detail="capture job is already active")
    try:
        from audio_processor.tasks import capture_receiver

        result = capture_receiver.delay(item.id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="capture worker queue is unavailable") from exc
    item.status = "STARTING"
    db.commit()
    return Envelope(data={"capture_job_id": item.id, "task_id": result.id, "status": "STARTING"})


@router.get("/capture", response_model=Envelope[list[dict[str, Any]]])
def captures(
    _user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope(data=list_model(db, CaptureJob, limit), pagination={"limit": limit})


@router.get("/automation/status", response_model=Envelope[dict[str, Any]])
def automation_status(
    _user: CurrentUser,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, Any]]:
    """Expose the persisted autonomous-collection control plane.

    The browser is only a control surface.  These counts are derived from the
    database state consumed by the scheduler/worker containers, so they remain
    meaningful while the user is offline.
    """
    now = datetime.now(UTC)
    sources = list(
        db.scalars(select(Source).where(Source.deleted_at.is_(None))).all()
    )
    captures = list(
        db.scalars(select(CaptureJob).where(CaptureJob.deleted_at.is_(None))).all()
    )
    receiver_rows = list(
        db.scalars(select(Receiver).where(Receiver.deleted_at.is_(None))).all()
    )
    source_jobs = list(
        db.scalars(
            select(SourceFetchJob).where(
                SourceFetchJob.deleted_at.is_(None),
                SourceFetchJob.status.in_(["FETCHING", "RETRYING"]),
            )
        ).all()
    )
    processing_jobs = list(
        db.scalars(
            select(ProcessingJob).where(
                ProcessingJob.deleted_at.is_(None),
                ProcessingJob.status.in_(["PENDING", "PROCESSING"]),
            )
        ).all()
    )
    enabled_sources = [source for source in sources if source.enabled]
    enabled_captures = [job for job in captures if job.enabled]
    configured_receivers = [
        receiver
        for receiver in receiver_rows
        if receiver.metadata_json.get("capture_enabled")
        and receiver.metadata_json.get("capture_url_template")
    ]
    warnings: list[str] = []
    if enabled_captures and not settings.CAPTURE_ENABLED:
        warnings.append("capture schedules are enabled but CAPTURE_ENABLED is false")
    if enabled_captures and not configured_receivers:
        warnings.append("no receiver has an explicitly enabled direct-audio transport")
    return Envelope(
        data={
            "scheduler": {
                "service": "celery-beat",
                "runs_without_browser": True,
                "capture_globally_enabled": settings.CAPTURE_ENABLED,
                "source_tick_seconds": 60,
                "capture_tick_seconds": 30,
            },
            "sources": {
                "registered": len(sources),
                "enabled": len(enabled_sources),
                "active_fetches": len(source_jobs),
            },
            "captures": {
                "registered": len(captures),
                "enabled": len(enabled_captures),
                "due": sum(
                    1
                    for job in enabled_captures
                    if job.status == "SCHEDULED"
                    and job.next_run_at is not None
                    and job.next_run_at <= now
                ),
                "active": sum(
                    1
                    for job in captures
                    if job.status in {"STARTING", "CAPTURING", "PROCESSING"}
                ),
                "failed": sum(1 for job in captures if job.status == "FAILED"),
            },
            "receivers": {
                "registered": len(receiver_rows),
                "capture_configured": len(configured_receivers),
            },
            "processing": {"active": len(processing_jobs)},
        },
        warnings=warnings,
    )


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
