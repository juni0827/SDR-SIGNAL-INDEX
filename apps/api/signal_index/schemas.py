from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: T
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    query: dict[str, Any] = Field(default_factory=dict)
    pagination: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    generated_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=1024)


class SearchRequest(BaseModel):
    text: str | None = Field(default=None, max_length=500)
    frequency_min_hz: int | None = Field(default=None, ge=0, le=100_000_000_000)
    frequency_max_hz: int | None = Field(default=None, ge=0, le=100_000_000_000)
    started_after: datetime | None = None
    started_before: datetime | None = None
    receiver_id: str | None = None
    signal_class: str | None = None
    language: str | None = None
    confidence_min: float | None = Field(default=None, ge=0, le=1)
    reviewed: bool | None = None
    status: str | None = None
    category: str | None = None
    callsign: str | None = Field(default=None, max_length=100)
    number_group: str | None = Field(default=None, pattern=r"^[0-9 -]{1,80}$")
    exact_number: bool = True
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> SearchRequest:
        if (
            self.frequency_min_hz is not None
            and self.frequency_max_hz is not None
            and self.frequency_min_hz > self.frequency_max_hz
        ):
            raise ValueError("frequency_min_hz must be <= frequency_max_hz")
        if self.started_after and self.started_before and self.started_after > self.started_before:
            raise ValueError("started_after must be <= started_before")
        return self


class TranscriptCorrection(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    language: str | None = Field(default=None, max_length=12)
    mark_preferred: bool = True


class SegmentSplit(BaseModel):
    at_sec: float = Field(gt=0)


class SegmentMerge(BaseModel):
    segment_ids: list[str] = Field(min_length=2, max_length=20)


class RelationCreate(BaseModel):
    subject_type: str
    subject_id: str
    predicate: str
    object_type: str
    object_id: str
    delta_seconds: float | None = None
    confidence: float = Field(ge=0, le=1)
    relation_status: Literal["OBSERVED", "COMPUTED", "USER_ASSERTED", "LLM_HYPOTHESIS"]
    causal_claim: bool = False
    evidence_ids: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_causal_claim(self) -> RelationCreate:
        if self.causal_claim and self.relation_status != "USER_ASSERTED":
            raise ValueError("only an explicit user assertion may set causal_claim=true")
        return self


class HypothesisCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    statement: str = Field(min_length=1, max_length=100_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    related_session_ids: list[str] = Field(default_factory=list)
    related_event_ids: list[str] = Field(default_factory=list)
    created_by: Literal["USER", "LOCAL_LLM"] = "USER"


class HypothesisPatch(BaseModel):
    status: Literal[
        "DRAFT", "ACTIVE", "SUPPORTED", "CONTRADICTED", "INCONCLUSIVE", "ARCHIVED"
    ] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evaluation_notes: str | None = Field(default=None, max_length=100_000)
    supporting_evidence_ids: list[str] | None = None
    contradicting_evidence_ids: list[str] | None = None


class AnnotationCreate(BaseModel):
    target_type: str
    target_id: str
    body: str = Field(min_length=1, max_length=100_000)
    start_sec: float | None = Field(default=None, ge=0)
    end_sec: float | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list, max_length=100)
    client_id: str | None = Field(default=None, max_length=80)
    sync_version: int = Field(default=1, ge=1)


class ContextBundleRequest(BaseModel):
    task: str = Field(max_length=120)
    subject_session_id: str | None = None
    comparison_session_ids: list[str] = Field(default_factory=list, max_length=50)
    include: list[str] = Field(default_factory=list, max_length=30)
    exclude_raw_audio: bool = True
    token_budget: int = Field(default=24_000, ge=1_000, le=100_000)


class CorrelationRequest(BaseModel):
    subject_session_id: str
    event_window_before_sec: int = Field(default=0, ge=0, le=31_536_000)
    event_window_after_sec: int = Field(default=86_400, ge=0, le=31_536_000)
    minimum_confidence: float = Field(default=0.0, ge=0, le=1)
