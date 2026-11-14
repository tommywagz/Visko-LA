"""Layer 1A Unit Tests: Coupled ISA Atmospheric Physics, Dryden Gusts & Weather Directive Engine."""

from __future__ import annotations

import json

import pytest

from app.services.telemetry_engine import (
    ECOSYSTEM_PROFILES,
    SessionTelemetryEngine,
    build_ws_telemetry_envelope,
    classify_turbulence_level,
    compute_isa_atmosphere,
    parse_weather_directives,
)


def test_isa_pressure_and_density_decrease_monotonically_with_altitude() -> None:
    """T1-C1: Coastal (~1013 hPa) vs Alpine (< 880 hPa) and strict monotonic decrease with AGL."""
    coastal_engine = SessionTelemetryEngine(
        session_seed=101,
        ecosystem_type="coastal",
        drone_altitude_agl_m=20.0,
    )
    alpine_engine = SessionTelemetryEngine(
        session_seed=101,
        ecosystem_type="alpine",
        drone_altitude_agl_m=65.0,
    )

    coastal_frame = coastal_engine.sample(dt_seconds=0.1)
    alpine_frame = alpine_engine.sample(dt_seconds=0.1)

    assert 1005.0 <= coastal_frame.air_pressure_hpa <= 1015.0
    assert alpine_frame.air_pressure_hpa < 880.0
    assert alpine_frame.air_density_kgm3 < coastal_frame.air_density_kgm3

    # Verify strict monotonic decrease across increasing AGL altitudes in any fixed ecosystem
    altitudes = [10.0, 50.0, 150.0, 300.0, 600.0, 1200.0, 2500.0]
    base_msl = ECOSYSTEM_PROFILES["coastal"].base_elevation_msl_m
    surf_t = ECOSYSTEM_PROFILES["coastal"].surface_temp_c

    pressures: list[float] = []
    densities: list[float] = []
    for agl in altitudes:
        p_hpa, rho_kgm3, _ = compute_isa_atmosphere(
            base_msl + agl,
            surface_temp_c=surf_t,
            drone_altitude_agl_m=agl,
        )
        pressures.append(p_hpa)
        densities.append(rho_kgm3)

    for idx in range(len(altitudes) - 1):
        assert pressures[idx + 1] < pressures[idx], (
            f"Pressure did not decrease monotonically from {altitudes[idx]}m to {altitudes[idx + 1]}m"
        )
        assert densities[idx + 1] < densities[idx], (
            f"Density did not decrease monotonically from {altitudes[idx]}m to {altitudes[idx + 1]}m"
        )


def test_weather_prompt_directives_shift_wind_gusts_and_turbulence_physically() -> None:
    """T1-C2: Verify weather directives ('crosswind 22 m/s and severe ridge turbulence') elevate targets."""
    parsed = parse_weather_directives("Inject crosswind 22 m/s and severe ridge turbulence")
    assert parsed["wind_speed_mps"] >= 22.0
    assert parsed["wind_gust_mps"] > parsed["wind_speed_mps"]
    assert parsed["turbulence_edr"] >= 0.45

    engine = SessionTelemetryEngine(
        session_seed=77,
        ecosystem_type="coastal",
        drone_altitude_agl_m=50.0,
    )
    baseline = engine.sample(dt_seconds=0.1)
    assert baseline.wind_speed_mps < 12.0
    assert baseline.turbulence_edr < 0.25

    targets = engine.apply_prompt_directives(
        "Crosswind 22 m/s and severe ridge turbulence over rocky cliffs"
    )
    assert targets["wind_speed_mps"] >= 22.0
    assert targets["turbulence_edr"] >= 0.45
    assert targets["turbulence_level"] in ("severe", "extreme")

    # Advance through 3.0s smoothstep ramp (> 2.5s RAMP_DURATION_SECONDS)
    steered_samples = [engine.sample(dt_seconds=0.25) for _ in range(12)]
    converged = steered_samples[-1]
    assert converged.wind_speed_mps > baseline.wind_speed_mps + 8.0
    assert converged.wind_gust_mps >= converged.wind_speed_mps
    assert converged.turbulence_edr >= 0.45
    assert converged.turbulence_level in ("severe", "extreme")

    # Now steer to calm conditions and verify downward shift
    calm_targets = engine.apply_prompt_directives("Calm still air under clear sunlit sky", immediate=True)
    assert calm_targets["turbulence_level"] == "light"
    calm_sample = engine.sample(dt_seconds=0.1)
    assert calm_sample.wind_speed_mps < 5.0
    assert calm_sample.turbulence_edr < 0.20
    assert calm_sample.turbulence_level == "light"


@pytest.mark.parametrize(
    ("edr_val", "expected_level"),
    [
        (0.0, "light"),
        (0.199, "light"),
        (0.20, "moderate"),
        (0.449, "moderate"),
        (0.45, "severe"),
        (0.699, "severe"),
        (0.70, "extreme"),
        (1.15, "extreme"),
    ],
)
def test_edr_turbulence_classification_boundaries(edr_val: float, expected_level: str) -> None:
    """Verify exact ws_protocol.md §2.3 EDR thresholds."""
    assert classify_turbulence_level(edr_val) == expected_level


def test_seeded_determinism_window_aggregation_and_ws_envelope_parity() -> None:
    """Verify Dryden seed determinism, 16-field WS envelope parity, and capture window aggregates."""
    eng_a = SessionTelemetryEngine(session_seed=999, ecosystem_type="alpine", drone_altitude_agl_m=90.0)
    eng_b = SessionTelemetryEngine(session_seed=999, ecosystem_type="alpine", drone_altitude_agl_m=90.0)

    sample_a = eng_a.sample(dt_seconds=0.2, chunk_index=2, timestamp_ms=1763151000000)
    sample_b = eng_b.sample(dt_seconds=0.2, chunk_index=2, timestamp_ms=1763151000000)
    assert sample_a == sample_b
    assert 0.0 <= sample_a.wind_direction_deg <= 360.0
    assert 0.0 <= sample_a.drone_yaw_deg <= 360.0
    assert sample_a.wind_gust_mps >= sample_a.wind_speed_mps

    # Check WS envelope flattened + nested telemetry + nested data parity
    env = build_ws_telemetry_envelope("sess_unit_01", sample_a)
    assert env["type"] == "telemetry"
    assert env["session_id"] == "sess_unit_01"
    expected_16_fields = {
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
    for key in expected_16_fields:
        assert key in env
        assert env["telemetry"][key] == env[key]
        assert env["data"][key] == env[key]

    # Advance samples and verify window aggregation
    for idx in range(25):
        eng_a.sample(dt_seconds=0.2, timestamp_ms=1763151000200 + idx * 200)
    agg = eng_a.aggregate_window(5)
    assert agg["max_wind_gust_mps"] >= agg["avg_wind_speed_mps"]
    assert agg["max_turbulence_edr"] >= agg["avg_turbulence_edr"]
    assert 0.0 <= agg["wind_direction_deg"] < 360.0
    summary = json.loads(agg["telemetry_summary_json"])
    assert summary["window_duration_seconds"] == 5
    assert summary["sample_count"] >= 5
