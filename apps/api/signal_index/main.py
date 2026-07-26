from __future__ import annotations

import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse
from redis import Redis
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from .config import get_settings
from .database import SessionLocal
from .logging import configure_logging
from .models import User
from .routes import auth, catalog, health, realtime, recordings, tools
from .security import hash_password

settings = get_settings()
configure_logging("api")
log = structlog.get_logger()
redis_client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.25, socket_timeout=0.25)
local_rate: defaultdict[tuple[str, int], int] = defaultdict(int)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == str(settings.FIRST_USER_EMAIL).lower()))
        if existing is None:
            user = User(
                email=str(settings.FIRST_USER_EMAIL).lower(),
                display_name="Signal Index Owner",
                password_hash=hash_password(settings.FIRST_USER_PASSWORD.get_secret_value()),
            )
            db.add(user)
            db.commit()
            log.info("first_user_created", user_id=user.id)
    yield


app = FastAPI(
    title="Signal Index API",
    version="0.1.0",
    description="Private structured SDR observation, processing, search, and local-agent API.",
    default_response_class=ORJSONResponse,
    debug=False,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["content-type", "authorization", "x-csrf-token", "x-request-id"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "[::1]", "*.local", "*.openai.site"]
    if not settings.production
    else [settings.APP_URL.split("://", 1)[-1].split("/", 1)[0]],
)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    ip = request.client.host if request.client else "unknown"
    window = int(time.time() // 60)
    limit = 10 if request.url.path.endswith("/auth/login") else 300
    key = f"rate:{ip}:{request.url.path}:{window}"
    try:
        count = cast(int, redis_client.incr(key))
        if count == 1:
            redis_client.expire(key, 90)
    except Exception as exc:
        local_key = (f"{ip}:{request.url.path}", window)
        local_rate[local_key] += 1
        count = local_rate[local_key]
        log.warning("redis_rate_limit_fallback", error_type=type(exc).__name__)
        for candidate in list(local_rate):
            if candidate[1] < window - 1:
                del local_rate[candidate]
    if count > limit:
        return JSONResponse(
            status_code=429,
            content={
                "data": {},
                "provenance": [],
                "query": {},
                "pagination": {},
                "warnings": ["rate limit exceeded"],
                "generated_at_utc": __import__("datetime").datetime.now(
                    __import__("datetime").UTC
                ).isoformat(),
            },
            headers={"retry-after": "60", "x-request-id": request_id},
        )
    try:
        response = await call_next(request)
    except Exception as exc:
        log.exception(
            "request_failed",
            error_type=type(exc).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "same-origin"
    response.headers["permissions-policy"] = "camera=(), microphone=(), geolocation=(self)"
    if settings.production:
        response.headers["strict-transport-security"] = "max-age=63072000; includeSubDomains"
    log.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    structlog.contextvars.clear_contextvars()
    return response


for route in (auth.router, health.router, recordings.router, tools.router, catalog.router, realtime.router):
    app.include_router(route, prefix="/api/v1")
