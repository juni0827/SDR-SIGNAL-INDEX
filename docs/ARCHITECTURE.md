# Architecture

Signal Index uses a provenance-first relational core. References between entities are explicit; JSON fields hold source-specific metadata and bounded arrays, not primary truth.

## Data layers

| Layer | Primary records | May overwrite another layer |
|---|---|---|
| Observed | receiver, frequency, immutable recording, external event | No |
| Machine-generated | segment, ASR candidate, extracted entity, embedding | No |
| User-corrected | manual transcript and segment/session edit | No |
| User interpretation | annotation, asserted relation, hypothesis | No |
| Local LLM hypothesis | draft hypothesis and hypothesis relation | No |
| Verification | review/status/history | No |

`Provenance` links any record to a source, URL, fetch/observation time, parser and pipeline versions, raw hash, confidence, correction state, license note, and optional archived raw object.

## Storage

PostgreSQL stores metadata, revisions, graph edges, searches and 384-dimensional vectors. Originals and derivatives use separate S3 keys:

```text
originals/{sha-prefix}/{sha256}/{safe-filename}
derived/{recording-id}/{pipeline-version}/processed.wav
derived/{recording-id}/{pipeline-version}/preview.ogg
derived/{recording-id}/{pipeline-version}/segments/{segment-id}.*
source-archive/{source-id}/{sha256}.bin
```

HTTP range requests are handled by S3 signed media URLs. The PWA service worker deliberately skips audio and media routes.

## Extension interfaces

- `SourceAdapter`: async fetch, parse, and deterministic deduplication.
- `SignalClassifier`: feature-to-label contract.
- `EmbeddingProvider`: replaceable audio embedding contract.
- Capture adapters can be attached to explicitly enabled receiver watchlists.

Temporal relations always store `causal_claim=false` unless a user explicitly creates a causal assertion. Computed code never promotes time order into causality.
