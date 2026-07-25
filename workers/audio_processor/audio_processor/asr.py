from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from signal_index.config import get_settings


@lru_cache(maxsize=2)
def model(model_name: str, device: str, compute_type: str) -> Any:
    from faster_whisper import WhisperModel

    resolved_device = "cpu" if device in {"auto", "mps"} else device
    resolved_compute = "int8" if compute_type == "auto" and resolved_device == "cpu" else compute_type
    if resolved_compute == "auto":
        resolved_compute = "float16"
    return WhisperModel(model_name, device=resolved_device, compute_type=resolved_compute)


def transcribe(path: Path) -> list[dict[str, Any]]:
    settings = get_settings()
    engine = model(settings.ASR_MODEL, settings.ASR_DEVICE, settings.ASR_COMPUTE_TYPE)
    segments, info = engine.transcribe(
        str(path),
        language=None,
        beam_size=settings.ASR_BEAM_SIZE,
        temperature=[0.0, 0.2, 0.4, 0.6],
        word_timestamps=True,
        vad_filter=False,
        condition_on_previous_text=True,
    )
    words: list[dict[str, Any]] = []
    text: list[str] = []
    average_log_probability: list[float] = []
    for segment in segments:
        text.append(segment.text.strip())
        average_log_probability.append(float(segment.avg_logprob))
        for word in segment.words or []:
            words.append(
                {
                    "word": word.word,
                    "start": float(word.start),
                    "end": float(word.end),
                    "confidence": float(word.probability),
                }
            )
    if not text:
        return []
    confidence = sum(max(0.0, min(1.0, 1.0 + value)) for value in average_log_probability) / max(
        1, len(average_log_probability)
    )
    return [
        {
            "text": " ".join(text).strip(),
            "language": str(info.language),
            "confidence": confidence,
            "word_timestamps": words,
            "model_name": settings.ASR_MODEL,
            "model_version": "faster-whisper",
        }
    ]
