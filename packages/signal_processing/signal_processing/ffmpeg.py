from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ProcessingPreset


class MediaProcessError(RuntimeError):
    def __init__(self, stage: str, return_code: int, stderr: str) -> None:
        super().__init__(f"{stage} failed with code {return_code}: {stderr[-500:]}")
        self.stage = stage
        self.return_code = return_code
        self.stderr = stderr


@dataclass(frozen=True)
class MediaMetadata:
    duration_sec: float
    sample_rate: int
    channels: int
    codec: str


def run(args: list[str], stage: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=900)
    if result.returncode != 0:
        raise MediaProcessError(stage, result.returncode, result.stderr)
    return result


def probe(path: Path, ffprobe_path: str = "ffprobe") -> MediaMetadata:
    result = run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels,codec_name:format=duration",
            "-of",
            "json",
            str(path),
        ],
        "METADATA_EXTRACTION",
    )
    payload: dict[str, Any] = json.loads(result.stdout)
    if not payload.get("streams"):
        raise MediaProcessError("METADATA_EXTRACTION", 1, "no audio stream")
    stream = payload["streams"][0]
    return MediaMetadata(
        duration_sec=float(payload.get("format", {}).get("duration", 0.0)),
        sample_rate=int(stream["sample_rate"]),
        channels=int(stream["channels"]),
        codec=str(stream.get("codec_name", "unknown")),
    )


def normalize_audio(
    source: Path,
    destination: Path,
    preset: ProcessingPreset,
    ffmpeg_path: str = "ffmpeg",
) -> None:
    filters = (
        f"highpass=f={preset.low_hz},lowpass=f={preset.high_hz},"
        f"adeclick,highpass=f=20,loudnorm=I={preset.loudness_lufs}:TP=-1.5:LRA=11"
    )
    run(
        [
            ffmpeg_path,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-i",
            str(source),
            "-map_metadata",
            "-1",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            filters,
            "-c:a",
            "pcm_s16le",
            str(destination),
        ],
        "NORMALIZE",
    )


def create_preview(source: Path, destination: Path, ffmpeg_path: str = "ffmpeg") -> None:
    run(
        [
            ffmpeg_path,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-i",
            str(source),
            "-c:a",
            "libopus",
            "-b:a",
            "48k",
            str(destination),
        ],
        "PREVIEW",
    )


def extract_segment(
    source: Path,
    destination: Path,
    start_sec: float,
    end_sec: float,
    ffmpeg_path: str = "ffmpeg",
) -> None:
    if end_sec <= start_sec:
        raise ValueError("segment end must be after start")
    run(
        [
            ffmpeg_path,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-ss",
            f"{start_sec:.3f}",
            "-to",
            f"{end_sec:.3f}",
            "-i",
            str(source),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ],
        "SEGMENT_EXTRACTION",
    )
