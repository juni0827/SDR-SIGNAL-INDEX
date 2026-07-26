from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from redis import Redis

from .config import Settings, get_settings

CHANNEL = "signal-index:events"


def publish_event(
    event_type: str,
    data: dict[str, Any],
    settings: Settings | None = None,
) -> None:
    config = settings or get_settings()
    payload = {
        "type": event_type,
        "data": data,
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    client = Redis.from_url(
        config.REDIS_URL,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        client.publish(CHANNEL, json.dumps(payload, default=str))
    finally:
        client.close()
