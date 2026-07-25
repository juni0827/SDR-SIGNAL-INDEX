from __future__ import annotations

import io
import os
import time
import wave
from datetime import UTC, datetime

import httpx
import pytest

pytestmark = pytest.mark.integration


def client() -> httpx.Client:
    if os.getenv("SIGNAL_INDEX_INTEGRATION") != "1":
        pytest.skip("set SIGNAL_INDEX_INTEGRATION=1 with the full Compose stack running")
    return httpx.Client(
        base_url=os.getenv("API_URL", "http://localhost:8000"),
        headers={"authorization": f"Bearer {os.environ['TOOL_API_KEY']}"},
        timeout=60,
    )


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16_000)
        recording.writeframes(b"\0\0" * 16_000 * 2)
    return output.getvalue()


def test_upload_processing_transcript_session_and_context_bundle() -> None:
    with client() as api:
        upload = api.post(
            "/api/v1/recordings/upload",
            files={"file": ("integration.wav", wav_bytes(), "audio/wav")},
            data={
                "frequency_hz": "4625000",
                "mode": "USB",
                "started_at_utc": datetime.now(UTC).isoformat(),
                "source_type": "MANUAL_UPLOAD",
            },
        )
        upload.raise_for_status()
        recording_id = upload.json()["data"]["recording"]["id"]
        recording: dict[str, object] = {}
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            response = api.get(f"/api/v1/recordings/{recording_id}")
            response.raise_for_status()
            recording = response.json()["data"]
            if recording["processing_status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(2)
        assert recording["processing_status"] == "COMPLETED", recording
        segments = recording["segments"]
        assert isinstance(segments, list) and segments
        sessions = api.post(
            "/api/v1/search/sessions",
            json={"frequency_min_hz": 4_625_000, "frequency_max_hz": 4_625_000},
        )
        sessions.raise_for_status()
        matching = [
            row
            for row in sessions.json()["data"]
            if recording_id in row["recording_ids"]
        ]
        assert matching
        bundle = api.post(
            "/api/v1/export/context-bundle",
            json={
                "task": "integration_test",
                "subject_session_id": matching[0]["id"],
                "include": ["metadata", "preferred_transcripts", "entities", "relations"],
                "exclude_raw_audio": True,
                "token_budget": 24000,
            },
        )
        bundle.raise_for_status()
        assert bundle.json()["data"]["raw_audio_included"] is False


def test_csv_source_import() -> None:
    with client() as api:
        response = api.post(
            "/api/v1/sources/import",
            files={"file": ("frequency.csv", b"frequency_hz,label\n4625000,Imported\n", "text/csv")},
            data={
                "source_name": f"Integration source {time.time_ns()}",
                "adapter_type": "csv",
                "record_type": "FREQUENCY",
                "archive_raw": "true",
            },
        )
        response.raise_for_status()
        assert response.json()["data"]["count"] == 1
