from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from statistics import median


@dataclass(frozen=True)
class ActivityPoint:
    observed_at: datetime
    duration_sec: float
    frequency_hz: int
    receiver_ids: tuple[str, ...]
    callsigns: tuple[str, ...]
    number_groups: tuple[str, ...]
    confidence: float


def summarize_activity(points: list[ActivityPoint]) -> dict[str, object]:
    ordered = sorted(points, key=lambda point: point.observed_at)
    arrivals = [
        (right.observed_at - left.observed_at).total_seconds()
        for left, right in zip(ordered, ordered[1:], strict=False)
    ]
    hourly = Counter(point.observed_at.hour for point in ordered)
    weekday = Counter(point.observed_at.weekday() for point in ordered)
    callsigns = Counter(value for point in ordered for value in point.callsigns)
    numbers = Counter(value for point in ordered for value in point.number_groups)
    cooccurrence = Counter(
        tuple(sorted((left, right)))
        for point in ordered
        for left in point.callsigns
        for right in point.number_groups
    )
    daily = Counter(point.observed_at.date().isoformat() for point in ordered)
    daily_values = list(daily.values())
    rolling_z: list[dict[str, float | str]] = []
    for index, (day, value) in enumerate(sorted(daily.items())):
        baseline = daily_values[max(0, index - 14) : index]
        if len(baseline) < 3:
            continue
        mean = sum(baseline) / len(baseline)
        variance = sum((item - mean) ** 2 for item in baseline) / len(baseline)
        deviation = variance**0.5
        z = (value - mean) / deviation if deviation else 0.0
        rolling_z.append({"day": day, "z_score": z, "change_point_candidate": abs(z) >= 3})
    confidence_buckets = Counter(min(9, int(point.confidence * 10)) for point in ordered)
    return {
        "activity_count": len(ordered),
        "active_duration_sec": sum(point.duration_sec for point in ordered),
        "session_count": len(ordered),
        "receiver_coverage": len({receiver for point in ordered for receiver in point.receiver_ids}),
        "hourly_seasonality": dict(sorted(hourly.items())),
        "weekly_seasonality": dict(sorted(weekday.items())),
        "callsign_frequency": dict(callsigns.most_common()),
        "number_group_frequency": dict(numbers.most_common()),
        "cooccurrence_matrix": [
            {"callsign": pair[0], "number_group": pair[1], "count": count}
            for pair, count in cooccurrence.most_common()
        ],
        "inter_arrival_seconds": arrivals,
        "repeated_pattern_interval_sec": median(arrivals) if arrivals else None,
        "rolling_z_score": rolling_z,
        "confidence_distribution": {
            f"{bucket / 10:.1f}-{(bucket + 1) / 10:.1f}": count
            for bucket, count in sorted(confidence_buckets.items())
        },
    }
