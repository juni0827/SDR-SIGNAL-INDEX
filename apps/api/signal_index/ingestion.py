from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from source_adapters.base import NormalizedRecord, stable_dedup_key
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ExternalEvent, FrequencyEntry, Provenance, Receiver, Source


def _optional_string(value: Any) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _optional_datetime(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    normalized = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def materialize_record(
    db: Session,
    *,
    source: Source,
    record: NormalizedRecord,
    fetched_at: datetime | None,
    raw_object_key: str | None,
) -> tuple[str, bool]:
    """Idempotently persist a normalized source record and its provenance."""

    dedup_key = stable_dedup_key(record)
    existing = db.scalar(
        select(Provenance).where(
            Provenance.source_id == source.id,
            Provenance.record_type == record.record_type,
            Provenance.raw_hash == dedup_key,
            Provenance.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing.record_id, False

    data = record.data
    record_type = record.record_type.upper()
    created = True
    if record_type == "FREQUENCY":
        item: Any = FrequencyEntry(
            frequency_hz=int(data["frequency_hz"]),
            lower_frequency_hz=(
                int(data["lower_frequency_hz"]) if data.get("lower_frequency_hz") else None
            ),
            upper_frequency_hz=(
                int(data["upper_frequency_hz"]) if data.get("upper_frequency_hz") else None
            ),
            mode=_optional_string(data.get("mode")),
            label=str(data.get("label") or data["frequency_hz"]),
            category=str(data.get("category") or "UNKNOWN").upper(),
            country_code=_optional_string(data.get("country_code")),
            station_name=_optional_string(data.get("station_name")),
            callsigns=_string_list(data.get("callsigns")),
            active_from=_optional_datetime(data.get("active_from")),
            active_to=_optional_datetime(data.get("active_to")),
            schedule=data.get("schedule") if isinstance(data.get("schedule"), dict) else {},
            source_id=source.id,
            confidence=float(data.get("confidence") or record.confidence),
            notes=_optional_string(data.get("notes")),
        )
    elif record_type == "RECEIVER":
        existing_receiver = db.scalar(
            select(Receiver).where(
                Receiver.base_url == str(data["base_url"]),
                Receiver.deleted_at.is_(None),
            )
        )
        if existing_receiver is None:
            item = Receiver(
                name=str(data["name"]),
                receiver_type=str(data.get("receiver_type") or "OTHER").upper(),
                base_url=str(data["base_url"]),
                country_code=_optional_string(data.get("country_code")),
                latitude=float(data["latitude"]) if data.get("latitude") not in {None, ""} else None,
                longitude=float(data["longitude"]) if data.get("longitude") not in {None, ""} else None,
                grid_locator=_optional_string(data.get("grid_locator")),
                min_frequency_hz=(
                    int(data["min_frequency_hz"]) if data.get("min_frequency_hz") else None
                ),
                max_frequency_hz=(
                    int(data["max_frequency_hz"]) if data.get("max_frequency_hz") else None
                ),
                supported_modes=_string_list(data.get("supported_modes")),
                status=str(data.get("status") or "UNKNOWN").upper(),
                metadata_json=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
                tuning_url_template=_optional_string(data.get("tuning_url_template")),
            )
        else:
            # Directory refreshes must not overwrite an owner's capture
            # transport or bookmark.  Merge only provenance-facing catalogue
            # metadata and retain the established receiver identity.
            item = existing_receiver
            metadata = dict(item.metadata_json or {})
            discovered_value = data.get("metadata")
            discovered: dict[str, Any] = (
                discovered_value if isinstance(discovered_value, dict) else {}
            )
            metadata["directory_url"] = discovered.get("directory_url", metadata.get("directory_url"))
            metadata["directory_adapter"] = discovered.get(
                "directory_adapter", metadata.get("directory_adapter")
            )
            metadata["catalogue_only"] = bool(discovered.get("catalogue_only", True))
            item.metadata_json = metadata
            if item.tuning_url_template is None:
                item.tuning_url_template = _optional_string(data.get("tuning_url_template"))
            created = False
    elif record_type == "EVENT":
        item = ExternalEvent(
            title=str(data["title"]),
            event_type=str(data.get("event_type") or "IMPORTED"),
            started_at_utc=_optional_datetime(
                data.get("started_at_utc") or data.get("published")
            ),
            ended_at_utc=_optional_datetime(data.get("ended_at_utc")),
            country_codes=_string_list(data.get("country_codes")),
            location=(
                data["location"]
                if isinstance(data.get("location"), dict)
                else {"text": _optional_string(data.get("location"))}
            ),
            description=_optional_string(data.get("description")),
            source_url=_optional_string(data.get("source_url")) or record.source_url,
            source_name=source.name,
            confidence=float(data.get("confidence") or record.confidence),
        )
    else:
        raise ValueError(f"unsupported normalized record type: {record.record_type}")

    db.add(item)
    db.flush()
    db.add(
        Provenance(
            record_type=record_type,
            record_id=item.id,
            source_id=source.id,
            source_url=record.source_url,
            fetched_at=fetched_at,
            first_observed_at=record.observed_at,
            parser_version=source.parser_version,
            raw_hash=dedup_key,
            confidence=record.confidence,
            license_notes=record.license_notes or source.license_notes,
            raw_object_key=raw_object_key,
        )
    )
    return item.id, created
