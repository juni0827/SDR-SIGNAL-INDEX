from datetime import UTC, datetime, timedelta

import pytest
from signal_processing.config import VADPreset
from signal_processing.relations import temporal_relation
from signal_processing.session import MergeWeights, SessionFeatures, merge_score
from signal_processing.vad import TimeRange, merge_and_split_ranges


def test_vad_merges_short_silence_and_splits_long_ranges() -> None:
    preset = VADPreset(
        minimum_speech_ms=100,
        minimum_silence_ms=300,
        padding_ms=0,
        maximum_segment_sec=2,
        merge_shorter_than_ms=100,
    )
    result = merge_and_split_ranges(
        [TimeRange(0, 1), TimeRange(1.2, 5.2)], preset, recording_duration=6
    )
    assert result == [TimeRange(0, 2), TimeRange(2, 4), TimeRange(4, 5.2)]


def test_session_grouping_score_rewards_shared_entities() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    left = SessionFeatures(now, 4_625_000, "r1", 0.9, frozenset({"K72"}), frozenset({"281"}), 0.8)
    right = SessionFeatures(
        now + timedelta(seconds=30),
        4_625_100,
        "r1",
        0.9,
        frozenset({"K72"}),
        frozenset({"281"}),
        0.8,
    )
    unrelated = SessionFeatures(
        now + timedelta(hours=2),
        12_000_000,
        "r2",
        0.1,
        frozenset(),
        frozenset(),
        0.1,
    )
    assert merge_score(left, right, MergeWeights()) > 0.8
    assert merge_score(left, unrelated, MergeWeights()) < 0.1


def test_temporal_relation_never_claims_causality() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    relation = temporal_relation(now, now + timedelta(minutes=10), 3600)
    assert relation is not None
    assert relation.predicate == "TEMPORALLY_PRECEDES"
    assert relation.causal_claim is False


def test_temporal_window_validation() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        temporal_relation(now, now, 0)
