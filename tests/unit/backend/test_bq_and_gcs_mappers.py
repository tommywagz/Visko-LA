"""Layer 1A Unit Tests: BigQuery 7-Col/27-Col Schema Mappers, GCS URIs & Cloud Adapter Mocks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

import pytest

from app.adapters.catalog import (
    BigQueryCatalogAdapter,
    DuplicateConflictError,
    SQLiteCatalogAdapter,
    compute_normalized_folder_path,
)
from app.adapters.storage import (
    GCSStorageAdapter,
    LocalStorageAdapter,
    build_dataset_gcs_uri,
    build_seed_gcs_uri,
    clean_folder_path_for_gcs,
    parse_gcs_uri,
)
from app.models.schemas import (
    BQ_AERIAL_DATASETS_COLUMNS,
    BQ_AERIAL_FOLDERS_COLUMNS,
    CANONICAL_MODEL_ID,
    DatasetRecord,
    FolderRecord,
    PromptEntry,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BQ_SCHEMA_PATH = REPO_ROOT / "jobs" / "contracts" / "bq_schema.sql"


def _parse_bq_create_table_columns(sql_text: str, table_name: str) -> list[tuple[str, str, bool]]:
    """Extract [(col_name, sql_type, not_null)] from jobs/contracts/bq_schema.sql."""
    active_sql = "\n".join(
        line for line in sql_text.splitlines() if not line.lstrip().startswith("--")
    )
    pattern = re.compile(
        rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`[^`]*\.{re.escape(table_name)}`\s*\((.*?)\)\s*(?:PARTITION|CLUSTER|;)",
        re.S | re.I,
    )
    match = pattern.search(active_sql)
    assert match is not None, f"Table {table_name} not found in bq_schema.sql"
    body = match.group(1)

    cols: list[tuple[str, str, bool]] = []
    col_re = re.compile(
        r"^\s*([a-z0-9_]+)\s+(STRING|INT64|FLOAT64|TIMESTAMP)\b(.*)$",
        re.I,
    )
    for raw_line in body.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        m = col_re.match(line)
        if m:
            col_name = m.group(1)
            col_type = m.group(2).upper()
            not_null = "NOT NULL" in m.group(3).upper()
            cols.append((col_name, col_type, not_null))
    return cols


def test_bq_schema_sql_matches_7_folder_and_27_dataset_columns_and_types() -> None:
    """T1-D4: Assert exact column names, count (7 & 27), nullability, and types vs bq_schema.sql."""
    sql_text = BQ_SCHEMA_PATH.read_text(encoding="utf-8")

    folder_cols = _parse_bq_create_table_columns(sql_text, "aerial_folders")
    dataset_cols = _parse_bq_create_table_columns(sql_text, "aerial_datasets")

    assert len(folder_cols) == 7
    assert tuple(c[0] for c in folder_cols) == BQ_AERIAL_FOLDERS_COLUMNS

    assert len(dataset_cols) == 27
    assert tuple(c[0] for c in dataset_cols) == BQ_AERIAL_DATASETS_COLUMNS

    prompt_entry = PromptEntry(
        prompt_id="prm_01",
        prompt="Crosswind 18 m/s over alpine ridge",
        compiled_prompt="Stabilized nose-mounted autonomous UAV perception camera pitched 35 degrees downward...",
        passthrough=True,
        chunk_index=1,
        status="applied",
        created_at="2026-11-14T23:00:00Z",
    )
    record = DatasetRecord(
        video_id="vid_test001",
        project_id="default-uav-project",
        folder_id="alpine-trials",
        folder_path="/alpine-trials",
        title="Alpine Crosswind 10s",
        session_id="sess_test001",
        model_id=CANONICAL_MODEL_ID,
        ecosystem_type="alpine",
        duration_seconds=10,
        resolution="1080p",
        fps=18,
        gcs_video_uri="gs://visko-orbis-aerial-datasets/datasets/default-uav-project/alpine-trials/vid_test001.mp4",
        seed_media_gcs_uri="gs://visko-orbis-aerial-datasets/seeds/default-uav-project/seed_01.jpg",
        initial_prompt="Crosswind 18 m/s over alpine ridge",
        prompt_history_json=json.dumps([prompt_entry.model_dump()]),
        avg_wind_speed_mps=17.4,
        max_wind_gust_mps=23.1,
        wind_direction_deg=252.0,
        avg_air_pressure_hpa=829.6,
        avg_air_density_kgm3=1.028,
        ambient_temp_c=3.1,
        avg_turbulence_edr=0.39,
        max_turbulence_edr=0.51,
        drone_altitude_agl_m=65.0,
        telemetry_summary_json=json.dumps({"sample_count": 40}),
        file_size_bytes=48120,
        created_at="2026-11-14T23:00:10Z",
        download_url="/api/v1/datasets/vid_test001/download",
        direct_stream_url="/api/v1/datasets/vid_test001/file",
    )

    bq_row = record.to_bq_row()
    assert tuple(bq_row.keys()) == BQ_AERIAL_DATASETS_COLUMNS
    assert len(bq_row) == 27
    # Extra API convenience URLs must NOT leak into the 27-col BigQuery insert row
    assert "download_url" not in bq_row
    assert "direct_stream_url" not in bq_row

    for col_name, sql_type, not_null in dataset_cols:
        val = bq_row[col_name]
        if not_null:
            assert val is not None, f"NOT NULL column {col_name} was None"
        if val is not None:
            if sql_type in ("STRING", "TIMESTAMP"):
                assert isinstance(val, str), f"Column {col_name} expected str for {sql_type}, got {type(val)}"
            elif sql_type == "INT64":
                assert isinstance(val, int) and not isinstance(val, bool)
            elif sql_type == "FLOAT64":
                assert isinstance(val, (int, float)) and not isinstance(val, bool)

    # Verify prompt_history_json round-trips to PromptEntry
    decoded_history = json.loads(bq_row["prompt_history_json"])
    assert isinstance(decoded_history, list) and len(decoded_history) == 1
    parsed_entry = PromptEntry(**decoded_history[0])
    assert parsed_entry.passthrough is True

    # Check FolderRecord 7 canonical fields
    folder = FolderRecord(
        folder_id="alpine-trials",
        project_id="default-uav-project",
        parent_folder_id="root",
        name="Alpine Trials",
        folder_path="/alpine-trials",
        ecosystem_default="alpine",
        created_at="2026-11-14T23:00:00Z",
    )
    folder_dump = folder.model_dump()
    for f_col, _, f_not_null in folder_cols:
        assert f_col in folder_dump
        if f_not_null:
            assert folder_dump[f_col] is not None


def test_gcs_uri_builders_local_storage_and_mocked_live_gcs_adapter(tmp_path: Path) -> None:
    """Verify GCS URI templates, byte-range reads, and GCSStorageAdapter V4 signed URL + ADC fallback."""
    assert clean_folder_path_for_gcs("/") == "root"
    assert clean_folder_path_for_gcs("/coastal-winds/gusts/") == "coastal-winds/gusts"
    assert compute_normalized_folder_path("/", "Coastal Winds") == "/coastal-winds"
    assert compute_normalized_folder_path("/coastal-winds", "Gust Runs") == "/coastal-winds/gust-runs"

    seed_uri = build_seed_gcs_uri(
        bucket_name="visko-bucket",
        seed_prefix="seeds",
        project_id="proj-1",
        seed_id="seed_abc",
        safe_filename="tile.jpg",
    )
    assert seed_uri == "gs://visko-bucket/seeds/proj-1/seed_abc_tile.jpg"
    assert parse_gcs_uri(seed_uri) == ("visko-bucket", "seeds/proj-1/seed_abc_tile.jpg")

    ds_uri = build_dataset_gcs_uri(
        bucket_name="visko-bucket",
        dataset_prefix="datasets",
        project_id="proj-1",
        folder_path="/",
        video_id="vid_99",
    )
    assert ds_uri == "gs://visko-bucket/datasets/proj-1/root/vid_99.mp4"

    with pytest.raises(ValueError):
        parse_gcs_uri("https://storage.googleapis.com/not-gs-uri")

    # LocalStorageAdapter round-trip & range read
    local_adapter = LocalStorageAdapter(tmp_path / "local_gcs")
    payload = b"\x00\x00\x00\x18ftypisom" + b"A" * 100
    assert local_adapter.upload_bytes(ds_uri, payload, content_type="video/mp4") == len(payload)
    assert local_adapter.exists(ds_uri) is True
    assert local_adapter.get_size_bytes(ds_uri) == len(payload)
    assert local_adapter.download_range(ds_uri, 4, 7) == b"ftyp"
    assert local_adapter.download_bytes(ds_uri) == payload

    # Mocked Live GCSStorageAdapter (both V4 signed URL success and keyless ADC fallback)
    class FakeBlob:
        def __init__(self, store: dict[str, bytes], key: str, *, fail_sign: bool = False) -> None:
            self._store = store
            self.key = key
            self.fail_sign = fail_sign
            self.size: int | None = None

        def upload_from_string(self, data: bytes, content_type: str = "") -> None:
            self._store[self.key] = data
            self.size = len(data)

        def exists(self) -> bool:
            return self.key in self._store

        def reload(self) -> None:
            if self.key in self._store:
                self.size = len(self._store[self.key])

        def download_as_bytes(self, start: int | None = None, end: int | None = None) -> bytes:
            raw = self._store[self.key]
            if start is not None and end is not None:
                return raw[start : end + 1]
            return raw

        def generate_signed_url(self, **kwargs: Any) -> str:
            if self.fail_sign:
                raise RuntimeError("Credentials lack private key for V4 signing")
            assert kwargs["version"] == "v4"
            return f"https://storage.googleapis.com/visko-bucket/{self.key}?X-Goog-Algorithm=GOOG4-RSA-SHA256"

    class FakeBucket:
        def __init__(self, store: dict[str, bytes], *, fail_sign: bool = False) -> None:
            self._store = store
            self.fail_sign = fail_sign

        def blob(self, key: str) -> FakeBlob:
            return FakeBlob(self._store, key, fail_sign=self.fail_sign)

    class FakeStorageClient:
        def __init__(self, *, fail_sign: bool = False) -> None:
            self.store: dict[str, bytes] = {}
            self.fail_sign = fail_sign

        def bucket(self, _name: str) -> FakeBucket:
            return FakeBucket(self.store, fail_sign=self.fail_sign)

    live_gcs = GCSStorageAdapter(gcp_project_id="visko-prod", storage_client=FakeStorageClient())
    live_gcs.upload_bytes(ds_uri, payload, content_type="video/mp4")
    assert live_gcs.exists(ds_uri) is True
    assert live_gcs.get_size_bytes(ds_uri) == len(payload)
    assert live_gcs.download_range(ds_uri, 4, 7) == b"ftyp"
    signed = live_gcs.generate_download_url(
        ds_uri,
        filename="vid_99.mp4",
        fallback_stream_url="http://localhost:8000/api/v1/datasets/vid_99/file",
    )
    assert "X-Goog-Algorithm=GOOG4-RSA-SHA256" in signed

    # ADC fallback when signing raises
    adc_gcs = GCSStorageAdapter(
        gcp_project_id="visko-prod",
        storage_client=FakeStorageClient(fail_sign=True),
    )
    fallback_url = adc_gcs.generate_download_url(
        ds_uri,
        filename="vid_99.mp4",
        fallback_stream_url="http://localhost:8000/api/v1/datasets/vid_99/file",
    )
    assert fallback_url == "http://localhost:8000/api/v1/datasets/vid_99/file"


def test_bigquery_catalog_adapter_with_mocked_client_and_sqlite_parity(tmp_path: Path) -> None:
    """Verify BigQueryCatalogAdapter DDL, 27-col parameterized INSERT, and duplicate conflict checks."""
    executed_queries: list[tuple[str, list[Any]]] = []
    fake_projects: dict[str, dict[str, Any]] = {}
    fake_folders: list[dict[str, Any]] = []
    fake_datasets: dict[str, dict[str, Any]] = {}

    class FakeQueryJob:
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            self._rows = rows

        def result(self) -> list[dict[str, Any]]:
            return self._rows

    class FakeBQClient:
        def __init__(self) -> None:
            self.datasets_created: list[str] = []

        def create_dataset(self, dataset_ref: Any, exists_ok: bool = True) -> None:
            assert exists_ok is True
            self.datasets_created.append(str(dataset_ref.dataset_id))

        def query(self, sql: str, job_config: Any = None) -> FakeQueryJob:
            params = list(getattr(job_config, "query_parameters", []) or [])
            executed_queries.append((sql, params))
            pmap = {p.name: p.value for p in params}
            norm_sql = " ".join(sql.split())

            if norm_sql.startswith("CREATE TABLE IF NOT EXISTS"):
                return FakeQueryJob([])
            if "FROM `visko-prod.visko_bq.projects` WHERE project_id =" in norm_sql:
                pid = pmap["project_id"]
                return FakeQueryJob([fake_projects[pid]] if pid in fake_projects else [])
            if norm_sql.startswith("INSERT INTO `visko-prod.visko_bq.projects`"):
                fake_projects[pmap["project_id"]] = {
                    "project_id": pmap["project_id"],
                    "name": pmap["name"],
                    "description": pmap["description"],
                    "created_at": datetime.now(timezone.utc),
                }
                return FakeQueryJob([])
            if "SELECT folder_id FROM `visko-prod.visko_bq.aerial_folders`" in norm_sql:
                pid = pmap["project_id"]
                return FakeQueryJob([{"folder_id": f["folder_id"]} for f in fake_folders if f["project_id"] == pid])
            if "SELECT 1 AS exists_flag FROM `visko-prod.visko_bq.aerial_folders`" in norm_sql:
                matches = [
                    f
                    for f in fake_folders
                    if f["project_id"] == pmap["project_id"]
                    and (f["parent_folder_id"] or "root") == pmap["parent_folder_id"]
                    and f["name"].lower() == pmap["name"].lower()
                ]
                return FakeQueryJob([{"exists_flag": 1}] if matches else [])
            if "FROM `visko-prod.visko_bq.aerial_folders` WHERE project_id = @project_id AND folder_id = @folder_id" in norm_sql:
                matches = [
                    f
                    for f in fake_folders
                    if f["project_id"] == pmap["project_id"] and f["folder_id"] == pmap["folder_id"]
                ]
                return FakeQueryJob(matches[:1])
            if norm_sql.startswith("INSERT INTO `visko-prod.visko_bq.aerial_folders`"):
                fake_folders.append(
                    {
                        "folder_id": pmap["folder_id"],
                        "project_id": pmap["project_id"],
                        "parent_folder_id": pmap["parent_folder_id"],
                        "name": pmap["name"],
                        "folder_path": pmap["folder_path"],
                        "ecosystem_default": pmap["ecosystem_default"],
                        "created_at": pmap["created_at"],
                    }
                )
                return FakeQueryJob([])
            if norm_sql.startswith("INSERT INTO `visko-prod.visko_bq.aerial_datasets`"):
                assert len(params) == 27
                fake_datasets[pmap["video_id"]] = dict(pmap)
                return FakeQueryJob([])
            if "FROM `visko-prod.visko_bq.aerial_datasets` WHERE video_id = @video_id" in norm_sql:
                vid = pmap["video_id"]
                return FakeQueryJob([fake_datasets[vid]] if vid in fake_datasets else [])
            if norm_sql.startswith("UPDATE `visko-prod.visko_bq.aerial_datasets`"):
                vid = pmap["video_id"]
                fake_datasets[vid]["folder_id"] = pmap["folder_id"]
                fake_datasets[vid]["folder_path"] = pmap["folder_path"]
                fake_datasets[vid]["title"] = pmap["title"]
                return FakeQueryJob([])
            return FakeQueryJob([])

    bq_adapter = BigQueryCatalogAdapter(
        gcp_project_id="visko-prod",
        bq_dataset_id="visko_bq",
        bq_client=FakeBQClient(),
    )
    assert any("CREATE TABLE IF NOT EXISTS `visko-prod.visko_bq.aerial_datasets`" in q[0] for q in executed_queries)
    assert "default-uav-project" in fake_projects

    created_folder = bq_adapter.create_folder(
        project_id="default-uav-project",
        name="Rotor Eval",
        parent_folder_id="root",
    )
    assert created_folder.folder_path == "/rotor-eval"
    with pytest.raises(DuplicateConflictError):
        bq_adapter.create_folder(
            project_id="default-uav-project",
            name="rotor eval",
            parent_folder_id="root",
        )

    sample_ds = DatasetRecord(
        video_id="vid_bq_live_1",
        project_id="default-uav-project",
        folder_id="root",
        folder_path="/",
        title="BQ Clip",
        session_id="sess_bq_1",
        model_id=CANONICAL_MODEL_ID,
        ecosystem_type="alpine",
        duration_seconds=5,
        resolution="1080p",
        fps=18,
        gcs_video_uri="gs://visko-bucket/datasets/default-uav-project/root/vid_bq_live_1.mp4",
        seed_media_gcs_uri=None,
        initial_prompt="Alpine test",
        prompt_history_json="[]",
        avg_wind_speed_mps=12.0,
        max_wind_gust_mps=16.5,
        wind_direction_deg=240.0,
        avg_air_pressure_hpa=831.2,
        avg_air_density_kgm3=1.03,
        ambient_temp_c=4.0,
        avg_turbulence_edr=0.28,
        max_turbulence_edr=0.35,
        drone_altitude_agl_m=65.0,
        telemetry_summary_json="{}",
        file_size_bytes=12345,
        created_at="2026-11-14T23:00:00Z",
    )
    inserted = bq_adapter.insert_dataset(sample_ds)
    assert inserted.video_id == "vid_bq_live_1"
    moved = bq_adapter.update_dataset("vid_bq_live_1", folder_id=created_folder.folder_id, title="Moved BQ Clip")
    assert moved.folder_id == created_folder.folder_id
    assert moved.folder_path == "/rotor-eval"
    assert moved.title == "Moved BQ Clip"

    # Also verify SQLiteCatalogAdapter sibling uniqueness allows same name under DIFFERENT parent
    sqlite_cat = SQLiteCatalogAdapter(tmp_path / "parity.db")
    f1 = sqlite_cat.create_folder(project_id="default-uav-project", name="Gusts", parent_folder_id="alpine-trials")
    f2 = sqlite_cat.create_folder(project_id="default-uav-project", name="Gusts", parent_folder_id="coastal-crosswinds")
    assert f1.folder_path == "/alpine-trials/gusts"
    assert f2.folder_path == "/coastal-crosswinds/gusts"
