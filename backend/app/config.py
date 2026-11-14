"""Runtime configuration and dual-mode credential detection for Visko-LA Backend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CANONICAL_MODEL_ID = "reactor/visko-orbis-stable"
DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parent.parent

_PLACEHOLDER_VALUES = {
    "",
    "unset",
    "none",
    "null",
    "changeme",
    "your-api-key",
    "rk_your_reactor_api_key_here",
    "your_reactor_api_key",
    "your-gcp-project-id",
    "<gcp-project-id>",
    "<reactor-api-key>",
}


def _parse_bool_env(raw: str | None) -> bool | None:
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return None


def _is_real_credential(val: str | None) -> bool:
    if val is None:
        return False
    stripped = val.strip()
    if not stripped:
        return False
    if stripped.lower() in _PLACEHOLDER_VALUES:
        return False
    if stripped.startswith("<") and stripped.endswith(">"):
        return False
    return True


def _has_gcp_credentials(explicit_creds_path: str | None) -> bool:
    """Check whether usable GCP credentials exist without blocking on metadata servers."""
    if explicit_creds_path:
        path = Path(explicit_creds_path.strip())
        return path.is_file() and path.stat().st_size > 0

    adc_candidates = [
        Path(os.environ.get("CLOUDSDK_CONFIG", Path.home() / ".config" / "gcloud"))
        / "application_default_credentials.json",
    ]
    for candidate in adc_candidates:
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of backend configuration resolved from environment variables."""

    # Reactor / Visko Orbis Stable
    reactor_api_key: str
    reactor_api_url: str
    orbis_model_slug: str
    orbis_aerial_system_prompt: str | None
    reactor_mcp_url: str
    orbis_mock_mode: bool

    # Google Cloud Storage & BigQuery
    gcp_project_id: str
    gcp_region: str
    google_application_credentials: str | None
    gcs_bucket_name: str
    gcs_seed_prefix: str
    gcs_dataset_prefix: str
    gcs_signed_url_expiry_seconds: int
    bq_dataset_id: str
    bq_datasets_table_id: str
    bq_folders_table_id: str
    gcp_mock_mode: bool

    # Local emulator & HTTP server
    local_storage_dir: Path
    backend_host: str
    backend_port: int
    allowed_origins: tuple[str, ...]

    @property
    def orbis_mode(self) -> str:
        return "mock" if self.orbis_mock_mode else "live"

    @property
    def gcp_mode(self) -> str:
        return "mock" if self.gcp_mock_mode else "live"

    @property
    def overall_mode(self) -> str:
        if not self.orbis_mock_mode and not self.gcp_mock_mode:
            return "live"
        return "mock"

    def __repr__(self) -> str:
        """Ensure REACTOR_API_KEY is redacted in debug/repr output."""
        return (
            f"Settings(orbis_mode={self.orbis_mode!r}, gcp_mode={self.gcp_mode!r}, "
            f"model={self.orbis_model_slug!r}, project={self.gcp_project_id!r}, "
            f"bucket={self.gcs_bucket_name!r}, bq_dataset={self.bq_dataset_id!r}, "
            f"reactor_api_key='***REDACTED***')"
        )


def get_settings() -> Settings:
    """Resolve current settings dynamically from os.environ."""
    raw_reactor_key = os.environ.get("REACTOR_API_KEY", "").strip()
    explicit_orbis_mock = _parse_bool_env(os.environ.get("ORBIS_MOCK_MODE"))
    if explicit_orbis_mock is True:
        orbis_mock_mode = True
    elif not _is_real_credential(raw_reactor_key):
        orbis_mock_mode = True
    else:
        orbis_mock_mode = False

    raw_gcp_project = os.environ.get("GCP_PROJECT_ID", "").strip()
    raw_gcs_bucket = os.environ.get("GCS_BUCKET_NAME", "").strip()
    raw_creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip() or None
    explicit_gcp_mock = _parse_bool_env(os.environ.get("GCP_MOCK_MODE"))

    has_real_gcp_env = (
        _is_real_credential(raw_gcp_project)
        and raw_gcp_project != "visko-local-dev"
        and _is_real_credential(raw_gcs_bucket)
        and _has_gcp_credentials(raw_creds_path)
    )
    if explicit_gcp_mock is True:
        gcp_mock_mode = True
    elif not has_real_gcp_env:
        gcp_mock_mode = True
    else:
        gcp_mock_mode = False

    gcp_project_id = raw_gcp_project if _is_real_credential(raw_gcp_project) else "visko-local-dev"
    gcs_bucket_name = (
        raw_gcs_bucket if _is_real_credential(raw_gcs_bucket) else "visko-orbis-aerial-datasets"
    )

    raw_local_dir = os.environ.get("LOCAL_STORAGE_DIR", "").strip()
    local_storage_dir = (
        Path(raw_local_dir).expanduser().resolve()
        if raw_local_dir
        else (DEFAULT_BACKEND_ROOT / ".local_storage").resolve()
    )

    raw_origins = os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    origins = tuple(o.strip() for o in raw_origins.split(",") if o.strip()) or (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )

    raw_override = os.environ.get("ORBIS_AERIAL_SYSTEM_PROMPT", "").strip()
    orbis_override = raw_override if raw_override else None

    raw_expiry = os.environ.get("GCS_SIGNED_URL_EXPIRY_SECONDS", "3600").strip()
    try:
        signed_expiry = max(60, int(raw_expiry))
    except ValueError:
        signed_expiry = 3600

    raw_port = os.environ.get("BACKEND_PORT", "8000").strip()
    try:
        backend_port = int(raw_port)
    except ValueError:
        backend_port = 8000

    return Settings(
        reactor_api_key=raw_reactor_key,
        reactor_api_url=os.environ.get("REACTOR_API_URL", "https://api.reactor.inc").rstrip("/"),
        orbis_model_slug=os.environ.get("ORBIS_MODEL_SLUG", CANONICAL_MODEL_ID).strip()
        or CANONICAL_MODEL_ID,
        orbis_aerial_system_prompt=orbis_override,
        reactor_mcp_url=os.environ.get(
            "REACTOR_MCP_URL", "https://docs.reactor.inc/mcp"
        ).strip(),
        orbis_mock_mode=orbis_mock_mode,
        gcp_project_id=gcp_project_id,
        gcp_region=os.environ.get("GCP_REGION", "us-central1").strip() or "us-central1",
        google_application_credentials=raw_creds_path,
        gcs_bucket_name=gcs_bucket_name,
        gcs_seed_prefix=os.environ.get("GCS_SEED_PREFIX", "seeds").strip("/") or "seeds",
        gcs_dataset_prefix=os.environ.get("GCS_DATASET_PREFIX", "datasets").strip("/")
        or "datasets",
        gcs_signed_url_expiry_seconds=signed_expiry,
        bq_dataset_id=os.environ.get("BQ_DATASET_ID", "visko_aerial_telemetry").strip()
        or "visko_aerial_telemetry",
        bq_datasets_table_id=os.environ.get("BQ_DATASETS_TABLE_ID", "aerial_datasets").strip()
        or "aerial_datasets",
        bq_folders_table_id=os.environ.get("BQ_FOLDERS_TABLE_ID", "aerial_folders").strip()
        or "aerial_folders",
        gcp_mock_mode=gcp_mock_mode,
        local_storage_dir=local_storage_dir,
        backend_host=os.environ.get("BACKEND_HOST", "0.0.0.0").strip() or "0.0.0.0",
        backend_port=backend_port,
        allowed_origins=origins,
    )
