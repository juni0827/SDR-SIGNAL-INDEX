from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

import feedparser
from bs4 import BeautifulSoup

from .base import FetchResult, NormalizedRecord, stable_dedup_key
from .http import PoliteFetcher


class PayloadAdapter:
    source_name = "payload"
    parser_version = "1.0.0"

    def __init__(self, payload: bytes, record_type: str) -> None:
        self.payload = payload
        self.record_type = record_type

    async def fetch(self, cursor: str | None) -> FetchResult:
        return FetchResult(self.payload, cursor, None, datetime.now(UTC))

    def deduplicate_key(self, record: NormalizedRecord) -> str:
        return stable_dedup_key(record)


class CSVAdapter(PayloadAdapter):
    source_name = "csv"

    def parse(self, payload: bytes) -> list[NormalizedRecord]:
        text = payload.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows and text.strip():
            raise ValueError("CSV requires a header and at least one data row")
        return [
            NormalizedRecord(self.record_type, dict(row), confidence=0.8, raw=dict(row))
            for row in rows
        ]


class JSONAdapter(PayloadAdapter):
    source_name = "json"

    def parse(self, payload: bytes) -> list[NormalizedRecord]:
        decoded: Any = json.loads(payload)
        rows = decoded if isinstance(decoded, list) else [decoded]
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError("JSON source must contain an object or array of objects")
        return [
            NormalizedRecord(self.record_type, dict(row), confidence=0.8, raw=dict(row))
            for row in rows
        ]


class ManualFrequencyAdapter(JSONAdapter):
    source_name = "manual_frequency_list"

    def __init__(self, payload: bytes) -> None:
        super().__init__(payload, "FREQUENCY")


class ManualReceiverAdapter(JSONAdapter):
    source_name = "manual_receiver_list"

    def __init__(self, payload: bytes) -> None:
        super().__init__(payload, "RECEIVER")


class StaticSourceAdapter(JSONAdapter):
    source_name = "user_defined_static"


class RemoteAdapter:
    parser_version = "1.0.0"

    def __init__(
        self,
        url: str,
        record_type: str,
        allowed_hosts: set[str] | None = None,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        self.fetcher = PoliteFetcher(url, allowed_hosts=allowed_hosts)
        self.record_type = record_type
        self.etag = etag
        self.last_modified = last_modified

    async def fetch(self, cursor: str | None) -> FetchResult:
        return await self.fetcher.fetch(cursor, self.etag, self.last_modified)

    def deduplicate_key(self, record: NormalizedRecord) -> str:
        return stable_dedup_key(record)


class RSSAtomAdapter(RemoteAdapter):
    source_name = "rss_atom"

    def parse(self, payload: bytes) -> list[NormalizedRecord]:
        feed = feedparser.parse(payload)
        if feed.bozo and not feed.entries:
            raise ValueError(f"invalid RSS/Atom feed: {feed.bozo_exception}")
        return [
            NormalizedRecord(
                self.record_type,
                {
                    "title": entry.get("title", ""),
                    "description": entry.get("summary", ""),
                    "source_url": entry.get("link"),
                    "published": entry.get("published"),
                },
                source_url=entry.get("link"),
                confidence=0.7,
                raw=dict(entry),
            )
            for entry in feed.entries
        ]


class HTMLTableAdapter(RemoteAdapter):
    source_name = "generic_html_table"

    def __init__(
        self,
        url: str,
        record_type: str,
        table_selector: str = "table",
        allowed_hosts: set[str] | None = None,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        super().__init__(
            url,
            record_type,
            allowed_hosts,
            etag=etag,
            last_modified=last_modified,
        )
        self.table_selector = table_selector

    def parse(self, payload: bytes) -> list[NormalizedRecord]:
        soup = BeautifulSoup(payload, "html.parser")
        table = soup.select_one(self.table_selector)
        if table is None:
            raise ValueError("configured HTML table was not found")
        rows = table.select("tr")
        if not rows:
            return []
        headers = [cell.get_text(" ", strip=True) for cell in rows[0].select("th,td")]
        records: list[NormalizedRecord] = []
        for row in rows[1:]:
            values = [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
            if len(values) != len(headers):
                continue
            data = dict(zip(headers, values, strict=True))
            records.append(NormalizedRecord(self.record_type, data, confidence=0.6, raw=data))
        return records
