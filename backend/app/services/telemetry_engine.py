"""Coupled International Standard Atmosphere (ISA) & Dryden/Perlin UAV Telemetry Engine."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import math
import re
import time
from typing import Any

from app.models.schemas import (
    SUPPORTED_ECOSYSTEMS,
    EcosystemType,
    TelemetryFrame,
    TurbulenceLevel,
)

# ISA Constants
ISA_SEA_LEVEL_PRESSURE_HPA = 1013.25
ISA_SEA_LEVEL_TEMP_K = 288.15
ISA_LAPSE_RATE_K_PER_M = 0.0065
ISA_EXPONENT = 5.25588
ISA_PRESSURE_SCALE = 2.25577e-5
DRY_AIR_GAS_CONSTANT = 287.058  # J / (kg * K)

ORBIS_CHUNK_DURATION_SECONDS = 1.833
ORBIS_NATIVE_FPS = 18


@dataclass(frozen=True)
class EcosystemPhysicsProfile:
    base_elevation_msl_m: float
    surface_temp_c: float
    base_wind_speed_mps: float
    base_wind_gust_mps: float
    base_wind_direction_deg: float
    base_turbulence_edr: float
    default_airspeed_mps: float


ECOSYSTEM_PROFILES: dict[EcosystemType, EcosystemPhysicsProfile] = {
    "coastal": EcosystemPhysicsProfile(
        base_elevation_msl_m=10.0,
        surface_temp_c=18.5,
        base_wind_speed_mps=6.8,
        base_wind_gust_mps=9.4,
        base_wind_direction_deg=265.0,
        base_turbulence_edr=0.14,
        default_airspeed_mps=12.5,
    ),
    "wetlands": EcosystemPhysicsProfile(
        base_elevation_msl_m=25.0,
        surface_temp_c=21.0,
        base_wind_speed_mps=4.2,
        base_wind_gust_mps=6.1,
        base_wind_direction_deg=140.0,
        base_turbulence_edr=0.09,
        default_airspeed_mps=10.5,
    ),
    "urban_canyon": EcosystemPhysicsProfile(
        base_elevation_msl_m=80.0,
        surface_temp_c=22.0,
        base_wind_speed_mps=7.6,
        base_wind_gust_mps=11.8,
        base_wind_direction_deg=215.0,
        base_turbulence_edr=0.24,
        default_airspeed_mps=10.0,
    ),
    "custom": EcosystemPhysicsProfile(
        base_elevation_msl_m=100.0,
        surface_temp_c=17.0,
        base_wind_speed_mps=5.5,
        base_wind_gust_mps=7.8,
        base_wind_direction_deg=180.0,
        base_turbulence_edr=0.12,
        default_airspeed_mps=11.5,
    ),
    "temperate_forest": EcosystemPhysicsProfile(
        base_elevation_msl_m=350.0,
        surface_temp_c=14.5,
        base_wind_speed_mps=5.8,
        base_wind_gust_mps=8.5,
        base_wind_direction_deg=230.0,
        base_turbulence_edr=0.16,
        default_airspeed_mps=11.2,
    ),
    "arid_desert": EcosystemPhysicsProfile(
        base_elevation_msl_m=450.0,
        surface_temp_c=32.5,
        base_wind_speed_mps=8.4,
        base_wind_gust_mps=12.2,
        base_wind_direction_deg=110.0,
        base_turbulence_edr=0.22,
        default_airspeed_mps=13.5,
    ),
    "alpine": EcosystemPhysicsProfile(
        base_elevation_msl_m=1650.0,
        surface_temp_c=4.2,
        base_wind_speed_mps=11.6,
        base_wind_gust_mps=16.2,
        base_wind_direction_deg=250.0,
        base_turbulence_edr=0.28,
        default_airspeed_mps=11.8,
    ),
}

CAMERA_PITCH_BASE_DEG: dict[str, float] = {
    "forward_downward_oblique": -35.0,
    "nadir_downward": -88.0,
    "forward_fpv": -15.0,
}


def classify_turbulence_level(edr: float) -> TurbulenceLevel:
    """Classify Eddy Dissipation Rate (m^(2/3) s^-1) per ws_protocol.md §2.3."""
    if edr < 0.20:
        return "light"
    if edr < 0.45:
        return "moderate"
    if edr < 0.70:
        return "severe"
    return "extreme"


def compute_isa_atmosphere(
    elevation_msl_m: float,
    *,
    surface_temp_c: float | None = None,
    drone_altitude_agl_m: float = 0.0,
    pressure_offset_hpa: float = 0.0,
    temp_offset_c: float = 0.0,
) -> tuple[float, float, float]:
    """Compute ISA (air_pressure_hpa, air_density_kgm3, display_ambient_temp_c).

    Pressure and air density follow the International Standard Atmosphere barometric
    relation monotonically with total MSL altitude (elevation_msl_m), while ambient_temp_c
    reflects local ecosystem surface temperature lapsed with AGL altitude.
    """
    clamped_msl = max(0.0, float(elevation_msl_m))
    isa_factor = max(0.05, 1.0 - ISA_PRESSURE_SCALE * clamped_msl)
    pressure_hpa = ISA_SEA_LEVEL_PRESSURE_HPA * (isa_factor**ISA_EXPONENT) + pressure_offset_hpa
    pressure_hpa = max(150.0, pressure_hpa)

    isa_temp_k = max(180.0, ISA_SEA_LEVEL_TEMP_K - ISA_LAPSE_RATE_K_PER_M * clamped_msl + temp_offset_c)
    if surface_temp_c is not None:
        local_temp_c = surface_temp_c - ISA_LAPSE_RATE_K_PER_M * max(0.0, drone_altitude_agl_m) + temp_offset_c
        # Blend local temperature modestly into thermodynamic density while preserving strict MSL monotonicity
        effective_temp_k = 0.75 * isa_temp_k + 0.25 * (local_temp_c + 273.15)
        ambient_temp_c = local_temp_c
    else:
        effective_temp_k = isa_temp_k
        ambient_temp_c = isa_temp_k - 273.15

    air_density_kgm3 = (pressure_hpa * 100.0) / (DRY_AIR_GAS_CONSTANT * max(180.0, effective_temp_k))
    return (
        round(pressure_hpa, 2),
        round(air_density_kgm3, 4),
        round(ambient_temp_c, 2),
    )


def _deterministic_gust_wave(seed: int, t_sec: float) -> tuple[float, float, float]:
    """Seeded multi-harmonic Dryden/Perlin-like continuous gust oscillator in [-1, 1]."""
    phase1 = (seed % 97) * 0.13
    phase2 = (seed % 53) * 0.29
    phase3 = (seed % 31) * 0.47
    longitudinal = (
        0.55 * math.sin(0.85 * t_sec + phase1)
        + 0.30 * math.sin(2.15 * t_sec + phase2)
        + 0.15 * math.cos(4.10 * t_sec + phase3)
    )
    lateral = (
        0.50 * math.cos(1.10 * t_sec + phase2)
        + 0.35 * math.sin(2.60 * t_sec + phase3)
        + 0.15 * math.sin(5.05 * t_sec + phase1)
    )
    vertical = (
        0.60 * math.sin(1.45 * t_sec + phase3)
        + 0.40 * math.cos(3.20 * t_sec + phase1)
    )
    return longitudinal, lateral, vertical


def parse_weather_directives(prompt: str) -> dict[str, float]:
    """Parse natural-language steering prompts into target meteorological & flight deltas."""
    if not prompt or not prompt.strip():
        return {}
    text = prompt.lower()
    targets: dict[str, float] = {}

    # 1. Explicit wind speed / gust values (m/s, mps, knots, km/h)
    mps_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:m/s|mps|meters?\s+per\s+second)\b", text)
    kt_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:kt|kts|knots?)\b", text)
    kph_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:km/h|kph)\b", text)

    parsed_wind_mps: float | None = None
    if mps_matches:
        parsed_wind_mps = float(mps_matches[-1])
    elif kt_matches:
        parsed_wind_mps = float(kt_matches[-1]) * 0.514444
    elif kph_matches:
        parsed_wind_mps = float(kph_matches[-1]) / 3.6

    if parsed_wind_mps is not None:
        wind_val = max(0.0, min(65.0, parsed_wind_mps))
        targets["wind_speed_mps"] = round(wind_val, 2)
        targets["wind_gust_mps"] = round(max(wind_val + 2.5, wind_val * 1.3), 2)
        # Couple wind magnitude to realistic mechanical shear turbulence EDR
        implied_edr = min(0.92, max(0.08, wind_val * 0.022))
        targets["turbulence_edr"] = round(implied_edr, 3)

    # 2. Explicit barometric pressure (hPa)
    pressure_match = re.search(r"(\d{3,4}(?:\.\d+)?)\s*hpa\b", text)
    if pressure_match:
        targets["explicit_pressure_hpa"] = float(pressure_match.group(1))

    # 3. Explicit drone altitude AGL (avoid matching m/s)
    alt_match = re.search(
        r"(?:altitude|agl|climb\s+to|descend\s+to|fly\s+at|cruising\s+at)\s*(?:of\s*|to\s*)?(\d+(?:\.\d+)?)\s*(?:m|meters?)\b(?!\s*/\s*s)",
        text,
    )
    if not alt_match:
        alt_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|meters?)\s+agl\b", text)
    if alt_match:
        targets["drone_altitude_agl_m"] = max(1.0, min(5000.0, float(alt_match.group(1))))

    # 4. Explicit wind direction / cardinal bearings
    dir_match = re.search(
        r"(?:wind\s+direction|bearing|heading)\s*(?:of\s*|to\s*)?(\d{1,3}(?:\.\d+)?)\s*(?:deg|degrees?|°)?",
        text,
    )
    if dir_match:
        targets["wind_direction_deg"] = float(dir_match.group(1)) % 360.0
    elif "eastward" in text or "westerly" in text:
        targets["wind_direction_deg"] = 270.0
    elif "westward" in text or "easterly" in text:
        targets["wind_direction_deg"] = 90.0
    elif "northward" in text or "southerly" in text:
        targets["wind_direction_deg"] = 180.0
    elif "southward" in text or "northerly" in text:
        targets["wind_direction_deg"] = 0.0

    # 5. Semantic weather & turbulence regimes
    if any(k in text for k in ("calm", "still air", "tranquil", "zero wind")):
        targets.setdefault("wind_speed_mps", 1.8)
        targets.setdefault("wind_gust_mps", 2.7)
        targets["turbulence_edr"] = 0.06
        targets["pressure_delta_hpa"] = 4.0
    elif any(k in text for k in ("gentle breeze", "light breeze", "breeze")):
        targets.setdefault("wind_speed_mps", 5.8)
        targets.setdefault("wind_gust_mps", 8.0)
        targets.setdefault("turbulence_edr", 0.14)

    if any(k in text for k in ("storm", "squall", "tempest", "hurricane", "thunderstorm")):
        targets["wind_speed_mps"] = max(targets.get("wind_speed_mps", 0.0), 22.0)
        targets["wind_gust_mps"] = max(
            targets.get("wind_gust_mps", 0.0), targets["wind_speed_mps"] * 1.3
        )
        targets["turbulence_edr"] = max(targets.get("turbulence_edr", 0.0), 0.58)
        targets["pressure_delta_hpa"] = -14.0
        targets["temp_delta_c"] = -3.0
    elif any(k in text for k in ("gale", "high wind", "strong crosswind", "strong wind")):
        targets["wind_speed_mps"] = max(targets.get("wind_speed_mps", 0.0), 19.5)
        targets["wind_gust_mps"] = max(
            targets.get("wind_gust_mps", 0.0), targets["wind_speed_mps"] * 1.3
        )
        targets["turbulence_edr"] = max(targets.get("turbulence_edr", 0.0), 0.48)
        targets.setdefault("pressure_delta_hpa", -10.0)
    elif "crosswind" in text and "wind_speed_mps" not in targets:
        targets["wind_speed_mps"] = 16.0
        targets["wind_gust_mps"] = 21.5
        targets["turbulence_edr"] = max(targets.get("turbulence_edr", 0.0), 0.34)

    if any(k in text for k in ("extreme turbulence", "microburst", "violent rotor")):
        targets["turbulence_edr"] = max(targets.get("turbulence_edr", 0.0), 0.78)
        targets["wind_gust_mps"] = max(targets.get("wind_gust_mps", 0.0), 28.0)
    elif any(
        k in text
        for k in (
            "severe ridge turbulence",
            "heavy ridge turbulence",
            "severe turbulence",
            "heavy turbulence",
            "mountain rotor",
        )
    ):
        targets["turbulence_edr"] = max(targets.get("turbulence_edr", 0.0), 0.56)
        targets["wind_speed_mps"] = max(targets.get("wind_speed_mps", 0.0), 18.0)
        targets["wind_gust_mps"] = max(targets.get("wind_gust_mps", 0.0), 24.5)
    elif any(
        k in text
        for k in ("ridge turbulence", "urban thermal", "thermal updraft", "turbulence", "chop")
    ):
        targets["turbulence_edr"] = max(targets.get("turbulence_edr", 0.0), 0.34)

    if any(k in text for k in ("mist", "fog", "overcast", "rain", "snow")):
        targets.setdefault("pressure_delta_hpa", -4.5)
        targets.setdefault("temp_delta_c", -1.8)
    elif any(k in text for k in ("clear sunlit", "high pressure", "clear sky", "golden hour")):
        targets.setdefault("pressure_delta_hpa", 3.0)

    return {k: round(v, 3) if isinstance(v, float) else v for k, v in targets.items()}


class SessionTelemetryEngine:
    """Stateful per-session physics & atmospheric telemetry generator with 60s rolling buffer."""

    RAMP_DURATION_SECONDS = 2.5
    RING_BUFFER_WINDOW_SECONDS = 60.0

    def __init__(
        self,
        *,
        session_seed: int = 42,
        ecosystem_type: EcosystemType = "alpine",
        camera_mode: str = "forward_downward_oblique",
        drone_altitude_agl_m: float = 65.0,
        initial_prompt: str | None = None,
    ) -> None:
        if ecosystem_type not in SUPPORTED_ECOSYSTEMS:
            ecosystem_type = "alpine"
        self.session_seed = int(session_seed)
        self.ecosystem_type: EcosystemType = ecosystem_type
        self.camera_mode: str = camera_mode
        self.drone_altitude_agl_m: float = float(drone_altitude_agl_m)

        profile = ECOSYSTEM_PROFILES[self.ecosystem_type]
        self.drone_airspeed_mps: float = profile.default_airspeed_mps
        self.drone_yaw_deg: float = (profile.base_wind_direction_deg + 15.0) % 360.0

        # Current smoothed state
        self._wind_speed_mps: float = profile.base_wind_speed_mps
        self._wind_gust_mps: float = profile.base_wind_gust_mps
        self._wind_direction_deg: float = profile.base_wind_direction_deg
        self._turbulence_edr: float = profile.base_turbulence_edr
        self._pressure_delta_hpa: float = 0.0
        self._temp_delta_c: float = 0.0

        # Ramp start & target states
        self._start_wind_speed_mps: float = self._wind_speed_mps
        self._target_wind_speed_mps: float = self._wind_speed_mps
        self._start_wind_gust_mps: float = self._wind_gust_mps
        self._target_wind_gust_mps: float = self._wind_gust_mps
        self._start_wind_dir_deg: float = self._wind_direction_deg
        self._target_wind_dir_deg: float = self._wind_direction_deg
        self._start_edr: float = self._turbulence_edr
        self._target_edr: float = self._turbulence_edr
        self._start_pressure_delta: float = 0.0
        self._target_pressure_delta: float = 0.0
        self._start_temp_delta: float = 0.0
        self._target_temp_delta: float = 0.0
        self._start_altitude_agl_m: float = self.drone_altitude_agl_m
        self._target_altitude_agl_m: float = self.drone_altitude_agl_m

        self._ramp_elapsed_s: float = self.RAMP_DURATION_SECONDS
        self._sim_time_s: float = 0.0
        self._last_wall_monotonic: float = time.monotonic()
        self._session_created_monotonic: float = self._last_wall_monotonic
        self._ring_buffer: deque[TelemetryFrame] = deque(maxlen=1200)

        if initial_prompt:
            self.apply_prompt_directives(initial_prompt, immediate=True)

    @property
    def current_chunk_index(self) -> int:
        elapsed = max(self._sim_time_s, time.monotonic() - self._session_created_monotonic)
        return int(elapsed // ORBIS_CHUNK_DURATION_SECONDS)

    def reset_chunk_clock(self) -> None:
        self._session_created_monotonic = time.monotonic()
        self._last_wall_monotonic = self._session_created_monotonic
        self._sim_time_s = 0.0

    def apply_prompt_directives(
        self, prompt: str, *, immediate: bool = False
    ) -> dict[str, Any]:
        """Update meteorological & kinematic ramp targets from natural-language steering."""
        directives = parse_weather_directives(prompt)
        if not directives:
            return {
                "wind_speed_mps": round(self._target_wind_speed_mps, 2),
                "wind_gust_mps": round(self._target_wind_gust_mps, 2),
                "turbulence_edr": round(self._target_edr, 3),
                "pressure_delta_hpa": round(self._target_pressure_delta, 2),
            }

        self._start_wind_speed_mps = self._wind_speed_mps
        self._start_wind_gust_mps = self._wind_gust_mps
        self._start_wind_dir_deg = self._wind_direction_deg
        self._start_edr = self._turbulence_edr
        self._start_pressure_delta = self._pressure_delta_hpa
        self._start_temp_delta = self._temp_delta_c
        self._start_altitude_agl_m = self.drone_altitude_agl_m

        if "wind_speed_mps" in directives:
            self._target_wind_speed_mps = directives["wind_speed_mps"]
        if "wind_gust_mps" in directives:
            self._target_wind_gust_mps = max(
                self._target_wind_speed_mps + 1.0, directives["wind_gust_mps"]
            )
        if "wind_direction_deg" in directives:
            self._target_wind_dir_deg = directives["wind_direction_deg"] % 360.0
        if "turbulence_edr" in directives:
            self._target_edr = directives["turbulence_edr"]
        if "drone_altitude_agl_m" in directives:
            self._target_altitude_agl_m = directives["drone_altitude_agl_m"]
        if "temp_delta_c" in directives:
            self._target_temp_delta = directives["temp_delta_c"]

        if "explicit_pressure_hpa" in directives:
            profile = ECOSYSTEM_PROFILES[self.ecosystem_type]
            base_p, _, _ = compute_isa_atmosphere(
                profile.base_elevation_msl_m + self._target_altitude_agl_m,
                surface_temp_c=profile.surface_temp_c,
                drone_altitude_agl_m=self._target_altitude_agl_m,
            )
            self._target_pressure_delta = directives["explicit_pressure_hpa"] - base_p
        elif "pressure_delta_hpa" in directives:
            self._target_pressure_delta = directives["pressure_delta_hpa"]

        if immediate:
            self._ramp_elapsed_s = self.RAMP_DURATION_SECONDS
            self._apply_interpolation(1.0)
        else:
            # Begin smooth 2.5s chunk-aligned transition with an immediate 35% onset step
            # so rapid stream subscribers observe directional movement right away while
            # full convergence lands smoothly across 1-2 Orbis chunks (~2.5s).
            self._ramp_elapsed_s = 0.35 * self.RAMP_DURATION_SECONDS
            self._apply_interpolation(0.35)

        return {
            "wind_speed_mps": round(self._target_wind_speed_mps, 2),
            "wind_gust_mps": round(self._target_wind_gust_mps, 2),
            "wind_direction_deg": round(self._target_wind_dir_deg, 1),
            "turbulence_edr": round(self._target_edr, 3),
            "turbulence_level": classify_turbulence_level(self._target_edr),
            "drone_altitude_agl_m": round(self._target_altitude_agl_m, 1),
            "pressure_delta_hpa": round(self._target_pressure_delta, 2),
        }

    def adjust_flight(
        self,
        *,
        drone_altitude_agl_m: float | None = None,
        drone_airspeed_mps: float | None = None,
        camera_mode: str | None = None,
        ecosystem_type: EcosystemType | None = None,
    ) -> None:
        """Apply live WS flight_adjust updates without dropping the session."""
        if ecosystem_type is not None and ecosystem_type in SUPPORTED_ECOSYSTEMS:
            if ecosystem_type != self.ecosystem_type:
                self.ecosystem_type = ecosystem_type
                profile = ECOSYSTEM_PROFILES[ecosystem_type]
                self._start_wind_speed_mps = self._wind_speed_mps
                self._target_wind_speed_mps = profile.base_wind_speed_mps
                self._start_wind_gust_mps = self._wind_gust_mps
                self._target_wind_gust_mps = profile.base_wind_gust_mps
                self._start_wind_dir_deg = self._wind_direction_deg
                self._target_wind_dir_deg = profile.base_wind_direction_deg
                self._start_edr = self._turbulence_edr
                self._target_edr = profile.base_turbulence_edr
                self._ramp_elapsed_s = 0.5 * self.RAMP_DURATION_SECONDS

        if drone_altitude_agl_m is not None:
            clamped = max(1.0, min(5000.0, float(drone_altitude_agl_m)))
            self.drone_altitude_agl_m = clamped
            self._start_altitude_agl_m = clamped
            self._target_altitude_agl_m = clamped

        if drone_airspeed_mps is not None:
            self.drone_airspeed_mps = max(0.0, min(80.0, float(drone_airspeed_mps)))

        if camera_mode is not None and camera_mode in CAMERA_PITCH_BASE_DEG:
            self.camera_mode = camera_mode

    def _apply_interpolation(self, alpha: float) -> None:
        a = max(0.0, min(1.0, alpha))
        # Smoothstep easing: 3a^2 - 2a^3
        s = a * a * (3.0 - 2.0 * a)
        self._wind_speed_mps = self._start_wind_speed_mps + s * (
            self._target_wind_speed_mps - self._start_wind_speed_mps
        )
        self._wind_gust_mps = self._start_wind_gust_mps + s * (
            self._target_wind_gust_mps - self._start_wind_gust_mps
        )
        # Shortest angular path for wind direction
        delta_ang = ((self._target_wind_dir_deg - self._start_wind_dir_deg + 540.0) % 360.0) - 180.0
        self._wind_direction_deg = (self._start_wind_dir_deg + s * delta_ang) % 360.0
        self._turbulence_edr = self._start_edr + s * (self._target_edr - self._start_edr)
        self._pressure_delta_hpa = self._start_pressure_delta + s * (
            self._target_pressure_delta - self._start_pressure_delta
        )
        self._temp_delta_c = self._start_temp_delta + s * (
            self._target_temp_delta - self._start_temp_delta
        )
        self.drone_altitude_agl_m = self._start_altitude_agl_m + s * (
            self._target_altitude_agl_m - self._start_altitude_agl_m
        )

    def sample(
        self,
        *,
        dt_seconds: float | None = None,
        chunk_index: int | None = None,
        timestamp_ms: int | None = None,
    ) -> TelemetryFrame:
        """Advance physics clock and emit a normalized 16-field TelemetryFrame."""
        now_mono = time.monotonic()
        if dt_seconds is None:
            dt = max(0.02, min(1.0, now_mono - self._last_wall_monotonic))
        else:
            dt = max(0.0, float(dt_seconds))
        self._last_wall_monotonic = now_mono
        self._sim_time_s += dt

        if self._ramp_elapsed_s < self.RAMP_DURATION_SECONDS:
            self._ramp_elapsed_s = min(self.RAMP_DURATION_SECONDS, self._ramp_elapsed_s + dt)
            self._apply_interpolation(self._ramp_elapsed_s / self.RAMP_DURATION_SECONDS)

        g_long, g_lat, g_vert = _deterministic_gust_wave(self.session_seed, self._sim_time_s)
        profile = ECOSYSTEM_PROFILES[self.ecosystem_type]

        edr_scale = max(0.02, self._turbulence_edr)
        inst_wind = max(0.0, self._wind_speed_mps + g_long * (1.2 * edr_scale * 4.0))
        inst_gust = max(
            inst_wind,
            self._wind_gust_mps + abs(g_lat) * (1.5 * edr_scale * 4.5),
        )
        inst_dir = (self._wind_direction_deg + g_lat * 4.5) % 360.0
        inst_edr = max(0.01, self._turbulence_edr * (1.0 + 0.08 * g_vert))

        total_msl_m = profile.base_elevation_msl_m + self.drone_altitude_agl_m
        pressure_hpa, density_kgm3, temp_c = compute_isa_atmosphere(
            total_msl_m,
            surface_temp_c=profile.surface_temp_c,
            drone_altitude_agl_m=self.drone_altitude_agl_m,
            pressure_offset_hpa=self._pressure_delta_hpa,
            temp_offset_c=self._temp_delta_c,
        )

        # Coupled UAV attitude perturbations
        pitch_base = -6.0 if self.camera_mode == "forward_downward_oblique" else (
            -2.5 if self.camera_mode == "nadir_downward" else -8.5
        )
        pitch_deg = pitch_base + g_vert * (edr_scale * 6.5) - (inst_wind * 0.08)
        crosswind_rad = math.radians(inst_dir - self.drone_yaw_deg)
        crosswind_component = inst_wind * math.sin(crosswind_rad)
        roll_deg = max(-35.0, min(35.0, crosswind_component * 0.42 + g_lat * (edr_scale * 7.0)))
        yaw_deg = (self.drone_yaw_deg + g_lat * (edr_scale * 3.0)) % 360.0
        airspeed_mps = max(0.5, self.drone_airspeed_mps + g_long * 0.6)

        resolved_ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        resolved_chunk = chunk_index if chunk_index is not None else self.current_chunk_index

        frame = TelemetryFrame(
            timestamp_ms=resolved_ts,
            chunk_index=resolved_chunk,
            ecosystem_type=self.ecosystem_type,
            wind_speed_mps=round(inst_wind, 2),
            wind_gust_mps=round(inst_gust, 2),
            wind_direction_deg=round(inst_dir % 360.0, 1),
            air_pressure_hpa=pressure_hpa,
            air_density_kgm3=density_kgm3,
            ambient_temp_c=temp_c,
            turbulence_edr=round(inst_edr, 3),
            turbulence_level=classify_turbulence_level(inst_edr),
            drone_altitude_agl_m=round(self.drone_altitude_agl_m, 1),
            drone_airspeed_mps=round(airspeed_mps, 2),
            drone_pitch_deg=round(pitch_deg, 2),
            drone_roll_deg=round(roll_deg, 2),
            drone_yaw_deg=round(yaw_deg, 1),
        )
        self._append_to_ring_buffer(frame)
        return frame

    def _append_to_ring_buffer(self, frame: TelemetryFrame) -> None:
        self._ring_buffer.append(frame)
        cutoff_ms = frame.timestamp_ms - int(self.RING_BUFFER_WINDOW_SECONDS * 1000)
        while len(self._ring_buffer) > 1 and self._ring_buffer[0].timestamp_ms < cutoff_ms:
            self._ring_buffer.popleft()

    @property
    def latest_frame(self) -> TelemetryFrame:
        if self._ring_buffer:
            return self._ring_buffer[-1]
        return self.sample(dt_seconds=0.0)

    def get_recent_samples(self, duration_seconds: int) -> list[TelemetryFrame]:
        """Slice samples spanning the last `duration_seconds` from the 60s rolling ring buffer."""
        if not self._ring_buffer:
            self.sample(dt_seconds=0.1)
        latest_ts = self._ring_buffer[-1].timestamp_ms
        window_start_ms = latest_ts - int(duration_seconds * 1000)
        sliced = [f for f in self._ring_buffer if f.timestamp_ms >= window_start_ms]
        if len(sliced) < 3:
            # Ensure rich multi-sample representation across the window even if recorded immediately after session creation
            needed = max(5, duration_seconds * 2) - len(sliced)
            for _ in range(needed):
                sliced.append(self.sample(dt_seconds=0.15))
        return sliced

    def aggregate_window(self, duration_seconds: int) -> dict[str, Any]:
        """Compute exact BigQuery physics aggregates and telemetry_summary_json over capture window."""
        samples = self.get_recent_samples(duration_seconds)
        n = len(samples)

        avg_wind = sum(s.wind_speed_mps for s in samples) / n
        max_gust = max(s.wind_gust_mps for s in samples)
        sin_sum = sum(math.sin(math.radians(s.wind_direction_deg)) for s in samples)
        cos_sum = sum(math.cos(math.radians(s.wind_direction_deg)) for s in samples)
        mean_dir = (math.degrees(math.atan2(sin_sum / n, cos_sum / n)) + 360.0) % 360.0

        avg_pressure = sum(s.air_pressure_hpa for s in samples) / n
        avg_density = sum(s.air_density_kgm3 for s in samples) / n
        avg_temp = sum(s.ambient_temp_c for s in samples) / n
        avg_edr = sum(s.turbulence_edr for s in samples) / n
        max_edr = max(s.turbulence_edr for s in samples)
        avg_alt = sum(s.drone_altitude_agl_m for s in samples) / n

        summary_payload = {
            "sample_count": n,
            "window_duration_seconds": duration_seconds,
            "turbulence_level_peak": classify_turbulence_level(max_edr),
            "avg_drone_airspeed_mps": round(sum(s.drone_airspeed_mps for s in samples) / n, 2),
            "avg_drone_pitch_deg": round(sum(s.drone_pitch_deg for s in samples) / n, 2),
            "max_abs_drone_roll_deg": round(max(abs(s.drone_roll_deg) for s in samples), 2),
            "mean_drone_yaw_deg": round(sum(s.drone_yaw_deg for s in samples) / n, 1),
            "min_air_pressure_hpa": round(min(s.air_pressure_hpa for s in samples), 2),
            "max_air_pressure_hpa": round(max(s.air_pressure_hpa for s in samples), 2),
        }

        return {
            "avg_wind_speed_mps": round(avg_wind, 2),
            "max_wind_gust_mps": round(max_gust, 2),
            "wind_direction_deg": round(mean_dir, 1),
            "avg_air_pressure_hpa": round(avg_pressure, 2),
            "avg_air_density_kgm3": round(avg_density, 4),
            "ambient_temp_c": round(avg_temp, 2),
            "avg_turbulence_edr": round(avg_edr, 3),
            "max_turbulence_edr": round(max_edr, 3),
            "drone_altitude_agl_m": round(avg_alt, 1),
            "telemetry_summary_json": json.dumps(summary_payload),
        }


def build_ws_telemetry_envelope(session_id: str, frame: TelemetryFrame) -> dict[str, Any]:
    """Format canonical WS `telemetry` message with all 16 fields at top-level AND nested in `telemetry` and `data`."""
    payload = frame.model_dump()
    return {
        "type": "telemetry",
        "session_id": session_id,
        **payload,
        "telemetry": dict(payload),
        "data": dict(payload),
    }
