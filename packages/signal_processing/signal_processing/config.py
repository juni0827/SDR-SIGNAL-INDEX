from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessingPreset:
    name: str
    low_hz: int
    high_hz: int
    loudness_lufs: float = -20.0
    spectral_gate: bool = False


PRESETS = {
    "VOICE": ProcessingPreset("VOICE", 300, 3_000),
    "AM": ProcessingPreset("AM", 150, 4_500),
    "USB": ProcessingPreset("USB", 300, 3_000),
    "LSB": ProcessingPreset("LSB", 300, 3_000),
    "WIDE": ProcessingPreset("WIDE", 80, 7_500),
}


@dataclass(frozen=True)
class VADPreset:
    threshold: float = 0.55
    minimum_speech_ms: int = 250
    minimum_silence_ms: int = 400
    padding_ms: int = 180
    maximum_segment_sec: float = 45.0
    merge_shorter_than_ms: int = 350
