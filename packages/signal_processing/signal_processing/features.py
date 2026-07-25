from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class AcousticFeatures:
    snr_db: float
    rms_energy: float
    spectral_centroid: float
    spectral_flatness: float
    bandwidth_hz: float
    zero_crossing_rate: float
    clipping_fraction: float

    def dict(self) -> dict[str, float]:
        return asdict(self)


def extract_features(samples: np.ndarray, sample_rate: int) -> AcousticFeatures:
    import librosa

    mono = np.asarray(samples, dtype=np.float32)
    if mono.size == 0:
        raise ValueError("cannot extract features from empty audio")
    rms = float(np.sqrt(np.mean(np.square(mono))))
    frame_rms = librosa.feature.rms(y=mono)[0]
    noise = float(np.percentile(frame_rms, 20))
    signal = float(np.percentile(frame_rms, 80))
    snr = float(20 * np.log10(max(signal, 1e-9) / max(noise, 1e-9)))
    return AcousticFeatures(
        snr_db=snr,
        rms_energy=rms,
        spectral_centroid=float(np.mean(librosa.feature.spectral_centroid(y=mono, sr=sample_rate))),
        spectral_flatness=float(np.mean(librosa.feature.spectral_flatness(y=mono))),
        bandwidth_hz=float(np.mean(librosa.feature.spectral_bandwidth(y=mono, sr=sample_rate))),
        zero_crossing_rate=float(np.mean(librosa.feature.zero_crossing_rate(mono))),
        clipping_fraction=float(np.mean(np.abs(mono) >= 0.999)),
    )


class SignalClassifier(Protocol):
    name: str

    def classify(self, features: AcousticFeatures) -> tuple[str, float]: ...


class RuleBasedClassifier:
    name = "rf-acoustic-rules-v1"

    def classify(self, value: AcousticFeatures) -> tuple[str, float]:
        if value.rms_energy < 0.004:
            return "CARRIER", 0.65
        if value.spectral_flatness > 0.55 and value.bandwidth_hz > 2_000:
            return "NOISE", 0.72
        if value.spectral_flatness < 0.04 and value.bandwidth_hz < 300:
            return "TONE", 0.78
        if value.zero_crossing_rate > 0.23 and value.spectral_flatness > 0.2:
            return "DIGITAL", 0.61
        if 0.015 < value.zero_crossing_rate < 0.2 and value.spectral_centroid < 2_800:
            return "VOICE", 0.68
        return "UNKNOWN", 0.35
