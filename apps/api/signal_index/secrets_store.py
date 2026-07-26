from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import SecretRecord
from .security import decrypt_secret


def resolved_secret(db: Session, settings: Settings, key: str, fallback: str) -> str:
    item = db.scalar(
        select(SecretRecord).where(
            SecretRecord.key == key,
            SecretRecord.deleted_at.is_(None),
        )
    )
    if item is None:
        return fallback
    return decrypt_secret(
        item.encrypted_value,
        settings.SECRET_ENCRYPTION_KEY.get_secret_value(),
    )
