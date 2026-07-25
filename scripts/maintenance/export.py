from __future__ import annotations

import argparse
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from signal_index.database import SessionLocal
from signal_index.models import (
    Annotation,
    AudioSegment,
    ExternalEvent,
    ExtractedEntity,
    FrequencyEntry,
    Hypothesis,
    Provenance,
    Receiver,
    Recording,
    Relation,
    Source,
    Transcript,
    TransmissionSession,
)
from signal_index.serialization import model_dict
from sqlalchemy import select

MODELS: dict[str, type[Any]] = {
    "annotations": Annotation,
    "segments": AudioSegment,
    "events": ExternalEvent,
    "entities": ExtractedEntity,
    "frequencies": FrequencyEntry,
    "hypotheses": Hypothesis,
    "provenance": Provenance,
    "receivers": Receiver,
    "recordings": Recording,
    "relations": Relation,
    "sources": Source,
    "transcripts": Transcript,
    "sessions": TransmissionSession,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Signal Index metadata as a ZIP of JSONL.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--type", choices=sorted(MODELS), action="append")
    parser.add_argument("--id", action="append", default=[])
    arguments = parser.parse_args()
    selected = arguments.type or sorted(MODELS)
    manifest = {
        "app_version": "0.1.0",
        "schema_version": "0001",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "types": selected,
        "selective_ids": arguments.id,
        "raw_audio_included": False,
    }
    with SessionLocal() as db, zipfile.ZipFile(
        arguments.output, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        for name in selected:
            model = MODELS[name]
            statement = select(model)
            if arguments.id:
                statement = statement.where(model.id.in_(arguments.id))
            rows = db.scalars(statement.order_by(model.created_at))
            content = "\n".join(
                json.dumps(model_dict(row), ensure_ascii=False, default=str) for row in rows
            )
            archive.writestr(f"{name}.jsonl", content + ("\n" if content else ""))
    print(arguments.output)


if __name__ == "__main__":
    main()
