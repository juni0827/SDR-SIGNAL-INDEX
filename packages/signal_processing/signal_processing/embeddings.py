from __future__ import annotations

from typing import Protocol

import numpy as np


class EmbeddingProvider(Protocol):
    name: str
    version: str
    dimension: int

    def embed_audio(self, samples: np.ndarray, sample_rate: int) -> np.ndarray: ...


class MelStatisticsEmbedding:
    name = "mel-statistics"
    version = "1.0.0"
    dimension = 384

    def embed_audio(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        import librosa

        mel = librosa.feature.melspectrogram(y=samples, sr=sample_rate, n_mels=128)
        log_mel = librosa.power_to_db(mel, ref=np.max)
        vector = np.concatenate(
            [np.mean(log_mel, axis=1), np.std(log_mel, axis=1), np.max(log_mel, axis=1)]
        ).astype(np.float32)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector
