from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    APP_ENV: Literal["development", "test", "production"] = "development"
    APP_URL: str = "http://localhost:3000"
    API_URL: str = "http://localhost:8000"
    DATABASE_URL: str = "postgresql+psycopg://signal:signal@localhost:5432/signal"
    REDIS_URL: str = "redis://localhost:6379/0"
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_REGION: str = "auto"
    S3_BUCKET: str = "signal-index"
    S3_ACCESS_KEY: str = "minio"
    S3_SECRET_KEY: SecretStr = SecretStr("miniosecret")
    S3_SECURE: bool = False
    SESSION_SECRET: SecretStr = SecretStr("development-session-secret-change-this-value")
    JWT_SECRET: SecretStr = SecretStr("development-jwt-secret-change-this-value")
    TOOL_API_KEY: SecretStr = SecretStr("development-agent-key-change-this-value")
    FIRST_USER_EMAIL: str = "owner@local.test"
    FIRST_USER_PASSWORD: SecretStr = SecretStr("change-this-password")
    ACCOUNT_ALLOWLIST: str = "owner@local.test"
    CORS_ORIGINS: str = "http://localhost:3000"
    MAX_UPLOAD_BYTES: int = Field(default=2_147_483_648, ge=1_024, le=10_737_418_240)
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"
    ASR_MODEL: str = "large-v3"
    ASR_DEVICE: str = "auto"
    ASR_COMPUTE_TYPE: str = "auto"
    ASR_BEAM_SIZE: int = Field(default=5, ge=1, le=20)
    ASR_ALTERNATIVE_CANDIDATES: int = Field(default=1, ge=0, le=3)
    ASR_USE_VAD: bool = False
    SILERO_VAD_ENABLED: bool = True
    VAD_THRESHOLD: float = Field(default=0.55, ge=0.0, le=1.0)
    VAD_MINIMUM_SPEECH_MS: int = Field(default=250, ge=50, le=10_000)
    VAD_MINIMUM_SILENCE_MS: int = Field(default=400, ge=50, le=10_000)
    VAD_PADDING_MS: int = Field(default=180, ge=0, le=5_000)
    VAD_MAXIMUM_SEGMENT_SEC: float = Field(default=45.0, ge=1.0, le=3_600)
    VAD_MERGE_SHORTER_THAN_MS: int = Field(default=350, ge=0, le=10_000)
    SESSION_MERGE_THRESHOLD: float = Field(default=0.68, ge=0.0, le=1.0)
    SESSION_WINDOW_SEC: int = Field(default=1_800, ge=1, le=86_400)
    SESSION_FREQUENCY_WINDOW_HZ: int = Field(default=20_000, ge=0, le=10_000_000)
    SESSION_WEIGHT_TIME: float = Field(default=0.25, ge=0.0, le=1.0)
    SESSION_WEIGHT_FREQUENCY: float = Field(default=0.20, ge=0.0, le=1.0)
    SESSION_WEIGHT_ACOUSTIC: float = Field(default=0.20, ge=0.0, le=1.0)
    SESSION_WEIGHT_CALLSIGN: float = Field(default=0.15, ge=0.0, le=1.0)
    SESSION_WEIGHT_NUMBERS: float = Field(default=0.12, ge=0.0, le=1.0)
    SESSION_WEIGHT_MESSAGE: float = Field(default=0.08, ge=0.0, le=1.0)
    LOCAL_LLM_ENABLED: bool = False
    LOCAL_LLM_BASE_URL: str = "http://host.docker.internal:1234/v1"
    LOCAL_LLM_MODEL: str = ""
    LOCAL_LLM_API_KEY: SecretStr = SecretStr("local")
    PIPELINE_VERSION: str = "1.0.0"
    PARSER_VERSION: str = "1.0.0"
    CAPTURE_ENABLED: bool = False
    MALWARE_SCAN_ENABLED: bool = False
    CLAMAV_HOST: str = "clamav"
    CLAMAV_PORT: int = Field(default=3310, ge=1, le=65535)

    @field_validator("SESSION_SECRET", "JWT_SECRET")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("secret must contain at least 32 characters")
        return value

    @field_validator("FIRST_USER_EMAIL")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("FIRST_USER_EMAIL must be an email-like address")
        return normalized

    @model_validator(mode="after")
    def validate_session_weights(self) -> "Settings":
        total = sum(
            (
                self.SESSION_WEIGHT_TIME,
                self.SESSION_WEIGHT_FREQUENCY,
                self.SESSION_WEIGHT_ACOUSTIC,
                self.SESSION_WEIGHT_CALLSIGN,
                self.SESSION_WEIGHT_NUMBERS,
                self.SESSION_WEIGHT_MESSAGE,
            )
        )
        if total <= 0:
            raise ValueError("at least one session grouping weight must be positive")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]

    @property
    def account_allowlist(self) -> set[str]:
        return {item.strip().lower() for item in self.ACCOUNT_ALLOWLIST.split(",") if item.strip()}

    @property
    def production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
