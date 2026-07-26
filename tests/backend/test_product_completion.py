from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from audio_processor.maintenance_tasks import retention_days_for_recording
from audio_processor.runtime_config import effective_worker_settings
from fastapi import HTTPException
from signal_index.config import Settings
from signal_index.file_security import (
    detect_file,
    validate_declared_type,
)
from signal_index.schemas import HypothesisPatch, LocalLLMRequest
from signal_index.security import decrypt_secret, encrypt_secret
from signal_processing.analytics import ActivityPoint, summarize_activity


def test_binary_signature_detection_does_not_trust_requested_type() -> None:
    detected = detect_file(b"%PDF-1.7\nsynthetic")
    assert detected.mime_type == "application/pdf"
    assert detected.item_type == "pdf"
    with pytest.raises(HTTPException, match="file signature"):
        validate_declared_type(detected, "image")


def test_encrypted_secret_round_trip_and_wrong_key_failure() -> None:
    encrypted = encrypt_secret("local-only-secret", "a" * 32)
    assert "local-only-secret" not in encrypted
    assert decrypt_secret(encrypted, "a" * 32) == "local-only-secret"
    with pytest.raises(ValueError, match="could not be decrypted"):
        decrypt_secret(encrypted, "b" * 32)


def test_hypothesis_patch_preserves_all_evidence_layers() -> None:
    patch = HypothesisPatch(
        title="Revised title",
        statement="Revised statement",
        supporting_evidence_ids=["support"],
        contradicting_evidence_ids=["contradict"],
        unresolved_evidence_ids=["unresolved"],
        related_session_ids=["session"],
        related_event_ids=["event"],
        saved_query_ids=["query"],
        user_notes="User interpretation",
        llm_notes="Local LLM hypothesis",
    )
    assert patch.unresolved_evidence_ids == ["unresolved"]
    assert patch.user_notes == "User interpretation"
    assert patch.llm_notes == "Local LLM hypothesis"


def test_local_llm_request_is_bounded() -> None:
    request = LocalLLMRequest(task="compare", prompt="Use bounded evidence", max_tokens=2000)
    assert request.max_tokens == 2000
    with pytest.raises(ValueError):
        LocalLLMRequest(task="compare", prompt="x", max_tokens=200_000)


def test_analytics_returns_baseline_and_change_candidate_without_causal_claim() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    points: list[ActivityPoint] = []
    counts = [1, 1, 1, 20]
    for day, count in enumerate(counts):
        for offset in range(count):
            points.append(
                ActivityPoint(
                    observed_at=start + timedelta(days=day, seconds=offset),
                    duration_sec=1,
                    frequency_hz=4_625_000,
                    receiver_ids=("receiver",),
                    callsigns=("TEST",),
                    number_groups=("281",),
                    confidence=0.8,
                )
            )
    summary = summarize_activity(points)
    rolling = summary["rolling_z_score"]
    assert isinstance(rolling, list)
    assert rolling[-1]["baseline_mean"] == 1
    assert rolling[-1]["baseline_deviation"] == 19
    assert summary["cooccurrence_matrix"] == [
        {"callsign": "TEST", "number_group": "281", "count": 23}
    ]


def test_source_or_capture_retention_overrides_default() -> None:
    recording = SimpleNamespace()
    capture = SimpleNamespace(retention_policy={"days": 30})
    source = SimpleNamespace(config={"retention_days": 90})
    assert retention_days_for_recording(recording, capture, source, 3650) == 30
    capture.retention_policy = {}
    assert retention_days_for_recording(recording, capture, source, 3650) == 90
    source.config = {}
    assert retention_days_for_recording(recording, capture, source, 3650) == 3650


def test_runtime_worker_settings_are_validated() -> None:
    base = Settings()
    effective = effective_worker_settings(
        base,
        {"vad.threshold": 0.72, "asr.model": "small", "processing.preset": "USB"},
    )
    assert effective.VAD_THRESHOLD == 0.72
    assert effective.ASR_MODEL == "small"
    with pytest.raises(ValueError):
        effective_worker_settings(base, {"vad.threshold": 2.0})
