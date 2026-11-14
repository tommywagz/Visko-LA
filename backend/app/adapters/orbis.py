"""Reactor Platform & Visko Orbis Stable Dual-Mode Adapter (Live SDK + Deterministic Mock)."""

from __future__ import annotations

from abc import ABC, abstractmethod
import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import time
from typing import Any, Callable
import uuid

import httpx

from app.models.schemas import (
    CANONICAL_MODEL_ID,
    AdapterMode,
    ReactorTokenResponse,
    ResolutionOption,
    SessionStatus,
    validate_model_slug,
    validate_strict_duration,
)
from app.services.clip_recorder import remux_mpegts_to_mp4, synthesize_mock_orbis_mp4

ORBIS_CHUNK_DURATION_SECONDS = 1.833
ORBIS_FPS = 18
ORBIS_FRAMES_PER_CHUNK = 33


def build_reactor_token_request_payload(
    *,
    session_id_to_bind: str | None = None,
    max_sessions: int = 5,
    expires_after: int = 3600,
    model_id: str = CANONICAL_MODEL_ID,
) -> dict[str, Any]:
    """Construct the exact Reactor POST /tokens request body per SKILL.md §2."""
    validate_model_slug(model_id)
    resources: dict[str, Any] = {
        "models": {"match": [CANONICAL_MODEL_ID]},
    }
    effective_max_sessions = int(max_sessions)
    if session_id_to_bind:
        resources["sessions"] = {"bind": [session_id_to_bind]}
        effective_max_sessions = max(effective_max_sessions, 1)

    return {
        "expires_after": int(expires_after),
        "authorization_details": [
            {
                "type": "session",
                "resources": resources,
                "constraints": {
                    "max_sessions": effective_max_sessions,
                    "max_session_duration_seconds": 3600,
                },
            }
        ],
    }


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _mint_deterministic_mock_jwt(
    *,
    bound_session_id: str | None,
    expires_at: int,
    max_sessions: int = 5,
) -> str:
    """Create a realistic local session-scoped JWT without ever touching or embedding REACTOR_API_KEY."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims_dict: dict[str, Any] = {
        "iss": "visko-orbis-mock-broker",
        "sub": f"orbis_client_{uuid.uuid4().hex[:8]}",
        "iat": int(time.time()),
        "exp": int(expires_at),
        "model_id": CANONICAL_MODEL_ID,
        "mode": "mock",
        "max_sessions": max_sessions,
    }
    if bound_session_id:
        claims_dict["bound_session_id"] = bound_session_id
        claims_dict["sessions_bind"] = [bound_session_id]
    claims = _b64url(json.dumps(claims_dict, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode("ascii")
    # Static local-only mock signing key (distinct from REACTOR_API_KEY)
    sig = _b64url(hmac.new(b"visko-local-mock-jwt-key", signing_input, hashlib.sha256).digest())
    return f"{header}.{claims}.{sig}"


@dataclass
class OrbisDriverSession:
    """Internal per-session transport handle tracked by an Orbis adapter."""

    reactor_session_id: str
    mode: AdapterMode
    status: SessionStatus = "waiting"
    resolution: ResolutionOption = "1080p"
    active_prompt: str = ""
    has_seed_image: bool = False
    started_monotonic: float = field(default_factory=time.monotonic)
    command_log: list[dict[str, Any]] = field(default_factory=list)
    sdk_handle: Any = None

    @property
    def chunk_index(self) -> int:
        if self.status in ("waiting", "closed"):
            return 0
        elapsed = max(0.0, time.monotonic() - self.started_monotonic)
        return int(elapsed // ORBIS_CHUNK_DURATION_SECONDS)

    @property
    def effective_status(self) -> SessionStatus:
        if self.status in ("paused", "closed", "waiting", "reanchoring"):
            return self.status
        # Chunk 0 emits 0 frames (warm-up priming); visible frames start at chunk >= 1
        return "priming" if self.chunk_index == 0 else "generating"


class ReactorOrbisAdapter(ABC):
    """Abstract adapter interface for Reactor Platform & Visko Orbis Stable."""

    mode: AdapterMode

    @abstractmethod
    async def mint_jwt(
        self,
        *,
        session_id_to_bind: str | None = None,
        max_sessions: int = 5,
        expires_after: int = 3600,
        model_id: str = CANONICAL_MODEL_ID,
    ) -> ReactorTokenResponse:
        """Mint a session-scoped Reactor JWT without exposing REACTOR_API_KEY."""

    @abstractmethod
    async def start_session(
        self,
        *,
        compiled_initial_prompt: str,
        resolution: ResolutionOption = "1080p",
        seed_image_bytes: bytes | None = None,
        seed_filename: str = "seed_16x9.jpg",
        model_id: str = CANONICAL_MODEL_ID,
    ) -> OrbisDriverSession:
        """Open an Orbis session and run sequential initial prompt (+ optional seed I2V) commands."""

    @abstractmethod
    async def steer_prompt(
        self,
        reactor_session_id: str,
        compiled_steering_prompt: str,
    ) -> list[str]:
        """Hot-swap prompt mid-stream via set_prompt(passthrough=True) WITHOUT reset or start."""

    @abstractmethod
    async def reanchor_seed(
        self,
        reactor_session_id: str,
        *,
        seed_image_bytes: bytes,
        compiled_prompt: str,
        seed_filename: str = "seed_16x9.jpg",
    ) -> list[str]:
        """Re-anchor active session strictly awaiting reset -> upload_file -> set_image -> set_prompt -> start."""

    @abstractmethod
    async def capture_clip_mp4(
        self,
        reactor_session_id: str,
        duration_seconds: int,
        *,
        ecosystem_type: str = "alpine",
    ) -> bytes:
        """Capture exact 5s, 10s, or 15s clip and return valid ISO BMFF MP4 bytes."""

    @abstractmethod
    async def close_session(self, reactor_session_id: str) -> None:
        """Disconnect Reactor session cleanly."""

    @abstractmethod
    def get_driver_session(self, reactor_session_id: str) -> OrbisDriverSession | None:
        """Inspect active transport session state."""


class MockReactorOrbisAdapter(ReactorOrbisAdapter):
    """Deterministic offline simulator for reactor/visko-orbis-stable."""

    mode: AdapterMode = "mock"

    def __init__(self) -> None:
        self._sessions: dict[str, OrbisDriverSession] = {}

    async def mint_jwt(
        self,
        *,
        session_id_to_bind: str | None = None,
        max_sessions: int = 5,
        expires_after: int = 3600,
        model_id: str = CANONICAL_MODEL_ID,
    ) -> ReactorTokenResponse:
        # Validate canonical model slug & payload shape identically to live mode
        build_reactor_token_request_payload(
            session_id_to_bind=session_id_to_bind,
            max_sessions=max_sessions,
            expires_after=expires_after,
            model_id=model_id,
        )
        expires_at = int(time.time()) + int(expires_after)
        jwt_token = _mint_deterministic_mock_jwt(
            bound_session_id=session_id_to_bind,
            expires_at=expires_at,
            max_sessions=max_sessions,
        )
        return ReactorTokenResponse(
            jwt=jwt_token,
            expires_at=expires_at,
            model_id=CANONICAL_MODEL_ID,
            mode="mock",
            bound_session_id=session_id_to_bind,
        )

    async def start_session(
        self,
        *,
        compiled_initial_prompt: str,
        resolution: ResolutionOption = "1080p",
        seed_image_bytes: bytes | None = None,
        seed_filename: str = "seed_16x9.jpg",
        model_id: str = CANONICAL_MODEL_ID,
    ) -> OrbisDriverSession:
        validate_model_slug(model_id)
        reactor_session_id = f"orbis_mock_{uuid.uuid4().hex[:10]}"
        drv = OrbisDriverSession(
            reactor_session_id=reactor_session_id,
            mode="mock",
            status="waiting",
            resolution=resolution,
        )

        drv.command_log.append({"command": "set_resolution", "payload": {"resolution": resolution}})
        drv.command_log.append(
            {"command": "set_audio_enabled", "payload": {"audio_enabled": False}}
        )

        if seed_image_bytes:
            file_ref = {"file_id": f"file_{uuid.uuid4().hex[:8]}", "name": seed_filename}
            drv.command_log.append(
                {
                    "command": "upload_file",
                    "payload": {"name": seed_filename, "bytes_len": len(seed_image_bytes)},
                }
            )
            drv.command_log.append({"command": "set_image", "payload": {"image": file_ref}})
            drv.has_seed_image = True

        drv.command_log.append(
            {
                "command": "set_prompt",
                "payload": {"prompt": compiled_initial_prompt, "passthrough": True},
            }
        )
        drv.command_log.append({"command": "start", "payload": {}})

        drv.active_prompt = compiled_initial_prompt
        drv.started_monotonic = time.monotonic()
        drv.status = "priming"
        self._sessions[reactor_session_id] = drv
        return drv

    async def steer_prompt(
        self,
        reactor_session_id: str,
        compiled_steering_prompt: str,
    ) -> list[str]:
        drv = self._sessions.get(reactor_session_id)
        if drv is None or drv.status == "closed":
            raise KeyError(f"Orbis session {reactor_session_id} is not active.")
        # Hot-swap live prompt WITHOUT reset or start
        drv.command_log.append(
            {
                "command": "set_prompt",
                "payload": {"prompt": compiled_steering_prompt, "passthrough": True},
            }
        )
        drv.active_prompt = compiled_steering_prompt
        return ["set_prompt"]

    async def reanchor_seed(
        self,
        reactor_session_id: str,
        *,
        seed_image_bytes: bytes,
        compiled_prompt: str,
        seed_filename: str = "seed_16x9.jpg",
    ) -> list[str]:
        drv = self._sessions.get(reactor_session_id)
        if drv is None or drv.status == "closed":
            raise KeyError(f"Orbis session {reactor_session_id} is not active.")

        sequence: list[str] = []
        # 1. reset
        drv.status = "waiting"
        drv.command_log.append({"command": "reset", "payload": {}})
        sequence.append("reset")

        # 2. upload_file
        file_ref = {"file_id": f"file_{uuid.uuid4().hex[:8]}", "name": seed_filename}
        drv.command_log.append(
            {
                "command": "upload_file",
                "payload": {"name": seed_filename, "bytes_len": len(seed_image_bytes)},
            }
        )
        sequence.append("upload_file")

        # 3. set_image
        drv.command_log.append({"command": "set_image", "payload": {"image": file_ref}})
        drv.has_seed_image = True
        sequence.append("set_image")

        # 4. set_prompt (passthrough=True)
        drv.command_log.append(
            {
                "command": "set_prompt",
                "payload": {"prompt": compiled_prompt, "passthrough": True},
            }
        )
        drv.active_prompt = compiled_prompt
        sequence.append("set_prompt")

        # 5. start
        drv.command_log.append({"command": "start", "payload": {}})
        drv.started_monotonic = time.monotonic()
        drv.status = "priming"
        sequence.append("start")
        return sequence

    async def capture_clip_mp4(
        self,
        reactor_session_id: str,
        duration_seconds: int,
        *,
        ecosystem_type: str = "alpine",
    ) -> bytes:
        validated = validate_strict_duration(duration_seconds=duration_seconds)
        drv = self._sessions.get(reactor_session_id)
        if drv is None or drv.status == "closed":
            raise KeyError(f"Orbis session {reactor_session_id} is not active.")
        drv.command_log.append(
            {"command": "request_clip", "payload": {"duration_seconds": float(validated)}}
        )
        return synthesize_mock_orbis_mp4(validated, ecosystem_type=ecosystem_type)

    async def close_session(self, reactor_session_id: str) -> None:
        drv = self._sessions.get(reactor_session_id)
        if drv is not None:
            drv.status = "closed"
            drv.command_log.append({"command": "disconnect", "payload": {}})

    def get_driver_session(self, reactor_session_id: str) -> OrbisDriverSession | None:
        return self._sessions.get(reactor_session_id)


class LiveReactorOrbisAdapter(ReactorOrbisAdapter):
    """Production Reactor Platform & Visko Orbis Stable adapter using reactor-sdk and httpx."""

    mode: AdapterMode = "live"

    def __init__(
        self,
        *,
        api_key: str,
        api_url: str = "https://api.reactor.inc",
        model_slug: str = CANONICAL_MODEL_ID,
        http_transport: httpx.AsyncBaseTransport | None = None,
        reactor_factory: Callable[..., Any] | None = None,
        download_clip_fn: Callable[[Any, Path], Any] | None = None,
    ) -> None:
        validate_model_slug(model_slug)
        if not api_key or not api_key.strip():
            raise ValueError("REACTOR_API_KEY is required for LiveReactorOrbisAdapter.")
        self._api_key = api_key.strip()
        self._api_url = api_url.rstrip("/")
        self._model_slug = model_slug
        self._http_transport = http_transport
        self._reactor_factory = reactor_factory
        self._download_clip_fn = download_clip_fn
        self._sessions: dict[str, OrbisDriverSession] = {}

    def _create_sdk_instance(self) -> Any:
        if self._reactor_factory is not None:
            return self._reactor_factory(
                model_name=CANONICAL_MODEL_ID,
                api_key=self._api_key,
            )
        from reactor_sdk import Reactor  # type: ignore[import-not-found]

        return Reactor(
            model_name=CANONICAL_MODEL_ID,
            api_key=self._api_key,
        )

    async def _download_clip(self, clip: Any, ts_path: Path) -> None:
        if self._download_clip_fn is not None:
            await self._download_clip_fn(clip, ts_path)
            return
        from reactor_sdk import download_clip  # type: ignore[import-not-found]

        await download_clip(clip, ts_path)

    async def mint_jwt(
        self,
        *,
        session_id_to_bind: str | None = None,
        max_sessions: int = 5,
        expires_after: int = 3600,
        model_id: str = CANONICAL_MODEL_ID,
    ) -> ReactorTokenResponse:
        payload = build_reactor_token_request_payload(
            session_id_to_bind=session_id_to_bind,
            max_sessions=max_sessions,
            expires_after=expires_after,
            model_id=model_id,
        )
        async with httpx.AsyncClient(
            timeout=15.0, transport=self._http_transport
        ) as client:
            resp = await client.post(
                f"{self._api_url}/tokens",
                headers={
                    "Reactor-API-Key": self._api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        jwt_str = str(data.get("jwt") or data.get("token") or "")
        if not jwt_str or self._api_key in jwt_str:
            raise RuntimeError("Upstream Reactor /tokens returned an invalid JWT payload.")
        default_exp = int(time.time()) + int(expires_after)
        expires_at = int(data.get("expires_at") or default_exp)

        return ReactorTokenResponse(
            jwt=jwt_str,
            expires_at=expires_at,
            model_id=CANONICAL_MODEL_ID,
            mode="live",
            bound_session_id=session_id_to_bind,
        )

    async def start_session(
        self,
        *,
        compiled_initial_prompt: str,
        resolution: ResolutionOption = "1080p",
        seed_image_bytes: bytes | None = None,
        seed_filename: str = "seed_16x9.jpg",
        model_id: str = CANONICAL_MODEL_ID,
    ) -> OrbisDriverSession:
        validate_model_slug(model_id)
        reactor = self._create_sdk_instance()
        await reactor.connect()

        reactor_session_id = str(
            getattr(reactor, "session_id", None) or f"orbis_live_{uuid.uuid4().hex[:10]}"
        )
        drv = OrbisDriverSession(
            reactor_session_id=reactor_session_id,
            mode="live",
            status="waiting",
            resolution=resolution,
            sdk_handle=reactor,
        )

        await reactor.send_command("set_resolution", {"resolution": resolution})
        drv.command_log.append({"command": "set_resolution", "payload": {"resolution": resolution}})

        await reactor.send_command("set_audio_enabled", {"audio_enabled": False})
        drv.command_log.append(
            {"command": "set_audio_enabled", "payload": {"audio_enabled": False}}
        )

        if seed_image_bytes:
            file_ref = await reactor.upload_file(
                seed_image_bytes, name=seed_filename, mime_type="image/jpeg"
            )
            drv.command_log.append(
                {
                    "command": "upload_file",
                    "payload": {"name": seed_filename, "bytes_len": len(seed_image_bytes)},
                }
            )
            await reactor.send_command("set_image", {"image": file_ref})
            drv.command_log.append({"command": "set_image", "payload": {"image": file_ref}})
            drv.has_seed_image = True

        await reactor.send_command(
            "set_prompt",
            {"prompt": compiled_initial_prompt, "passthrough": True},
        )
        drv.command_log.append(
            {
                "command": "set_prompt",
                "payload": {"prompt": compiled_initial_prompt, "passthrough": True},
            }
        )

        await reactor.send_command("start", {})
        drv.command_log.append({"command": "start", "payload": {}})

        drv.active_prompt = compiled_initial_prompt
        drv.started_monotonic = time.monotonic()
        drv.status = "priming"
        self._sessions[reactor_session_id] = drv
        return drv

    async def steer_prompt(
        self,
        reactor_session_id: str,
        compiled_steering_prompt: str,
    ) -> list[str]:
        drv = self._sessions.get(reactor_session_id)
        if drv is None or drv.sdk_handle is None or drv.status == "closed":
            raise KeyError(f"Live Orbis session {reactor_session_id} is not active.")

        await drv.sdk_handle.send_command(
            "set_prompt",
            {"prompt": compiled_steering_prompt, "passthrough": True},
        )
        drv.command_log.append(
            {
                "command": "set_prompt",
                "payload": {"prompt": compiled_steering_prompt, "passthrough": True},
            }
        )
        drv.active_prompt = compiled_steering_prompt
        return ["set_prompt"]

    async def reanchor_seed(
        self,
        reactor_session_id: str,
        *,
        seed_image_bytes: bytes,
        compiled_prompt: str,
        seed_filename: str = "seed_16x9.jpg",
    ) -> list[str]:
        drv = self._sessions.get(reactor_session_id)
        if drv is None or drv.sdk_handle is None or drv.status == "closed":
            raise KeyError(f"Live Orbis session {reactor_session_id} is not active.")

        reactor = drv.sdk_handle
        sequence: list[str] = []

        # Strict sequential awaits per SKILL.md §3
        await reactor.send_command("reset", {})
        drv.command_log.append({"command": "reset", "payload": {}})
        sequence.append("reset")

        file_ref = await reactor.upload_file(
            seed_image_bytes, name=seed_filename, mime_type="image/jpeg"
        )
        drv.command_log.append(
            {
                "command": "upload_file",
                "payload": {"name": seed_filename, "bytes_len": len(seed_image_bytes)},
            }
        )
        sequence.append("upload_file")

        await reactor.send_command("set_image", {"image": file_ref})
        drv.command_log.append({"command": "set_image", "payload": {"image": file_ref}})
        drv.has_seed_image = True
        sequence.append("set_image")

        await reactor.send_command(
            "set_prompt",
            {"prompt": compiled_prompt, "passthrough": True},
        )
        drv.command_log.append(
            {
                "command": "set_prompt",
                "payload": {"prompt": compiled_prompt, "passthrough": True},
            }
        )
        drv.active_prompt = compiled_prompt
        sequence.append("set_prompt")

        await reactor.send_command("start", {})
        drv.command_log.append({"command": "start", "payload": {}})
        drv.started_monotonic = time.monotonic()
        drv.status = "priming"
        sequence.append("start")

        return sequence

    async def capture_clip_mp4(
        self,
        reactor_session_id: str,
        duration_seconds: int,
        *,
        ecosystem_type: str = "alpine",
    ) -> bytes:
        validated = validate_strict_duration(duration_seconds=duration_seconds)
        drv = self._sessions.get(reactor_session_id)
        if drv is None or drv.sdk_handle is None or drv.status == "closed":
            raise KeyError(f"Live Orbis session {reactor_session_id} is not active.")

        reactor = drv.sdk_handle
        clip = await reactor.request_clip(float(validated))
        drv.command_log.append(
            {"command": "request_clip", "payload": {"duration_seconds": float(validated)}}
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ts_path = tmp_path / "capture.ts"
            mp4_path = tmp_path / "output.mp4"
            await self._download_clip(clip, ts_path)
            return remux_mpegts_to_mp4(ts_path, mp4_path)

    async def close_session(self, reactor_session_id: str) -> None:
        drv = self._sessions.get(reactor_session_id)
        if drv is None:
            return
        drv.status = "closed"
        if drv.sdk_handle is not None:
            try:
                await drv.sdk_handle.disconnect()
            except Exception:
                pass
        try:
            async with httpx.AsyncClient(
                timeout=8.0, transport=self._http_transport
            ) as client:
                await client.delete(
                    f"{self._api_url}/sessions/{reactor_session_id}",
                    headers={"Reactor-API-Key": self._api_key},
                )
        except Exception:
            pass

    def get_driver_session(self, reactor_session_id: str) -> OrbisDriverSession | None:
        return self._sessions.get(reactor_session_id)
