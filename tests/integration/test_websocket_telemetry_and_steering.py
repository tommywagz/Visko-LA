"""Layer 2 Integration Tests: Live 5-10 Hz WebSocket Telemetry Stream & Mid-Stream Chat Steering."""

from __future__ import annotations

from typing import Any

from starlette.testclient import TestClient

from app.models.schemas import CANONICAL_MODEL_ID
from app.services.prompt_compiler import STEERING_ANCHOR_PREFIX

EXPECTED_16_TELEMETRY_KEYS = {
    "timestamp_ms",
    "chunk_index",
    "ecosystem_type",
    "wind_speed_mps",
    "wind_gust_mps",
    "wind_direction_deg",
    "air_pressure_hpa",
    "air_density_kgm3",
    "ambient_temp_c",
    "turbulence_edr",
    "turbulence_level",
    "drone_altitude_agl_m",
    "drone_airspeed_mps",
    "drone_pitch_deg",
    "drone_roll_deg",
    "drone_yaw_deg",
}


def _collect_ws_messages_until(
    ws: Any,
    predicate: Any,
    *,
    max_messages: int = 25,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for _ in range(max_messages):
        msg = ws.receive_json()
        collected.append(msg)
        if predicate(msg, collected):
            break
    return collected


def test_websocket_continuous_telemetry_and_rest_mid_stream_steering(
    ws_test_client: TestClient,
) -> None:
    """T1-C3 & T1-C4: Connect WS, verify 16-field telemetry stream, steer via POST /prompt without disconnect."""
    create_resp = ws_test_client.post(
        "/api/v1/sessions",
        json={
            "ecosystem_type": "coastal",
            "camera_mode": "forward_downward_oblique",
            "drone_altitude_agl_m": 45.0,
            "initial_prompt": "Calm coastal shoreline cruise under clear sunlit sky",
        },
    )
    assert create_resp.status_code in (200, 201)
    session = create_resp.json()
    session_id = session["session_id"]

    with ws_test_client.websocket_connect(f"/ws/orbis/stream/{session_id}") as ws:
        # 1. First message must be orbis_state, followed immediately by telemetry (& synthetic_frame in mock mode)
        initial_msgs = _collect_ws_messages_until(
            ws,
            lambda _m, acc: sum(1 for x in acc if x.get("type") == "telemetry") >= 3,
            max_messages=12,
        )
        assert initial_msgs[0]["type"] == "orbis_state"
        assert initial_msgs[0]["model_id"] == CANONICAL_MODEL_ID

        telemetry_frames = [m for m in initial_msgs if m.get("type") == "telemetry"]
        assert len(telemetry_frames) >= 3
        first_tel = telemetry_frames[0]
        for k in EXPECTED_16_TELEMETRY_KEYS:
            assert k in first_tel
            assert first_tel["telemetry"][k] == first_tel[k]
            assert first_tel["data"][k] == first_tel[k]

        baseline_wind = first_tel["wind_speed_mps"]
        baseline_edr = first_tel["turbulence_edr"]
        assert 1000.0 <= first_tel["air_pressure_hpa"] <= 1020.0

        # 2. Mid-stream steering via REST POST /api/v1/sessions/{session_id}/prompt while WS stays open
        steer_prompt_text = "Heavy storm front with 24 m/s crosswind gusts"
        steer_resp = ws_test_client.post(
            f"/api/v1/sessions/{session_id}/prompt",
            json={"prompt": steer_prompt_text},
        )
        assert steer_resp.status_code == 200
        steered_body = steer_resp.json()
        assert steered_body["passthrough"] is True
        assert steered_body["compiled_prompt"].startswith(STEERING_ANCHOR_PREFIX)
        assert len(steered_body["prompt_history"]) == 2
        assert steered_body["prompt_history"][-1]["prompt"] == steer_prompt_text

        # 3. Verify WS receives prompt_ack and continues streaming elevated telemetry without disconnecting
        post_steer_msgs = _collect_ws_messages_until(
            ws,
            lambda _m, acc: (
                any(x.get("type") == "prompt_ack" for x in acc)
                and sum(1 for x in acc if x.get("type") == "telemetry") >= 6
            ),
            max_messages=25,
        )
        ack_msgs = [m for m in post_steer_msgs if m.get("type") == "prompt_ack"]
        assert len(ack_msgs) == 1
        assert ack_msgs[0]["passthrough"] is True
        assert ack_msgs[0]["prompt"] == steer_prompt_text

        post_telemetry = [m for m in post_steer_msgs if m.get("type") == "telemetry"]
        assert len(post_telemetry) >= 4
        latest_tel = post_telemetry[-1]
        assert latest_tel["wind_speed_mps"] > baseline_wind + 5.0
        assert latest_tel["turbulence_edr"] > baseline_edr + 0.10


def test_websocket_client_messages_ping_steer_flight_adjust_and_unknown_session(
    ws_test_client: TestClient,
) -> None:
    """T1-C5: Test client-to-server ping/pong, steer_prompt, flight_adjust, recoverable errors, and 4404."""
    # Unknown session emits error SESSION_NOT_FOUND and closes cleanly
    with ws_test_client.websocket_connect("/ws/orbis/stream/sess_does_not_exist") as bad_ws:
        err_msg = bad_ws.receive_json()
        assert err_msg["type"] == "error"
        assert err_msg["code"] == "SESSION_NOT_FOUND"

    sess_resp = ws_test_client.post(
        "/api/v1/sessions",
        json={"ecosystem_type": "coastal", "drone_altitude_agl_m": 40.0},
    )
    session_id = sess_resp.json()["session_id"]

    with ws_test_client.websocket_connect(f"/ws/orbis/stream/{session_id}") as ws:
        init_msgs = _collect_ws_messages_until(
            ws,
            lambda m, _acc: m.get("type") == "telemetry",
            max_messages=6,
        )
        low_alt_pressure = next(m for m in init_msgs if m["type"] == "telemetry")["air_pressure_hpa"]

        # 1. ping -> pong
        ws.send_json({"type": "ping", "timestamp_ms": 1763151004000})
        pong_msgs = _collect_ws_messages_until(
            ws,
            lambda m, _acc: m.get("type") == "pong",
            max_messages=8,
        )
        pong = next(m for m in pong_msgs if m["type"] == "pong")
        assert pong["session_id"] == session_id
        assert pong["timestamp_ms"] == 1763151004000

        # 2. flight_adjust raising drone_altitude_agl_m 40m -> 450m lowers ISA pressure
        ws.send_json({"type": "flight_adjust", "drone_altitude_agl_m": 450.0, "drone_airspeed_mps": 15.0})
        adj_msgs = _collect_ws_messages_until(
            ws,
            lambda m, _acc: m.get("type") == "telemetry" and m.get("drone_altitude_agl_m") == 450.0,
            max_messages=10,
        )
        high_alt_tel = next(
            m for m in adj_msgs if m.get("type") == "telemetry" and m.get("drone_altitude_agl_m") == 450.0
        )
        assert high_alt_tel["air_pressure_hpa"] < low_alt_pressure - 35.0

        # 3. WS steer_prompt -> prompt_ack
        ws.send_json({"type": "steer_prompt", "prompt": "Increase crosswind gusts to 19 m/s"})
        ws_steer_msgs = _collect_ws_messages_until(
            ws,
            lambda m, _acc: m.get("type") == "prompt_ack",
            max_messages=10,
        )
        assert any(m.get("type") == "prompt_ack" for m in ws_steer_msgs)

        # 4. Malformed message yields recoverable error without closing socket
        ws.send_text("{not_valid_json")
        err_msgs = _collect_ws_messages_until(
            ws,
            lambda m, _acc: m.get("type") == "error",
            max_messages=10,
        )
        err = next(m for m in err_msgs if m.get("type") == "error")
        assert err["recoverable"] is True
