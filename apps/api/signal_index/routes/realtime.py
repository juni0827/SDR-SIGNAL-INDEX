import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from ..config import get_settings
from ..dependencies import CurrentUser
from ..event_bus import CHANNEL

router = APIRouter(tags=["realtime"])


@router.get("/realtime/events")
async def events(_user: CurrentUser) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        client = Redis.from_url(
            get_settings().REDIS_URL,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(CHANNEL)
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=12
                )
                if message and message.get("type") == "message":
                    raw = str(message.get("data", "{}"))
                    event_type = str(json.loads(raw).get("type", "update"))
                    yield f"event: {event_type}\ndata: {raw}\n\n"
                else:
                    payload = {
                        "type": "heartbeat",
                        "generated_at_utc": datetime.now(UTC).isoformat(),
                        "polling_fallback_sec": 10,
                    }
                    yield f"event: heartbeat\ndata: {json.dumps(payload)}\n\n"
                    await asyncio.sleep(3)
        except Exception as exc:
            payload = {
                "type": "realtime_unavailable",
                "error_type": type(exc).__name__,
                "polling_fallback_sec": 10,
                "generated_at_utc": datetime.now(UTC).isoformat(),
            }
            yield f"event: realtime_unavailable\ndata: {json.dumps(payload)}\n\n"
        finally:
            await pubsub.close()
            await client.aclose()

    return StreamingResponse(stream(), media_type="text/event-stream")
