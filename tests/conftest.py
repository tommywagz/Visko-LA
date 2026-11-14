"""Shared pytest harness, isolated temporary storage/SQLite/mock env, and ASGI fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import httpx
from PIL import Image, ImageDraw
import pytest
import pytest_asyncio
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402
from app.services.seed_normalizer import find_ffmpeg_binary  # noqa: E402
from app.services.session_manager import runtime  # noqa: E402


def ensure_deterministic_fixtures() -> Path:
    """Programmatically create tests/fixtures/{sample_alpine_seed.png,sample_coastal_seed.jpg,sample_clip.mp4} if absent."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    alpine_path = FIXTURES_DIR / "sample_alpine_seed.png"
    if not alpine_path.is_file() or alpine_path.stat().st_size == 0:
        alpine = Image.new("RGB", (832, 480), (42, 64, 96))
        draw_a = ImageDraw.Draw(alpine)
        draw_a.polygon(
            [(0, 480), (0, 220), (260, 130), (540, 210), (832, 110), (832, 480)],
            fill=(78, 86, 98),
        )
        draw_a.polygon(
            [(0, 480), (180, 310), (450, 360), (832, 260), (832, 480)],
            fill=(46, 84, 58),
        )
        draw_a.line([(360, 480), (410, 360), (470, 280)], fill=(120, 198, 228), width=14)
        alpine.save(alpine_path, format="PNG", optimize=True)

    coastal_path = FIXTURES_DIR / "sample_coastal_seed.jpg"
    if not coastal_path.is_file() or coastal_path.stat().st_size == 0:
        coastal = Image.new("RGB", (832, 480), (18, 118, 152))
        draw_c = ImageDraw.Draw(coastal)
        draw_c.polygon(
            [(0, 480), (0, 280), (420, 340), (832, 220), (832, 480)],
            fill=(214, 192, 152),
        )
        draw_c.line([(0, 280), (420, 340), (832, 220)], fill=(242, 248, 252), width=10)
        coastal.save(coastal_path, format="JPEG", quality=90)

    clip_path = FIXTURES_DIR / "sample_clip.mp4"
    if not clip_path.is_file() or clip_path.stat().st_size == 0:
        ffmpeg_bin = find_ffmpeg_binary() or "/opt/homebrew/bin/ffmpeg"
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x1e293b:s=320x180:r=18:d=5,drawgrid=w=64:h=45:t=2:c=0x38bdf8@0.5",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(clip_path),
            ],
            check=True,
            capture_output=True,
        )

    return FIXTURES_DIR


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return ensure_deterministic_fixtures()


@pytest.fixture(scope="session")
def alpine_seed_bytes(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "sample_alpine_seed.png").read_bytes()


@pytest.fixture(scope="session")
def coastal_seed_bytes(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "sample_coastal_seed.jpg").read_bytes()


@pytest.fixture(scope="session")
def sample_clip_bytes(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "sample_clip.mp4").read_bytes()


@pytest.fixture(autouse=True)
def isolated_test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Give every test its own temporary LOCAL_STORAGE_DIR, SQLite catalog, and mock adapters."""
    storage_dir = tmp_path / "visko_local_storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("ORBIS_MOCK_MODE", "true")
    monkeypatch.setenv("GCP_MOCK_MODE", "true")
    monkeypatch.setenv("GCS_BUCKET_NAME", "visko-orbis-aerial-datasets")
    monkeypatch.setenv("BQ_DATASET_ID", "visko_aerial_telemetry")
    monkeypatch.delenv("REACTOR_API_KEY", raising=False)
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("ORBIS_AERIAL_SYSTEM_PROMPT", raising=False)

    runtime.set_custom_adapters(orbis=None, storage=None, catalog=None)
    runtime._seeds.clear()
    runtime._sessions.clear()
    runtime._settings_key = None
    runtime.ensure_initialized()

    yield storage_dir

    for sess in list(runtime._sessions.values()):
        sess.closed = True
    runtime.set_custom_adapters(orbis=None, storage=None, catalog=None)
    runtime._seeds.clear()
    runtime._sessions.clear()
    runtime._settings_key = None


@pytest.fixture
def reactor_token_capture() -> tuple[list[dict[str, Any]], httpx.MockTransport]:
    """Mock httpx transport for POST https://api.reactor.inc/tokens recording outbound payloads."""
    captured_requests: list[dict[str, Any]] = []

    async def _handler(request: httpx.Request) -> httpx.Response:
        body_json = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured_requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
                "json": body_json,
            }
        )
        if request.method == "POST" and request.url.path == "/tokens":
            return httpx.Response(
                200,
                json={
                    "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJyZWFjdG9yLmxpdmUifQ.sig_ok",
                    "expires_at": int(time.time()) + 3600,
                },
            )
        if request.method == "DELETE" and request.url.path.startswith("/sessions/"):
            return httpx.Response(200, json={"status": "deleted"})
        return httpx.Response(404, json={"detail": "Not found"})

    return captured_requests, httpx.MockTransport(_handler)


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    """Real FastAPI ASGI client running against isolated temporary mock storage."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def ws_test_client() -> Iterator[TestClient]:
    """Starlette TestClient for synchronous WebSocket + HTTP multi-channel integration tests."""
    with TestClient(app) as client:
        yield client
