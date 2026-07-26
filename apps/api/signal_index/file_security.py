from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

from fastapi import HTTPException

from .config import Settings


@dataclass(frozen=True)
class DetectedFile:
    mime_type: str
    item_type: str


def detect_file(payload: bytes) -> DetectedFile:
    header = payload[:32]
    stripped = payload[:4096].lstrip()
    if header.startswith(b"%PDF-"):
        return DetectedFile("application/pdf", "pdf")
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return DetectedFile("image/png", "image")
    if header.startswith(b"\xff\xd8\xff"):
        return DetectedFile("image/jpeg", "image")
    if header.startswith((b"GIF87a", b"GIF89a")):
        return DetectedFile("image/gif", "image")
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return DetectedFile("audio/wav", "audio")
    if header.startswith(b"fLaC"):
        return DetectedFile("audio/flac", "audio")
    if header.startswith(b"OggS"):
        return DetectedFile("audio/ogg", "audio")
    if header.startswith(b"\x1aE\xdf\xa3"):
        return DetectedFile("audio/webm", "audio")
    if stripped.startswith((b"{", b"[")):
        return DetectedFile("application/json", "json")
    try:
        text = payload[:64_000].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="unsupported or unrecognized file signature") from exc
    if "\x00" in text:
        raise HTTPException(status_code=415, detail="binary file type is not allowlisted")
    if "," in text and "\n" in text:
        return DetectedFile("text/csv", "csv")
    return DetectedFile("text/plain", "text")


def validate_declared_type(detected: DetectedFile, requested_type: str) -> None:
    if requested_type == "observation":
        return
    if detected.item_type != requested_type:
        raise HTTPException(
            status_code=415,
            detail=f"file signature is {detected.item_type}, not requested type {requested_type}",
        )


def scan_payload(payload: bytes, settings: Settings) -> None:
    if not settings.MALWARE_SCAN_ENABLED:
        return
    try:
        with socket.create_connection(
            (settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=10
        ) as connection:
            connection.sendall(b"zINSTREAM\0")
            view = memoryview(payload)
            for offset in range(0, len(view), 64 * 1024):
                chunk = view[offset : offset + 64 * 1024]
                connection.sendall(struct.pack(">I", len(chunk)))
                connection.sendall(chunk)
            connection.sendall(struct.pack(">I", 0))
            result = connection.recv(4096).decode("utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=503, detail="malware scanner is unavailable") from exc
    if "FOUND" in result:
        raise HTTPException(status_code=422, detail="malware scanner rejected the upload")
    if "OK" not in result:
        raise HTTPException(status_code=503, detail=f"malware scanner returned: {result[:200]}")
