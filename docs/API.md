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
