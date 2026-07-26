from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from signal_index.config import Settings, get_settings


@lru_cache(maxsize=2)
def model(model_name: str, device: str, compute_type: str) -> Any:
    from faster_whisper import WhisperModel

    resolved_device = "cpu" if device in {"auto", "mps"} else device
    resolved_compute = "int8" if compute_type == "auto" and resolved_device == "cpu" else compute_type
    if resolved_compute == "auto":
        resolved_compute = "float16"
    return WhisperModel(model_name, device=resolved_device, compute_type=resolved_compute)


def _candidate(
    engine: Any,
    path: Path,
    *,
    beam_size: int,
    temperature: list[float],
    vad_filter: bool,
    profile: str,
    model_name: str,
) -> dict[str, Any] | None:
    segments, info = engine.transcribe(
        str(path),
        language=None,
        beam_size=beam_size,
        temperature=temperature,
        word_timestamps=True,
        vad_filter=vad_filter,
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
    joined = " ".join(value for value in text if value).strip()
    if not joined:
        return None
    confidence = sum(max(0.0, min(1.0, 1.0 + value)) for value in average_log_probability) / max(
        1, len(average_log_probability)
    )
    return {
        "text": joined,
        "language": str(info.language),
        "confidence": confidence,
        "word_timestamps": words,
        "model_name": model_name,
        "model_version": f"faster-whisper:{profile}",
        "profile": profile,
    }


def transcribe(path: Path, runtime_settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = runtime_settings or get_settings()
    engine = model(settings.ASR_MODEL, settings.ASR_DEVICE, settings.ASR_COMPUTE_TYPE)
    profiles: list[tuple[int, list[float], str]] = [
        (settings.ASR_BEAM_SIZE, [0.0, 0.2, 0.4, 0.6], "beam-primary")
    ]
    alternatives = [
        (1, [0.2, 0.4, 0.6, 0.8], "temperature-alternative"),
        (max(2, settings.ASR_BEAM_SIZE // 2), [0.0, 0.3, 0.6], "beam-alternative"),
        (1, [0.0], "greedy-alternative"),
    ]
    profiles.extend(alternatives[: settings.ASR_ALTERNATIVE_CANDIDATES])
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for beam_size, temperatures, profile in profiles:
        candidate = _candidate(
            engine,
            path,
            beam_size=beam_size,
            temperature=temperatures,
            vad_filter=settings.ASR_USE_VAD,
            profile=profile,
            model_name=settings.ASR_MODEL,
        )
        if candidate is None:
            continue
        key = (str(candidate["language"]), str(candidate["text"]).casefold())
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates
