"""Health check and session-scoped Reactor JWT token broker endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
import httpx

from app.models.schemas import (
    CANONICAL_MODEL_ID,
    HealthResponse,
    ReactorTokenRequest,
    ReactorTokenResponse,
)
from app.services.session_manager import runtime

router = APIRouter(tags=["Health & Auth"])


@router.get("/api/v1/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    settings = runtime.ensure_initialized()
    orbis_mode = runtime.orbis.mode
    gcp_mode = runtime.storage.mode
    overall_mode = "live" if (orbis_mode == "live" and gcp_mode == "live") else "mock"
    return HealthResponse(
        status="ok",
        service="visko-la-backend",
        mode=overall_mode,
        orbis_mode=orbis_mode,
        gcp_mode=gcp_mode,
        model_id=CANONICAL_MODEL_ID,
        gcp_project_id=settings.gcp_project_id,
        gcs_bucket_name=settings.gcs_bucket_name,
        gcs_bucket=settings.gcs_bucket_name,
        bq_dataset_id=settings.bq_dataset_id,
    )


@router.post("/api/v1/auth/reactor-token", response_model=ReactorTokenResponse)
async def mint_reactor_token(
    payload: ReactorTokenRequest | None = Body(default=None),
) -> ReactorTokenResponse:
    runtime.ensure_initialized()
    req = payload or ReactorTokenRequest()
    bound_id = req.session_id or req.reactor_session_id
    try:
        return await runtime.orbis.mint_jwt(
            session_id_to_bind=bound_id,
            max_sessions=req.max_sessions,
            expires_after=req.expires_after,
            model_id=req.model_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Reactor token service returned HTTP {exc.response.status_code}.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to reach Reactor token endpoint.",
        ) from exc
