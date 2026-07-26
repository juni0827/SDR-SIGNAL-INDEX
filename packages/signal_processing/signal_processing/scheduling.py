from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from croniter import croniter  # type: ignore[import-untyped]


def next_schedule(value: str, *, after: datetime | None = None) -> datetime:
    normalized = value.strip()
    if not normalized:
        raise ValueError("schedule must not be empty")
    base = (after or datetime.now(UTC)).astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        if not croniter.is_valid(normalized):
            raise ValueError("schedule must be an ISO-8601 UTC timestamp or five-field cron") from None
        next_value = croniter(normalized, base).get_next(datetime)
        return cast(datetime, next_value).astimezone(UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def subsequent_schedule(
    schedule_utc: str,
    repetition: str | None,
    *,
    after: datetime | None = None,
) -> datetime | None:
    candidate = (repetition or schedule_utc).strip()
    if croniter.is_valid(candidate):
        return next_schedule(candidate, after=after)
    if repetition:
        return next_schedule(repetition, after=after)
    return None
