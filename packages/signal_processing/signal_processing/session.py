from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SessionFeatures:
    observed_at: datetime
    frequency_hz: int
    receiver_id: str | None
    acoustic_similarity: float
    callsigns: frozenset[str]
    number_groups: frozenset[str]
    message_structure_similarity: float


@dataclass(frozen=True)
class MergeWeights:
    time: float = 0.25
    frequency: float = 0.20
    acoustic: float = 0.20
    callsign: float = 0.15
    numbers: float = 0.12
    message: float = 0.08


def merge_score(left: SessionFeatures, right: SessionFeatures, weights: MergeWeights) -> float:
    delta = abs((right.observed_at - left.observed_at).total_seconds())
    time_score = max(0.0, 1.0 - delta / 600)
    frequency_score = max(0.0, 1.0 - abs(right.frequency_hz - left.frequency_hz) / 20_000)
    if left.receiver_id and right.receiver_id and left.receiver_id != right.receiver_id:
        frequency_score *= 0.85
    callsign_score = 1.0 if left.callsigns & right.callsigns else 0.0
    number_score = 1.0 if left.number_groups & right.number_groups else 0.0
    return (
        weights.time * time_score
        + weights.frequency * frequency_score
        + weights.acoustic * max(0.0, min(1.0, right.acoustic_similarity))
        + weights.callsign * callsign_score
        + weights.numbers * number_score
        + weights.message * max(0.0, min(1.0, right.message_structure_similarity))
    )
