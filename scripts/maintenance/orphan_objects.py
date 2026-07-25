from __future__ import annotations

from signal_index.config import get_settings
from signal_index.database import SessionLocal
from signal_index.models import AudioSegment, Recording
from signal_index.storage import ObjectStorage


def main(delete: bool = False) -> None:
    settings = get_settings()
    storage = ObjectStorage(settings)
    with SessionLocal() as db:
        keys = {
            key
            for recording in db.query(Recording)
            for key in (
                recording.object_key,
                recording.processed_object_key,
                recording.preview_object_key,
            )
            if key
        }
        keys.update(
            key
            for segment in db.query(AudioSegment)
            for key in (
                segment.processed_object_key,
                segment.waveform_object_key,
                segment.spectrogram_object_key,
            )
            if key
        )
    paginator = storage.client.get_paginator("list_objects_v2")
    orphans: list[str] = []
    for page in paginator.paginate(Bucket=settings.S3_BUCKET):
        for item in page.get("Contents", []):
            if item["Key"] not in keys:
                orphans.append(str(item["Key"]))
    for key in orphans:
        print(key)
        if delete:
            storage.delete(key)
    print(f"{len(orphans)} orphan object(s); delete={delete}")


if __name__ == "__main__":
    main()
