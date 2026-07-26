from __future__ import annotations

import argparse
import json
import time
from typing import Any

from signal_index.config import get_settings
from signal_index.database import SessionLocal
from sqlalchemy import text

PREFIX = "benchmark:"


def timed(db: Any, statement: Any, parameters: dict[str, Any]) -> float:
    started = time.perf_counter()
    db.execute(statement, parameters).all()
    return round((time.perf_counter() - started) * 1_000, 2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create deterministic scale fixtures and measure indexed metadata queries."
    )
    parser.add_argument("--segments", type=int, default=100_000)
    parser.add_argument("--entities", type=int, default=1_000_000)
    parser.add_argument("--cleanup", action="store_true")
    arguments = parser.parse_args()
    if not 1 <= arguments.segments <= 1_000_000:
        parser.error("--segments must be between 1 and 1000000")
    if not 1 <= arguments.entities <= 5_000_000:
        parser.error("--entities must be between 1 and 5000000")
    if get_settings().production:
        parser.error("benchmark fixtures are forbidden in production")
    with SessionLocal.begin() as db:
        if arguments.cleanup:
            db.execute(
                text("DELETE FROM extracted_entities WHERE raw_value LIKE :prefix"),
                {"prefix": f"{PREFIX}%"},
            )
            db.execute(
                text("DELETE FROM audio_segments WHERE class_features->>'benchmark' = 'true'")
            )
            print(json.dumps({"cleanup": "completed"}))
            return
        recording_id = db.scalar(
            text("SELECT id FROM recordings WHERE deleted_at IS NULL ORDER BY created_at LIMIT 1")
        )
        if not recording_id:
            parser.error("seed at least one recording before benchmarking")
        db.execute(
            text(
                """
                INSERT INTO audio_segments (
                    id, created_at, updated_at, recording_id, start_sec, end_sec,
                    duration_sec, segment_type, class_confidence, class_features,
                    reviewed, manually_adjusted
                )
                SELECT
                    md5('benchmark-segment-' || value::text),
                    now(), now(), :recording_id,
                    value::double precision, value::double precision + 0.8,
                    0.8, CASE WHEN value % 3 = 0 THEN 'VOICE' ELSE 'NOISE' END,
                    0.5, '{"benchmark": true}'::json, false, false
                FROM generate_series(1, :segment_count) AS value
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "recording_id": recording_id,
                "segment_count": arguments.segments,
            },
        )
        db.execute(
            text(
                """
                INSERT INTO extracted_entities (
                    id, created_at, updated_at, segment_id, entity_type, raw_value,
                    normalized_value, confidence, source, occurrences
                )
                SELECT
                    md5('benchmark-entity-' || value::text),
                    now(), now(),
                    md5('benchmark-segment-' || (((value - 1) % :segment_count) + 1)::text),
                    CASE WHEN value % 5 = 0 THEN 'CALLSIGN' ELSE 'NUMBER_GROUP' END,
                    :prefix || value::text,
                    lpad((value % 100000)::text, 5, '0'),
                    0.5, 'RULE', '[]'::json
                FROM generate_series(1, :entity_count) AS value
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "segment_count": arguments.segments,
                "entity_count": arguments.entities,
                "prefix": PREFIX,
            },
        )
    with SessionLocal() as db:
        segment_filter_ms = timed(
            db,
            text(
                "SELECT id FROM audio_segments "
                "WHERE deleted_at IS NULL AND segment_type='VOICE' "
                "ORDER BY created_at DESC, id DESC LIMIT 50"
            ),
            {},
        )
        entity_exact_ms = timed(
            db,
            text(
                "SELECT id FROM extracted_entities "
                "WHERE deleted_at IS NULL AND entity_type='NUMBER_GROUP' "
                "AND normalized_value=:value LIMIT 50"
            ),
            {"value": "12345"},
        )
        results = {
            "segments": arguments.segments,
            "entities": arguments.entities,
            "segment_filter_ms": segment_filter_ms,
            "entity_exact_ms": entity_exact_ms,
            "targets_ms": {"metadata_search_p95": 500, "session_detail_p95": 800},
        }
        results["passes_single_run_targets"] = (
            segment_filter_ms <= 500 and entity_exact_ms <= 500
        )
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
