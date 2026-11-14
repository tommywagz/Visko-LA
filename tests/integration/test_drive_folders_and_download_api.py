"""Layer 2 Integration Tests: Google Drive Folder Hierarchy, Dataset Upload, Move & MP4 Downloads."""

from __future__ import annotations

import httpx
import pytest

from app.models.schemas import BQ_AERIAL_DATASETS_COLUMNS


@pytest.mark.asyncio
async def test_drive_projects_folder_hierarchy_duplicate_409_and_isolation(
    async_client: httpx.AsyncClient,
    sample_clip_bytes: bytes,
) -> None:
    """T1-E1..E5, T2-07, T2-09, T3-03 & T3-04: Folders, recording + upload isolation, move & MP4 download."""
    # 1. Verify default startup project and folders
    proj_resp = await async_client.get("/api/v1/projects")
    assert proj_resp.status_code == 200
    project_ids = {p["project_id"] for p in proj_resp.json()["projects"]}
    assert "default-uav-project" in project_ids

    init_folders_resp = await async_client.get("/api/v1/projects/default-uav-project/folders")
    assert init_folders_resp.status_code == 200
    init_folder_ids = {f["folder_id"] for f in init_folders_resp.json()["folders"]}
    assert {"root", "alpine-trials", "coastal-crosswinds", "urban-canyon"}.issubset(init_folder_ids)

    # 2. Create "coastal-winds", "mountain-rotors", and nested "gust-runs"
    f_coastal_resp = await async_client.post(
        "/api/v1/projects/default-uav-project/folders",
        json={"name": "coastal-winds", "parent_folder_id": "root", "ecosystem_default": "coastal"},
    )
    assert f_coastal_resp.status_code == 201
    f_coastal = f_coastal_resp.json()
    assert f_coastal["folder_path"] == "/coastal-winds"

    f_rotors_resp = await async_client.post(
        "/api/v1/projects/default-uav-project/folders",
        json={"name": "mountain-rotors", "parent_folder_id": "root", "ecosystem_default": "alpine"},
    )
    assert f_rotors_resp.status_code == 201
    f_rotors = f_rotors_resp.json()
    assert f_rotors["folder_path"] == "/mountain-rotors"

    f_nested_resp = await async_client.post(
        "/api/v1/projects/default-uav-project/folders",
        json={"name": "gust-runs", "parent_folder_id": f_coastal["folder_id"]},
    )
    assert f_nested_resp.status_code == 201
    assert f_nested_resp.json()["folder_path"] == "/coastal-winds/gust-runs"

    # Case-insensitive duplicate sibling folder MUST return 409 Conflict
    dup_resp = await async_client.post(
        "/api/v1/projects/default-uav-project/folders",
        json={"name": "COASTAL-WINDS", "parent_folder_id": "root"},
    )
    assert dup_resp.status_code == 409

    # Same folder name under a DIFFERENT parent succeeds (201)
    same_name_other_parent = await async_client.post(
        "/api/v1/projects/default-uav-project/folders",
        json={"name": "gust-runs", "parent_folder_id": f_rotors["folder_id"]},
    )
    assert same_name_other_parent.status_code == 201

    # 3. Record one 5s clip into "coastal-winds"
    sess_resp = await async_client.post(
        "/api/v1/sessions",
        json={
            "project_id": "default-uav-project",
            "folder_id": f_coastal["folder_id"],
            "ecosystem_type": "coastal",
            "initial_prompt": "Brisk coastal headland whitecaps",
        },
    )
    session_id = sess_resp.json()["session_id"]
    rec_resp = await async_client.post(
        f"/api/v1/sessions/{session_id}/record",
        json={"duration_seconds": 5, "title": "Coastal Wind Clip"},
    )
    assert rec_resp.status_code == 201
    recorded_clip = rec_resp.json()
    assert recorded_clip["folder_id"] == f_coastal["folder_id"]
    assert recorded_clip["folder_path"] == "/coastal-winds"

    # 4. Upload a second .mp4 dataset clip directly into "mountain-rotors"
    upload_resp = await async_client.post(
        "/api/v1/projects/default-uav-project/datasets/upload",
        files={"file": ("rotor_trial.mp4", sample_clip_bytes, "video/mp4")},
        data={
            "folder_id": f_rotors["folder_id"],
            "title": "Uploaded Mountain Rotor Clip",
            "ecosystem_type": "alpine",
            "duration_seconds": "5",
        },
    )
    assert upload_resp.status_code == 201, upload_resp.text
    uploaded_clip = upload_resp.json()
    assert uploaded_clip["folder_id"] == f_rotors["folder_id"]
    assert uploaded_clip["folder_path"] == "/mountain-rotors"
    for col in BQ_AERIAL_DATASETS_COLUMNS:
        assert col in uploaded_clip

    # 5. Strict folder-scoped isolation vs project-wide 'all'
    coastal_list = await async_client.get(
        f"/api/v1/projects/default-uav-project/datasets?folder_id={f_coastal['folder_id']}"
    )
    assert coastal_list.status_code == 200
    assert [d["video_id"] for d in coastal_list.json()["datasets"]] == [recorded_clip["video_id"]]

    rotors_list = await async_client.get(
        f"/api/v1/projects/default-uav-project/datasets?folder_id={f_rotors['folder_id']}"
    )
    assert rotors_list.status_code == 200
    assert [d["video_id"] for d in rotors_list.json()["datasets"]] == [uploaded_clip["video_id"]]

    all_list = await async_client.get("/api/v1/projects/default-uav-project/datasets?folder_id=all")
    assert all_list.status_code == 200
    assert all_list.json()["total"] == 2

    # Keyword search filter
    search_list = await async_client.get(
        "/api/v1/projects/default-uav-project/datasets?search=Mountain%20Rotor"
    )
    assert search_list.status_code == 200
    assert [d["video_id"] for d in search_list.json()["datasets"]] == [uploaded_clip["video_id"]]

    # 6. Move uploaded dataset from "mountain-rotors" -> "coastal-winds" via PATCH /api/v1/datasets/{video_id}
    patch_resp = await async_client.patch(
        f"/api/v1/datasets/{uploaded_clip['video_id']}",
        json={
            "folder_id": f_coastal["folder_id"],
            "title": "Relocated Rotor Clip",
        },
    )
    assert patch_resp.status_code == 200
    moved = patch_resp.json()
    assert moved["folder_id"] == f_coastal["folder_id"]
    assert moved["folder_path"] == "/coastal-winds"
    assert moved["title"] == "Relocated Rotor Clip"

    rotors_after = await async_client.get(
        f"/api/v1/projects/default-uav-project/datasets?folder_id={f_rotors['folder_id']}"
    )
    assert rotors_after.json()["total"] == 0

    coastal_after = await async_client.get(
        f"/api/v1/projects/default-uav-project/datasets?folder_id={f_coastal['folder_id']}"
    )
    assert coastal_after.json()["total"] == 2

    # 7. Download metadata (/download) & binary attachment + byte-range stream (/file)
    dl_info_resp = await async_client.get(f"/api/v1/datasets/{uploaded_clip['video_id']}/download")
    assert dl_info_resp.status_code == 200
    dl_info = dl_info_resp.json()
    assert dl_info["video_id"] == uploaded_clip["video_id"]
    assert dl_info["filename"].endswith(".mp4")
    assert dl_info["gcs_video_uri"] == dl_info["gcs_uri"]
    assert dl_info["direct_stream_url"] == f"/api/v1/datasets/{uploaded_clip['video_id']}/file"
    assert len(dl_info["signed_url"]) > 0

    file_resp = await async_client.get(f"/api/v1/datasets/{uploaded_clip['video_id']}/file")
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"].startswith("video/mp4")
    assert "attachment" in file_resp.headers.get("content-disposition", "")
    assert ".mp4" in file_resp.headers.get("content-disposition", "")
    assert file_resp.headers.get("accept-ranges") == "bytes"
    assert len(file_resp.content) == len(sample_clip_bytes)
    assert file_resp.content[4:8] == b"ftyp"

    # Byte-range request (206 Partial Content)
    range_resp = await async_client.get(
        f"/api/v1/datasets/{uploaded_clip['video_id']}/file",
        headers={"Range": "bytes=0-63"},
    )
    assert range_resp.status_code == 206
    assert range_resp.headers["content-type"].startswith("video/mp4")
    assert range_resp.headers["content-range"] == f"bytes 0-63/{len(sample_clip_bytes)}"
    assert len(range_resp.content) == 64
    assert range_resp.content[4:8] == b"ftyp"

    # 8. 404 checks for nonexistent IDs
    assert (await async_client.get("/api/v1/datasets/vid_missing_999")).status_code == 404
    assert (
        await async_client.patch("/api/v1/datasets/vid_missing_999", json={"title": "Nope"})
    ).status_code == 404
    assert (await async_client.get("/api/v1/projects/missing-proj/folders")).status_code == 404
