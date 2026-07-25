from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from signal_index.security import validate_external_url

from .base import FetchResult

_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_last_request: defaultdict[str, float] = defaultdict(float)


class PoliteFetcher:
    def __init__(
        self,
        url: str,
        *,
        user_agent: str = "SignalIndex/0.1 (+private research index)",
        requests_per_second: float = 0.2,
        timeout_sec: float = 20,
        allowed_hosts: set[str] | None = None,
    ) -> None:
        self.url = validate_external_url(url, allowed_hosts)
        self.user_agent = user_agent
        self.interval = 1 / max(0.01, requests_per_second)
        self.timeout_sec = timeout_sec

    async def fetch(
        self,
        cursor: str | None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult:
        host = urlparse(self.url).hostname or ""
        async with _locks[host]:
            remaining = self.interval - (time.monotonic() - _last_request[host])
            if remaining > 0:
                await asyncio.sleep(remaining)
            headers = {"user-agent": self.user_agent}
            if etag:
                headers["if-none-match"] = etag
            if last_modified:
                headers["if-modified-since"] = last_modified
            async with httpx.AsyncClient(
                timeout=self.timeout_sec, follow_redirects=False, headers=headers
            ) as client:
                robots_url = urljoin(self.url, "/robots.txt")
                robots_response = await client.get(robots_url)
                if robots_response.status_code < 400:
                    parser = RobotFileParser()
                    parser.set_url(robots_url)
                    parser.parse(robots_response.text.splitlines())
                    if not parser.can_fetch(self.user_agent, self.url):
                        raise PermissionError("robots.txt disallows this source")
                response: httpx.Response | None = None
                for attempt in range(4):
                    response = await client.get(self.url)
                    if response.status_code not in {429, 500, 502, 503, 504}:
                        break
                    await asyncio.sleep(2**attempt)
                if response is None:
                    raise RuntimeError("source fetch produced no response")
                if response.status_code == 304:
                    return FetchResult(
                        payload=b"",
                        cursor=cursor,
                        source_url=self.url,
                        fetched_at=datetime.now(UTC),
                        etag=etag,
                        last_modified=last_modified,
                        not_modified=True,
                    )
                response.raise_for_status()
                if len(response.content) > 50 * 1024 * 1024:
                    raise ValueError("source response exceeds 50 MiB")
                _last_request[host] = time.monotonic()
                return FetchResult(
                    payload=response.content,
                    cursor=cursor,
                    source_url=self.url,
                    fetched_at=datetime.now(UTC),
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                )
