# Local tool API

Browser sessions use the secure cookie and CSRF header. Local agents may use:

```http
Authorization: Bearer <TOOL_API_KEY>
```

Every JSON response has:

```json
{
  "data": {},
  "provenance": [],
  "query": {},
  "pagination": {},
  "warnings": [],
  "generated_at_utc": "2026-07-25T00:00:00Z"
}
```

## Core endpoints

```text
GET  /api/v1/health
GET  /api/v1/capabilities
POST /api/v1/search/sessions
POST /api/v1/search/segments
POST /api/v1/search/entities
POST /api/v1/search/relations
POST /api/v1/search/events
GET  /api/v1/sessions/{id}
GET  /api/v1/segments/{id}
POST /api/v1/segments/{id}/transcripts
PATCH /api/v1/segments/{id}/transcripts/{transcript_id}/preferred
GET  /api/v1/recordings/{id}
GET  /api/v1/recordings/{id}/media
GET  /api/v1/frequencies/{frequency_hz}/activity
GET  /api/v1/entities/{id}/relations
GET  /api/v1/sessions/{id}/similar
POST /api/v1/correlations/query
POST /api/v1/relations
POST /api/v1/hypotheses
PATCH /api/v1/hypotheses/{id}
POST /api/v1/annotations
GET  /api/v1/export/context-bundle
POST /api/v1/export/context-bundle
GET  /api/v1/export/evidence-bundle
GET  /api/v1/events
POST /api/v1/events
PATCH /api/v1/events/{id}
POST /api/v1/inbox/upload
GET  /api/v1/inbox/{id}/media
GET  /api/v1/graph-layouts
POST /api/v1/graph-layouts
GET  /api/v1/export/data
GET  /api/v1/export/hypotheses/{id}/report
POST /api/v1/local-llm/chat
GET  /api/v1/realtime/events
GET  /api/v1/automation/status
PATCH /api/v1/receivers/{id}/capture
GET  /api/v1/receivers/{id}/tune?frequency_hz={hz}&mode={mode}
POST /api/v1/capture
PATCH /api/v1/capture/{id}
POST /api/v1/capture/{id}/run-now
POST /api/v1/sources
GET  /api/v1/sources/profiles
POST /api/v1/sources/profiles/{profile_id}/install
PATCH /api/v1/sources/{id}
POST /api/v1/sources/{id}/fetch
```

Search requests support bounded cursor pagination, frequency/date ranges, receiver, class, language, confidence, review/status/category, callsign and exact or normalized number group.

## Context bundle

```json
{
  "task": "compare_session_patterns",
  "subject_session_id": "session-a",
  "comparison_session_ids": ["session-b"],
  "include": [
    "metadata",
    "preferred_transcripts",
    "entities",
    "relations",
    "audio_feature_summary",
    "external_events",
    "provenance"
  ],
  "exclude_raw_audio": true,
  "token_budget": 24000
}
```

Raw audio is never inserted into context. Items contain IDs and PWA permalinks. The server rejects a bundle whose estimated serialized size exceeds the requested token budget.

The local-LLM endpoint is disabled by default, uses a server-side encrypted or environment API key, imposes prompt/output bounds, and returns its result explicitly labeled `LOCAL_LLM_HYPOTHESIS`.

## Autonomous collection control plane

`GET /api/v1/automation/status` reports persisted enabled sources and capture
schedules, active/failed jobs, direct-audio receiver configuration, scheduler
cadence, and environment blockers. It is safe for a local agent or monitoring
dashboard; it returns no capture URL template or credential.

For unattended capture the owner must first `PATCH /receivers/{id}/capture`
with an authorised same-host direct-audio template and `capture_enabled=true`.
Templates support only `{frequency_hz}`, `{frequency_khz}`, and `{mode}`. Then
create or enable a capture schedule. `CAPTURE_ENABLED=true` must be set in the
worker and scheduler environment. Sources and schedules are persisted in
PostgreSQL, so Celery Beat and workers continue without an open browser.

`GET /api/v1/sources/profiles` exposes maintained catalogue profiles for the
public WebSDR directory, the Receiverbook KiwiSDR directory, and Priyom's
public number-station calendar. `POST /api/v1/sources/profiles/{profile_id}/install`
creates (or re-enables) an auditable `Source`. The WebSDR profile remains
paused until its required reuse permission is recorded as `terms_approved`.
Other profiles are background-enabled. These
profiles materialize receiver or frequency *catalogue* data and preserve
provenance; they do not enable audio recording. `GET /receivers/{id}/tune`
renders a same-host browser tuning link when a receiver has a verified tuning
template, otherwise it returns the receiver home page with a warning.
