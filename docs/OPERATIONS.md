# Operations

## Health

`GET /api/v1/health` checks API execution, PostgreSQL, Redis, S3, FFmpeg, configured ASR/embedding models and optional local LLM configuration. Worker processing state is also visible through `processing_jobs` and SSE/polling UI.

## Structured logs

API and worker logs are JSON and include available values for timestamp, level, service, request ID, user/job/recording ID, stage, duration, error type and traceback.

## Retention and deletion

Domain records have `deleted_at` for soft deletion. Hard deletion and derived cleanup should run only after a reviewed retention decision. `scripts/maintenance/orphan_objects.py` reports objects missing a database reference; pass `delete=True` only in a controlled maintenance invocation.

## Backup and restore

The backup includes the PostgreSQL custom dump, object snapshot and SHA-256 manifest. Restore validates every listed item, drops/recreates only the `signal` database in the configured Compose stack, restores the dump and copies objects.

Test restore operations against a separate environment before relying on a backup policy.
