import shutil
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..schemas import Envelope
from ..secrets_store import resolved_secret
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
    checks["embedding_model"] = {
        "status": "available",
        "models": ["torch-spectral-statistics-v2", "torch-hash-text-v1"],
    }
    try:
        from audio_processor.celery_app import celery

        replies = celery.control.inspect(timeout=0.5).ping() or {}
        checks["worker"] = {
            "status": "ok" if replies else "error",
            "workers": sorted(replies),
        }
    except Exception as exc:
        checks["worker"] = {"status": "error", "detail": type(exc).__name__}
    if settings.LOCAL_LLM_ENABLED:
        try:
            api_key = resolved_secret(
                db,
                settings,
                "local_llm.api_key",
                settings.LOCAL_LLM_API_KEY.get_secret_value(),
            )
            response = httpx.get(
                f"{settings.LOCAL_LLM_BASE_URL.rstrip('/')}/models",
                headers={
                    "Authorization": f"Bearer {api_key}"
                },
                timeout=1.0,
            )
            response.raise_for_status()
            checks["local_llm"] = {
                "status": "ok",
                "model": settings.LOCAL_LLM_MODEL or None,
            }
        except Exception as exc:
            checks["local_llm"] = {
                "status": "error",
                "model": settings.LOCAL_LLM_MODEL or None,
                "detail": type(exc).__name__,
            }
    else:
        checks["local_llm"] = {"status": "disabled", "model": None}
    critical_ok = checks["database"]["status"] == "ok"
    return Envelope(data={"status": "ok" if critical_ok else "degraded", "checks": checks})


@router.get("/capabilities", response_model=Envelope[dict[str, Any]])
def capabilities(settings: Settings = Depends(get_settings)) -> Envelope[dict[str, Any]]:
    return Envelope(
        data={
            "app": "Signal Index",
            "version": "0.1.0",
            "schema_version": "0003",
            "llm_optional": True,
            "local_llm_enabled": settings.LOCAL_LLM_ENABLED,
            "implemented": {
                "search": [
                    "structured",
                    "full_text",
                    "trigram_fuzzy",
                    "number_exact_normalized_fuzzy",
                    "callsign",
                    "session_vector_similarity",
                ],
                "embeddings": ["audio", "transcript_text", "session_composite"],
                "exports": [
                    "json_api",
                    "json",
                    "jsonl",
                    "csv",
                    "markdown",
                    "zip_evidence_bundle",
                    "signed_wav",
                    "signed_spectrogram_png",
                    "graph_json_png_svg",
                    "hypothesis_markdown_report",
                ],
                "graph": ["filtered_neighborhood", "layout_persistence", "json_png_svg_export"],
                "timeline": ["multilayer", "period_overlay", "delta_calculation"],
                "pwa": ["offline_shell", "offline_inbox", "offline_annotations", "conflict_status"],
                "authentication": ["password", "webauthn_passkey"],
                "object_storage": ["private_signed_urls", "multipart_transfer"],
                "realtime": ["redis_sse", "polling_fallback"],
                "capture": "explicit_receiver_template_only",
            },
            "not_implemented": [
                "speaker_identity",
                "generic_transmitter_location_inference",
                "spectrogram_tiles",
                "production_scale_benchmark_evidence",
                "full_device_matrix_evidence",
                "fresh_host_twenty_step_release_gate",
            ],
            "causality_policy": "temporal association is never promoted to a causal claim automatically",
        }
    )
