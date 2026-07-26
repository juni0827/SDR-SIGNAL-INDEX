import shutil
from typing import Any

from fastapi import APIRouter, Depends
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..schemas import Envelope
from ..storage import ObjectStorage

router = APIRouter(tags=["system"])


@router.get("/health", response_model=Envelope[dict[str, Any]])
def health(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> Envelope[dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": type(exc).__name__}
    try:
        Redis.from_url(settings.REDIS_URL, socket_timeout=1).ping()
        checks["redis"] = {"status": "ok"}
    except Exception as exc:
        checks["redis"] = {"status": "error", "detail": type(exc).__name__}
    try:
        ObjectStorage(settings).health()
        checks["object_storage"] = {"status": "ok"}
    except Exception as exc:
        checks["object_storage"] = {"status": "error", "detail": type(exc).__name__}
    checks["ffmpeg"] = {
        "status": "ok" if shutil.which(settings.FFMPEG_PATH) else "error",
        "path": shutil.which(settings.FFMPEG_PATH),
    }
    checks["asr_model"] = {"status": "configured", "model": settings.ASR_MODEL}
    checks["embedding_model"] = {"status": "configured", "model": "mel-statistics-v1"}
    checks["local_llm"] = {
        "status": "disabled" if not settings.LOCAL_LLM_ENABLED else "configured",
        "model": settings.LOCAL_LLM_MODEL or None,
    }
    critical_ok = checks["database"]["status"] == "ok"
    return Envelope(data={"status": "ok" if critical_ok else "degraded", "checks": checks})


@router.get("/capabilities", response_model=Envelope[dict[str, Any]])
def capabilities(settings: Settings = Depends(get_settings)) -> Envelope[dict[str, Any]]:
    return Envelope(
        data={
            "app": "Signal Index",
            "version": "0.1.0",
            "schema_version": "0001",
            "llm_optional": True,
            "local_llm_enabled": settings.LOCAL_LLM_ENABLED,
            "search": [
                "structured",
                "full_text",
                "trigram_fuzzy",
                "number_exact",
                "callsign",
                "vector_similarity",
            ],
            "embeddings": ["audio", "transcript", "session_composite"],
            "exports": ["json", "csv", "jsonl", "markdown", "zip", "wav", "png", "graph_json"],
            "causality_policy": "temporal association is never promoted to a causal claim automatically",
        }
    )
