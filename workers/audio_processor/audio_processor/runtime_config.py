from __future__ import annotations

from typing import Any

from signal_index.config import Settings
from signal_index.models import SettingRevision
from sqlalchemy import select
from sqlalchemy.orm import Session

SETTING_FIELDS = {
    "asr.model": "ASR_MODEL",
    "asr.device": "ASR_DEVICE",
    "vad.threshold": "VAD_THRESHOLD",
    "session.merge_threshold": "SESSION_MERGE_THRESHOLD",
    "similarity.threshold": "SIMILARITY_THRESHOLD",
}


def active_setting_values(db: Session) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(SettingRevision)
            .where(SettingRevision.deleted_at.is_(None))
            .order_by(SettingRevision.created_at.desc())
        )
    )
    values: dict[str, Any] = {}
    for row in rows:
        if row.key in values:
            continue
        stored = row.value
        values[row.key] = stored.get("value") if set(stored) == {"value"} else stored
    return values


def effective_worker_settings(base: Settings, values: dict[str, Any]) -> Settings:
    updates = {
        field: values[key]
        for key, field in SETTING_FIELDS.items()
        if key in values
    }
    return Settings.model_validate({**base.model_dump(), **updates})
