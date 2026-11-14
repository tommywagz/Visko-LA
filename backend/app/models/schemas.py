"""Canonical Pydantic v2 request/response and WebSocket models matching jobs/contracts/."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CANONICAL_MODEL_ID = "reactor/visko-orbis-stable"
DUBAI_SOURCE_DATASET = "ayoubkirouane/Dubai_dataset-Aerial_Imagery_256x256"

AdapterMode = Literal["live", "mock"]
CameraMode = Literal["forward_downward_oblique", "nadir_downward", "forward_fpv"]
EcosystemType = Literal[
    "alpine",
    "coastal",
    "urban_canyon",
    "temperate_forest",
    "arid_desert",
    "wetlands",
    "custom",
]
TurbulenceLevel = Literal["light", "moderate", "severe", "extreme"]
SessionStatus = Literal["waiting", "priming", "generating", "paused", "reanchoring", "closed"]
ResolutionOption = Literal["1080p", "2k", "4k"]

SUPPORTED_CAMERA_MODES: tuple[CameraMode, ...] = (
    "forward_downward_oblique",
    "nadir_downward",
    "forward_fpv",
)
SUPPORTED_ECOSYSTEMS: tuple[EcosystemType, ...] = (
    "alpine",
    "coastal",
    "urban_canyon",
    "temperate_forest",
    "arid_desert",
    "wetlands",
    "custom",
)
VALID_RECORDING_DURATIONS: tuple[int, ...] = (5, 10, 15)
VALID_INTERVAL_SETTINGS: dict[str, int] = {"5s": 5, "10s": 10, "15s": 15}

BQ_AERIAL_DATASETS_COLUMNS: tuple[str, ...] = (
    "video_id",
    "project_id",
    "folder_id",
    "folder_path",
    "title",
    "session_id",
    "model_id",
    "ecosystem_type",
    "duration_seconds",
    "resolution",
    "fps",
    "gcs_video_uri",
    "seed_media_gcs_uri",
    "initial_prompt",
    "prompt_history_json",
    "avg_wind_speed_mps",
    "max_wind_gust_mps",
    "wind_direction_deg",
    "avg_air_pressure_hpa",
    "avg_air_density_kgm3",
    "ambient_temp_c",
    "avg_turbulence_edr",
    "max_turbulence_edr",
    "drone_altitude_agl_m",
    "telemetry_summary_json",
    "file_size_bytes",
    "created_at",
)

BQ_AERIAL_FOLDERS_COLUMNS: tuple[str, ...] = (
    "folder_id",
    "project_id",
    "parent_folder_id",
    "name",
    "folder_path",
    "ecosystem_default",
    "created_at",
)


def validate_model_slug(value: Any) -> str:
    """Enforce canonical 'reactor/visko-orbis-stable' model slug (reject bare 'visko-orbis-stable')."""
    if not isinstance(value, str) or value != CANONICAL_MODEL_ID:
        raise ValueError(
            f"Invalid model_id {value!r}; must be strictly {CANONICAL_MODEL_ID!r} "
            "(with mandatory 'reactor/' owner prefix)."
        )
    return value


def validate_strict_duration(
    duration_seconds: Any = None,
    interval_setting: Any = None,
) -> int:
    """Strictly validate recording interval in {5, 10, 15} or {'5s', '10s', '15s'}."""
    resolved_from_duration: int | None = None
    resolved_from_setting: int | None = None

    if duration_seconds is not None:
        if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, int):
            raise ValueError(
                f"duration_seconds must be an integer in (5, 10, 15); got {duration_seconds!r}"
            )
        if duration_seconds not in VALID_RECORDING_DURATIONS:
            raise ValueError(
                f"duration_seconds must be strictly 5, 10, or 15; got {duration_seconds!r}"
            )
        resolved_from_duration = duration_seconds

    if interval_setting is not None:
        if not isinstance(interval_setting, str) or interval_setting not in VALID_INTERVAL_SETTINGS:
            raise ValueError(
                f"interval_setting must be one of '5s', '10s', '15s'; got {interval_setting!r}"
            )
        resolved_from_setting = VALID_INTERVAL_SETTINGS[interval_setting]

    if resolved_from_duration is None and resolved_from_setting is None:
        raise ValueError(
            "Either duration_seconds (5, 10, 15) or interval_setting ('5s', '10s', '15s') is required."
        )

    if (
        resolved_from_duration is not None
        and resolved_from_setting is not None
        and resolved_from_duration != resolved_from_setting
    ):
        raise ValueError(
            f"Conflicting duration_seconds={resolved_from_duration} and interval_setting={interval_setting!r}."
        )

    return resolved_from_duration if resolved_from_duration is not None else int(resolved_from_setting)  # type: ignore[arg-type]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "visko-la-backend"
    mode: AdapterMode
    orbis_mode: AdapterMode
    gcp_mode: AdapterMode
    model_id: str = CANONICAL_MODEL_ID
    gcp_project_id: str
    gcs_bucket_name: str
    gcs_bucket: str
    bq_dataset_id: str


class ReactorTokenRequest(BaseModel):
    session_id: str | None = None
    reactor_session_id: str | None = None
    model_id: str = CANONICAL_MODEL_ID
    max_sessions: int = Field(default=5, ge=1, le=20)
    expires_after: int = Field(default=3600, ge=60, le=86400)

    @field_validator("model_id", mode="before")
    @classmethod
    def _check_model_id(cls, v: Any) -> str:
        if v is None:
            return CANONICAL_MODEL_ID
        return validate_model_slug(v)


class ReactorTokenResponse(BaseModel):
    jwt: str
    expires_at: int
    model_id: str = CANONICAL_MODEL_ID
    mode: AdapterMode
    bound_session_id: str | None = None


class SystemPromptTemplates(BaseModel):
    forward_downward_oblique: str
    nadir_downward: str
    forward_fpv: str


class SystemPromptResponse(BaseModel):
    model_id: str = CANONICAL_MODEL_ID
    default_camera_mode: CameraMode = "forward_downward_oblique"
    selected_camera_mode: CameraMode = "forward_downward_oblique"
    selected_template: str
    passthrough: Literal[True] = True
    supported_camera_modes: list[CameraMode]
    templates: SystemPromptTemplates
    steering_anchor_prefix: str
    custom_override_active: bool
    active_override: str | None = None


class PresetTileItem(BaseModel):
    preset_id: str
    title: str
    source_dataset: str = DUBAI_SOURCE_DATASET
    row_index: int
    ecosystem_type: EcosystemType
    recommended_camera_mode: CameraMode
    suggested_prompt: str
    preview_url: str


class PresetCatalogResponse(BaseModel):
    dataset: str = DUBAI_SOURCE_DATASET
    source_dataset: str = DUBAI_SOURCE_DATASET
    presets: list[PresetTileItem]


class SeedFromPresetRequest(BaseModel):
    preset_id: str = Field(..., min_length=1)
    project_id: str = Field(default="default-uav-project", min_length=1)


class SeedMediaResponse(BaseModel):
    seed_id: str
    project_id: str
    preset_id: str | None = None
    filename: str
    mime_type: str
    media_kind: Literal["image", "video"] = "image"
    seed_media_gcs_uri: str
    gcs_uri: str
    preview_url: str
    width: int = 832
    height: int = 480
    aspect_ratio: str = "16:9"
    ecosystem_type: str | None = None
    recommended_camera_mode: str | None = None
    suggested_prompt: str | None = None
    created_at: str


class TelemetryFrame(BaseModel):
    timestamp_ms: int
    chunk_index: int
    ecosystem_type: EcosystemType
    wind_speed_mps: float
    wind_gust_mps: float
    wind_direction_deg: float = Field(..., ge=0.0, le=360.0)
    air_pressure_hpa: float
    air_density_kgm3: float
    ambient_temp_c: float
    turbulence_edr: float = Field(..., ge=0.0)
    turbulence_level: TurbulenceLevel
    drone_altitude_agl_m: float
    drone_airspeed_mps: float
    drone_pitch_deg: float
    drone_roll_deg: float
    drone_yaw_deg: float = Field(..., ge=0.0, le=360.0)


class PromptEntry(BaseModel):
    prompt_id: str
    prompt: str
    compiled_prompt: str
    passthrough: Literal[True] = True
    chunk_index: int
    status: Literal["morphing", "applied"] = "applied"
    created_at: str


class CreateSessionRequest(BaseModel):
    project_id: str = "default-uav-project"
    folder_id: str = "root"
    model_id: str = CANONICAL_MODEL_ID
    camera_mode: CameraMode = "forward_downward_oblique"
    ecosystem_type: EcosystemType = "alpine"
    drone_altitude_agl_m: float = Field(default=65.0, ge=1.0, le=5000.0)
    initial_prompt: str | None = None
    seed_id: str | None = None
    seed_media_gcs_uri: str | None = None
    seed_gcs_uri: str | None = None
    resolution: ResolutionOption = "1080p"

    @field_validator("model_id", mode="before")
    @classmethod
    def _check_model_id(cls, v: Any) -> str:
        if v is None:
            return CANONICAL_MODEL_ID
        return validate_model_slug(v)


class SessionStateResponse(BaseModel):
    session_id: str
    reactor_session_id: str | None = None
    project_id: str
    folder_id: str
    model_id: str = CANONICAL_MODEL_ID
    mode: AdapterMode
    status: SessionStatus
    chunk_index: int = 0
    camera_mode: CameraMode
    ecosystem_type: EcosystemType
    passthrough: Literal[True] = True
    compiled_system_prompt: str
    reactor_jwt: str
    expires_at: int
    reactor_jwt_expires_at: int
    ws_url: str
    seed_id: str | None = None
    seed_media_gcs_uri: str | None = None
    preview_url: str | None = None
    initial_telemetry: TelemetryFrame
    latest_telemetry: TelemetryFrame
    prompt_history: list[PromptEntry]
    created_at: str


class CloseSessionResponse(BaseModel):
    session_id: str
    status: Literal["closed", "disconnected"] = "closed"


class SteerPromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    camera_mode: CameraMode | None = None

    @field_validator("prompt")
    @classmethod
    def _validate_non_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Prompt text must not be empty or whitespace-only.")
        return stripped


class SteerPromptResponse(BaseModel):
    session_id: str
    status: Literal["morphing", "applied"] = "applied"
    chunk_index: int
    raw_prompt: str
    compiled_prompt: str
    passthrough: Literal[True] = True
    prompt_entry: PromptEntry
    prompt_history: list[PromptEntry]
    updated_telemetry_targets: dict[str, Any]
    latest_telemetry: TelemetryFrame


class ReanchorSeedRequest(BaseModel):
    seed_id: str | None = None
    seed_media_gcs_uri: str | None = None
    seed_gcs_uri: str | None = None
    prompt: str | None = None

    @model_validator(mode="after")
    def _ensure_seed_reference(self) -> ReanchorSeedRequest:
        if not (self.seed_id or self.seed_media_gcs_uri or self.seed_gcs_uri):
            raise ValueError(
                "At least one of seed_id, seed_media_gcs_uri, or seed_gcs_uri must be supplied."
            )
        return self


class ReanchorSeedResponse(BaseModel):
    session_id: str
    status: Literal["reanchoring", "applied"] = "applied"
    seed_id: str | None = None
    seed_media_gcs_uri: str
    gcs_uri: str
    preview_url: str | None = None
    command_sequence: list[str]
    compiled_prompt: str
    passthrough: Literal[True] = True
    chunk_index: int


class RecordClipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: Any = None
    interval_setting: Any = None
    project_id: str | None = None
    folder_id: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def _validate_interval(self) -> RecordClipRequest:
        resolved = validate_strict_duration(
            duration_seconds=self.duration_seconds,
            interval_setting=self.interval_setting,
        )
        self.duration_seconds = resolved
        self.interval_setting = f"{resolved}s"
        return self


class ProjectRecord(BaseModel):
    project_id: str
    name: str
    description: str | None = ""
    created_at: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectRecord]


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1)
    project_id: str | None = None
    description: str | None = ""

    @field_validator("name")
    @classmethod
    def _non_blank_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Project name must not be empty.")
        return stripped


class FolderRecord(BaseModel):
    folder_id: str
    project_id: str
    parent_folder_id: str | None = None
    name: str
    folder_path: str
    ecosystem_default: str | None = None
    dataset_count: int = 0
    created_at: str


class FolderListResponse(BaseModel):
    project_id: str
    folders: list[FolderRecord]


class CreateFolderRequest(BaseModel):
    name: str = Field(..., min_length=1)
    parent_folder_id: str | None = None
    ecosystem_default: EcosystemType | None = None

    @field_validator("name")
    @classmethod
    def _non_blank_folder_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Folder name must not be empty.")
        return stripped


class DatasetRecord(BaseModel):
    video_id: str
    project_id: str
    folder_id: str
    folder_path: str
    title: str
    session_id: str
    model_id: str = CANONICAL_MODEL_ID
    ecosystem_type: EcosystemType
    duration_seconds: Literal[5, 10, 15]
    resolution: str
    fps: int
    gcs_video_uri: str
    seed_media_gcs_uri: str | None = None
    initial_prompt: str
    prompt_history_json: str
    avg_wind_speed_mps: float
    max_wind_gust_mps: float
    wind_direction_deg: float
    avg_air_pressure_hpa: float
    avg_air_density_kgm3: float
    ambient_temp_c: float
    avg_turbulence_edr: float
    max_turbulence_edr: float
    drone_altitude_agl_m: float
    telemetry_summary_json: str | None = None
    file_size_bytes: int
    created_at: str
    download_url: str | None = None
    direct_stream_url: str | None = None

    def to_bq_row(self) -> dict[str, Any]:
        """Serialize strictly to the canonical 27-column BigQuery aerial_datasets dictionary."""
        data = self.model_dump()
        return {col: data[col] for col in BQ_AERIAL_DATASETS_COLUMNS}


class DatasetListResponse(BaseModel):
    project_id: str
    datasets: list[DatasetRecord]
    total: int
    storage_bytes_total: int


class UpdateDatasetRequest(BaseModel):
    folder_id: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def _ensure_update_fields(self) -> UpdateDatasetRequest:
        if self.folder_id is None and self.title is None:
            raise ValueError("At least one of folder_id or title must be supplied.")
        if self.title is not None and not self.title.strip():
            raise ValueError("title must not be empty.")
        if self.title is not None:
            self.title = self.title.strip()
        return self


class DatasetDownloadResponse(BaseModel):
    video_id: str
    filename: str
    gcs_video_uri: str
    gcs_uri: str
    signed_url: str
    direct_stream_url: str
    expires_in_seconds: int = 3600
