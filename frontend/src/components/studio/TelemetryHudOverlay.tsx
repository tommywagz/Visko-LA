'use client';

import React from 'react';
import {
  Activity,
  Compass,
  Eye,
  EyeOff,
  Gauge,
  Navigation,
  Wind,
} from 'lucide-react';
import type { TelemetryFrame } from '../../types/api';
import {
  classifyTurbulenceEdr,
  compassDirectionLabel,
  formatAirDensity,
  formatAltitudeAgl,
  formatAttitudeDegrees,
  formatEdr,
  formatPressureHpa,
  formatTemperatureC,
  formatWindSpeed,
  normalizeCompassDegrees,
} from '../../lib/telemetry';

export interface TelemetryHudOverlayProps {
  telemetry: TelemetryFrame;
  visible: boolean;
  onToggleVisible: () => void;
}

export function TelemetryHudOverlay({
  telemetry,
  visible,
  onToggleVisible,
}: TelemetryHudOverlayProps) {
  const windDeg = normalizeCompassDegrees(telemetry.wind_direction_deg);
  const windCard = compassDirectionLabel(windDeg);
  const turb = classifyTurbulenceEdr(telemetry.turbulence_edr);
  const edrPct = Math.min(100, Math.max(4, (telemetry.turbulence_edr / 0.85) * 100));
  const yawDeg = normalizeCompassDegrees(telemetry.drone_yaw_deg);

  const badgeClasses = (() => {
    switch (turb.level) {
      case 'light':
        return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40';
      case 'moderate':
        return 'bg-amber-500/20 text-amber-300 border-amber-500/40';
      case 'severe':
      case 'extreme':
      default:
        return 'bg-red-500/25 text-red-300 border-red-500/50';
    }
  })();

  return (
    <>
      {/* HUD Visibility Toggle Button */}
      <div className="absolute top-3 right-3 z-20 flex items-center gap-2">
        <button
          type="button"
          onClick={onToggleVisible}
          className="flex items-center gap-1.5 rounded-lg border border-slate-700/80 bg-[#0F172A]/90 px-2.5 py-1.5 text-xs font-medium text-slate-200 shadow-md backdrop-blur-sm hover:border-sky-500/50 hover:text-white transition"
        >
          {visible ? (
            <>
              <EyeOff className="h-3.5 w-3.5 text-sky-400" />
              <span>Hide HUD</span>
            </>
          ) : (
            <>
              <Eye className="h-3.5 w-3.5 text-sky-400" />
              <span>Show HUD</span>
            </>
          )}
        </button>
      </div>

      {visible && (
        <div
          data-testid="telemetry-hud"
          className="pointer-events-none absolute inset-x-3 bottom-3 z-10 grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-4"
        >
          {/* 1. Wind Vector Compass & Readout */}
          <div className="rounded-xl border border-slate-400/20 bg-[#0F172A]/85 p-3 backdrop-blur-md shadow-lg">
            <div className="flex items-center justify-between text-[11px] font-medium text-slate-400">
              <span className="flex items-center gap-1.5">
                <Wind className="h-3.5 w-3.5 text-[#38BDF8]" />
                WIND VECTOR
              </span>
              <span className="font-telemetry text-sky-300">
                {windDeg.toFixed(0)}° {windCard}
              </span>
            </div>
            <div className="mt-2 flex items-center justify-between gap-2">
              <div>
                <div className="font-telemetry text-lg font-bold text-white">
                  {formatWindSpeed(telemetry.wind_speed_mps)}
                </div>
                <div className="font-telemetry text-[11px] text-slate-400">
                  Gust: {formatWindSpeed(telemetry.wind_gust_mps)}
                </div>
              </div>
              <div
                aria-label={`Wind direction ${windDeg.toFixed(0)} degrees`}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-sky-500/30 bg-[#070B12]/90"
              >
                <Navigation
                  className="h-4 w-4 text-[#38BDF8] transition-transform duration-150"
                  style={{ transform: `rotate(${windDeg}deg)` }}
                />
              </div>
            </div>
          </div>

          {/* 2. Atmospheric Barometer Card */}
          <div className="rounded-xl border border-slate-400/20 bg-[#0F172A]/85 p-3 backdrop-blur-md shadow-lg">
            <div className="flex items-center justify-between text-[11px] font-medium text-slate-400">
              <span className="flex items-center gap-1.5">
                <Gauge className="h-3.5 w-3.5 text-emerald-400" />
                BAROMETER (ISA)
              </span>
              <span className="font-telemetry text-slate-300">
                {formatTemperatureC(telemetry.ambient_temp_c)}
              </span>
            </div>
            <div className="mt-2">
              <div className="font-telemetry text-lg font-bold text-white">
                {formatPressureHpa(telemetry.air_pressure_hpa)}
              </div>
              <div className="font-telemetry text-[11px] text-slate-400">
                Density: {formatAirDensity(telemetry.air_density_kgm3)}
              </div>
            </div>
          </div>

          {/* 3. Turbulence Gauge (EDR) */}
          <div className="rounded-xl border border-slate-400/20 bg-[#0F172A]/85 p-3 backdrop-blur-md shadow-lg">
            <div className="flex items-center justify-between text-[11px] font-medium text-slate-400">
              <span className="flex items-center gap-1.5">
                <Activity className="h-3.5 w-3.5" style={{ color: turb.severityColor }} />
                TURBULENCE (EDR)
              </span>
              <span
                className={`rounded border px-1.5 py-0.5 font-telemetry text-[10px] font-bold ${badgeClasses}`}
              >
                {turb.badge}
              </span>
            </div>
            <div className="mt-2">
              <div className="font-telemetry text-lg font-bold text-white">
                {formatEdr(telemetry.turbulence_edr)}
              </div>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full rounded-full transition-all duration-150"
                  style={{
                    width: `${edrPct}%`,
                    backgroundColor: turb.severityColor,
                  }}
                />
              </div>
            </div>
          </div>

          {/* 4. UAV Attitude & Altitude Readout */}
          <div className="rounded-xl border border-slate-400/20 bg-[#0F172A]/85 p-3 backdrop-blur-md shadow-lg">
            <div className="flex items-center justify-between text-[11px] font-medium text-slate-400">
              <span className="flex items-center gap-1.5">
                <Compass className="h-3.5 w-3.5 text-[#4285F4]" />
                UAV KINEMATICS
              </span>
              <span className="font-telemetry text-slate-300">
                {formatWindSpeed(telemetry.drone_airspeed_mps)} TAS
              </span>
            </div>
            <div className="mt-2">
              <div className="font-telemetry text-lg font-bold text-white">
                {formatAltitudeAgl(telemetry.drone_altitude_agl_m)}
              </div>
              <div className="font-telemetry text-[11px] text-slate-400">
                P {formatAttitudeDegrees(telemetry.drone_pitch_deg)} · R{' '}
                {formatAttitudeDegrees(telemetry.drone_roll_deg)} · Y {yawDeg.toFixed(0)}°
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
