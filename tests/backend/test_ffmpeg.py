import subprocess

import pytest
from signal_processing.ffmpeg import MediaProcessError, run


def test_failed_ffmpeg_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["ffmpeg"], 2, "", "invalid input"),
    )
    with pytest.raises(MediaProcessError) as captured:
        run(["ffmpeg", "-i", "bad"], "PROBE")
    assert captured.value.stage == "PROBE"
    assert captured.value.stderr == "invalid input"
