import hashlib
import ipaddress
import secrets
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import jwt
from argon2 import PasswordHasher
from fastapi import HTTPException, Request, status

from .config import Settings

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except Exception:
        return False


def create_session_token(user_id: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(hours=24), "type": "session"}
    return jwt.encode(payload, settings.JWT_SECRET.get_secret_value(), algorithm="HS256")


def decode_session_token(token: str, settings: Settings) -> str:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET.get_secret_value(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session") from exc
    if payload.get("type") != "session" or not isinstance(payload.get("sub"), str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    return str(payload["sub"])


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def require_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    cookie = request.cookies.get("signal_csrf")
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")


def hash_ip(ip: str | None, secret: str) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(f"{secret}:{ip}".encode()).hexdigest()


def validate_external_url(url: str, allowed_hosts: set[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("only unauthenticated HTTP(S) URLs are allowed")
    hostname = parsed.hostname.lower().rstrip(".")
    if allowed_hosts and hostname not in allowed_hosts:
        raise ValueError("host is not allowlisted")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("host could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("private, loopback, link-local, and reserved hosts are blocked")
    return url
