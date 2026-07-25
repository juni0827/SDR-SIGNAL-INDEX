from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TemporalRelation:
    predicate: str
    delta_seconds: float
    confidence: float
    causal_claim: bool = False


def temporal_relation(subject_end: datetime, object_start: datetime, window_sec: float) -> TemporalRelation | None:
    if window_sec <= 0:
        raise ValueError("window_sec must be positive")
    delta = (object_start - subject_end).total_seconds()
    if abs(delta) > window_sec:
        return None
    if delta > 0:
        predicate = "TEMPORALLY_PRECEDES"
    elif delta < 0:
        predicate = "FOLLOWS"
    else:
        predicate = "CO_OCCURS_WITH"
    confidence = max(0.1, 1.0 - abs(delta) / window_sec)
    return TemporalRelation(predicate, delta, confidence, causal_claim=False)
