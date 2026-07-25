from __future__ import annotations

import io
import json

import numpy as np
from PIL import Image


def waveform_json(samples: np.ndarray, points: int = 1200) -> bytes:
    if samples.size == 0:
        return b'{"min":[],"max":[]}'
    block = max(1, samples.size // points)
    usable = samples[: samples.size - samples.size % block]
    framed = usable.reshape(-1, block) if usable.size else samples.reshape(1, -1)
    payload = {
        "min": np.min(framed, axis=1).round(5).tolist(),
        "max": np.max(framed, axis=1).round(5).tolist(),
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def spectrogram_png(samples: np.ndarray, sample_rate: int, width: int = 1200, height: int = 320) -> bytes:
    import librosa

    stft = np.abs(librosa.stft(samples, n_fft=1024, hop_length=256))
    db = librosa.amplitude_to_db(stft, ref=np.max)
    normalized = np.clip((db + 80) / 80, 0, 1)
    red = np.clip(normalized * 2.4, 0, 1)
    green = np.clip((normalized - 0.25) * 1.9, 0, 1)
    blue = np.clip((normalized - 0.62) * 2.6, 0, 1)
    rgb = np.stack([red, green, blue], axis=-1)
    rgb = (np.flipud(rgb) * 255).astype(np.uint8)
    image = Image.fromarray(rgb, mode="RGB").resize((width, height), Image.Resampling.BILINEAR)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
