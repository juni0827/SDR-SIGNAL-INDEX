from __future__ import annotations

import hashlib
import re
from typing import Protocol, cast

import numpy as np


class AudioEmbeddingProvider(Protocol):
    name: str
    version: str
    dimension: int

    def embed_audio(self, samples: np.ndarray, sample_rate: int) -> np.ndarray: ...


class TextEmbeddingProvider(Protocol):
    name: str
    version: str
    dimension: int

    def embed_text(self, text: str) -> np.ndarray: ...


def _normalized(value: object) -> np.ndarray:
    import torch

    tensor = torch.as_tensor(value, dtype=torch.float32).flatten()
    norm = torch.linalg.vector_norm(tensor)
    if float(norm) > 0:
        tensor = tensor / norm
    return cast(np.ndarray, tensor.detach().cpu().numpy().astype(np.float32, copy=False))


class TorchSpectralEmbedding:
    """Deterministic PyTorch acoustic-format embedding.

    This vector is for acoustic similarity only. It must not be presented as
    speaker identification. Learned providers can replace this implementation
    without changing the database contract.
    """

    name = "torch-spectral-statistics"
    version = "2.0.0"
    dimension = 384

    def embed_audio(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        import torch
        import torch.nn.functional as functional

        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        waveform = torch.as_tensor(samples, dtype=torch.float32).flatten()
        if waveform.numel() == 0:
            raise ValueError("cannot embed empty audio")
        waveform = waveform - waveform.mean()
        window = torch.hann_window(512, dtype=waveform.dtype, device=waveform.device)
        spectrum = torch.stft(
            waveform,
            n_fft=512,
            hop_length=160,
            win_length=512,
            window=window,
            return_complex=True,
            center=True,
        ).abs()
        log_power = torch.log1p(spectrum.square())
        resized = functional.interpolate(
            log_power.unsqueeze(0).unsqueeze(0),
            size=(128, max(1, log_power.shape[1])),
            mode="bilinear",
            align_corners=False,
        ).squeeze(0).squeeze(0)
        vector = torch.cat(
            [resized.mean(dim=1), resized.std(dim=1, unbiased=False), resized.amax(dim=1)]
        )
        return _normalized(vector)


class TorchHashTextEmbedding:
    """Local deterministic text vector with no external model dependency.

    Token and character n-grams are projected with signed feature hashing.
    This is deliberately model-replaceable and is not claimed to be a full
    semantic language model embedding.
    """

    name = "torch-hash-text"
    version = "1.0.0"
    dimension = 384

    def embed_text(self, text: str) -> np.ndarray:
        import torch

        normalized = " ".join(text.casefold().split())
        if not normalized:
            raise ValueError("cannot embed empty transcript")
        tokens = re.findall(r"[\w'-]+", normalized, re.UNICODE)
        features = tokens + [
            normalized[index : index + width]
            for width in (3, 4, 5)
            for index in range(max(0, len(normalized) - width + 1))
        ]
        vector = torch.zeros(self.dimension, dtype=torch.float32)
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimension
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign
        return _normalized(vector)


# Compatibility alias for third-party plugins importing the original provider.
MelStatisticsEmbedding = TorchSpectralEmbedding
