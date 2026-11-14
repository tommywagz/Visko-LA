"""Dubai 256x256 aerial starter presets and 832x480 (16:9) seed upload endpoints."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status

from app.adapters.catalog import CatalogNotFoundError
from app.models.schemas import (
    PresetCatalogResponse,
    SeedFromPresetRequest,
    SeedMediaResponse,
)
from app.services.seed_normalizer import SeedValidationError
from app.services.session_manager import runtime

router = APIRouter(tags=["Seed Media & Presets"])


@router.get("/api/v1/media/presets", response_model=PresetCatalogResponse)
async def list_media_presets(
    limit: int = Query(default=12, ge=1, le=72),
    offset: int = Query(default=0, ge=0),
) -> PresetCatalogResponse:
    runtime.ensure_initialized()
    return runtime.presets.list_presets(limit=limit, offset=offset)


@router.post(
    "/api/v1/media/seed/from-preset",
    response_model=SeedMediaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_seed_from_preset(req: SeedFromPresetRequest) -> SeedMediaResponse:
    try:
        return await runtime.create_seed_from_preset(
            preset_id=req.preset_id,
            project_id=req.project_id,
        )
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SeedValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/api/v1/media/seed",
    response_model=SeedMediaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_seed_media(
    file: UploadFile = File(...),
    project_id: str = Form(default="default-uav-project"),
) -> SeedMediaResponse:
    raw_bytes = await file.read()
    try:
        return runtime.create_seed_from_upload(
            filename=file.filename or "seed.jpg",
            content_type=file.content_type,
            raw_bytes=raw_bytes,
            project_id=project_id.strip() or "default-uav-project",
        )
    except SeedValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/v1/media/seed/{seed_id}/preview")
async def get_seed_preview(seed_id: str) -> Response:
    try:
        jpeg_bytes = await runtime.get_seed_preview_bytes(seed_id)
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )
