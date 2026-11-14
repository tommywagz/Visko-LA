"""Google BigQuery & Embedded SQLite Metadata Catalog Adapters matching bq_schema.sql."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any
import uuid

from app.models.schemas import (
    BQ_AERIAL_DATASETS_COLUMNS,
    AdapterMode,
    DatasetListResponse,
    DatasetRecord,
    FolderRecord,
    ProjectRecord,
)

DEFAULT_PROJECT_ID = "default-uav-project"
DEFAULT_PROJECT_NAME = "Visko UAV Perception Datasets"
DEFAULT_PROJECT_DESCRIPTION = (
    "Synthetic Drone-POV perception video clips and coupled ISA/Dryden flight telemetry."
)

DEFAULT_FOLDERS: tuple[dict[str, str | None], ...] = (
    {
        "folder_id": "root",
        "parent_folder_id": None,
        "name": "My Aerial Datasets",
        "folder_path": "/",
        "ecosystem_default": None,
    },
    {
        "folder_id": "alpine-trials",
        "parent_folder_id": "root",
        "name": "Alpine Trials",
        "folder_path": "/alpine-trials",
        "ecosystem_default": "alpine",
    },
    {
        "folder_id": "coastal-crosswinds",
        "parent_folder_id": "root",
        "name": "Coastal Crosswinds",
        "folder_path": "/coastal-crosswinds",
        "ecosystem_default": "coastal",
    },
    {
        "folder_id": "urban-canyon",
        "parent_folder_id": "root",
        "name": "Urban Canyon",
        "folder_path": "/urban-canyon",
        "ecosystem_default": "urban_canyon",
    },
)

ALLOWED_SORT_COLUMNS: dict[str, str] = {
    "created_at": "created_at",
    "title": "title",
    "duration_seconds": "duration_seconds",
    "avg_wind_speed_mps": "avg_wind_speed_mps",
    "avg_air_pressure_hpa": "avg_air_pressure_hpa",
    "max_turbulence_edr": "max_turbulence_edr",
    "avg_turbulence_edr": "avg_turbulence_edr",
    "file_size_bytes": "file_size_bytes",
    "drone_altitude_agl_m": "drone_altitude_agl_m",
}


class CatalogNotFoundError(LookupError):
    """Raised when a requested project, folder, or dataset record does not exist."""


class DuplicateConflictError(ValueError):
    """Raised when a duplicate project_id or duplicate sibling folder name is created (HTTP 409)."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify_identifier(name: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or fallback


def compute_normalized_folder_path(parent_folder_path: str | None, name: str) -> str:
    slug = slugify_identifier(name, fallback="folder")
    if not parent_folder_path or parent_folder_path == "/":
        return f"/{slug}"
    return f"{parent_folder_path.rstrip('/')}/{slug}"


def enrich_dataset_urls(record_dict: dict[str, Any]) -> DatasetRecord:
    vid = record_dict["video_id"]
    payload = dict(record_dict)
    if isinstance(payload.get("created_at"), datetime):
        dt = payload["created_at"]
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        payload["created_at"] = dt.isoformat().replace("+00:00", "Z")
    payload.setdefault("download_url", f"/api/v1/datasets/{vid}/download")
    payload.setdefault("direct_stream_url", f"/api/v1/datasets/{vid}/file")
    return DatasetRecord(**payload)


class MetadataCatalogAdapter(ABC):
    """Abstract interface for BigQuery and local SQLite metadata catalog persistence."""

    mode: AdapterMode

    @abstractmethod
    def bootstrap_defaults(self) -> None:
        """Idempotently seed default-uav-project and root/ecosystem folders."""

    @abstractmethod
    def list_projects(self) -> list[ProjectRecord]:
        """List all projects."""

    @abstractmethod
    def get_project(self, project_id: str) -> ProjectRecord | None:
        """Fetch a single project by project_id."""

    @abstractmethod
    def create_project(
        self,
        *,
        name: str,
        project_id: str | None = None,
        description: str | None = "",
    ) -> ProjectRecord:
        """Create a project and seed its 'root' folder (raising DuplicateConflictError on conflict)."""

    @abstractmethod
    def list_folders(self, project_id: str) -> list[FolderRecord]:
        """List all folders in a project with dataset counts."""

    @abstractmethod
    def get_folder(self, project_id: str, folder_id: str) -> FolderRecord | None:
        """Fetch a folder inside a project."""

    @abstractmethod
    def create_folder(
        self,
        *,
        project_id: str,
        name: str,
        parent_folder_id: str | None = None,
        ecosystem_default: str | None = None,
    ) -> FolderRecord:
        """Create a folder inside a project, enforcing sibling uniqueness (409 Conflict)."""

    @abstractmethod
    def insert_dataset(self, dataset: DatasetRecord) -> DatasetRecord:
        """Insert all 27 canonical columns into aerial_datasets."""

    @abstractmethod
    def get_dataset(self, video_id: str) -> DatasetRecord | None:
        """Fetch a single dataset record by video_id."""

    @abstractmethod
    def list_datasets(
        self,
        *,
        project_id: str,
        folder_id: str | None = None,
        ecosystem_type: str | None = None,
        duration_seconds: int | None = None,
        min_turbulence_edr: float | None = None,
        max_turbulence_edr: float | None = None,
        search: str | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> DatasetListResponse:
        """Query, filter, search, and sort datasets in a project."""

    @abstractmethod
    def update_dataset(
        self,
        video_id: str,
        *,
        folder_id: str | None = None,
        title: str | None = None,
    ) -> DatasetRecord:
        """Move dataset across folders (recomputing folder_path) and/or rename title."""


class SQLiteCatalogAdapter(MetadataCatalogAdapter):
    """Embedded SQLite catalog mirroring BigQuery schemas at ${LOCAL_STORAGE_DIR}/bq_catalog.db."""

    mode: AdapterMode = "mock"

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()
        self.bootstrap_defaults()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                  project_id TEXT PRIMARY KEY NOT NULL,
                  name TEXT NOT NULL,
                  description TEXT DEFAULT '',
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS aerial_folders (
                  folder_key TEXT PRIMARY KEY NOT NULL,
                  folder_id TEXT NOT NULL,
                  project_id TEXT NOT NULL,
                  parent_folder_id TEXT,
                  name TEXT NOT NULL,
                  folder_path TEXT NOT NULL,
                  ecosystem_default TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_proj_id
                  ON aerial_folders (project_id, folder_id);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_unique_sibling
                  ON aerial_folders (project_id, COALESCE(parent_folder_id, '__ROOT__'), LOWER(name));

                CREATE TABLE IF NOT EXISTS aerial_datasets (
                  video_id TEXT PRIMARY KEY NOT NULL,
                  project_id TEXT NOT NULL,
                  folder_id TEXT NOT NULL,
                  folder_path TEXT NOT NULL,
                  title TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  model_id TEXT NOT NULL,
                  ecosystem_type TEXT NOT NULL,
                  duration_seconds INTEGER NOT NULL CHECK (duration_seconds IN (5, 10, 15)),
                  resolution TEXT NOT NULL,
                  fps INTEGER NOT NULL,
                  gcs_video_uri TEXT NOT NULL,
                  seed_media_gcs_uri TEXT,
                  initial_prompt TEXT NOT NULL,
                  prompt_history_json TEXT NOT NULL,
                  avg_wind_speed_mps REAL NOT NULL,
                  max_wind_gust_mps REAL NOT NULL,
                  wind_direction_deg REAL NOT NULL,
                  avg_air_pressure_hpa REAL NOT NULL,
                  avg_air_density_kgm3 REAL NOT NULL,
                  ambient_temp_c REAL NOT NULL,
                  avg_turbulence_edr REAL NOT NULL,
                  max_turbulence_edr REAL NOT NULL,
                  drone_altitude_agl_m REAL NOT NULL,
                  telemetry_summary_json TEXT,
                  file_size_bytes INTEGER NOT NULL CHECK (file_size_bytes > 0),
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );

                CREATE INDEX IF NOT EXISTS idx_datasets_project_folder_eco
                  ON aerial_datasets (project_id, folder_id, ecosystem_type, created_at DESC);
                """
            )

    def bootstrap_defaults(self) -> None:
        now = utc_now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO projects (project_id, name, description, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (DEFAULT_PROJECT_ID, DEFAULT_PROJECT_NAME, DEFAULT_PROJECT_DESCRIPTION, now),
            )
            for f in DEFAULT_FOLDERS:
                folder_key = f"{DEFAULT_PROJECT_ID}::{f['folder_id']}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO aerial_folders (
                      folder_key, folder_id, project_id, parent_folder_id,
                      name, folder_path, ecosystem_default, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        folder_key,
                        f["folder_id"],
                        DEFAULT_PROJECT_ID,
                        f["parent_folder_id"],
                        f["name"],
                        f["folder_path"],
                        f["ecosystem_default"],
                        now,
                    ),
                )

    def list_projects(self) -> list[ProjectRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT project_id, name, description, created_at FROM projects ORDER BY created_at ASC"
            ).fetchall()
        return [ProjectRecord(**dict(r)) for r in rows]

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT project_id, name, description, created_at FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return ProjectRecord(**dict(row)) if row else None

    def create_project(
        self,
        *,
        name: str,
        project_id: str | None = None,
        description: str | None = "",
    ) -> ProjectRecord:
        resolved_id = (
            project_id.strip()
            if project_id and project_id.strip()
            else slugify_identifier(name, fallback=f"proj-{uuid.uuid4().hex[:6]}")
        )
        now = utc_now_iso()
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM projects WHERE project_id = ?", (resolved_id,)
            ).fetchone()
            if existing:
                raise DuplicateConflictError(
                    f"Project with project_id={resolved_id!r} already exists."
                )
            conn.execute(
                "INSERT INTO projects (project_id, name, description, created_at) VALUES (?, ?, ?, ?)",
                (resolved_id, name.strip(), description or "", now),
            )
            # Auto-seed root folder for new project
            conn.execute(
                """
                INSERT INTO aerial_folders (
                  folder_key, folder_id, project_id, parent_folder_id,
                  name, folder_path, ecosystem_default, created_at
                ) VALUES (?, 'root', ?, NULL, 'My Aerial Datasets', '/', NULL, ?)
                """,
                (f"{resolved_id}::root", resolved_id, now),
            )
        return ProjectRecord(
            project_id=resolved_id,
            name=name.strip(),
            description=description or "",
            created_at=now,
        )

    def list_folders(self, project_id: str) -> list[FolderRecord]:
        if self.get_project(project_id) is None:
            raise CatalogNotFoundError(f"Project {project_id!r} not found.")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  f.folder_id,
                  f.project_id,
                  f.parent_folder_id,
                  f.name,
                  f.folder_path,
                  f.ecosystem_default,
                  f.created_at,
                  COUNT(d.video_id) AS dataset_count
                FROM aerial_folders f
                LEFT JOIN aerial_datasets d
                  ON d.project_id = f.project_id AND d.folder_id = f.folder_id
                WHERE f.project_id = ?
                GROUP BY
                  f.folder_id, f.project_id, f.parent_folder_id,
                  f.name, f.folder_path, f.ecosystem_default, f.created_at
                ORDER BY CASE WHEN f.folder_id = 'root' THEN 0 ELSE 1 END, f.folder_path ASC
                """,
                (project_id,),
            ).fetchall()
        return [FolderRecord(**dict(r)) for r in rows]

    def get_folder(self, project_id: str, folder_id: str) -> FolderRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  f.folder_id,
                  f.project_id,
                  f.parent_folder_id,
                  f.name,
                  f.folder_path,
                  f.ecosystem_default,
                  f.created_at,
                  (
                    SELECT COUNT(*) FROM aerial_datasets d
                    WHERE d.project_id = f.project_id AND d.folder_id = f.folder_id
                  ) AS dataset_count
                FROM aerial_folders f
                WHERE f.project_id = ? AND f.folder_id = ?
                """,
                (project_id, folder_id),
            ).fetchone()
        return FolderRecord(**dict(row)) if row else None

    def create_folder(
        self,
        *,
        project_id: str,
        name: str,
        parent_folder_id: str | None = None,
        ecosystem_default: str | None = None,
    ) -> FolderRecord:
        if self.get_project(project_id) is None:
            raise CatalogNotFoundError(f"Project {project_id!r} not found.")

        clean_name = name.strip()
        effective_parent_id = (
            parent_folder_id.strip()
            if parent_folder_id and parent_folder_id.strip()
            else "root"
        )
        parent_folder = self.get_folder(project_id, effective_parent_id)
        if parent_folder is None:
            raise CatalogNotFoundError(
                f"Parent folder {effective_parent_id!r} not found in project {project_id!r}."
            )

        folder_path = compute_normalized_folder_path(parent_folder.folder_path, clean_name)
        base_slug = slugify_identifier(clean_name, fallback="folder")
        now = utc_now_iso()

        with self._lock, self._connect() as conn:
            dup = conn.execute(
                """
                SELECT 1 FROM aerial_folders
                WHERE project_id = ?
                  AND COALESCE(parent_folder_id, 'root') = ?
                  AND LOWER(name) = LOWER(?)
                """,
                (project_id, effective_parent_id, clean_name),
            ).fetchone()
            if dup:
                raise DuplicateConflictError(
                    f"Folder {clean_name!r} already exists under parent {effective_parent_id!r}."
                )

            candidate_id = base_slug
            existing_id = conn.execute(
                "SELECT 1 FROM aerial_folders WHERE project_id = ? AND folder_id = ?",
                (project_id, candidate_id),
            ).fetchone()
            if existing_id or candidate_id in ("all", "root"):
                candidate_id = f"{base_slug}-{uuid.uuid4().hex[:6]}"

            folder_key = f"{project_id}::{candidate_id}"
            try:
                conn.execute(
                    """
                    INSERT INTO aerial_folders (
                      folder_key, folder_id, project_id, parent_folder_id,
                      name, folder_path, ecosystem_default, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        folder_key,
                        candidate_id,
                        project_id,
                        effective_parent_id,
                        clean_name,
                        folder_path,
                        ecosystem_default,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateConflictError(
                    f"Folder {clean_name!r} conflicts with an existing sibling folder."
                ) from exc

        return FolderRecord(
            folder_id=candidate_id,
            project_id=project_id,
            parent_folder_id=effective_parent_id,
            name=clean_name,
            folder_path=folder_path,
            ecosystem_default=ecosystem_default,
            dataset_count=0,
            created_at=now,
        )

    def insert_dataset(self, dataset: DatasetRecord) -> DatasetRecord:
        bq_row = dataset.to_bq_row()
        placeholders = ", ".join(["?"] * len(BQ_AERIAL_DATASETS_COLUMNS))
        cols_sql = ", ".join(BQ_AERIAL_DATASETS_COLUMNS)
        values = tuple(bq_row[col] for col in BQ_AERIAL_DATASETS_COLUMNS)

        with self._lock, self._connect() as conn:
            conn.execute(
                f"INSERT INTO aerial_datasets ({cols_sql}) VALUES ({placeholders})",
                values,
            )
        return enrich_dataset_urls(bq_row)

    def get_dataset(self, video_id: str) -> DatasetRecord | None:
        cols_sql = ", ".join(BQ_AERIAL_DATASETS_COLUMNS)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {cols_sql} FROM aerial_datasets WHERE video_id = ?",
                (video_id,),
            ).fetchone()
        return enrich_dataset_urls(dict(row)) if row else None

    def list_datasets(
        self,
        *,
        project_id: str,
        folder_id: str | None = None,
        ecosystem_type: str | None = None,
        duration_seconds: int | None = None,
        min_turbulence_edr: float | None = None,
        max_turbulence_edr: float | None = None,
        search: str | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> DatasetListResponse:
        if self.get_project(project_id) is None:
            raise CatalogNotFoundError(f"Project {project_id!r} not found.")

        where_clauses = ["project_id = ?"]
        params: list[Any] = [project_id]

        if folder_id and folder_id.strip().lower() != "all":
            where_clauses.append("folder_id = ?")
            params.append(folder_id.strip())

        if ecosystem_type and ecosystem_type.strip().lower() != "all":
            where_clauses.append("ecosystem_type = ?")
            params.append(ecosystem_type.strip())

        if duration_seconds is not None:
            where_clauses.append("duration_seconds = ?")
            params.append(int(duration_seconds))

        if min_turbulence_edr is not None:
            where_clauses.append("max_turbulence_edr >= ?")
            params.append(float(min_turbulence_edr))

        if max_turbulence_edr is not None:
            where_clauses.append("max_turbulence_edr <= ?")
            params.append(float(max_turbulence_edr))

        if search and search.strip():
            like_pat = f"%{search.strip().lower()}%"
            where_clauses.append(
                "("
                "LOWER(title) LIKE ? OR "
                "LOWER(video_id) LIKE ? OR "
                "LOWER(initial_prompt) LIKE ? OR "
                "LOWER(folder_path) LIKE ?"
                ")"
            )
            params.extend([like_pat, like_pat, like_pat, like_pat])

        sort_col = ALLOWED_SORT_COLUMNS.get(sort_by, "created_at")
        direction = "ASC" if (sort_dir or "").strip().lower() == "asc" else "DESC"
        cols_sql = ", ".join(BQ_AERIAL_DATASETS_COLUMNS)
        where_sql = " AND ".join(where_clauses)

        query = (
            f"SELECT {cols_sql} FROM aerial_datasets "
            f"WHERE {where_sql} "
            f"ORDER BY {sort_col} {direction}, video_id DESC"
        )
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        records = [enrich_dataset_urls(dict(r)) for r in rows]
        total_bytes = sum(r.file_size_bytes for r in records)
        return DatasetListResponse(
            project_id=project_id,
            datasets=records,
            total=len(records),
            storage_bytes_total=total_bytes,
        )

    def update_dataset(
        self,
        video_id: str,
        *,
        folder_id: str | None = None,
        title: str | None = None,
    ) -> DatasetRecord:
        existing = self.get_dataset(video_id)
        if existing is None:
            raise CatalogNotFoundError(f"Dataset {video_id!r} not found.")

        new_folder_id = existing.folder_id
        new_folder_path = existing.folder_path
        if folder_id is not None:
            target_folder = self.get_folder(existing.project_id, folder_id.strip())
            if target_folder is None:
                raise CatalogNotFoundError(
                    f"Target folder {folder_id!r} not found in project {existing.project_id!r}."
                )
            new_folder_id = target_folder.folder_id
            new_folder_path = target_folder.folder_path

        new_title = title.strip() if title is not None else existing.title

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE aerial_datasets
                SET folder_id = ?, folder_path = ?, title = ?
                WHERE video_id = ?
                """,
                (new_folder_id, new_folder_path, new_title, video_id),
            )

        updated = self.get_dataset(video_id)
        assert updated is not None
        return updated


class BigQueryCatalogAdapter(MetadataCatalogAdapter):
    """Production Google BigQuery catalog adapter matching jobs/contracts/bq_schema.sql."""

    mode: AdapterMode = "live"

    def __init__(
        self,
        *,
        gcp_project_id: str,
        bq_dataset_id: str = "visko_aerial_telemetry",
        bq_datasets_table_id: str = "aerial_datasets",
        bq_folders_table_id: str = "aerial_folders",
        gcp_region: str = "us-central1",
        bq_client: Any = None,
    ) -> None:
        self.gcp_project_id = gcp_project_id
        self.bq_dataset_id = bq_dataset_id
        self.bq_datasets_table_id = bq_datasets_table_id
        self.bq_folders_table_id = bq_folders_table_id
        self.gcp_region = gcp_region

        if bq_client is not None:
            self._client = bq_client
        else:
            from google.cloud import bigquery

            self._client = bigquery.Client(project=gcp_project_id, location=gcp_region)

        self._dataset_fqn = f"{self.gcp_project_id}.{self.bq_dataset_id}"
        self._projects_table = f"`{self._dataset_fqn}.projects`"
        self._folders_table = f"`{self._dataset_fqn}.{self.bq_folders_table_id}`"
        self._datasets_table = f"`{self._dataset_fqn}.{self.bq_datasets_table_id}`"

        self._ensure_tables()
        self.bootstrap_defaults()

    def _param(self, name: str, bq_type: str, value: Any) -> Any:
        from google.cloud import bigquery

        return bigquery.ScalarQueryParameter(name, bq_type, value)

    def _run_query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(query_parameters=params or [])
        job = self._client.query(sql, job_config=job_config)
        result = job.result()
        return [dict(row) for row in result]

    def _ensure_tables(self) -> None:
        from google.cloud import bigquery

        dataset_ref = bigquery.Dataset(self._dataset_fqn)
        dataset_ref.location = self.gcp_region
        self._client.create_dataset(dataset_ref, exists_ok=True)

        self._run_query(
            f"""
            CREATE TABLE IF NOT EXISTS {self._projects_table} (
              project_id STRING NOT NULL,
              name STRING NOT NULL,
              description STRING,
              created_at TIMESTAMP NOT NULL
            )
            """
        )
        self._run_query(
            f"""
            CREATE TABLE IF NOT EXISTS {self._folders_table} (
              folder_id STRING NOT NULL,
              project_id STRING NOT NULL,
              parent_folder_id STRING,
              name STRING NOT NULL,
              folder_path STRING NOT NULL,
              ecosystem_default STRING,
              created_at TIMESTAMP NOT NULL
            )
            CLUSTER BY project_id, parent_folder_id
            """
        )
        self._run_query(
            f"""
            CREATE TABLE IF NOT EXISTS {self._datasets_table} (
              video_id STRING NOT NULL,
              project_id STRING NOT NULL,
              folder_id STRING NOT NULL,
              folder_path STRING NOT NULL,
              title STRING NOT NULL,
              session_id STRING NOT NULL,
              model_id STRING NOT NULL,
              ecosystem_type STRING NOT NULL,
              duration_seconds INT64 NOT NULL,
              resolution STRING NOT NULL,
              fps INT64 NOT NULL,
              gcs_video_uri STRING NOT NULL,
              seed_media_gcs_uri STRING,
              initial_prompt STRING NOT NULL,
              prompt_history_json STRING NOT NULL,
              avg_wind_speed_mps FLOAT64 NOT NULL,
              max_wind_gust_mps FLOAT64 NOT NULL,
              wind_direction_deg FLOAT64 NOT NULL,
              avg_air_pressure_hpa FLOAT64 NOT NULL,
              avg_air_density_kgm3 FLOAT64 NOT NULL,
              ambient_temp_c FLOAT64 NOT NULL,
              avg_turbulence_edr FLOAT64 NOT NULL,
              max_turbulence_edr FLOAT64 NOT NULL,
              drone_altitude_agl_m FLOAT64 NOT NULL,
              telemetry_summary_json STRING,
              file_size_bytes INT64 NOT NULL,
              created_at TIMESTAMP NOT NULL
            )
            PARTITION BY DATE(created_at)
            CLUSTER BY project_id, folder_id, ecosystem_type
            """
        )

    def bootstrap_defaults(self) -> None:
        if self.get_project(DEFAULT_PROJECT_ID) is None:
            now = utc_now_iso()
            self._run_query(
                f"""
                INSERT INTO {self._projects_table} (project_id, name, description, created_at)
                VALUES (@project_id, @name, @description, TIMESTAMP(@created_at))
                """,
                [
                    self._param("project_id", "STRING", DEFAULT_PROJECT_ID),
                    self._param("name", "STRING", DEFAULT_PROJECT_NAME),
                    self._param("description", "STRING", DEFAULT_PROJECT_DESCRIPTION),
                    self._param("created_at", "STRING", now),
                ],
            )
        existing_folders = {
            r["folder_id"]
            for r in self._run_query(
                f"SELECT folder_id FROM {self._folders_table} WHERE project_id = @project_id",
                [self._param("project_id", "STRING", DEFAULT_PROJECT_ID)],
            )
        }
        now = utc_now_iso()
        for f in DEFAULT_FOLDERS:
            if f["folder_id"] not in existing_folders:
                self._run_query(
                    f"""
                    INSERT INTO {self._folders_table} (
                      folder_id, project_id, parent_folder_id, name,
                      folder_path, ecosystem_default, created_at
                    ) VALUES (
                      @folder_id, @project_id, @parent_folder_id, @name,
                      @folder_path, @ecosystem_default, TIMESTAMP(@created_at)
                    )
                    """,
                    [
                        self._param("folder_id", "STRING", f["folder_id"]),
                        self._param("project_id", "STRING", DEFAULT_PROJECT_ID),
                        self._param("parent_folder_id", "STRING", f["parent_folder_id"]),
                        self._param("name", "STRING", f["name"]),
                        self._param("folder_path", "STRING", f["folder_path"]),
                        self._param("ecosystem_default", "STRING", f["ecosystem_default"]),
                        self._param("created_at", "STRING", now),
                    ],
                )

    def _normalize_ts(self, val: Any) -> str:
        if isinstance(val, datetime):
            dt = val if val.tzinfo else val.replace(tzinfo=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        return str(val)

    def list_projects(self) -> list[ProjectRecord]:
        rows = self._run_query(
            f"SELECT project_id, name, description, created_at FROM {self._projects_table} ORDER BY created_at ASC"
        )
        return [
            ProjectRecord(
                project_id=r["project_id"],
                name=r["name"],
                description=r.get("description") or "",
                created_at=self._normalize_ts(r["created_at"]),
            )
            for r in rows
        ]

    def get_project(self, project_id: str) -> ProjectRecord | None:
        rows = self._run_query(
            f"SELECT project_id, name, description, created_at FROM {self._projects_table} WHERE project_id = @project_id LIMIT 1",
            [self._param("project_id", "STRING", project_id)],
        )
        if not rows:
            return None
        r = rows[0]
        return ProjectRecord(
            project_id=r["project_id"],
            name=r["name"],
            description=r.get("description") or "",
            created_at=self._normalize_ts(r["created_at"]),
        )

    def create_project(
        self,
        *,
        name: str,
        project_id: str | None = None,
        description: str | None = "",
    ) -> ProjectRecord:
        resolved_id = (
            project_id.strip()
            if project_id and project_id.strip()
            else slugify_identifier(name, fallback=f"proj-{uuid.uuid4().hex[:6]}")
        )
        if self.get_project(resolved_id) is not None:
            raise DuplicateConflictError(
                f"Project with project_id={resolved_id!r} already exists."
            )
        now = utc_now_iso()
        self._run_query(
            f"""
            INSERT INTO {self._projects_table} (project_id, name, description, created_at)
            VALUES (@project_id, @name, @description, TIMESTAMP(@created_at))
            """,
            [
                self._param("project_id", "STRING", resolved_id),
                self._param("name", "STRING", name.strip()),
                self._param("description", "STRING", description or ""),
                self._param("created_at", "STRING", now),
            ],
        )
        self._run_query(
            f"""
            INSERT INTO {self._folders_table} (
              folder_id, project_id, parent_folder_id, name, folder_path, ecosystem_default, created_at
            ) VALUES ('root', @project_id, NULL, 'My Aerial Datasets', '/', NULL, TIMESTAMP(@created_at))
            """,
            [
                self._param("project_id", "STRING", resolved_id),
                self._param("created_at", "STRING", now),
            ],
        )
        return ProjectRecord(
            project_id=resolved_id,
            name=name.strip(),
            description=description or "",
            created_at=now,
        )

    def list_folders(self, project_id: str) -> list[FolderRecord]:
        if self.get_project(project_id) is None:
            raise CatalogNotFoundError(f"Project {project_id!r} not found.")
        rows = self._run_query(
            f"""
            SELECT
              f.folder_id,
              f.project_id,
              f.parent_folder_id,
              f.name,
              f.folder_path,
              f.ecosystem_default,
              f.created_at,
              COUNT(d.video_id) AS dataset_count
            FROM {self._folders_table} f
            LEFT JOIN {self._datasets_table} d
              ON d.project_id = f.project_id AND d.folder_id = f.folder_id
            WHERE f.project_id = @project_id
            GROUP BY
              f.folder_id, f.project_id, f.parent_folder_id,
              f.name, f.folder_path, f.ecosystem_default, f.created_at
            ORDER BY IF(f.folder_id = 'root', 0, 1), f.folder_path ASC
            """,
            [self._param("project_id", "STRING", project_id)],
        )
        return [
            FolderRecord(
                folder_id=r["folder_id"],
                project_id=r["project_id"],
                parent_folder_id=r.get("parent_folder_id"),
                name=r["name"],
                folder_path=r["folder_path"],
                ecosystem_default=r.get("ecosystem_default"),
                dataset_count=int(r.get("dataset_count") or 0),
                created_at=self._normalize_ts(r["created_at"]),
            )
            for r in rows
        ]

    def get_folder(self, project_id: str, folder_id: str) -> FolderRecord | None:
        rows = self._run_query(
            f"""
            SELECT
              folder_id, project_id, parent_folder_id, name, folder_path, ecosystem_default, created_at
            FROM {self._folders_table}
            WHERE project_id = @project_id AND folder_id = @folder_id
            LIMIT 1
            """,
            [
                self._param("project_id", "STRING", project_id),
                self._param("folder_id", "STRING", folder_id),
            ],
        )
        if not rows:
            return None
        r = rows[0]
        return FolderRecord(
            folder_id=r["folder_id"],
            project_id=r["project_id"],
            parent_folder_id=r.get("parent_folder_id"),
            name=r["name"],
            folder_path=r["folder_path"],
            ecosystem_default=r.get("ecosystem_default"),
            dataset_count=0,
            created_at=self._normalize_ts(r["created_at"]),
        )

    def create_folder(
        self,
        *,
        project_id: str,
        name: str,
        parent_folder_id: str | None = None,
        ecosystem_default: str | None = None,
    ) -> FolderRecord:
        if self.get_project(project_id) is None:
            raise CatalogNotFoundError(f"Project {project_id!r} not found.")
        clean_name = name.strip()
        effective_parent_id = (
            parent_folder_id.strip()
            if parent_folder_id and parent_folder_id.strip()
            else "root"
        )
        parent = self.get_folder(project_id, effective_parent_id)
        if parent is None:
            raise CatalogNotFoundError(
                f"Parent folder {effective_parent_id!r} not found in project {project_id!r}."
            )

        dup = self._run_query(
            f"""
            SELECT 1 AS exists_flag FROM {self._folders_table}
            WHERE project_id = @project_id
              AND COALESCE(parent_folder_id, 'root') = @parent_folder_id
              AND LOWER(name) = LOWER(@name)
            LIMIT 1
            """,
            [
                self._param("project_id", "STRING", project_id),
                self._param("parent_folder_id", "STRING", effective_parent_id),
                self._param("name", "STRING", clean_name),
            ],
        )
        if dup:
            raise DuplicateConflictError(
                f"Folder {clean_name!r} already exists under parent {effective_parent_id!r}."
            )

        base_slug = slugify_identifier(clean_name, fallback="folder")
        candidate_id = (
            f"{base_slug}-{uuid.uuid4().hex[:6]}"
            if (self.get_folder(project_id, base_slug) or base_slug in ("all", "root"))
            else base_slug
        )
        folder_path = compute_normalized_folder_path(parent.folder_path, clean_name)
        now = utc_now_iso()

        self._run_query(
            f"""
            INSERT INTO {self._folders_table} (
              folder_id, project_id, parent_folder_id, name,
              folder_path, ecosystem_default, created_at
            ) VALUES (
              @folder_id, @project_id, @parent_folder_id, @name,
              @folder_path, @ecosystem_default, TIMESTAMP(@created_at)
            )
            """,
            [
                self._param("folder_id", "STRING", candidate_id),
                self._param("project_id", "STRING", project_id),
                self._param("parent_folder_id", "STRING", effective_parent_id),
                self._param("name", "STRING", clean_name),
                self._param("folder_path", "STRING", folder_path),
                self._param("ecosystem_default", "STRING", ecosystem_default),
                self._param("created_at", "STRING", now),
            ],
        )
        return FolderRecord(
            folder_id=candidate_id,
            project_id=project_id,
            parent_folder_id=effective_parent_id,
            name=clean_name,
            folder_path=folder_path,
            ecosystem_default=ecosystem_default,
            dataset_count=0,
            created_at=now,
        )

    def insert_dataset(self, dataset: DatasetRecord) -> DatasetRecord:
        row = dataset.to_bq_row()
        self._run_query(
            f"""
            INSERT INTO {self._datasets_table} (
              video_id, project_id, folder_id, folder_path, title, session_id, model_id,
              ecosystem_type, duration_seconds, resolution, fps, gcs_video_uri,
              seed_media_gcs_uri, initial_prompt, prompt_history_json,
              avg_wind_speed_mps, max_wind_gust_mps, wind_direction_deg,
              avg_air_pressure_hpa, avg_air_density_kgm3, ambient_temp_c,
              avg_turbulence_edr, max_turbulence_edr, drone_altitude_agl_m,
              telemetry_summary_json, file_size_bytes, created_at
            ) VALUES (
              @video_id, @project_id, @folder_id, @folder_path, @title, @session_id, @model_id,
              @ecosystem_type, @duration_seconds, @resolution, @fps, @gcs_video_uri,
              @seed_media_gcs_uri, @initial_prompt, @prompt_history_json,
              @avg_wind_speed_mps, @max_wind_gust_mps, @wind_direction_deg,
              @avg_air_pressure_hpa, @avg_air_density_kgm3, @ambient_temp_c,
              @avg_turbulence_edr, @max_turbulence_edr, @drone_altitude_agl_m,
              @telemetry_summary_json, @file_size_bytes, TIMESTAMP(@created_at)
            )
            """,
            [
                self._param("video_id", "STRING", row["video_id"]),
                self._param("project_id", "STRING", row["project_id"]),
                self._param("folder_id", "STRING", row["folder_id"]),
                self._param("folder_path", "STRING", row["folder_path"]),
                self._param("title", "STRING", row["title"]),
                self._param("session_id", "STRING", row["session_id"]),
                self._param("model_id", "STRING", row["model_id"]),
                self._param("ecosystem_type", "STRING", row["ecosystem_type"]),
                self._param("duration_seconds", "INT64", int(row["duration_seconds"])),
                self._param("resolution", "STRING", row["resolution"]),
                self._param("fps", "INT64", int(row["fps"])),
                self._param("gcs_video_uri", "STRING", row["gcs_video_uri"]),
                self._param("seed_media_gcs_uri", "STRING", row["seed_media_gcs_uri"]),
                self._param("initial_prompt", "STRING", row["initial_prompt"]),
                self._param("prompt_history_json", "STRING", row["prompt_history_json"]),
                self._param("avg_wind_speed_mps", "FLOAT64", float(row["avg_wind_speed_mps"])),
                self._param("max_wind_gust_mps", "FLOAT64", float(row["max_wind_gust_mps"])),
                self._param("wind_direction_deg", "FLOAT64", float(row["wind_direction_deg"])),
                self._param("avg_air_pressure_hpa", "FLOAT64", float(row["avg_air_pressure_hpa"])),
                self._param("avg_air_density_kgm3", "FLOAT64", float(row["avg_air_density_kgm3"])),
                self._param("ambient_temp_c", "FLOAT64", float(row["ambient_temp_c"])),
                self._param("avg_turbulence_edr", "FLOAT64", float(row["avg_turbulence_edr"])),
                self._param("max_turbulence_edr", "FLOAT64", float(row["max_turbulence_edr"])),
                self._param("drone_altitude_agl_m", "FLOAT64", float(row["drone_altitude_agl_m"])),
                self._param("telemetry_summary_json", "STRING", row["telemetry_summary_json"]),
                self._param("file_size_bytes", "INT64", int(row["file_size_bytes"])),
                self._param("created_at", "STRING", str(row["created_at"])),
            ],
        )
        return enrich_dataset_urls(row)

    def get_dataset(self, video_id: str) -> DatasetRecord | None:
        cols_sql = ", ".join(BQ_AERIAL_DATASETS_COLUMNS)
        rows = self._run_query(
            f"SELECT {cols_sql} FROM {self._datasets_table} WHERE video_id = @video_id LIMIT 1",
            [self._param("video_id", "STRING", video_id)],
        )
        return enrich_dataset_urls(rows[0]) if rows else None

    def list_datasets(
        self,
        *,
        project_id: str,
        folder_id: str | None = None,
        ecosystem_type: str | None = None,
        duration_seconds: int | None = None,
        min_turbulence_edr: float | None = None,
        max_turbulence_edr: float | None = None,
        search: str | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> DatasetListResponse:
        if self.get_project(project_id) is None:
            raise CatalogNotFoundError(f"Project {project_id!r} not found.")

        where_clauses = ["project_id = @project_id"]
        params: list[Any] = [self._param("project_id", "STRING", project_id)]

        if folder_id and folder_id.strip().lower() != "all":
            where_clauses.append("folder_id = @folder_id")
            params.append(self._param("folder_id", "STRING", folder_id.strip()))

        if ecosystem_type and ecosystem_type.strip().lower() != "all":
            where_clauses.append("ecosystem_type = @ecosystem_type")
            params.append(self._param("ecosystem_type", "STRING", ecosystem_type.strip()))

        if duration_seconds is not None:
            where_clauses.append("duration_seconds = @duration_seconds")
            params.append(self._param("duration_seconds", "INT64", int(duration_seconds)))

        if min_turbulence_edr is not None:
            where_clauses.append("max_turbulence_edr >= @min_turbulence_edr")
            params.append(self._param("min_turbulence_edr", "FLOAT64", float(min_turbulence_edr)))

        if max_turbulence_edr is not None:
            where_clauses.append("max_turbulence_edr <= @max_turbulence_edr")
            params.append(self._param("max_turbulence_edr", "FLOAT64", float(max_turbulence_edr)))

        if search and search.strip():
            where_clauses.append(
                "("
                "STRPOS(LOWER(title), @search) > 0 OR "
                "STRPOS(LOWER(video_id), @search) > 0 OR "
                "STRPOS(LOWER(initial_prompt), @search) > 0 OR "
                "STRPOS(LOWER(folder_path), @search) > 0"
                ")"
            )
            params.append(self._param("search", "STRING", search.strip().lower()))

        sort_col = ALLOWED_SORT_COLUMNS.get(sort_by, "created_at")
        direction = "ASC" if (sort_dir or "").strip().lower() == "asc" else "DESC"
        cols_sql = ", ".join(BQ_AERIAL_DATASETS_COLUMNS)
        where_sql = " AND ".join(where_clauses)

        rows = self._run_query(
            f"SELECT {cols_sql} FROM {self._datasets_table} WHERE {where_sql} ORDER BY {sort_col} {direction}",
            params,
        )
        records = [enrich_dataset_urls(r) for r in rows]
        return DatasetListResponse(
            project_id=project_id,
            datasets=records,
            total=len(records),
            storage_bytes_total=sum(r.file_size_bytes for r in records),
        )

    def update_dataset(
        self,
        video_id: str,
        *,
        folder_id: str | None = None,
        title: str | None = None,
    ) -> DatasetRecord:
        existing = self.get_dataset(video_id)
        if existing is None:
            raise CatalogNotFoundError(f"Dataset {video_id!r} not found.")

        new_folder_id = existing.folder_id
        new_folder_path = existing.folder_path
        if folder_id is not None:
            target = self.get_folder(existing.project_id, folder_id.strip())
            if target is None:
                raise CatalogNotFoundError(
                    f"Target folder {folder_id!r} not found in project {existing.project_id!r}."
                )
            new_folder_id = target.folder_id
            new_folder_path = target.folder_path

        new_title = title.strip() if title is not None else existing.title

        self._run_query(
            f"""
            UPDATE {self._datasets_table}
            SET folder_id = @folder_id, folder_path = @folder_path, title = @title
            WHERE video_id = @video_id
            """,
            [
                self._param("folder_id", "STRING", new_folder_id),
                self._param("folder_path", "STRING", new_folder_path),
                self._param("title", "STRING", new_title),
                self._param("video_id", "STRING", video_id),
            ],
        )
        updated = self.get_dataset(video_id)
        assert updated is not None
        return updated
