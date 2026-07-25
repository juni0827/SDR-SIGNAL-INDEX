# SDR Signal Index

SDR Signal Index is a private, self-hosted PWA for preserving, processing, indexing, searching, and reviewing public SDR observations and user-supplied recordings. Observed facts, machine output, user corrections, interpretations, local-LLM hypotheses, external events, and verification state are stored as separate layers with provenance.

## Architecture

```text
Next.js PWA ── FastAPI ── PostgreSQL + pgvector
     │             │              │
 IndexedDB       Celery ─────── Redis
                   │
        FFmpeg / VAD / ASR / embeddings
                   │
             S3-compatible storage
```

The monorepo separates the web client, API, audio worker, source adapters, signal-processing package, database migrations, infrastructure, operational scripts, and tests.

## Local development

Requirements: Docker with Compose, Node.js 22+, Python 3.12+, FFmpeg, and GNU Make.

```bash
cp .env.example .env
docker compose up -d postgres redis minio minio-init
make install
make migrate
make seed
make dev
```

Open `http://localhost:3000`. The initial account is created from `FIRST_USER_EMAIL` and `FIRST_USER_PASSWORD` in `.env`; public registration is disabled.

Run validation with:

```bash
make lint
make typecheck
make test
make e2e
```

Start the complete containerized stack with:

```bash
docker compose up --build
```

## Data and security principles

- Original audio objects are immutable; every processed derivative has its own key and pipeline version.
- Local LLM output never overwrites observed or manually corrected data.
- Files are kept in a private S3-compatible bucket and served with short-lived signed URLs.
- Authentication uses an HTTP-only session cookie, CSRF protection, an account allowlist, and rate limits.
- Fetch adapters validate URLs, enforce per-domain limits, and are disabled until explicitly configured.
- Capture jobs only run for receivers and frequencies that the user explicitly enables.
- All internal timestamps are UTC.

## Deployment

The web and API containers can be deployed independently. PostgreSQL, Redis, and S3-compatible storage may be replaced by managed services. HTTPS is required in production, and secrets must be supplied by the deployment platform rather than committed.

API documentation is exposed at `/api-docs` in the PWA and `/docs` on the FastAPI service. The structured local-agent API is under `/api/v1`.

License: Apache-2.0. Public source data remains subject to its original license and terms recorded in each provenance entry.
