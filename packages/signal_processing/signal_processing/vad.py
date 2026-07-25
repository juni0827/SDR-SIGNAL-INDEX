from __future__ import annotations

from dataclasses import dataclass

from .config import VADPreset


@dataclass(frozen=True)
class TimeRange:
    start_sec: float
    end_sec: float

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


def merge_and_split_ranges(
    ranges: list[TimeRange], preset: VADPreset, recording_duration: float
) -> list[TimeRange]:
    if not ranges:
        return []
    padded = [
        TimeRange(
            max(0.0, item.start_sec - preset.padding_ms / 1000),
            min(recording_duration, item.end_sec + preset.padding_ms / 1000),
        )
        for item in sorted(ranges, key=lambda item: item.start_sec)
        if item.duration_sec * 1000 >= preset.minimum_speech_ms
    ]
    merged: list[TimeRange] = []
    for item in padded:
        if merged and item.start_sec - merged[-1].end_sec <= preset.minimum_silence_ms / 1000:
            merged[-1] = TimeRange(merged[-1].start_sec, max(merged[-1].end_sec, item.end_sec))
        else:
            merged.append(item)
    output: list[TimeRange] = []
    for item in merged:
        cursor = item.start_sec
        while item.end_sec - cursor > preset.maximum_segment_sec:
            output.append(TimeRange(cursor, cursor + preset.maximum_segment_sec))
            cursor += preset.maximum_segment_sec
        if item.end_sec > cursor:
            tail = TimeRange(cursor, item.end_sec)
            if (
                output
                and tail.duration_sec * 1000 < preset.merge_shorter_than_ms
                and output[-1].end_sec == cursor
            ):
                output[-1] = TimeRange(output[-1].start_sec, tail.end_sec)
            else:
                output.append(tail)
    return output


def silero_ranges(samples: object, sample_rate: int, preset: VADPreset) -> list[TimeRange]:
    try:
        from silero_vad import get_speech_timestamps, load_silero_vad
    except ImportError as exc:
        raise RuntimeError("silero-vad audio dependency is not installed") from exc
    model = load_silero_vad()
    stamps = get_speech_timestamps(
        samples,
        model,
        sampling_rate=sample_rate,
        threshold=preset.threshold,
        min_speech_duration_ms=preset.minimum_speech_ms,
        min_silence_duration_ms=preset.minimum_silence_ms,
        return_seconds=True,
    )
    return [TimeRange(float(item["start"]), float(item["end"])) for item in stamps]
