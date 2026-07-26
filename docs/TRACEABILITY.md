# Specification traceability

Status meanings:

- **IMPLEMENTED**: production path exists from API/UI through persistence, with at least focused automated coverage.
- **PARTIAL**: useful implementation exists, but one or more required behaviors or release evidence remain.
- **BLOCKED-VERIFY**: implementation exists but the current environment has not executed the required external runtime.
- **NOT IMPLEMENTED**: no claim of support is made.

| ID | Requirement | Status | Primary implementation | Verification or remaining gate |
|---:|---|---|---|---|
| 1 | Complete repository deliverables | PARTIAL | monorepo, Compose, API/web/worker/scripts/docs | full release gate pending |
| 2 | prescribed stack | IMPLEMENTED | `pyproject.toml`, `apps/web/package.json`, Compose | lock/install checks |
| 3 | separated system layers | IMPLEMENTED | apps/workers/packages separation | import-boundary review |
| 4 | evidence layer separation/provenance | IMPLEMENTED | models: Provenance, Revision, Transcript, Hypothesis, Relation | model/service tests |
| 5 | core entities | IMPLEMENTED | `models.py`, migrations | migration test pending current env |
| 6 | full audio pipeline | PARTIAL | `audio_processor/tasks.py` | real FFmpeg/ASR run pending |
| 7 | preprocessing modes/A-B | IMPLEMENTED | FFmpeg presets, signed media, audio review | browser test expansion |
| 8 | configurable VAD and manual rerun | IMPLEMENTED | VAD preset, reprocess job, split/merge API/UI | real worker rerun test |
| 9 | rule classifier/plugin boundary | IMPLEMENTED | `features.py`, manual classification endpoint | unit tests |
| 10 | faster-whisper candidates | IMPLEMENTED | `asr.py`, Transcript candidates/correction UI | model runtime pending |
| 11 | number/callsign processors | IMPLEMENTED | `numbers.py`, `entities.py` | unit tests |
| 12 | three embedding classes | IMPLEMENTED | PyTorch audio/text plus session composite | pgvector runtime pending |
| 13 | weighted session grouping | IMPLEMENTED | `grouping.py`, worker merge path, revisions | DB integration test needed |
| 14 | combined search | PARTIAL | `services.py`, pg indexes | remaining cross-table filters/performance |
| 15 | analysis metrics | PARTIAL | analytics summary/activity/correlation | change-point and complete matrix UI absent |
| 16 | relation graph | PARTIAL | graph API and React Flow filters/evidence/JSON | PNG/SVG and saved layouts absent |
| 17 | multilayer timeline | PARTIAL | timeline API and real layer UI | overlay comparison not complete |
| 18 | spectrum explorer | PARTIAL | frequency catalog/activity/filter backend | heatmap/watchlist interaction incomplete |
| 19 | receiver map | PARTIAL | MapLibre real receivers and detail | clustering/status history UI incomplete |
| 20 | audio review | PARTIAL | signed A/B media, artifacts, candidates, correction, split/merge/VAD/review/annotation | keyboard suite and full mobile QA pending |
| 21 | hypothesis notebook | PARTIAL | CRUD/history/context link | unresolved evidence editor/history UI incomplete |
| 22 | external events | PARTIAL | model/import/correlation candidates | dedicated event CRUD UI absent |
| 23 | adapter plugin architecture | IMPLEMENTED | protocol + CSV/JSON/RSS/HTML/manual/static adapters | adapter tests |
| 24 | capture scheduler | IMPLEMENTED | CaptureJob, beat dispatcher, Redis lock, FFmpeg capture | live receiver validation pending |
| 25 | optional local LLM/browser agent | PARTIAL | server-only config, semantic routes/API | local endpoint UI action not required/core works |
| 26 | LLM Tool API | IMPLEMENTED | required endpoints and Envelope | contract tests |
| 27 | bounded context bundle | IMPLEMENTED | budget-aware context builder/permalinks | integration test |
| 28 | required UI routes | IMPLEMENTED | explicit App Router files | route smoke test |
| 29 | dashboard | PARTIAL | live summaries/sessions/receivers/hypotheses | storage/worker/failure cards incomplete |
| 30 | universal inbox | PARTIAL | online/offline text + audio upload | binary image/PDF object ingestion incomplete |
| 31 | PWA | PARTIAL | manifest/SW/offline queue/fallback shell | device install/sync-conflict QA pending |
| 32 | responsive layouts | PARTIAL | mobile nav/desktop shell/touch CSS | tablet 3-pane/gamepad/resizable panels incomplete |
| 33 | command palette | PARTIAL | Ctrl+K and route commands | record-aware command execution incomplete |
| 34 | auth/security | PARTIAL | cookie/CSRF/rate/CORS/hash/signed URL/MIME/SSRF/audit hook | WebAuthn/encrypted secret store absent |
| 35 | deletion/retention | PARTIAL | soft delete, backup/restore, orphan maintenance | complete policy scheduler/selective hard delete incomplete |
| 36 | observation/interpretation labels | IMPLEMENTED | separate records and UI Layer labels | UI review |
| 37 | exports | PARTIAL | JSON APIs/evidence ZIP/signed artifacts/graph JSON/JSONL script | CSV/Markdown report/hypothesis report absent |
| 38 | realtime updates | PARTIAL | SSE and polling-capable Query clients | all event producers/reconnect UI verification pending |
| 39 | logs/health | IMPLEMENTED | structured logs and dependency checks | full stack health pending |
| 40 | settings | PARTIAL | versioned settings API/UI | runtime application of every setting incomplete |
| 41 | performance targets | BLOCKED-VERIFY | indexes/cursor limits/background processing/range S3 | 100k/1m benchmark not run |
| 42 | required tests | PARTIAL | backend/frontend/integration/Playwright suites | deeper real-stack assertions pending |
| 43 | deterministic seed | IMPLEMENTED | synthetic seed/audio | seed stack run pending current env |
| 44 | monorepo structure | IMPLEMENTED | repository tree | static review |
| 45 | development commands | PARTIAL | Makefile/README | fresh-host replay pending |
| 46 | environment variables | IMPLEMENTED | `.env.example`, Pydantic settings | config tests |
| 47 | failure conditions | PARTIAL | static fallbacks removed; persistence/worker paths exist | remaining partial rows above |
| 48 | twenty-step success scenario | BLOCKED-VERIFY | components exist across vertical path | single real-stack scenario not yet passed |
| 49 | phased implementation | PARTIAL | phase gates documented | phases not promoted until runtime evidence |
| 50 | truthful handoff | IMPLEMENTED | this matrix, phase gates, live capabilities | update on each release |

## Explicitly unimplemented or incomplete

The application does not currently claim WebAuthn, multipart S3 upload, spectrogram tiling, speaker identity, transmitter-location inference, full change-point analytics, graph PNG/SVG export, graph layout persistence, full tablet resizable panels, Gamepad navigation, or every requested export format. These remain visible here and in `/api/v1/capabilities` until code and release evidence exist.
