import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..dependencies import CurrentUser

router = APIRouter(tags=["realtime"])


@router.get("/events")
async def events(_user: CurrentUser) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        while True:
            payload = {
                "type": "heartbeat",
                "generated_at_utc": datetime.now(UTC).isoformat(),
                "polling_fallback_sec": 10,
            }
            yield f"event: heartbeat\ndata: {json.dumps(payload)}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(stream(), media_type="text/event-stream")
