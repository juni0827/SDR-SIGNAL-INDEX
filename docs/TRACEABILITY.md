# Specification traceability

Status meanings:

- **IMPLEMENTED**: production path exists from API/UI through persistence, with at least focused automated coverage.
- **PARTIAL**: useful implementation exists, but one or more required behaviors or release evidence remain.
- **BLOCKED-VERIFY**: implementation exists but the current environment has not executed the required external runtime.
- **NOT IMPLEMENTED**: no claim of support is made.

| ID | Requirement | Status | Primary implementation | Verification or remaining gate |
|---:|---|---|---|---|
| 1 | Complete repository deliverables | PARTIAL | monorepo, Compose, API/web/worker/scripts/docs | fresh-host release gate pending |
| 2 | prescribed stack | IMPLEMENTED | `pyproject.toml`, `apps/web/package.json`, Compose | lock/install checks |
| 3 | separated system layers | IMPLEMENTED | apps/workers/packages separation | import-boundary review |
| 4 | evidence layer separation/provenance | IMPLEMENTED | models: Provenance, Revision, Transcript, Hypothesis, Relation | model/service tests |
| 5 | core entities | IMPLEMENTED | `models.py`, migrations `0001`–`0003` | Alembic chain/import verified |
| 6 | full audio pipeline | BLOCKED-VERIFY | `audio_processor/tasks.py`, immutable S3 originals, versioned derivatives | real Compose FFmpeg/ASR run pending |
| 7 | preprocessing modes/A-B | IMPLEMENTED | FFmpeg presets, signed media, Web Audio A/B/noise preview | focused UI test; device QA remains |
| 8 | configurable VAD and manual rerun | IMPLEMENTED | versioned presets, reprocess, split/merge API/UI/revisions | unit coverage; real worker rerun gate remains |
| 9 | rule classifier/plugin boundary | IMPLEMENTED | `features.py`, manual classification endpoint | unit tests |
| 10 | faster-whisper candidates | BLOCKED-VERIFY | `asr.py`, multiple immutable candidates/correction/preferred UI | model download/inference pending |
| 11 | number/callsign processors | IMPLEMENTED | `numbers.py`, `entities.py` | unit tests |
| 12 | three embedding classes | BLOCKED-VERIFY | PyTorch audio/text plus session composite | pgvector migration exists; real DB/model run pending |
| 13 | weighted session grouping | IMPLEMENTED | configurable weighted candidate selection, actual merge, revisions | unit tests; real DB gate remains |
| 14 | combined search | IMPLEMENTED | structured/full-text/trigram/exact/vector filters and reproducible JSON | production-size latency unverified |
| 15 | analysis metrics | IMPLEMENTED | frequency/daily/hourly activity, baseline, rolling z, change candidates, co-occurrence, delays, source agreement | correlation is explicitly non-causal |
| 16 | relation graph | IMPLEMENTED | React Flow filters/evidence, layout persistence, JSON/SVG/PNG export | browser rendering QA pending |
| 17 | multilayer timeline | IMPLEMENTED | live layers, two-period overlay, UTC/local display, delta and query JSON | large-range UX QA pending |
| 18 | spectrum explorer | IMPLEMENTED | activity heatmap, date/mode/receiver filters, watch/favorite and tuning links | performance QA pending |
| 19 | receiver map | IMPLEMENTED | MapLibre clustering, range/status/detail/activity, tuning and status history | device GPU QA pending |
| 20 | audio review | IMPLEMENTED | signed A/B media, waveform/spectrogram, loop/rate/gain, candidates, correction, entity/annotation/split/merge/VAD/review/keys | device/audio-output QA pending |
| 21 | hypothesis notebook | IMPLEMENTED | layered evidence, sessions/events/queries, user/LLM notes, status history and report | real-stack workflow gate remains |
| 22 | external events | IMPLEMENTED | manual CRUD UI/API, imports and non-causal correlation candidates | bulk import covered by generic adapters |
| 23 | adapter plugin architecture | IMPLEMENTED-WITH-VERIFY | protocol + CSV/JSON/RSS/HTML/manual/static plus WebSDR directory, KiwiSDR Receiverbook and Priyom calendar adapters; profile install; robots/rate/ETag/DLQ/provenance | live source runs need Compose verification; public sites can change markup/API |
| 24 | capture scheduler | BLOCKED-VERIFY | persisted source/capture control plane, Beat dispatcher, Redis lock, receiver direct-audio opt-in, capacity/retention, safe FFmpeg capture | real permitted receiver stream and Compose run pending |
| 25 | optional local LLM/browser agent | IMPLEMENTED | bounded server-side OpenAI-compatible call plus semantic/ARIA/permalink API/UI | local endpoint availability remains optional |
| 26 | LLM Tool API | IMPLEMENTED | required endpoints and Envelope | contract tests |
| 27 | bounded context bundle | IMPLEMENTED | budget-aware context builder/permalinks | integration test |
| 28 | required UI routes | IMPLEMENTED | explicit App Router files | route smoke test |
| 29 | dashboard | IMPLEMENTED | live watchlist/capture/failures/session/entity/storage/receiver/worker/hypothesis/query cards | real-stack state QA pending |
| 30 | universal inbox | IMPLEMENTED | audio/text/URL/image/PDF/CSV/JSON/observation, signature/checksum/private object, offline queue | large audio intentionally not cached offline |
| 31 | PWA | BLOCKED-VERIFY | install manifest, shell/cache rules, IndexedDB annotation/inbox, reconnect, conflict badge | iOS/iPadOS/Android/desktop install matrix pending |
| 32 | responsive layouts | IMPLEMENTED | mobile bottom nav, tablet/desktop split and 3-pane, resize, keyboard, optional Gamepad | physical-device QA pending |
| 33 | command palette | IMPLEMENTED | Ctrl/⌘+K, filtered commands, record search/frequency parsing/current review | browser-agent contract test exists |
| 34 | auth/security | IMPLEMENTED | cookie/CSRF/rate/CORS/Argon2/WebAuthn/signed URL/signature/malware hook/SSRF/audit/AES-GCM secret store | production HTTPS/authenticator QA pending |
| 35 | deletion/retention | IMPLEMENTED | soft/hard paths, scheduled source/capture/default retention, derivative cleanup, backups, restore, orphan/checksum | fresh-host restore pending |
| 36 | observation/interpretation labels | IMPLEMENTED | separate records and UI Layer labels | UI review |
| 37 | exports | IMPLEMENTED | JSON/JSONL/CSV/Markdown/ZIP/WAV/spectrogram PNG/graph JSON+PNG+SVG/hypothesis report | ZIP runtime gate pending |
| 38 | realtime updates | IMPLEMENTED | Redis pub/sub SSE producers, heartbeat/reconnect and TanStack polling fallback | multi-process Compose QA pending |
| 39 | logs/health | IMPLEMENTED | structured logs and dependency checks | full stack health pending |
| 40 | settings | PARTIAL | versioned settings API/UI; ASR/VAD/preset/session thresholds applied by worker | display/storage/source settings still have component-specific application boundaries |
| 41 | performance targets | BLOCKED-VERIFY | indexes/cursors/background/range S3/multipart/low-res previews plus deterministic benchmark | 100k/1m benchmark not run without PostgreSQL |
| 42 | required tests | PARTIAL | backend/frontend/integration/Playwright suites; default E2E is not skipped | real-stack and browser sandbox gates pending |
| 43 | deterministic seed | IMPLEMENTED | synthetic seed/audio | seed stack run pending current env |
| 44 | monorepo structure | IMPLEMENTED | repository tree | static review |
| 45 | development commands | BLOCKED-VERIFY | Makefile/README including benchmark | fresh Docker host replay pending |
| 46 | environment variables | IMPLEMENTED | `.env.example`, Pydantic settings | config tests |
| 47 | failure conditions | PARTIAL | no mock-only routes, persistence/migrations/worker/provenance/tests exist | runtime gates above prevent final-complete claim |
| 48 | twenty-step success scenario | BLOCKED-VERIFY | components exist across vertical path | single real-stack scenario not yet passed |
| 49 | phased implementation | PARTIAL | phase gates documented | phases not promoted until runtime evidence |
| 50 | truthful handoff | IMPLEMENTED | this matrix, phase gates, live capabilities | update on each release |

## Explicitly incomplete or unverified

- The twenty-step PostgreSQL/Redis/MinIO/Celery/faster-whisper release scenario has not run in this workspace because Docker is unavailable.
- Playwright Chromium is not present and its CDN download is blocked/truncated in this sandbox; all six UI-contract cases fail before test-body execution and are not recorded as passing.
- The 100k-segment/1m-entity benchmark is implemented but has not run against PostgreSQL.
- The PWA/passkey/audio UI still needs the requested physical iPhone, iPad, Android, Windows, Linux, Legion Go and macOS matrix.
- Spectrograms use bounded low-resolution previews rather than tiles, which is one of the alternatives allowed by requirement 41.
- Speaker identity and transmitter-location inference are intentionally not implemented; the product exposes acoustic similarity and receiver location only.
