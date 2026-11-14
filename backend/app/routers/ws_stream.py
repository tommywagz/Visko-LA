"""WebSocket live 5-10 Hz ISA/Dryden telemetry stream & interactive flight steering."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.adapters.catalog import CatalogNotFoundError
from app.adapters.orbis import ORBIS_FPS
from app.models.schemas import SUPPORTED_CAMERA_MODES, SUPPORTED_ECOSYSTEMS
from app.services.session_manager import ManagedAerialSession, runtime
from app.services.telemetry_engine import build_ws_telemetry_envelope

router = APIRouter(tags=["WebSocket Telemetry Stream"])

TELEMETRY_TICK_SECONDS = 0.125  # 8 Hz (within 5-10 Hz contract specification)


def _build_synthetic_frame_event(
    sess: ManagedAerialSession,
    frame_index: int,
) -> dict[str, Any]:
    latest = sess.telemetry_engine.latest_frame
    return {
        "type": "synthetic_frame",
        "session_id": sess.session_id,
        "chunk_index": latest.chunk_index,
        "frame_index": frame_index,
        "ecosystem_type": latest.ecosystem_type,
        "camera_mode": sess.camera_mode,
        "horizon_pitch_deg": latest.drone_pitch_deg,
        "horizon_roll_deg": latest.drone_roll_deg,
        "wind_vector_deg": latest.wind_direction_deg,
        "wind_speed_mps": latest.wind_speed_mps,
        "turbulence_edr": latest.turbulence_edr,
        "terrain_seed": sess.telemetry_engine.session_seed % 10000,
        "timestamp_ms": latest.timestamp_ms,
    }


def _build_error_event(
    session_id: str,
    code: str,
    message: str,
    *,
    recoverable: bool = True,
) -> dict[str, Any]:
    return {
        "type": "error",
        "session_id": session_id,
        "code": code,
        "message": message,
        "recoverable": recoverable,
        "timestamp_ms": int(time.time() * 1000),
    }


@router.websocket("/ws/orbis/stream/{session_id}")
async def orbis_telemetry_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    try:
        sess = runtime.get_session(session_id)
    except CatalogNotFoundError:
        await websocket.send_json(
            _build_error_event(
                session_id,
                "SESSION_NOT_FOUND",
                f"Session {session_id!r} does not exist or is closed.",
                recoverable=False,
            )
        )
        await websocket.close(code=4404)
        return

    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=128)
    sess.ws_queues.add(event_queue)

    async def _send_telemetry_tick(tick_counter: int) -> None:
        chunk_idx = sess.driver_session.chunk_index
        sample = sess.telemetry_engine.sample(
            dt_seconds=TELEMETRY_TICK_SECONDS,
            chunk_index=chunk_idx,
        )
        await websocket.send_json(build_ws_telemetry_envelope(sess.session_id, sample))
        if sess.driver_session.mode == "mock":
            frame_idx = chunk_idx * 33 + ((tick_counter * 2) % max(1, ORBIS_FPS))
            await websocket.send_json(_build_synthetic_frame_event(sess, frame_idx))

    async def _handle_client_text(raw_text: str) -> None:
        try:
            msg = json.loads(raw_text)
        except json.JSONDecodeError:
            await websocket.send_json(
                _build_error_event(
                    sess.session_id,
                    "INVALID_JSON",
                    "WebSocket client message must be valid JSON.",
                )
            )
            return

        if not isinstance(msg, dict) or "type" not in msg:
            await websocket.send_json(
                _build_error_event(
                    sess.session_id,
                    "INVALID_MESSAGE",
                    "WebSocket JSON message must contain a 'type' property.",
                )
            )
            return

        msg_type = msg.get("type")
        if msg_type == "ping":
            echo_ts = msg.get("timestamp_ms")
            ts_val = int(echo_ts) if isinstance(echo_ts, (int, float)) else int(time.time() * 1000)
            await websocket.send_json(
                {
                    "type": "pong",
                    "session_id": sess.session_id,
                    "timestamp_ms": ts_val,
                }
            )
        elif msg_type == "steer_prompt":
            prompt_text = str(msg.get("prompt") or "").strip()
            if not prompt_text:
                await websocket.send_json(
                    _build_error_event(
                        sess.session_id,
                        "INVALID_MESSAGE",
                        "Prompt text must be non-empty.",
                    )
                )
                return
            try:
                await runtime.steer_session_prompt(
                    sess.session_id,
                    raw_prompt=prompt_text,
                    camera_mode=msg.get("camera_mode"),
                )
            except Exception as exc:
                await websocket.send_json(
                    _build_error_event(sess.session_id, "STEER_ERROR", str(exc))
                )
        elif msg_type == "flight_adjust":
            cam = msg.get("camera_mode")
            if cam is not None and cam not in SUPPORTED_CAMERA_MODES:
                await websocket.send_json(
                    _build_error_event(
                        sess.session_id,
                        "INVALID_CAMERA_MODE",
                        f"Unsupported camera_mode {cam!r}.",
                    )
                )
                return
            eco = msg.get("ecosystem_type")
            if eco is not None and eco not in SUPPORTED_ECOSYSTEMS:
                await websocket.send_json(
                    _build_error_event(
                        sess.session_id,
                        "INVALID_ECOSYSTEM",
                        f"Unsupported ecosystem_type {eco!r}.",
                    )
                )
                return
            try:
                alt = (
                    float(msg["drone_altitude_agl_m"])
                    if msg.get("drone_altitude_agl_m") is not None
                    else None
                )
                spd = (
                    float(msg["drone_airspeed_mps"])
                    if msg.get("drone_airspeed_mps") is not None
                    else None
                )
            except (TypeError, ValueError):
                await websocket.send_json(
                    _build_error_event(
                        sess.session_id,
                        "INVALID_MESSAGE",
                        "drone_altitude_agl_m and drone_airspeed_mps must be numeric.",
                    )
                )
                return

            if cam is not None:
                sess.camera_mode = cam  # type: ignore[assignment]
            if eco is not None:
                sess.ecosystem_type = eco  # type: ignore[assignment]
            sess.telemetry_engine.adjust_flight(
                drone_altitude_agl_m=alt,
                drone_airspeed_mps=spd,
                camera_mode=cam,
                ecosystem_type=eco,  # type: ignore[arg-type]
            )
            await websocket.send_json(sess.build_orbis_state_event())
            sample = sess.telemetry_engine.sample(
                dt_seconds=0.05,
                chunk_index=sess.driver_session.chunk_index,
            )
            await websocket.send_json(build_ws_telemetry_envelope(sess.session_id, sample))
        else:
            await websocket.send_json(
                _build_error_event(
                    sess.session_id,
                    "UNKNOWN_MESSAGE_TYPE",
                    f"Unsupported WebSocket message type {msg_type!r}.",
                )
            )

    recv_task: asyncio.Task[dict[str, Any]] | None = None
    queue_task: asyncio.Task[dict[str, Any]] | None = None
    tick_counter = 0
    last_chunk = sess.driver_session.chunk_index
    last_status = sess.driver_session.effective_status

    try:
        # 1. Immediate initial orbis_state + first telemetry sample on connect
        await websocket.send_json(sess.build_orbis_state_event())
        await _send_telemetry_tick(tick_counter)
        tick_counter += 1

        next_tick_at = time.monotonic() + TELEMETRY_TICK_SECONDS
        while not sess.closed:
            if recv_task is None:
                recv_task = asyncio.create_task(websocket.receive())
            if queue_task is None:
                queue_task = asyncio.create_task(event_queue.get())

            timeout = max(0.0, next_tick_at - time.monotonic())
            done, _ = await asyncio.wait(
                {recv_task, queue_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if recv_task in done:
                asgi_msg = recv_task.result()
                recv_task = None
                if asgi_msg.get("type") == "websocket.disconnect":
                    break
                text_data = asgi_msg.get("text")
                if text_data is not None:
                    await _handle_client_text(text_data)
                elif asgi_msg.get("bytes") is not None:
                    await _handle_client_text(asgi_msg["bytes"].decode("utf-8", errors="replace"))

            if queue_task in done:
                queued_evt = queue_task.result()
                queue_task = None
                await websocket.send_json(queued_evt)
                while not event_queue.empty():
                    await websocket.send_json(event_queue.get_nowait())

            now_mono = time.monotonic()
            if now_mono >= next_tick_at and not sess.closed:
                curr_chunk = sess.driver_session.chunk_index
                curr_status = sess.driver_session.effective_status
                if curr_chunk != last_chunk or curr_status != last_status:
                    last_chunk = curr_chunk
                    last_status = curr_status
                    await websocket.send_json(sess.build_orbis_state_event())
                await _send_telemetry_tick(tick_counter)
                tick_counter += 1
                next_tick_at = now_mono + TELEMETRY_TICK_SECONDS
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sess.ws_queues.discard(event_queue)
        for t in (recv_task, queue_task):
            if t is not None and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
