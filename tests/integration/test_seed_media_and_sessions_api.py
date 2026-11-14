"""Layer 2 Integration Tests: Health, Auth Token Broker, Presets, Seed Media & Sessions API."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import httpx
from PIL import Image
import pytest

from app.adapters.orbis import LiveReactorOrbisAdapter
from app.models.schemas import CANONICAL_MODEL_ID, DUBAI_SOURCE_DATASET
from app.services.session_manager import runtime


@pytest.mark.asyncio
async def test_health_auth_token_and_system_prompt_contracts(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    reactor_token_capture: tuple[list[dict[str, Any]], httpx.MockTransport],
) -> None:
    """T1-A1, T1-A2, T1-A6, T2-02 & T2-03: Health, JWT minting, system-prompt inspection & validation."""
    health_resp = await async_client.get("/api/v1/health")
    assert health_resp.status_code == 200
    health = health_resp.json()
    assert health["status"] == "ok"
    assert health["mode"] == "mock"
    assert health["orbis_mode"] == "mock"
    assert health["gcp_mode"] == "mock"
    assert health["model_id"] == CANONICAL_MODEL_ID
    assert health["gcs_bucket_name"] == health["gcs_bucket"]
    assert len(health["bq_dataset_id"]) > 0

    # Mock-mode JWT broker
    tok_resp = await async_client.post(
        "/api/v1/auth/reactor-token",
        json={"session_id": "sess_coattach_1", "max_sessions": 3},
    )
    assert tok_resp.status_code == 200
    tok = tok_resp.json()
    assert tok["model_id"] == CANONICAL_MODEL_ID
    assert tok["mode"] == "mock"
    assert tok["bound_session_id"] == "sess_coattach_1"
    assert tok["jwt"].count(".") == 2

    # Bare model_id must return 422
    bad_tok = await async_client.post(
        "/api/v1/auth/reactor-token",
        json={"model_id": "visko-orbis-stable"},
    )
    assert bad_tok.status_code == 422

    # Live-adapter HTTP integration check via mocked upstream /tokens transport
    captured, mock_transport = reactor_token_capture
    secret_key = "rk_live_integration_secret_do_not_expose"
    runtime.set_custom_adapters(
        orbis=LiveReactorOrbisAdapter(api_key=secret_key, http_transport=mock_transport)
    )
    live_tok_resp = await async_client.post("/api/v1/auth/reactor-token", json={})
    assert live_tok_resp.status_code == 200
    assert live_tok_resp.json()["mode"] == "live"
    assert secret_key not in live_tok_resp.text
    assert len(captured) == 1
    assert captured[0]["json"]["authorization_details"][0]["resources"]["models"]["match"] == [
        CANONICAL_MODEL_ID
    ]
    runtime.set_custom_adapters(orbis=None)

    # System prompt inspection & env override
    sys_resp = await async_client.get("/api/v1/sessions/system-prompt")
    assert sys_resp.status_code == 200
    sys_data = sys_resp.json()
    assert sys_data["model_id"] == CANONICAL_MODEL_ID
    assert sys_data["passthrough"] is True
    assert set(sys_data["supported_camera_modes"]) == {
        "forward_downward_oblique",
        "nadir_downward",
        "forward_fpv",
    }
    assert sys_data["custom_override_active"] is False

    monkeypatch.setenv("ORBIS_AERIAL_SYSTEM_PROMPT", "Override downward 45 deg gimbal")
    override_resp = await async_client.get("/api/v1/sessions/system-prompt?camera_mode=nadir_downward")
    assert override_resp.status_code == 200
    assert override_resp.json()["custom_override_active"] is True

    invalid_cam_resp = await async_client.get("/api/v1/sessions/system-prompt?camera_mode=side_view")
    assert invalid_cam_resp.status_code == 422


@pytest.mark.asyncio
async def test_dubai_presets_and_custom_seed_image_video_uploads(
    async_client: httpx.AsyncClient,
    alpine_seed_bytes: bytes,
    sample_clip_bytes: bytes,
) -> None:
    """T1-B1..B5 & T2-06: Presets, PNG/MP4 seed normalization to 832x480, storage persistence & negative checks."""
    presets_resp = await async_client.get("/api/v1/media/presets?limit=6&offset=0")
    assert presets_resp.status_code == 200
    catalog = presets_resp.json()
    assert catalog["dataset"] == DUBAI_SOURCE_DATASET
    assert catalog["source_dataset"] == DUBAI_SOURCE_DATASET
    assert len(catalog["presets"]) == 6
    first_preset = catalog["presets"][0]
    assert first_preset["recommended_camera_mode"] in (
        "forward_downward_oblique",
        "nadir_downward",
        "forward_fpv",
    )

    # Create seed from Dubai 256x256 preset
    from_preset_resp = await async_client.post(
        "/api/v1/media/seed/from-preset",
        json={"preset_id": first_preset["preset_id"], "project_id": "default-uav-project"},
    )
    assert from_preset_resp.status_code == 201
    preset_seed = from_preset_resp.json()
    assert preset_seed["width"] == 832
    assert preset_seed["height"] == 480
    assert preset_seed["aspect_ratio"] == "16:9"
    assert preset_seed["seed_media_gcs_uri"] == preset_seed["gcs_uri"]
    assert preset_seed["seed_media_gcs_uri"].startswith("gs://")
    assert runtime.storage.exists(preset_seed["seed_media_gcs_uri"])

    unknown_preset_resp = await async_client.post(
        "/api/v1/media/seed/from-preset",
        json={"preset_id": "nonexistent-dubai-tile"},
    )
    assert unknown_preset_resp.status_code == 404

    # Custom PNG seed upload
    png_resp = await async_client.post(
        "/api/v1/media/seed",
        files={"file": ("sample_alpine_seed.png", alpine_seed_bytes, "image/png")},
        data={"project_id": "default-uav-project"},
    )
    assert png_resp.status_code in (200, 201)
    png_seed = png_resp.json()
    assert png_seed["media_kind"] == "image"
    assert png_seed["width"] == 832
    assert png_seed["height"] == 480
    assert "/seeds/" in png_seed["seed_media_gcs_uri"]
    assert runtime.storage.exists(png_seed["seed_media_gcs_uri"])

    # Verify binary /preview image dimensions
    preview_resp = await async_client.get(png_seed["preview_url"])
    assert preview_resp.status_code == 200
    assert preview_resp.headers["content-type"].startswith("image/")
    with Image.open(BytesIO(preview_resp.content)) as im:
        assert im.size == (832, 480)

    # Custom MP4 video seed upload -> keyframe extracted via ffmpeg & normalized to 832x480
    mp4_resp = await async_client.post(
        "/api/v1/media/seed",
        files={"file": ("sample_clip.mp4", sample_clip_bytes, "video/mp4")},
        data={"project_id": "default-uav-project"},
    )
    assert mp4_resp.status_code in (200, 201)
    mp4_seed = mp4_resp.json()
    assert mp4_seed["media_kind"] == "video"
    assert mp4_seed["width"] == 832
    assert mp4_seed["height"] == 480

    # Unsupported file types & empty payload rejected with 422
    bad_txt = await async_client.post(
        "/api/v1/media/seed",
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )
    assert bad_txt.status_code == 422

    empty_img = await async_client.post(
        "/api/v1/media/seed",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert empty_img.status_code == 422

    missing_preview = await async_client.get("/api/v1/media/seed/seed_does_not_exist/preview")
    assert missing_preview.status_code == 404


@pytest.mark.asyncio
async def test_session_lifecycle_seed_reanchoring_and_teardown(
    async_client: httpx.AsyncClient,
    alpine_seed_bytes: bytes,
    coastal_seed_bytes: bytes,
) -> None:
    """T1-B6 & T2-09: Full session lifecycle (POST /sessions, GET, POST .../seed reanchor, DELETE)."""
    seed1_resp = await async_client.post(
        "/api/v1/media/seed",
        files={"file": ("alpine.png", alpine_seed_bytes, "image/png")},
    )
    seed1 = seed1_resp.json()

    seed2_resp = await async_client.post(
        "/api/v1/media/seed",
        files={"file": ("coastal.jpg", coastal_seed_bytes, "image/jpeg")},
    )
    seed2 = seed2_resp.json()

    create_resp = await async_client.post(
        "/api/v1/sessions",
        json={
            "project_id": "default-uav-project",
            "folder_id": "alpine-trials",
            "ecosystem_type": "alpine",
            "camera_mode": "forward_downward_oblique",
            "seed_id": seed1["seed_id"],
            "initial_prompt": "Snowy alpine granite ridge with pine valley below",
        },
    )
    assert create_resp.status_code in (200, 201)
    sess = create_resp.json()
    session_id = sess["session_id"]
    assert sess["model_id"] == CANONICAL_MODEL_ID
    assert sess["mode"] == "mock"
    assert sess["passthrough"] is True
    assert sess["seed_id"] == seed1["seed_id"]
    assert sess["seed_media_gcs_uri"] == seed1["seed_media_gcs_uri"]
    assert sess["ws_url"] == f"/ws/orbis/stream/{session_id}"
    assert len(sess["reactor_jwt"]) > 20
    assert sess["initial_telemetry"]["ecosystem_type"] == "alpine"
    assert sess["initial_telemetry"]["air_pressure_hpa"] < 880.0
    assert len(sess["prompt_history"]) == 1

    # Inspect active session
    get_resp = await async_client.get(f"/api/v1/sessions/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["session_id"] == session_id

    # Mid-session seed re-anchoring (strict sequential reset -> upload_file -> set_image -> set_prompt -> start)
    reanchor_resp = await async_client.post(
        f"/api/v1/sessions/{session_id}/seed",
        json={
            "seed_id": seed2["seed_id"],
            "prompt": "Transition over turquoise coastal cliffs with onshore whitecaps",
        },
    )
    assert reanchor_resp.status_code == 200
    reanchored = reanchor_resp.json()
    assert reanchored["command_sequence"] == [
        "reset",
        "upload_file",
        "set_image",
        "set_prompt",
        "start",
    ]
    assert reanchored["passthrough"] is True
    assert reanchored["seed_media_gcs_uri"] == seed2["seed_media_gcs_uri"]

    # Reject invalid model_id or camera_mode on session creation
    bad_model_sess = await async_client.post(
        "/api/v1/sessions",
        json={"model_id": "visko-orbis-stable"},
    )
    assert bad_model_sess.status_code == 422

    bad_cam_sess = await async_client.post(
        "/api/v1/sessions",
        json={"camera_mode": "orbit_360"},
    )
    assert bad_cam_sess.status_code == 422

    # Close session cleanly and confirm subsequent GET returns 404
    del_resp = await async_client.delete(f"/api/v1/sessions/{session_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] in ("closed", "disconnected")

    after_close = await async_client.get(f"/api/v1/sessions/{session_id}")
    assert after_close.status_code == 404

    missing_sess = await async_client.get("/api/v1/sessions/sess_nonexistent_999")
    assert missing_sess.status_code == 404
