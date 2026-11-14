"""Google Drive-style projects, hierarchical folders, dataset catalog, and MP4 downloads."""

from __future__ import annotations

import re

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from app.adapters.catalog import (
    CatalogNotFoundError,
    DuplicateConflictError,
    slugify_identifier,
)
from app.models.schemas import (
    CreateFolderRequest,
    CreateProjectRequest,
    DatasetDownloadResponse,
    DatasetListResponse,
    DatasetRecord,
    EcosystemType,
    FolderListResponse,
    FolderRecord,
    ProjectListResponse,
    ProjectRecord,
    SUPPORTED_ECOSYSTEMS,
    UpdateDatasetRequest,
    validate_strict_duration,
)
from app.services.seed_normalizer import SeedValidationError
from app.services.session_manager import runtime

router = APIRouter(tags=["Projects, Folders & Datasets"])


def _build_download_filename(record: DatasetRecord) -> str:
    clean_title = slugify_identifier(record.title or record.video_id, fallback=record.video_id)
    suffix = f"_{record.duration_seconds}s"
    if clean_title.endswith(suffix) or clean_title.endswith(f"-{record.duration_seconds}s"):
        return f"{clean_title}.mp4"
    return f"{clean_title}_{record.duration_seconds}s.mp4"


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    match = re.match(r"^bytes=(\d*)-(\d*)$", range_header.strip())
    if not match or file_size <= 0:
        return None
    start_str, end_str = match.group(1), match.group(2)
    if not start_str and not end_str:
        return None
    if start_str:
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
    else:
        suffix_len = int(end_str)
        start = max(0, file_size - suffix_len)
        end = file_size - 1
    if start >= file_size or start > end:
        return None
    return start, min(end, file_size - 1)


@router.get("/api/v1/projects", response_model=ProjectListResponse)
async def list_projects() -> ProjectListResponse:
    runtime.ensure_initialized()
    return ProjectListResponse(projects=runtime.catalog.list_projects())


@router.post(
    "/api/v1/projects",
    response_model=ProjectRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(req: CreateProjectRequest) -> ProjectRecord:
    runtime.ensure_initialized()
    try:
        return runtime.catalog.create_project(
            name=req.name,
            project_id=req.project_id,
            description=req.description,
        )
    except DuplicateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/api/v1/projects/{project_id}/folders",
    response_model=FolderListResponse,
)
async def list_project_folders(project_id: str) -> FolderListResponse:
    runtime.ensure_initialized()
    try:
        folders = runtime.catalog.list_folders(project_id)
        return FolderListResponse(project_id=project_id, folders=folders)
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/api/v1/projects/{project_id}/folders",
    response_model=FolderRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_folder(
    project_id: str,
    req: CreateFolderRequest,
) -> FolderRecord:
    runtime.ensure_initialized()
    try:
        return runtime.catalog.create_folder(
            project_id=project_id,
            name=req.name,
            parent_folder_id=req.parent_folder_id,
            ecosystem_default=req.ecosystem_default,
        )
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/api/v1/projects/{project_id}/datasets",
    response_model=DatasetListResponse,
)
async def list_project_datasets(
    project_id: str,
    folder_id: str | None = Query(default=None),
    ecosystem_type: str | None = Query(default=None),
    duration_seconds: str | None = Query(default=None),
    min_turbulence_edr: float | None = Query(default=None),
    max_turbulence_edr: float | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc"),
) -> DatasetListResponse:
    runtime.ensure_initialized()
    parsed_duration: int | None = None
    if duration_seconds is not None and duration_seconds.strip().lower() not in ("", "all"):
        raw_dur = duration_seconds.strip().lower()
        try:
            if raw_dur.endswith("s"):
                parsed_duration = validate_strict_duration(interval_setting=raw_dur)
            else:
                parsed_duration = validate_strict_duration(duration_seconds=int(raw_dur))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        return runtime.catalog.list_datasets(
            project_id=project_id,
            folder_id=folder_id,
            ecosystem_type=ecosystem_type,
            duration_seconds=parsed_duration,
            min_turbulence_edr=min_turbulence_edr,
            max_turbulence_edr=max_turbulence_edr,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/api/v1/projects/{project_id}/datasets/upload",
    response_model=DatasetRecord,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_dataset(
    project_id: str,
    file: UploadFile = File(...),
    folder_id: str = Form(default="root"),
    title: str | None = Form(default=None),
    ecosystem_type: str | None = Form(default=None),
    duration_seconds: int = Form(default=5),
    initial_prompt: str | None = Form(default=None),
    avg_wind_speed_mps: float | None = Form(default=None),
    max_wind_gust_mps: float | None = Form(default=None),
    wind_direction_deg: float | None = Form(default=None),
    avg_air_pressure_hpa: float | None = Form(default=None),
    avg_air_density_kgm3: float | None = Form(default=None),
    ambient_temp_c: float | None = Form(default=None),
    avg_turbulence_edr: float | None = Form(default=None),
    max_turbulence_edr: float | None = Form(default=None),
    drone_altitude_agl_m: float | None = Form(default=None),
) -> DatasetRecord:
    resolved_eco: EcosystemType | None = None
    if ecosystem_type is not None and ecosystem_type.strip():
        candidate_eco = ecosystem_type.strip()
        if candidate_eco not in SUPPORTED_ECOSYSTEMS:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid ecosystem_type {candidate_eco!r}; must be one of {list(SUPPORTED_ECOSYSTEMS)}.",
            )
        resolved_eco = candidate_eco  # type: ignore[assignment]

    raw_bytes = await file.read()
    try:
        return runtime.upload_manual_dataset(
            project_id=project_id,
            folder_id=folder_id.strip() or "root",
            filename=file.filename or "clip.mp4",
            content_type=file.content_type,
            raw_mp4_bytes=raw_bytes,
            title=title,
            ecosystem_type=resolved_eco,
            duration_seconds=duration_seconds,
            initial_prompt=initial_prompt,
            telemetry_overrides={
                "avg_wind_speed_mps": avg_wind_speed_mps,
                "max_wind_gust_mps": max_wind_gust_mps,
                "wind_direction_deg": wind_direction_deg,
                "avg_air_pressure_hpa": avg_air_pressure_hpa,
                "avg_air_density_kgm3": avg_air_density_kgm3,
                "ambient_temp_c": ambient_temp_c,
                "avg_turbulence_edr": avg_turbulence_edr,
                "max_turbulence_edr": max_turbulence_edr,
                "drone_altitude_agl_m": drone_altitude_agl_m,
            },
        )
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, SeedValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/v1/datasets/{video_id}", response_model=DatasetRecord)
async def get_dataset(video_id: str) -> DatasetRecord:
    runtime.ensure_initialized()
    record = runtime.catalog.get_dataset(video_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Dataset {video_id!r} not found.")
    return record


@router.patch("/api/v1/datasets/{video_id}", response_model=DatasetRecord)
async def update_dataset(
    video_id: str,
    req: UpdateDatasetRequest,
) -> DatasetRecord:
    runtime.ensure_initialized()
    try:
        return runtime.catalog.update_dataset(
            video_id,
            folder_id=req.folder_id,
            title=req.title,
        )
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/api/v1/datasets/{video_id}/download",
    response_model=DatasetDownloadResponse,
)
async def get_dataset_download_info(
    video_id: str,
    request: Request,
) -> DatasetDownloadResponse:
    settings = runtime.ensure_initialized()
    record = runtime.catalog.get_dataset(video_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Dataset {video_id!r} not found.")

    filename = _build_download_filename(record)
    direct_stream_path = f"/api/v1/datasets/{video_id}/file"
    base_url = str(request.base_url).rstrip("/")
    absolute_fallback_url = f"{base_url}{direct_stream_path}"

    signed_url = runtime.storage.generate_download_url(
        record.gcs_video_uri,
        filename=filename,
        fallback_stream_url=absolute_fallback_url,
        expires_in_seconds=settings.gcs_signed_url_expiry_seconds,
    )
    return DatasetDownloadResponse(
        video_id=record.video_id,
        filename=filename,
        gcs_video_uri=record.gcs_video_uri,
        gcs_uri=record.gcs_video_uri,
        signed_url=signed_url,
        direct_stream_url=direct_stream_path,
        expires_in_seconds=settings.gcs_signed_url_expiry_seconds,
    )


@router.get("/api/v1/datasets/{video_id}/file")
async def download_dataset_file(
    video_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
) -> Response:
    runtime.ensure_initialized()
    record = runtime.catalog.get_dataset(video_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Dataset {video_id!r} not found.")

    filename = _build_download_filename(record)
    common_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }

    try:
        total_size = runtime.storage.get_size_bytes(record.gcs_video_uri)
        if range_header:
            parsed_range = _parse_range_header(range_header, total_size)
            if parsed_range is not None:
                start, end = parsed_range
                chunk_bytes = runtime.storage.download_range(record.gcs_video_uri, start, end)
                headers = {
                    **common_headers,
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(len(chunk_bytes)),
                }
                return Response(
                    content=chunk_bytes,
                    status_code=status.HTTP_206_PARTIAL_CONTENT,
                    media_type="video/mp4",
                    headers=headers,
                )

        full_bytes = runtime.storage.download_bytes(record.gcs_video_uri)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Video blob for dataset {video_id!r} not found in storage.",
        ) from exc

    common_headers["Content-Length"] = str(len(full_bytes))
    return Response(
        content=full_bytes,
        status_code=status.HTTP_200_OK,
        media_type="video/mp4",
        headers=common_headers,
    )
