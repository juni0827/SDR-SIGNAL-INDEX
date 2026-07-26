from typing import Any

import httpx

from .config import Settings


async def local_chat(settings: Settings, messages: list[dict[str, str]]) -> dict[str, Any]:
    if not settings.LOCAL_LLM_ENABLED:
        raise RuntimeError("local LLM integration is disabled")
    if not settings.LOCAL_LLM_MODEL:
        raise RuntimeError("LOCAL_LLM_MODEL is not configured")
    headers = {
        "authorization": f"Bearer {settings.LOCAL_LLM_API_KEY.get_secret_value()}",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.LOCAL_LLM_BASE_URL.rstrip('/')}/chat/completions",
            headers=headers,
            json={"model": settings.LOCAL_LLM_MODEL, "messages": messages, "temperature": 0.1},
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload
