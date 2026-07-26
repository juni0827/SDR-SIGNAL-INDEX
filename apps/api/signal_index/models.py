from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class RecordMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(RecordMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(Text)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)


class Source(RecordMixin, Base):
    __tablename__ = "sources"
    name: Mapped[str] = mapped_column(String(200), unique=True)
    adapter_type: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    parser_version: Mapped[str] = mapped_column(String(80), default="1.0.0")
    license_notes: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cursor: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Provenance(RecordMixin, Base):
    __tablename__ = "provenance"
    record_type: Mapped[str] = mapped_column(String(80), index=True)
    record_id: Mapped[str] = mapped_column(String(36), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))
    source_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parser_version: Mapped[str | None] = mapped_column(String(80))
    pipeline_version: Mapped[str | None] = mapped_column(String(80))
    raw_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    manually_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    license_notes: Mapped[str | None] = mapped_column(Text)
    raw_object_key: Mapped[str | None] = mapped_column(Text)


class SourceFetchJob(RecordMixin, Base):
    __tablename__ = "source_fetch_jobs"
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    records_parsed: Mapped[int] = mapped_column(Integer, default=0)
    raw_response_object_key: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Revision(RecordMixin, Base):
    __tablename__ = "revisions"
    record_type: Mapped[str] = mapped_column(String(80), index=True)
    record_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_type: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str | None] = mapped_column(String(36))
    before: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(Text)


class Receiver(RecordMixin, Base):
    __tablename__ = "receivers"
    name: Mapped[str] = mapped_column(String(200), index=True)
    receiver_type: Mapped[str] = mapped_column(String(30))
    base_url: Mapped[str] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    grid_locator: Mapped[str | None] = mapped_column(String(12))
    min_frequency_hz: Mapped[int | None] = mapped_column(Integer)
    max_frequency_hz: Mapped[int | None] = mapped_column(Integer)
    supported_modes: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN", index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    tuning_url_template: Mapped[str | None] = mapped_column(Text)
    bookmarked: Mapped[bool] = mapped_column(Boolean, default=False)


class ReceiverStatus(RecordMixin, Base):
    __tablename__ = "receiver_status_history"
    receiver_id: Mapped[str] = mapped_column(ForeignKey("receivers.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FrequencyEntry(RecordMixin, Base):
    __tablename__ = "frequency_entries"
    frequency_hz: Mapped[int] = mapped_column(Integer, index=True)
    lower_frequency_hz: Mapped[int | None] = mapped_column(Integer)
    upper_frequency_hz: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str | None] = mapped_column(String(20), index=True)
    label: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(40), index=True)
    country_code: Mapped[str | None] = mapped_column(String(2))
    station_name: Mapped[str | None] = mapped_column(String(200))
    callsigns: Mapped[list[str]] = mapped_column(JSON, default=list)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    schedule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    notes: Mapped[str | None] = mapped_column(Text)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    watchlisted: Mapped[bool] = mapped_column(Boolean, default=False)


class Recording(RecordMixin, Base):
    __tablename__ = "recordings"
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    original_filename: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    receiver_id: Mapped[str | None] = mapped_column(ForeignKey("receivers.id"), index=True)
    frequency_hz: Mapped[int] = mapped_column(Integer, index=True)
    mode: Mapped[str | None] = mapped_column(String(20))
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_sec: Mapped[float] = mapped_column(Float)
    sample_rate: Mapped[int] = mapped_column(Integer)
    channels: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(40))
    source_url: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    processing_version: Mapped[str | None] = mapped_column(String(80))
    processed_object_key: Mapped[str | None] = mapped_column(Text)
    preview_object_key: Mapped[str | None] = mapped_column(Text)
    clipping_detected: Mapped[bool] = mapped_column(Boolean, default=False)


class ProcessingJob(RecordMixin, Base):
    __tablename__ = "processing_jobs"
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    stage: Mapped[str] = mapped_column(String(80))
    job_type: Mapped[str] = mapped_column(String(40), default="INITIAL")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_stderr: Mapped[str | None] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AudioSegment(RecordMixin, Base):
    __tablename__ = "audio_segments"
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id"), index=True)
    start_sec: Mapped[float] = mapped_column(Float)
    end_sec: Mapped[float] = mapped_column(Float)
    duration_sec: Mapped[float] = mapped_column(Float)
    segment_type: Mapped[str] = mapped_column(String(30), index=True)
    class_confidence: Mapped[float] = mapped_column(Float)
    class_features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    snr_db: Mapped[float | None] = mapped_column(Float, index=True)
    rms_energy: Mapped[float | None] = mapped_column(Float)
    spectral_centroid: Mapped[float | None] = mapped_column(Float)
    spectral_flatness: Mapped[float | None] = mapped_column(Float)
    bandwidth_hz: Mapped[float | None] = mapped_column(Float)
    zero_crossing_rate: Mapped[float | None] = mapped_column(Float)
    processed_object_key: Mapped[str | None] = mapped_column(Text)
    waveform_object_key: Mapped[str | None] = mapped_column(Text)
    spectrogram_object_key: Mapped[str | None] = mapped_column(Text)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    manually_adjusted: Mapped[bool] = mapped_column(Boolean, default=False)


class Transcript(RecordMixin, Base):
    __tablename__ = "transcripts"
    segment_id: Mapped[str] = mapped_column(ForeignKey("audio_segments.id"), index=True)
    transcript_type: Mapped[str] = mapped_column(String(40), index=True)
    language: Mapped[str | None] = mapped_column(String(12), index=True)
    text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(120))
    model_version: Mapped[str | None] = mapped_column(String(80))
    confidence: Mapped[float | None] = mapped_column(Float)
    word_timestamps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    parent_transcript_id: Mapped[str | None] = mapped_column(ForeignKey("transcripts.id"))


class ExtractedEntity(RecordMixin, Base):
    __tablename__ = "extracted_entities"
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("audio_segments.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("transmission_sessions.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    raw_value: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str] = mapped_column(String(500), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(30))
    occurrences: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class TransmissionSession(RecordMixin, Base):
    __tablename__ = "transmission_sessions"
    title: Mapped[str | None] = mapped_column(String(300))
    start_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    primary_frequency_hz: Mapped[int] = mapped_column(Integer, index=True)
    frequencies_hz: Mapped[list[int]] = mapped_column(JSON, default=list)
    receiver_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    recording_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    segment_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    callsigns: Mapped[list[str]] = mapped_column(JSON, default=list)
    number_groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(50), default="UNKNOWN", index=True)
    session_fingerprint: Mapped[str | None] = mapped_column(String(128), index=True)
    session_embedding_id: Mapped[str | None] = mapped_column(String(36))
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="UNREVIEWED", index=True)


class SessionEdit(RecordMixin, Base):
    __tablename__ = "session_edits"
    session_id: Mapped[str] = mapped_column(ForeignKey("transmission_sessions.id"), index=True)
    operation: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ExternalEvent(RecordMixin, Base):
    __tablename__ = "external_events"
    title: Mapped[str] = mapped_column(String(400), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    started_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ended_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    country_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    location: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(String(200))
    confidence: Mapped[float] = mapped_column(Float)


class Relation(RecordMixin, Base):
    __tablename__ = "relations"
    subject_type: Mapped[str] = mapped_column(String(60), index=True)
    subject_id: Mapped[str] = mapped_column(String(36), index=True)
    predicate: Mapped[str] = mapped_column(String(80), index=True)
    object_type: Mapped[str] = mapped_column(String(60), index=True)
    object_id: Mapped[str] = mapped_column(String(36), index=True)
    delta_seconds: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    relation_status: Mapped[str] = mapped_column(String(40), index=True)
    causal_claim: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(String(36))


class Hypothesis(RecordMixin, Base):
    __tablename__ = "hypotheses"
    title: Mapped[str] = mapped_column(String(300), index=True)
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    supporting_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    contradicting_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    unresolved_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    related_session_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    related_event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    saved_query_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by_type: Mapped[str] = mapped_column(String(30))
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    evaluation_notes: Mapped[str | None] = mapped_column(Text)
    user_notes: Mapped[str | None] = mapped_column(Text)
    llm_notes: Mapped[str | None] = mapped_column(Text)


class HypothesisHistory(RecordMixin, Base):
    __tablename__ = "hypothesis_history"
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str] = mapped_column(String(30))
    actor_type: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str | None] = mapped_column(String(36))
    notes: Mapped[str | None] = mapped_column(Text)


class Annotation(RecordMixin, Base):
    __tablename__ = "annotations"
    target_type: Mapped[str] = mapped_column(String(50), index=True)
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    start_sec: Mapped[float | None] = mapped_column(Float)
    end_sec: Mapped[float | None] = mapped_column(Float)
    body: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    client_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    sync_version: Mapped[int] = mapped_column(Integer, default=1)


class SavedQuery(RecordMixin, Base):
    __tablename__ = "saved_queries"
    name: Mapped[str] = mapped_column(String(200))
    query_type: Mapped[str] = mapped_column(String(60))
    query_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by_type: Mapped[str] = mapped_column(String(30), default="USER")
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class Embedding(RecordMixin, Base):
    __tablename__ = "embeddings"
    embedding_type: Mapped[str] = mapped_column(String(40), index=True)
    source_type: Mapped[str] = mapped_column(String(60), index=True)
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    model: Mapped[str] = mapped_column(String(200))
    model_version: Mapped[str] = mapped_column(String(100))
    dimension: Mapped[int] = mapped_column(Integer, default=384)
    preprocessing_version: Mapped[str] = mapped_column(String(80))
    vector: Mapped[list[float]] = mapped_column(Vector(384))


class CaptureJob(RecordMixin, Base):
    __tablename__ = "capture_jobs"
    receiver_id: Mapped[str] = mapped_column(ForeignKey("receivers.id"), index=True)
    frequency_hz: Mapped[int] = mapped_column(Integer, index=True)
    mode: Mapped[str] = mapped_column(String(20))
    schedule_utc: Mapped[str] = mapped_column(String(160))
    capture_duration_sec: Mapped[int] = mapped_column(Integer)
    repetition: Mapped[str | None] = mapped_column(String(160))
    maximum_storage_bytes: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="SCHEDULED", index=True)
    lock_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    recording_id: Mapped[str | None] = mapped_column(ForeignKey("recordings.id"), index=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class InboxItem(RecordMixin, Base):
    __tablename__ = "inbox_items"
    item_type: Mapped[str] = mapped_column(String(30))
    object_key: Mapped[str | None] = mapped_column(Text)
    text_content: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    frequency_hz: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str | None] = mapped_column(String(20))
    observed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receiver_id: Mapped[str | None] = mapped_column(ForeignKey("receivers.id"))
    note: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="UNCLASSIFIED")
    client_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    original_filename: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer)


class GraphLayout(RecordMixin, Base):
    __tablename__ = "graph_layouts"
    name: Mapped[str] = mapped_column(String(200), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    query_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    positions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    viewport: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SecretRecord(RecordMixin, Base):
    __tablename__ = "secret_records"
    key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    encrypted_value: Mapped[str] = mapped_column(Text)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class WebAuthnCredential(RecordMixin, Base):
    __tablename__ = "webauthn_credentials"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    credential_id: Mapped[str] = mapped_column(Text, unique=True)
    public_key: Mapped[str] = mapped_column(Text)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[list[str]] = mapped_column(JSON, default=list)
    name: Mapped[str] = mapped_column(String(200), default="Passkey")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SettingRevision(RecordMixin, Base):
    __tablename__ = "setting_revisions"
    key: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class AuditLog(RecordMixin, Base):
    __tablename__ = "audit_logs"
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str | None] = mapped_column(String(60))
    target_id: Mapped[str | None] = mapped_column(String(36))
    request_id: Mapped[str | None] = mapped_column(String(80), index=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


Index("ix_entity_type_normalized", ExtractedEntity.entity_type, ExtractedEntity.normalized_value)
Index("ix_relation_subject", Relation.subject_type, Relation.subject_id)
Index("ix_relation_object", Relation.object_type, Relation.object_id)
Index("ix_session_frequency_time", TransmissionSession.primary_frequency_hz, TransmissionSession.start_at_utc)
Index("ix_segment_recording_start", AudioSegment.recording_id, AudioSegment.start_sec)
Index(
    "uq_provenance_source_record_hash",
    Provenance.source_id,
    Provenance.record_type,
    Provenance.raw_hash,
    unique=True,
)
