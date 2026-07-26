# SDR Signal Index

SDR Signal Index is a private, self-hosted PWA that preserves, processes, indexes, searches, and reviews public SDR observations and user-supplied recordings. It works without an LLM. An optional local OpenAI-compatible model or browser agent can use bounded, provenance-aware APIs.

## 1. Confirmed architecture

```text
Data sources
  CSV / JSON / manual / RSS / HTML tables / static sources / user audio
       │
       ▼
Source adapters ── polite fetch, validation, dedup, raw archive, provenance, DLQ
       │
       ├────────────── PostgreSQL 16 + pgvector + pg_trgm + full-text indexes
       │
       ▼
S3 private originals ── Celery + Redis ── FFmpeg / Silero VAD / features
                                         faster-whisper / entities / embeddings
       │                                                    │
       └──────── immutable original + versioned derivatives ┘
                                │
                                ▼
FastAPI tool API / signed media URLs / SSE
                                │
                                ▼
Next.js PWA ── TanStack Query / Zustand / IndexedDB / service worker
  responsive shell / audio review / spectrum / map / timeline / graph / notebook
```

Observed facts, machine results, user corrections, user interpretations, local-LLM hypotheses, external-event relationships, and verification status are separate records. Local LLM output never overwrites observation or correction tables.

## 2. Repository tree

```text
.
├── apps
│   ├── api/signal_index        FastAPI, SQLAlchemy models, auth, tool API
│   └── web                     Next.js responsive PWA
├── workers/audio_processor     Celery audio and source workers
├── packages
│   ├── signal_processing       FFmpeg, VAD, features, entities, grouping, embeddings
│   └── source_adapters         adapter protocol and seven generic adapters
├── infra
│   ├── docker                  API, worker, and web images
│   └── migrations              Alembic schema and PostgreSQL indexes
├── scripts
│   ├── seed                    deterministic synthetic dataset and audio
│   ├── backup                  database and object backup
│   ├── restore                 checksum-verified restore
│   └── maintenance             orphan-object inspection and cleanup
├── tests
│   └── backend                 unit and integration tests
├── docs                        API, architecture, security, operations
├── docker-compose.yml
├── .env.example
├── Makefile
└── pyproject.toml
```

## 3. Core data flow

```text
upload
→ streaming size limit + content signature + SHA-256
→ immutable S3 original
→ PostgreSQL Recording + Provenance + ProcessingJob
→ Celery queue
→ ffprobe metadata
→ 16 kHz mono + DC/high-pass + selected band-pass + loudness normalization
→ processed WAV and Opus preview
→ Silero VAD; RF energy fallback; pad/merge/split
→ acoustic features and rule classifier
→ per-segment WAV, waveform JSON, spectrogram PNG
→ faster-whisper candidate with language and word timestamps
→ NATO/Russian-extensible number and callsign extraction
→ acoustic embeddings
→ initial session grouping and composite embedding
→ relational/full-text/trigram/vector indexes
→ search, timeline, graph, corrections, hypotheses, context/evidence bundles
```

Every failure records stage, error code, stderr, attempt count, and traceback. The original object is never changed.

## 4. Current implementation status

This repository is a functional, persistence-backed implementation. The formerly shallow product surfaces now have real API, database or object-storage paths: graph exports/layouts, timeline comparison, spectrum watchlists, clustered receiver status, binary inbox, external events, layered hypotheses, requested metadata/report exports, optional passkeys, encrypted secrets, retention scheduling, multipart S3 transfer and Redis-backed realtime updates. The source of truth is:

- [Requirement traceability](docs/TRACEABILITY.md)
- [Phase completion gates](docs/PHASE_GATES.md)

In particular, a route, model, button, or provider interface is not counted as a completed feature. The release is still not called fully verified until a fresh host passes the real PostgreSQL/Redis/MinIO/Celery/FFmpeg/faster-whisper twenty-step end-to-end gate, the scale benchmark and the physical PWA device matrix.

## 5. Implementation phases

- Phase 1: monorepo, Compose, login/session security, PostgreSQL, MinIO, CRUD, PWA shell.
- Phase 2: upload, Celery, FFmpeg, artifacts, VAD, audio review.
- Phase 3: faster-whisper candidates, entity processors, session grouping.
- Phase 4: structured/full-text/trigram/vector indexes and visual exploration.
- Phase 5: generic adapters, source scheduler, capture safeguards, provenance and DLQ.
- Phase 6: hypothesis history, relation engine, context bundle and local-agent API.
- Phase 7: IndexedDB sync, responsive layouts, tests, backup/restore and hardening.

## Quick start

Requirements: Docker with Compose. Native development additionally requires Node.js 22+, Python 3.12+, FFmpeg, and GNU Make.

```bash
git clone https://github.com/juni0827/SDR-SIGNAL-INDEX.git
cd SDR-SIGNAL-INDEX
cp .env.example .env
```

Replace all secrets and the initial password in `.env`, then:

```bash
docker compose up -d postgres redis minio minio-init
make install
make migrate
make seed
make dev
```

Or run everything in containers:

```bash
docker compose up --build
```

Open:

- PWA: `http://localhost:3000`
- API: `http://localhost:8000`
- OpenAPI: `http://localhost:8000/docs`
- MinIO console: `http://localhost:9001`

The first account is created from `FIRST_USER_EMAIL` and `FIRST_USER_PASSWORD`. Public registration is disabled.

## Development commands

```bash
make install
make infra
make migrate
make seed
make dev
make lint
make typecheck
make test
make test-integration
make e2e
make e2e-stack E2E_EXTERNAL_SERVER=1
make benchmark
make backup
make restore BACKUP=/absolute/path/to/signal-index-backup.tar.gz
```

Audio dependencies are intentionally an install extra because PyTorch, Silero, and faster-whisper are large. `make install` includes them. The worker container also includes them.

`make e2e` runs deterministic browser/UI contracts with intercepted API responses. It is not the release gate. `make e2e-stack E2E_EXTERNAL_SERVER=1` runs the non-skipped, real API/worker/storage scenario and fails if that stack is unavailable.

## Local LLM and browser agents

Core behavior does not depend on AI. To enable an OpenAI-compatible local server:

```dotenv
LOCAL_LLM_ENABLED=true
LOCAL_LLM_BASE_URL=http://host.docker.internal:1234/v1
LOCAL_LLM_MODEL=local-model
LOCAL_LLM_API_KEY=local
```

The API key remains server-side. A browser agent gets predictable routes, semantic landmarks, ARIA labels, `data-testid` selectors, permalinks, URL query state, query JSON, and export controls. Direct structured access uses `Authorization: Bearer $TOOL_API_KEY`.

`POST /api/v1/local-llm/chat` is a bounded server-side convenience path. It is disabled unless `LOCAL_LLM_ENABLED=true`, never returns the configured key, and labels output as a local-LLM hypothesis rather than an observed fact.

## Processing presets and platform notes

- `VOICE` and `USB`/`LSB`: 300–3,000 Hz.
- `AM`: 150–4,500 Hz.
- All processed audio: 16 kHz mono PCM with loudness normalization.
- CPU defaults to faster-whisper `int8`; CUDA uses `float16` when `auto`.
- faster-whisper currently has no native Apple Metal backend, so Apple Silicon uses the supported CPU path. The original and candidates remain identical in data semantics.
- The baseline audio embedding executes PyTorch STFT/statistical projection and the text embedding executes deterministic PyTorch signed feature hashing; both are 384-dimensional. They provide acoustic/text similarity, never speaker identity, and are replaceable through provider interfaces without changing stored provenance fields.

## Security and data handling

- HTTP-only, SameSite session cookie; double-submit CSRF token.
- Account allowlist and no public sign-up.
- Argon2 password hashes and per-minute login/API rate limits.
- CORS allowlist, trusted hosts, HSTS in production, security headers.
- Private object bucket and 10-minute signed URLs; S3 server-side encryption request.
- Upload byte limit, media signature checks, safe filenames, no extension trust.
- SQLAlchemy parameter binding; FFmpeg only receives argument arrays.
- Fetch URL scheme/credential/DNS/private-address validation and explicit host allowlists.
- Disabled-by-default public source and receiver capture.
- Structured JSON request/job logs and audit records.
- Optional passkeys use one-time Redis challenges and WebAuthn verification; password login remains available.
- UI-managed sensitive values use AES-GCM with `SECRET_ENCRYPTION_KEY`; secret status APIs never return values.
- Binary inbox inputs are detected from byte signatures, optionally scanned by ClamAV, hashed, and stored privately.
- Large object writes use bounded S3 multipart transfers; audio is deliberately excluded from automatic PWA caching.

Production requires HTTPS and secrets provided by the deployment platform. Never commit `.env`.

For production passkeys configure the HTTPS relying party:

```dotenv
WEBAUTHN_RP_ID=signal.example.com
WEBAUTHN_RP_NAME=Signal Index
WEBAUTHN_ORIGIN=https://signal.example.com
SECRET_ENCRYPTION_KEY=<at-least-32-random-characters>
```

## Backups

`make backup` creates a PostgreSQL custom dump, object snapshot, and SHA-256 manifest. Restore is destructive to the target database and therefore requires an explicit archive:

```bash
make restore BACKUP=/absolute/path/to/backup.tar.gz
```

The restore script verifies checksums before replacing the target database and object data.

## Remaining verification gates

The code and documentation do not turn unavailable infrastructure into a passing result:

- Docker is required to execute PostgreSQL, Redis, MinIO, Celery and the actual faster-whisper vertical path.
- `make e2e-stack E2E_EXTERNAL_SERVER=1` must pass on that host before release.
- `make benchmark` must meet the stated latency targets on the intended database hardware.
- Installation, offline sync/conflict handling, passkeys and audio review require the requested physical-device matrix.

Spectrograms currently use bounded low-resolution PNG previews, an option allowed by the specification, rather than a tiled pyramid. Speaker identity and transmitter-location inference are intentionally outside the product’s claims.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Tool API](docs/API.md)
- [Security model](docs/SECURITY.md)
- [Operations](docs/OPERATIONS.md)
- [Requirement traceability](docs/TRACEABILITY.md)
- [Phase gates](docs/PHASE_GATES.md)

License: Apache-2.0. Imported public data remains subject to its recorded source license and terms.
