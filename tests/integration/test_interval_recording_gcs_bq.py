"""Layer 2 Integration Tests: Exact 5s, 10s, 15s MP4 Clip Recording, GCS Storage & 27-Col BigQuery Catalog."""

from __future__ import annotations

import json

import httpx
import pytest

from app.models.schemas import BQ_AERIAL_DATASETS_COLUMNS, CANONICAL_MODEL_ID
from app.services.clip_recorder import verify_mp4_ftyp_signature
from app.services.session_manager import runtime


@pytest.mark.asyncio
async def test_record_5s_10s_15s_intervals_persist_valid_mp4_and_27_col_bq_rows(
    async_client: httpx.AsyncClient,
) -> None:
    """T1-D1, T1-D2, T1-D3, T1-D5 & T2-01: Record 5s/10s/15s clips, check ftyp MP4 & BQ catalog, reject 7s."""
    sess_resp = await async_client.post(
        "/api/v1/sessions",
        json={
            "project_id": "default-uav-project",
            "folder_id": "alpine-trials",
            "ecosystem_type": "alpine",
            "camera_mode": "forward_downward_oblique",
            "initial_prompt": "Autonomous UAV cruising above snowy alpine ridge pass",
        },
    )
    assert sess_resp.status_code in (200, 201)
    session_id = sess_resp.json()["session_id"]

    recorded_ids: list[str] = []
    for payload, expected_dur in (
        ({"duration_seconds": 5, "title": "Alpine Eval 5s"}, 5),
        ({"duration_seconds": 10, "title": "Alpine Eval 10s"}, 10),
        ({"interval_setting": "15s", "title": "Alpine Eval 15s"}, 15),
    ):
        rec_resp = await async_client.post(
            f"/api/v1/sessions/{session_id}/record",
            json=payload,
        )
        assert rec_resp.status_code == 201, rec_resp.text
        record = rec_resp.json()
        recorded_ids.append(record["video_id"])

        assert record["duration_seconds"] == expected_dur
        assert record["project_id"] == "default-uav-project"
        assert record["folder_id"] == "alpine-trials"
        assert record["folder_path"] == "/alpine-trials"
        assert record["model_id"] == CANONICAL_MODEL_ID
        assert record["fps"] == 18
        assert record["file_size_bytes"] > 0
        assert record["avg_air_pressure_hpa"] < 880.0
        assert record["max_wind_gust_mps"] >= record["avg_wind_speed_mps"]
        assert record["max_turbulence_edr"] >= record["avg_turbulence_edr"]

        # Verify all 27 canonical BigQuery columns exist in response
        for col in BQ_AERIAL_DATASETS_COLUMNS:
            assert col in record, f"Missing BigQuery column {col} in DatasetRecord"

        # Verify stored MP4 binary in GCS/local adapter has valid ISO BMFF 'ftyp' box
        gcs_uri = record["gcs_video_uri"]
        assert gcs_uri.startswith("gs://")
        assert runtime.storage.exists(gcs_uri)
        mp4_bytes = runtime.storage.download_bytes(gcs_uri)
        assert len(mp4_bytes) == record["file_size_bytes"]
        assert mp4_bytes[4:8] == b"ftyp"
        assert verify_mp4_ftyp_signature(mp4_bytes)

    # Verify BigQuery catalog endpoint returns all 3 recorded datasets
    list_resp = await async_client.get(
        "/api/v1/projects/default-uav-project/datasets?folder_id=alpine-trials"
    )
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert listed["total"] == 3
    listed_ids = {d["video_id"] for d in listed["datasets"]}
    assert listed_ids == set(recorded_ids)
    assert listed["storage_bytes_total"] == sum(d["file_size_bytes"] for d in listed["datasets"])

    # Invalid recording durations MUST fail with HTTP 422
    for invalid_body in (
        {"duration_seconds": 7},
        {"duration_seconds": 0},
        {"duration_seconds": -5},
        {"duration_seconds": 3},
        {"duration_seconds": 8},
        {"duration_seconds": 30},
        {"duration_seconds": 60},
        {"interval_setting": "20s"},
        {},
    ):
        bad_resp = await async_client.post(
            f"/api/v1/sessions/{session_id}/record",
            json=invalid_body,
        )
        assert bad_resp.status_code == 422, f"Expected 422 for {invalid_body}, got {bad_resp.status_code}"


@pytest.mark.asyncio
async def test_pairwise_dubai_preset_storm_steering_and_10s_bq_lineage(
    async_client: httpx.AsyncClient,
) -> None:
    """T3-01 & T3-02: Dubai nadir preset -> alpine session -> storm steer -> 10s record lineage check."""
    preset_seed_resp = await async_client.post(
        "/api/v1/media/seed/from-preset",
        json={"preset_id": "dubai-tile-10", "project_id": "default-uav-project"},
    )
    assert preset_seed_resp.status_code == 201
    preset_seed = preset_seed_resp.json()

    sess_resp = await async_client.post(
        "/api/v1/sessions",
        json={
            "project_id": "default-uav-project",
            "folder_id": "alpine-trials",
            "camera_mode": "nadir_downward",
            "ecosystem_type": "alpine",
            "seed_id": preset_seed["seed_id"],
            "initial_prompt": "Nadir mapping flight over rocky mountain escarpment",
        },
    )
    assert sess_resp.status_code in (200, 201)
    session_id = sess_resp.json()["session_id"]

    steer_resp = await async_client.post(
        f"/api/v1/sessions/{session_id}/prompt",
        json={"prompt": "Heavy storm front with 24 m/s crosswind gusts and severe ridge turbulence"},
    )
    assert steer_resp.status_code == 200

    rec_resp = await async_client.post(
        f"/api/v1/sessions/{session_id}/record",
        json={"duration_seconds": 10, "title": "Dubai Preset Storm Lineage"},
    )
    assert rec_resp.status_code == 201
    ds = rec_resp.json()

    assert ds["seed_media_gcs_uri"] == preset_seed["seed_media_gcs_uri"]
    assert ds["duration_seconds"] == 10
    assert ds["avg_air_pressure_hpa"] < 880.0
    history = json.loads(ds["prompt_history_json"])
    assert len(history) == 2
    assert "24 m/s" in history[1]["prompt"]
    assert history[1]["passthrough"] is True
