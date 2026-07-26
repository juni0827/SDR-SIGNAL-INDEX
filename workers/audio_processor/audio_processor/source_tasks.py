from __future__ import annotations

import hashlib
import time
import traceback
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from celery import Task
from signal_index.database import SessionLocal
from signal_index.event_bus import publish_event
from signal_index.ingestion import materialize_record
from signal_index.models import Receiver, ReceiverStatus, Source, SourceFetchJob
from signal_index.security import validate_external_url
from signal_index.storage import ObjectStorage
from source_adapters.adapters import HTMLTableAdapter, RSSAtomAdapter
from source_adapters.base import SourceAdapter
from sqlalchemy import select

from .celery_app import celery

log = structlog.get_logger()


@celery.task(bind=True, max_retries=4, name="audio_processor.source_tasks.fetch_source")
def fetch_source(self: Task, source_id: str) -> dict[str, int | str]:
    with SessionLocal.begin() as db:
        source = db.get(Source, source_id)
        if source is None or not source.enabled:
            raise RuntimeError("source is missing or manually disabled")
        job = SourceFetchJob(source_id=source.id, status="FETCHING", attempt=self.request.retries + 1)
        db.add(job)
        db.flush()
        job_id = job.id
        config = dict(source.config)
        url = source.base_url
        adapter_type = source.adapter_type
        cursor = source.cursor
        etag = source.etag
        last_modified = source.last_modified
    if not url:
        raise RuntimeError("remote source requires base_url")
    allowed_hosts = set(config.get("allowed_hosts", []))
    if adapter_type == "rss_atom":
        adapter: SourceAdapter = RSSAtomAdapter(
            url,
            str(config.get("record_type", "EVENT")),
            allowed_hosts,
            etag=etag,
            last_modified=last_modified,
        )
    elif adapter_type == "generic_html_table":
        adapter = HTMLTableAdapter(
            url,
            str(config.get("record_type", "FREQUENCY")),
            str(config.get("table_selector", "table")),
            allowed_hosts,
            etag=etag,
            last_modified=last_modified,
        )
    else:
        raise RuntimeError(f"scheduled remote adapter is not supported: {adapter_type}")
    try:
        import asyncio

        result = asyncio.run(adapter.fetch(cursor))
        records = [] if result.not_modified else adapter.parse(result.payload)
        raw_key = None
        if config.get("archive_raw_response", False) and result.payload:
            digest = hashlib.sha256(result.payload).hexdigest()
            raw_key = f"source-archive/{source_id}/{digest}.bin"
            ObjectStorage().upload(raw_key, result.payload, "application/octet-stream")
        with SessionLocal.begin() as db:
            source = db.get(Source, source_id)
            stored_job = db.get(SourceFetchJob, job_id)
            if source is None or stored_job is None:
                raise RuntimeError("source state disappeared during fetch")
            source.cursor = result.cursor
            source.etag = result.etag
            source.last_modified = result.last_modified
            source.last_fetched_at = result.fetched_at
            stored_job.status = "COMPLETED"
            stored_job.raw_response_object_key = raw_key
            materialized = 0
            for record in records:
                enriched_record = record
                if record.source_url is None and result.source_url is not None:
                    from source_adapters.base import NormalizedRecord

                    enriched_record = NormalizedRecord(
                        record_type=record.record_type,
                        data=record.data,
                        source_url=result.source_url,
                        observed_at=record.observed_at,
                        confidence=record.confidence,
                        license_notes=record.license_notes,
                        raw=record.raw,
                    )
                _, created = materialize_record(
                    db,
                    source=source,
                    record=enriched_record,
                    fetched_at=result.fetched_at,
                    raw_object_key=raw_key,
                )
                materialized += int(created)
            stored_job.records_parsed = materialized
        return {"source_id": source_id, "records": materialized}
    except Exception as exc:
        terminal = self.request.retries >= self.max_retries
        with SessionLocal.begin() as db:
            failed_job = db.get(SourceFetchJob, job_id)
            if failed_job:
                failed_job.status = "DEAD_LETTER" if terminal else "RETRYING"
                failed_job.error_type = type(exc).__name__
                failed_job.error_detail = f"{exc}\n{traceback.format_exc()}"[-40_000:]
                failed_job.dead_lettered_at = datetime.now(UTC) if terminal else None
        if terminal:
            raise
        raise self.retry(
            exc=exc, countdown=min(3600, 2 ** self.request.retries * 30)
        ) from exc


@celery.task(name="audio_processor.source_tasks.dispatch_due_sources")
def dispatch_due_sources() -> dict[str, int]:
    now = datetime.now(UTC)
    dispatched = 0
    with SessionLocal.begin() as db:
        sources = list(
            db.scalars(
                select(Source).where(
                    Source.enabled.is_(True),
                    Source.deleted_at.is_(None),
                    Source.adapter_type.in_(["rss_atom", "generic_html_table"]),
                )
            )
        )
        for source in sources:
            interval_sec = max(300, int(source.config.get("interval_sec", 3_600)))
            due_at = (source.last_fetched_at or source.created_at) + timedelta(
                seconds=interval_sec
            )
            active = db.scalar(
                select(SourceFetchJob).where(
                    SourceFetchJob.source_id == source.id,
                    SourceFetchJob.status.in_(["FETCHING", "RETRYING"]),
                    SourceFetchJob.deleted_at.is_(None),
                )
            )
            if due_at <= now and active is None:
                fetch_source.delay(source.id)
                dispatched += 1
    return {"dispatched": dispatched}


@celery.task(name="audio_processor.source_tasks.check_receivers")
def check_receivers() -> dict[str, int]:
    checked = 0
    online = 0
    with SessionLocal() as db:
        receiver_ids = list(
            db.scalars(
                select(Receiver.id).where(
                    Receiver.deleted_at.is_(None),
                ).limit(1_000)
            )
        )
    for receiver_id in receiver_ids:
        started = time.perf_counter()
        status = "OFFLINE"
        detail: dict[str, str] = {}
        try:
            with SessionLocal() as db:
                receiver = db.get(Receiver, receiver_id)
                if receiver is None:
                    continue
                host = receiver.base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
                url = validate_external_url(receiver.base_url, {host.lower()})
            response = httpx.head(url, timeout=8, follow_redirects=False)
            status = "ONLINE" if response.status_code < 500 else "OFFLINE"
            detail["http_status"] = str(response.status_code)
        except Exception as exc:
            detail = {"error_type": type(exc).__name__, "error": str(exc)[:500]}
        latency_ms = round((time.perf_counter() - started) * 1_000, 2)
        with SessionLocal.begin() as db:
            receiver = db.get(Receiver, receiver_id)
            if receiver is None:
                continue
            receiver.status = status
            receiver.last_checked_at = datetime.now(UTC)
            db.add(
                ReceiverStatus(
                    receiver_id=receiver.id,
                    status=status,
                    latency_ms=latency_ms,
                    detail=detail,
                )
            )
        try:
            publish_event(
                "receiver_status",
                {
                    "receiver_id": receiver_id,
                    "status": status,
                    "latency_ms": latency_ms,
                },
            )
        except Exception as exc:
            log.warning(
                "realtime_publish_failed",
                event_type="receiver_status",
                error_type=type(exc).__name__,
            )
        checked += 1
        online += int(status == "ONLINE")
    return {"checked": checked, "online": online}
