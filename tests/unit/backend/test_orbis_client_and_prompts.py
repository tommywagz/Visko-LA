"""Layer 1A Unit Tests: Reactor Orbis Protocol, JWT Scoping, Prompt Compiler & Seed Normalization."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
from typing import Any

import httpx
from PIL import Image, ImageDraw
from pydantic import ValidationError
import pytest

from app.adapters.orbis import (
    LiveReactorOrbisAdapter,
    MockReactorOrbisAdapter,
    build_reactor_token_request_payload,
)
from app.models.schemas import (
    CANONICAL_MODEL_ID,
    DUBAI_SOURCE_DATASET,
    CreateSessionRequest,
    ReactorTokenRequest,
    validate_model_slug,
)
from app.services.clip_recorder import verify_mp4_ftyp_signature
from app.services.prompt_compiler import (
    STEERING_ANCHOR_PREFIX,
    AerialSystemPromptCompiler,
    rewrite_negations,
    validate_camera_mode,
)
from app.services.seed_normalizer import (
    CURATED_DUBAI_PRESETS,
    DubaiPresetService,
    SeedValidationError,
    center_crop_16x9_box,
    find_ffmpeg_binary,
    normalize_image_bytes_to_832x480,
    validate_and_normalize_seed_upload,
)


def test_canonical_model_slug_enforced_and_bare_slug_rejected() -> None:
    """T2-02: Enforce 'reactor/visko-orbis-stable' and reject bare 'visko-orbis-stable'."""
    assert CANONICAL_MODEL_ID == "reactor/visko-orbis-stable"
    assert validate_model_slug("reactor/visko-orbis-stable") == "reactor/visko-orbis-stable"

    for invalid_slug in (
        "visko-orbis-stable",
        "visko-orbis-dynamic",
        "reactor/other-model",
        "",
        "   ",
        123,
    ):
        with pytest.raises(ValueError, match="reactor/visko-orbis-stable"):
            validate_model_slug(invalid_slug)

    with pytest.raises(ValidationError):
        ReactorTokenRequest(model_id="visko-orbis-stable")

    with pytest.raises(ValidationError):
        CreateSessionRequest(model_id="visko-orbis-stable")


@pytest.mark.asyncio
async def test_live_jwt_minting_unbound_and_bound_scoping_without_secret_leak(
    reactor_token_capture: tuple[list[dict[str, Any]], httpx.MockTransport],
) -> None:
    """T1-A2 & T1-A3: Verify POST /tokens authorization_details scoping and zero REACTOR_API_KEY leak."""
    captured_requests, mock_transport = reactor_token_capture
    fake_secret = "rk_live_ultra_secret_do_not_leak_987654"

    adapter = LiveReactorOrbisAdapter(
        api_key=fake_secret,
        api_url="https://api.reactor.inc",
        model_slug="reactor/visko-orbis-stable",
        http_transport=mock_transport,
    )

    # 1. Unbound session-scoped JWT
    unbound_resp = await adapter.mint_jwt(max_sessions=5, expires_after=3600)
    assert unbound_resp.mode == "live"
    assert unbound_resp.model_id == "reactor/visko-orbis-stable"
    assert unbound_resp.bound_session_id is None
    assert unbound_resp.jwt.startswith("eyJ")
    assert fake_secret not in unbound_resp.model_dump_json()

    assert len(captured_requests) == 1
    req1 = captured_requests[0]
    assert req1["method"] == "POST"
    assert req1["url"] == "https://api.reactor.inc/tokens"
    assert req1["headers"].get("reactor-api-key") == fake_secret
    auth_details_1 = req1["json"]["authorization_details"]
    assert len(auth_details_1) == 1
    assert auth_details_1[0]["type"] == "session"
    assert auth_details_1[0]["resources"] == {"models": {"match": ["reactor/visko-orbis-stable"]}}
    assert auth_details_1[0]["constraints"]["max_sessions"] == 5
    assert auth_details_1[0]["constraints"]["max_session_duration_seconds"] == 3600

    # 2. Session-bound JWT (co-attaching browser WebRTC to existing backend session)
    bound_resp = await adapter.mint_jwt(
        session_id_to_bind="sess_orbis_42",
        max_sessions=1,
        expires_after=1800,
    )
    assert bound_resp.bound_session_id == "sess_orbis_42"
    assert fake_secret not in bound_resp.model_dump_json()

    req2 = captured_requests[1]
    auth_details_2 = req2["json"]["authorization_details"][0]
    assert auth_details_2["resources"]["models"]["match"] == ["reactor/visko-orbis-stable"]
    assert auth_details_2["resources"]["sessions"] == {"bind": ["sess_orbis_42"]}
    assert auth_details_2["constraints"]["max_sessions"] >= 1


@pytest.mark.asyncio
async def test_live_jwt_guard_rejects_upstream_echoing_api_key() -> None:
    """Ensure LiveReactorOrbisAdapter refuses to return a token if upstream echoes REACTOR_API_KEY."""
    secret = "rk_accidental_echo_key_123"

    async def _bad_upstream(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jwt": f"prefix_{secret}_suffix", "expires_at": 1999999999})

    adapter = LiveReactorOrbisAdapter(
        api_key=secret,
        http_transport=httpx.MockTransport(_bad_upstream),
    )
    with pytest.raises(RuntimeError, match="invalid JWT"):
        await adapter.mint_jwt()


@pytest.mark.asyncio
async def test_mock_orbis_adapter_jwt_and_command_ordering() -> None:
    """Verify MockReactorOrbisAdapter enforces model slug, JWT claims, and sequential reanchor order."""
    mock_adapter = MockReactorOrbisAdapter()
    tok = await mock_adapter.mint_jwt(session_id_to_bind="sess_bind_99")
    assert tok.mode == "mock"
    assert tok.model_id == "reactor/visko-orbis-stable"
    assert len(tok.jwt.split(".")) == 3

    drv = await mock_adapter.start_session(
        compiled_initial_prompt="Stabilized nose-mounted UAV camera cruising forward.",
        seed_image_bytes=b"fake_jpeg_seed_bytes",
    )
    cmds = [entry["command"] for entry in drv.command_log]
    assert cmds == [
        "set_resolution",
        "set_audio_enabled",
        "upload_file",
        "set_image",
        "set_prompt",
        "start",
    ]
    set_prompt_entry = next(e for e in drv.command_log if e["command"] == "set_prompt")
    assert set_prompt_entry["payload"]["passthrough"] is True

    steer_seq = await mock_adapter.steer_prompt(
        drv.reactor_session_id,
        "Maintaining continuous forward-and-downward UAV aerial flight along the same trajectory, heavy mist.",
    )
    assert steer_seq == ["set_prompt"]

    reanchor_seq = await mock_adapter.reanchor_seed(
        drv.reactor_session_id,
        seed_image_bytes=b"updated_seed_bytes",
        compiled_prompt="Stabilized nadir camera over coastal pier.",
    )
    assert reanchor_seq == ["reset", "upload_file", "set_image", "set_prompt", "start"]


@pytest.mark.asyncio
async def test_live_orbis_adapter_sdk_sequence_and_mpegts_remux(
    reactor_token_capture: tuple[list[dict[str, Any]], httpx.MockTransport],
) -> None:
    """Verify LiveReactorOrbisAdapter sequences SDK calls and remuxes MPEG-TS capture into ISO BMFF MP4."""
    captured_requests, mock_transport = reactor_token_capture
    sdk_events: list[tuple[str, Any]] = []

    class FakeClipRef:
        session_id = "orbis_live_sdk_01"

    class FakeReactorSDK:
        def __init__(self, *, model_name: str, api_key: str) -> None:
            assert model_name == "reactor/visko-orbis-stable"
            assert api_key == "rk_test_sdk_key"
            self.session_id = "orbis_live_sdk_01"

        async def connect(self) -> None:
            sdk_events.append(("connect", {}))

        async def upload_file(self, data: bytes, *, name: str, mime_type: str) -> dict[str, str]:
            sdk_events.append(("upload_file", {"name": name, "mime_type": mime_type, "len": len(data)}))
            return {"file_id": "f_live_1", "name": name}

        async def send_command(self, cmd: str, payload: dict[str, Any]) -> None:
            sdk_events.append((cmd, payload))

        async def request_clip(self, duration_sec: float) -> FakeClipRef:
            sdk_events.append(("request_clip", duration_sec))
            return FakeClipRef()

        async def disconnect(self) -> None:
            sdk_events.append(("disconnect", {}))

    async def _fake_download_clip(_clip: Any, ts_path: Path) -> None:
        ffmpeg_bin = find_ffmpeg_binary() or "/opt/homebrew/bin/ffmpeg"
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x0e7490:s=320x180:r=18:d=5",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-f",
                "mpegts",
                str(ts_path),
            ],
            check=True,
            capture_output=True,
        )

    adapter = LiveReactorOrbisAdapter(
        api_key="rk_test_sdk_key",
        http_transport=mock_transport,
        reactor_factory=lambda **kw: FakeReactorSDK(**kw),
        download_clip_fn=_fake_download_clip,
    )

    drv = await adapter.start_session(
        compiled_initial_prompt="Opening UAV flight over alpine pass.",
        seed_image_bytes=b"1234567890",
    )
    assert [e[0] for e in sdk_events] == [
        "connect",
        "set_resolution",
        "set_audio_enabled",
        "upload_file",
        "set_image",
        "set_prompt",
        "start",
    ]
    assert sdk_events[5][1]["passthrough"] is True

    sdk_events.clear()
    await adapter.steer_prompt(drv.reactor_session_id, "Incremental crosswind delta.")
    assert sdk_events == [("set_prompt", {"prompt": "Incremental crosswind delta.", "passthrough": True})]

    sdk_events.clear()
    seq = await adapter.reanchor_seed(
        drv.reactor_session_id,
        seed_image_bytes=b"new_seed_jpeg",
        compiled_prompt="Reanchored coastal headland flight.",
    )
    assert seq == ["reset", "upload_file", "set_image", "set_prompt", "start"]
    assert [e[0] for e in sdk_events] == ["reset", "upload_file", "set_image", "set_prompt", "start"]

    mp4_bytes = await adapter.capture_clip_mp4(drv.reactor_session_id, 5, ecosystem_type="coastal")
    assert verify_mp4_ftyp_signature(mp4_bytes)

    await adapter.close_session(drv.reactor_session_id)
    assert any(r["method"] == "DELETE" and r["url"].endswith("/sessions/orbis_live_sdk_01") for r in captured_requests)


def test_aerial_system_prompt_compiler_three_modes_word_limit_and_passthrough() -> None:
    """T1-A4: Verify forward_downward_oblique, nadir_downward, forward_fpv, <= 95 words, passthrough=True."""
    compiler = AerialSystemPromptCompiler()

    oblique = compiler.compile_initial_prompt(
        "Snowy granite peaks and valley pine forest",
        camera_mode="forward_downward_oblique",
        ecosystem_type="alpine",
        drone_altitude_agl_m=55.0,
    )
    nadir = compiler.compile_initial_prompt(
        "Coastal harbour piers and turquoise water",
        camera_mode="nadir_downward",
        ecosystem_type="coastal",
        drone_altitude_agl_m=80.0,
    )
    fpv = compiler.compile_initial_prompt(
        "Narrow canyon corridor with wind-swept shrubs",
        camera_mode="forward_fpv",
        ecosystem_type="arid_desert",
        drone_altitude_agl_m=30.0,
    )

    assert "35 degrees downward" in oblique
    assert "straight downward" in nadir and "-90 degrees" in nadir
    assert "15 degrees downward" in fpv

    for compiled in (oblique, nadir, fpv):
        assert len(compiled.split()) <= 95
        payload = compiler.build_set_prompt_payload(compiled)
        assert payload == {"prompt": compiled, "passthrough": True}

    # Stress word limit with an overly verbose user prompt
    long_user_input = " ".join(["windswept alpine granite valley ridge"] * 30)
    capped = compiler.compile_initial_prompt(long_user_input, camera_mode="forward_downward_oblique")
    assert len(capped.split()) <= 95

    for invalid_cam in ("side_view", "orbit_360", "rear_chase"):
        with pytest.raises(ValueError, match="Unsupported camera_mode"):
            validate_camera_mode(invalid_cam)


def test_prompt_negation_rewrites_and_steering_camera_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T1-A5, T1-A6 & T2-04: Rewrite negations to positive physical descriptions and lock steering trajectory."""
    raw_negated = "Fly above highway with no people, no clouds, no trees, and no drone props"
    rewritten = rewrite_negations(raw_negated)

    assert "empty open roadways" in rewritten
    assert "clear sunlit sky" in rewritten
    assert "barren rocky tundra" in rewritten
    assert "unobstructed wide-angle lens view" in rewritten
    assert re.search(r"\bno\s+\w+", rewritten, flags=re.I) is None

    compiler = AerialSystemPromptCompiler()
    steered = compiler.compile_steering_prompt(
        "Increase crosswind gusts to 20 m/s with no people and no fog",
        camera_mode="forward_downward_oblique",
    )
    assert steered.startswith(STEERING_ANCHOR_PREFIX)
    assert "20 m/s" in steered
    assert "empty open roadways" in steered
    assert "crisp high-visibility air" in steered
    # Must NOT restate the full opening camera template
    assert "Stabilized nose-mounted autonomous UAV perception camera pitched 35 degrees" not in steered
    assert re.search(r"\bno\s+\w+", steered, flags=re.I) is None

    with pytest.raises(ValueError, match="empty"):
        compiler.compile_steering_prompt("   ")

    # Environment override check (T1-A6)
    monkeypatch.setenv(
        "ORBIS_AERIAL_SYSTEM_PROMPT",
        "Custom calibrated UAV perception rig pitched 40 degrees downward",
    )
    override_compiler = AerialSystemPromptCompiler()
    meta = override_compiler.get_system_prompt_metadata("forward_downward_oblique")
    assert meta.custom_override_active is True
    assert meta.passthrough is True
    assert "Custom calibrated UAV perception rig" in (meta.active_override or "")
    compiled_override = override_compiler.compile_initial_prompt("Rocky valley")
    assert "Custom calibrated UAV perception rig" in compiled_override


@pytest.mark.asyncio
async def test_dubai_256x256_center_crop_to_832x480_without_aspect_distortion(
    tmp_path: Path,
) -> None:
    """T1-B1, T1-B2 & T2-05: Center-crop non-16:9 seeds (256x256, 1:2, 4:1) to 832x480 without stretch."""
    # 1. Exact crop box for 256x256 -> 256x144 centered vertically
    assert center_crop_16x9_box(256, 256) == (0, 56, 256, 200)
    crop_l, crop_t, crop_r, crop_b = center_crop_16x9_box(256, 256)
    assert (crop_r - crop_l, crop_b - crop_t) == (256, 144)

    # 2. Geometric circle distortion test: draw a bright white square 64x64 at center of 256x256 black tile.
    # If stretched 1:1 -> 16:9 without cropping, horizontal span would become 1.777x vertical span!
    # With true 16:9 center-crop (256x144) -> 832x480 (scale 3.25x horizontal, 3.333x vertical),
    # the square stays ~1:1 in pixel width vs height!
    marker_img = Image.new("RGB", (256, 256), (0, 0, 0))
    draw = ImageDraw.Draw(marker_img)
    draw.rectangle([96, 96, 159, 159], fill=(255, 255, 255))
    raw_buf = BytesIO()
    marker_img.save(raw_buf, format="PNG")

    norm_bytes = normalize_image_bytes_to_832x480(raw_buf.getvalue(), output_format="PNG")
    with Image.open(BytesIO(norm_bytes)) as out_im:
        assert out_im.size == (832, 480)
        gray = out_im.convert("L")
        bbox = gray.point(lambda p: 255 if p > 128 else 0).getbbox()
        assert bbox is not None
        box_w = bbox[2] - bbox[0]
        box_h = bbox[3] - bbox[1]
        aspect_ratio_of_square = box_w / box_h
        assert 0.92 <= aspect_ratio_of_square <= 1.08, (
            f"Square marker was stretched! Expected ~1.0 aspect, got {aspect_ratio_of_square:.3f}"
        )

    # 3. Portrait (400x800 1:2) and Ultra-wide (1200x300 4:1)
    for src_size in ((400, 800), (1200, 300)):
        im = Image.new("RGB", src_size, (30, 120, 180))
        b = BytesIO()
        im.save(b, format="JPEG")
        normalized_b, _, kind = validate_and_normalize_seed_upload(
            filename="custom_aspect.jpg",
            content_type="image/jpeg",
            raw_bytes=b.getvalue(),
        )
        assert kind == "image"
        with Image.open(BytesIO(normalized_b)) as checked:
            assert checked.size == (832, 480)

    # 4. Reject invalid extension or empty bytes
    with pytest.raises(SeedValidationError):
        validate_and_normalize_seed_upload(
            filename="malicious.exe",
            content_type="application/octet-stream",
            raw_bytes=b"MZ_bad_payload",
        )
    with pytest.raises(SeedValidationError):
        validate_and_normalize_seed_upload(
            filename="empty.png",
            content_type="image/png",
            raw_bytes=b"",
        )

    # 5. DubaiPresetService offline deterministic mode
    preset_svc = DubaiPresetService(tmp_path / "dubai_offline", allow_network_fetch=False)
    catalog = preset_svc.list_presets(limit=12, offset=0)
    assert catalog.dataset == DUBAI_SOURCE_DATASET
    assert catalog.source_dataset == DUBAI_SOURCE_DATASET
    assert len(catalog.presets) == len(CURATED_DUBAI_PRESETS)
    first_spec = preset_svc.get_preset_spec("dubai-tile-00")
    assert first_spec is not None
    raw_256 = await preset_svc.get_raw_256_tile_bytes(first_spec)
    with Image.open(BytesIO(raw_256)) as raw_im:
        assert raw_im.size == (256, 256)
    norm_preset = await preset_svc.get_normalized_832x480_preset_bytes(first_spec)
    with Image.open(BytesIO(norm_preset)) as norm_im:
        assert norm_im.size == (832, 480)
