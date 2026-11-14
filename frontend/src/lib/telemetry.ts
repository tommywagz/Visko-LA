import type {
  CameraMode,
  EcosystemType,
  PromptEntry,
  TelemetryFrame,
  TurbulenceLevel,
} from '../types/api';

export type TurbulenceBadge = 'LIGHT' | 'MODERATE' | 'SEVERE' | 'EXTREME';

export interface TurbulenceClassification {
  level: TurbulenceLevel;
  badge: TurbulenceBadge;
  severityColor: string;
  color: string;
  label: string;
}

export const ECOSYSTEM_LABELS: Record<EcosystemType, string> = {
  alpine: 'Alpine Pass',
  coastal: 'Coastal Cliffs',
  urban_canyon: 'Urban Canyon',
  temperate_forest: 'Temperate Forest',
  arid_desert: 'Arid Desert',
  wetlands: 'River Wetlands',
  custom: 'Custom Terrain',
};

export const ECOSYSTEM_BASE_ELEVATION_MSL: Record<EcosystemType, number> = {
  coastal: 10,
  wetlands: 25,
  urban_canyon: 80,
  custom: 100,
  temperate_forest: 350,
  arid_desert: 450,
  alpine: 1650,
};

export const CAMERA_MODE_LABELS: Record<CameraMode, string> = {
  forward_downward_oblique: 'Forward + Downward (-35° Oblique)',
  nadir_downward: 'Nadir Top-Down (-90° Mapping)',
  forward_fpv: 'Forward FPV (-15° Corridor)',
};

function safeFinite(value: number, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export function formatWindSpeed(mps: number): string {
  const val = Math.max(0, safeFinite(mps, 0));
  return `${val.toFixed(1)} m/s`;
}

export function formatPressureHpa(hpa: number): string {
  const val = Math.max(0, safeFinite(hpa, 1013.25));
  return `${val.toFixed(1)} hPa`;
}

export function formatAirDensity(kgm3: number): string {
  const val = Math.max(0, safeFinite(kgm3, 1.225));
  return `${val.toFixed(3)} kg/m³`;
}

export function formatTemperatureC(tempC: number): string {
  const val = safeFinite(tempC, 15.0);
  const normalized = Object.is(val, -0) ? 0 : val;
  return `${normalized.toFixed(1)} °C`;
}

export function formatAltitudeAgl(meters: number): string {
  const val = Math.max(0, safeFinite(meters, 0));
  return `${val.toFixed(1)} m AGL`;
}

export function formatEdr(edr: number): string {
  const val = Math.max(0, safeFinite(edr, 0));
  return `${val.toFixed(2)} EDR`;
}

export function formatDurationPill(seconds: number): string {
  const totalSeconds = Math.max(0, Math.round(safeFinite(seconds, 0)));
  const minutes = Math.floor(totalSeconds / 60);
  const remSeconds = totalSeconds % 60;
  return `${minutes}:${String(remSeconds).padStart(2, '0')}`;
}

export function formatBytes(bytes: number): string {
  const val = Math.max(0, safeFinite(bytes, 0));
  if (val === 0) return '0 B';
  if (val < 1024) return `${Math.round(val)} B`;
  const kb = val / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  const gb = mb / 1024;
  return `${gb.toFixed(2)} GB`;
}

export function normalizeCompassDegrees(deg: number): number {
  if (typeof deg !== 'number' || !Number.isFinite(deg)) {
    return 0;
  }
  const wrapped = ((deg % 360) + 360) % 360;
  if (wrapped === 0 || wrapped >= 360 || Object.is(wrapped, -0)) {
    return 0;
  }
  const rounded = Number(wrapped.toFixed(6));
  return rounded >= 360 || rounded === 0 ? 0 : rounded;
}

const COMPASS_OCTANTS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const;

export function compassDirectionLabel(deg: number): string {
  const normalized = normalizeCompassDegrees(deg);
  const index = Math.floor(((normalized + 22.5) % 360) / 45) % 8;
  return COMPASS_OCTANTS[index];
}

export function classifyTurbulenceEdr(edr: number): TurbulenceClassification {
  const val = Math.max(0, safeFinite(edr, 0));
  if (val >= 0.7) {
    return {
      level: 'extreme',
      badge: 'EXTREME',
      severityColor: '#EF4444',
      color: '#EF4444',
      label: 'Extreme',
    };
  }
  if (val >= 0.45) {
    return {
      level: 'severe',
      badge: 'SEVERE',
      severityColor: '#EF4444',
      color: '#EF4444',
      label: 'Severe',
    };
  }
  if (val >= 0.2) {
    return {
      level: 'moderate',
      badge: 'MODERATE',
      severityColor: '#F59E0B',
      color: '#F59E0B',
      label: 'Moderate',
    };
  }
  return {
    level: 'light',
    badge: 'LIGHT',
    severityColor: '#10B981',
    color: '#10B981',
    label: 'Light',
  };
}

export function formatEcosystemLabel(slug: string | null | undefined): string {
  if (!slug) return 'Custom Terrain';
  const key = slug.trim().toLowerCase() as EcosystemType;
  if (key in ECOSYSTEM_LABELS) {
    return ECOSYSTEM_LABELS[key];
  }
  return slug
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export const getEcosystemLabel = formatEcosystemLabel;

export function formatCameraModeLabel(mode: string | null | undefined): string {
  if (!mode) return CAMERA_MODE_LABELS.forward_downward_oblique;
  const key = mode.trim() as CameraMode;
  return CAMERA_MODE_LABELS[key] ?? mode;
}

export function formatAttitudeDegrees(deg: number): string {
  const val = safeFinite(deg, 0);
  const normalized = Object.is(val, -0) ? 0 : val;
  const sign = normalized > 0 ? '+' : '';
  return `${sign}${normalized.toFixed(1)}°`;
}

export function extractTelemetryFrame(
  envelope: Record<string, unknown> | null | undefined
): TelemetryFrame | null {
  if (!envelope || typeof envelope !== 'object') return null;

  const candidate =
    (envelope.telemetry && typeof envelope.telemetry === 'object'
      ? (envelope.telemetry as Record<string, unknown>)
      : null) ??
    (envelope.data && typeof envelope.data === 'object'
      ? (envelope.data as Record<string, unknown>)
      : null) ??
    envelope;

  if (
    typeof candidate.wind_speed_mps !== 'number' &&
    typeof envelope.wind_speed_mps !== 'number'
  ) {
    return null;
  }

  const pickNum = (key: keyof TelemetryFrame, fallback = 0): number => {
    const raw = candidate[key] ?? envelope[key];
    return typeof raw === 'number' && Number.isFinite(raw) ? raw : fallback;
  };

  const pickStr = (key: keyof TelemetryFrame, fallback: string): string => {
    const raw = candidate[key] ?? envelope[key];
    return typeof raw === 'string' && raw.length > 0 ? raw : fallback;
  };

  const edr = pickNum('turbulence_edr', 0);
  return {
    timestamp_ms: pickNum('timestamp_ms', Date.now()),
    chunk_index: pickNum('chunk_index', 0),
    ecosystem_type: pickStr('ecosystem_type', 'alpine'),
    wind_speed_mps: pickNum('wind_speed_mps', 0),
    wind_gust_mps: pickNum('wind_gust_mps', pickNum('wind_speed_mps', 0)),
    wind_direction_deg: normalizeCompassDegrees(pickNum('wind_direction_deg', 0)),
    air_pressure_hpa: pickNum('air_pressure_hpa', 1013.25),
    air_density_kgm3: pickNum('air_density_kgm3', 1.225),
    ambient_temp_c: pickNum('ambient_temp_c', 15),
    turbulence_edr: edr,
    turbulence_level: pickStr('turbulence_level', classifyTurbulenceEdr(edr).level),
    drone_altitude_agl_m: pickNum('drone_altitude_agl_m', 65),
    drone_airspeed_mps: pickNum('drone_airspeed_mps', 12),
    drone_pitch_deg: pickNum('drone_pitch_deg', -5),
    drone_roll_deg: pickNum('drone_roll_deg', 0),
    drone_yaw_deg: normalizeCompassDegrees(pickNum('drone_yaw_deg', 0)),
  };
}

export function parsePromptHistoryJson(
  promptHistoryJson: string | null | undefined,
  fallbackPrompt?: string
): PromptEntry[] {
  if (promptHistoryJson && promptHistoryJson.trim().length > 0) {
    try {
      const parsed: unknown = JSON.parse(promptHistoryJson);
      if (Array.isArray(parsed)) {
        const items: PromptEntry[] = parsed
          .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
          .map((item, idx) => ({
            prompt_id:
              typeof item.prompt_id === 'string' ? item.prompt_id : `prm_${idx}`,
            prompt:
              typeof item.prompt === 'string'
                ? item.prompt
                : typeof item.raw_prompt === 'string'
                  ? item.raw_prompt
                  : '',
            compiled_prompt:
              typeof item.compiled_prompt === 'string'
                ? item.compiled_prompt
                : typeof item.prompt === 'string'
                  ? item.prompt
                  : '',
            passthrough: typeof item.passthrough === 'boolean' ? item.passthrough : true,
            chunk_index: typeof item.chunk_index === 'number' ? item.chunk_index : idx,
            status: typeof item.status === 'string' ? item.status : 'applied',
            created_at:
              typeof item.created_at === 'string'
                ? item.created_at
                : typeof item.timestamp === 'string'
                  ? item.timestamp
                  : new Date().toISOString(),
          }))
          .filter((entry) => entry.prompt.length > 0 || entry.compiled_prompt.length > 0);
        if (items.length > 0) {
          return items;
        }
      }
    } catch {
      // Fallback below if JSON string was malformed
    }
  }

  if (fallbackPrompt && fallbackPrompt.trim().length > 0) {
    return [
      {
        prompt_id: 'prm_initial',
        prompt: fallbackPrompt,
        compiled_prompt: fallbackPrompt,
        passthrough: true,
        chunk_index: 0,
        status: 'applied',
        created_at: new Date().toISOString(),
      },
    ];
  }

  return [];
}
