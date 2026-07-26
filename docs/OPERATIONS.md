# Operations

## Health

`GET /api/v1/health` checks API execution, PostgreSQL, Redis, S3, FFmpeg, configured ASR/embedding models, Celery workers and optional local LLM configuration. Runtime updates use `GET /api/v1/realtime/events`; the UI falls back to ten-second Query polling.

## Structured logs

API and worker logs are JSON and include available values for timestamp, level, service, request ID, user/job/recording ID, stage, duration, error type and traceback.

## Retention and deletion

Domain records have `deleted_at` for soft deletion. Celery Beat runs the retention task daily. Capture-job policy takes precedence over source policy, which takes precedence over `RECORDING_RETENTION_DAYS`. Derived objects can be cleaned automatically; original capture/source objects are deleted only when that policy explicitly opts in. `scripts/maintenance/orphan_objects.py` reports objects missing a database reference; pass `delete=True` only in a controlled maintenance invocation.

## Backup and restore

The backup includes the PostgreSQL custom dump, object snapshot and SHA-256 manifest. Restore validates every listed item, drops/recreates only the `signal` database in the configured Compose stack, restores the dump and copies objects.

Test restore operations against a separate environment before relying on a backup policy.

## Capacity benchmark

The benchmark refuses production environments, creates deterministic temporary fixtures, measures representative indexed queries, and removes its fixtures:

```bash
make benchmark
```

The default target is 100,000 segments and 1,000,000 entities. Record the host, PostgreSQL configuration and output before making latency claims.
