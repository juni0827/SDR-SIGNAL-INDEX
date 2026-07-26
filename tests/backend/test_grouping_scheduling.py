from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import numpy as np
from audio_processor.grouping import (
    configured_weights,
    cosine_similarity,
    merge_into_session,
    message_structure_similarity,
)
from signal_index.config import Settings
from signal_processing.scheduling import next_schedule, subsequent_schedule


class RevisionCollector:
    def __init__(self) -> None:
        self.values: list[Any] = []

    def add(self, value: Any) -> None:
        self.values.append(value)


def settings() -> Settings:
    return Settings(
        APP_ENV="test",
        SESSION_SECRET="s" * 32,
        JWT_SECRET="j" * 32,
        TOOL_API_KEY="t" * 32,
        SESSION_WEIGHT_TIME=0.4,
        SESSION_WEIGHT_FREQUENCY=0.4,
        SESSION_WEIGHT_ACOUSTIC=0.4,
        SESSION_WEIGHT_CALLSIGN=0.4,
        SESSION_WEIGHT_NUMBERS=0.2,
        SESSION_WEIGHT_MESSAGE=0.2,
    )


def test_configured_grouping_weights_are_normalized() -> None:
    weights = configured_weights(settings())
    assert sum(
        (
            weights.time,
            weights.frequency,
            weights.acoustic,
            weights.callsign,
            weights.numbers,
            weights.message,
        )
    ) == 1.0
    assert weights.time == 0.2


def test_similarity_is_bounded_and_structure_is_not_identity() -> None:
    assert cosine_similarity(np.array([1.0, 0.0]), np.array([1.0, 0.0])) == 1.0
    assert cosine_similarity(np.array([1.0]), np.array([1.0, 0.0])) == 0.0
    assert message_structure_similarity({"K72"}, {"S14"}, {"281", "46"}, {"999", "11"}) == 1.0


def test_merge_mutates_session_and_records_machine_revision() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    session = SimpleNamespace(
        id="session-a",
        start_at_utc=now,
        end_at_utc=now + timedelta(seconds=30),
        frequencies_hz=[4_625_000],
        receiver_ids=["receiver-a"],
        recording_ids=["recording-a"],
        segment_ids=["segment-a"],
        callsigns=["K72"],
        number_groups=["281"],
        languages=["en"],
        confidence=0.6,
    )
    recording = SimpleNamespace(
        id="recording-b",
        started_at_utc=now + timedelta(seconds=40),
        ended_at_utc=now + timedelta(seconds=70),
        frequency_hz=4_625_100,
        receiver_id="receiver-b",
    )
    db = RevisionCollector()
    merged = merge_into_session(
        db,  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
        recording=recording,  # type: ignore[arg-type]
        segment_ids=["segment-b"],
        callsigns={"K72", "S14"},
        number_groups={"992"},
        languages={"ru"},
        merge_score_value=0.86,
        evidence={"acoustic_similarity": 0.9},
    )
    assert merged.recording_ids == ["recording-a", "recording-b"]
    assert merged.segment_ids == ["segment-a", "segment-b"]
    assert merged.frequencies_hz == [4_625_000, 4_625_100]
    assert merged.callsigns == ["K72", "S14"]
    assert merged.confidence == 0.86
    assert len(db.values) == 1
    assert db.values[0].actor_type == "MACHINE"
    assert db.values[0].after["merge_score"] == 0.86


def test_iso_and_cron_schedules_are_utc_and_repeatable() -> None:
    base = datetime(2026, 1, 1, 18, 39, tzinfo=UTC)
    assert next_schedule("2026-01-02T18:40:00Z", after=base) == datetime(
        2026, 1, 2, 18, 40, tzinfo=UTC
    )
    assert next_schedule("40 18 * * *", after=base) == datetime(2026, 1, 1, 18, 40, tzinfo=UTC)
    assert subsequent_schedule("2026-01-02T18:40:00Z", None, after=base) is None
    assert subsequent_schedule("40 18 * * *", None, after=base) == datetime(
        2026, 1, 1, 18, 40, tzinfo=UTC
    )
