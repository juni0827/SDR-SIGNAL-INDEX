from __future__ import annotations

import hashlib
import traceback
from datetime import UTC, datetime, timedelta

from celery import Task
from signal_index.database import SessionLocal
from signal_index.ingestion import materialize_record
from signal_index.models import Source, SourceFetchJob
from signal_index.storage import ObjectStorage
from source_adapters.adapters import HTMLTableAdapter, RSSAtomAdapter
from source_adapters.base import SourceAdapter
from sqlalchemy import select

from .celery_app import celery


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
