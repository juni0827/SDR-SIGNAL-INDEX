from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class FetchResult:
    payload: bytes
    cursor: str | None
    source_url: str | None
    fetched_at: datetime
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


@dataclass(frozen=True)
class NormalizedRecord:
    record_type: str
    data: dict[str, Any]
    source_url: str | None = None
    observed_at: datetime | None = None
    confidence: float = 0.5
    license_notes: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    source_name: str
    parser_version: str

    async def fetch(self, cursor: str | None) -> FetchResult: ...

    def parse(self, payload: bytes) -> list[NormalizedRecord]: ...

    def deduplicate_key(self, record: NormalizedRecord) -> str: ...


def stable_dedup_key(record: NormalizedRecord) -> str:
    payload = json.dumps(
        {"record_type": record.record_type, "data": record.data},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
