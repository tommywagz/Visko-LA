"""Live Orbis session lifecycle, prompt steering, seed re-anchoring, and interval recording."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, status

from app.adapters.catalog import CatalogNotFoundError
from app.models.schemas import (
    CloseSessionResponse,
    CreateSessionRequest,
    DatasetRecord,
    ReanchorSeedRequest,
    ReanchorSeedResponse,
    RecordClipRequest,
    SessionStateResponse,
    SteerPromptRequest,
    SteerPromptResponse,
    SystemPromptResponse,
)
from app.services.seed_normalizer import SeedValidationError
from app.services.session_manager import runtime

router = APIRouter(tags=["Live Orbis Sessions"])


@router.get("/api/v1/sessions/system-prompt", response_model=SystemPromptResponse)
async def get_aerial_system_prompt(
    camera_mode: str | None = Query(default=None),
) -> SystemPromptResponse:
    try:
        return runtime.prompt_compiler.get_system_prompt_metadata(camera_mode=camera_mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/api/v1/sessions",
    response_model=SessionStateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: CreateSessionRequest | None = Body(default=None),
) -> SessionStateResponse:
    req = payload or CreateSessionRequest()
    try:
        managed = await runtime.create_session(req)
        return managed.to_response()
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, SeedValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/v1/sessions/{session_id}", response_model=SessionStateResponse)
async def get_session(session_id: str) -> SessionStateResponse:
    try:
        managed = runtime.get_session(session_id)
        return managed.to_response()
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/v1/sessions/{session_id}", response_model=CloseSessionResponse)
async def close_session(session_id: str) -> CloseSessionResponse:
    try:
        await runtime.close_session(session_id)
        return CloseSessionResponse(session_id=session_id, status="closed")
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/v1/sessions/{session_id}/prompt", response_model=SteerPromptResponse)
async def steer_session_prompt(
    session_id: str,
    req: SteerPromptRequest,
) -> SteerPromptResponse:
    try:
        return await runtime.steer_session_prompt(
            session_id,
            raw_prompt=req.prompt,
            camera_mode=req.camera_mode,
        )
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/v1/sessions/{session_id}/seed", response_model=ReanchorSeedResponse)
async def reanchor_session_seed(
    session_id: str,
    req: ReanchorSeedRequest,
) -> ReanchorSeedResponse:
    try:
        return await runtime.reanchor_session_seed(
            session_id,
            seed_id=req.seed_id,
            seed_media_gcs_uri=req.seed_media_gcs_uri or req.seed_gcs_uri,
            prompt=req.prompt,
        )
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, SeedValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/api/v1/sessions/{session_id}/record",
    response_model=DatasetRecord,
    status_code=status.HTTP_201_CREATED,
)
async def record_session_clip(
    session_id: str,
    req: RecordClipRequest,
) -> DatasetRecord:
    try:
        return await runtime.record_session_clip(
            session_id,
            duration_seconds=int(req.duration_seconds),
            project_id=req.project_id,
            folder_id=req.folder_id,
            title=req.title,
        )
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
