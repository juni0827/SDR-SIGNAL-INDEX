# Phase completion gates

A phase is complete only when all five gates pass. A file, route, interface, or mock is not completion evidence.

1. **Persistence:** a real migration and database record exist.
2. **Vertical behavior:** the UI or client request reaches the API, background work if applicable, persistence, and a read-back response.
3. **Failure behavior:** an actionable error is persisted or returned; no exception is silently ignored.
4. **Automated evidence:** a test asserts the resulting state, not only that a component renders or an input changes.
5. **Runtime evidence:** Compose services start and the phase smoke scenario runs against PostgreSQL, Redis, MinIO, and the worker.

## Current gate status

| Phase | Persistence | Vertical behavior | Failure behavior | Automated evidence | Runtime evidence | Status |
|---|---:|---:|---:|---:|---:|---|
| 1 — foundation | yes | yes | yes | partial | not rerun in current environment | PARTIAL |
| 2 — audio processing | yes | yes | yes | partial | not rerun in current environment | PARTIAL |
| 3 — ASR/entities/grouping | yes | yes | yes | partial | real ASR model run pending | PARTIAL |
| 4 — search/visual analysis | yes | yes | yes | partial | browser/API stack pending | PARTIAL |
| 5 — sources/capture | yes | yes | yes | partial | receiver-template capture pending | PARTIAL |
| 6 — hypotheses/agent API | yes | yes | yes | partial | context bundle stack test pending | PARTIAL |
| 7 — offline/QA/operations | yes | partial | yes | partial | backup/restore and PWA device matrix pending | PARTIAL |

No phase is marked complete until the last column is backed by a recorded command result.

## Required end-to-end release gate

The release gate is the twenty-step scenario in the original specification: login, upload, processing, VAD, artifacts, ASR candidates, entities, session creation, correction preservation, relation, timeline/graph, hypothesis, context bundle, PWA/offline sync, evidence ZIP, backup, and restore. The real-stack Playwright suite must fail fast when its services or fixture are unavailable; missing infrastructure must not be reported as a passing test.
