import { describe, expect, it } from 'vitest';
import {
  classifyTurbulenceEdr,
  compassDirectionLabel,
  extractTelemetryFrame,
  formatAirDensity,
  formatAltitudeAgl,
  formatAttitudeDegrees,
  formatBytes,
  formatCameraModeLabel,
  formatDurationPill,
  formatEcosystemLabel,
  formatEdr,
  formatPressureHpa,
  formatTemperatureC,
  formatWindSpeed,
  normalizeCompassDegrees,
  parsePromptHistoryJson,
} from '../../../frontend/src/lib/telemetry';
import {
  buildBreadcrumbs,
  buildFolderTree,
  filterDatasets,
  getChildFolders,
  normalizeFolderPath,
  sortDatasets,
} from '../../../frontend/src/lib/drive-filters';
import type { DatasetRecord, FolderRecord } from '../../../frontend/src/types/api';

function makeFolder(overrides: Partial<FolderRecord> & { folder_id: string; name: string }): FolderRecord {
  return {
    project_id: 'default-uav-project',
    parent_folder_id: 'root',
    folder_path: `/${overrides.folder_id}`,
    ecosystem_default: null,
    dataset_count: 0,
    created_at: '2026-11-14T22:00:00Z',
    ...overrides,
  };
}

function makeDataset(overrides: Partial<DatasetRecord> & { video_id: string }): DatasetRecord {
  return {
    project_id: 'default-uav-project',
    folder_id: 'root',
    folder_path: '/',
    title: `Clip ${overrides.video_id}`,
    session_id: 'sess_01',
    model_id: 'reactor/visko-orbis-stable',
    ecosystem_type: 'alpine',
    duration_seconds: 5,
    resolution: '1080p',
    fps: 18,
    gcs_video_uri: `gs://visko-orbis-aerial-datasets/datasets/default-uav-project/root/${overrides.video_id}.mp4`,
    seed_media_gcs_uri: null,
    initial_prompt: 'Stabilized nose-mounted UAV perception camera cruising over alpine pass',
    prompt_history_json: '[]',
    avg_wind_speed_mps: 12.0,
    max_wind_gust_mps: 16.5,
    wind_direction_deg: 245.0,
    avg_air_pressure_hpa: 832.4,
    avg_air_density_kgm3: 1.031,
    ambient_temp_c: 3.2,
    avg_turbulence_edr: 0.18,
    max_turbulence_edr: 0.24,
    drone_altitude_agl_m: 65.0,
    telemetry_summary_json: '{}',
    file_size_bytes: 24576,
    created_at: '2026-11-14T22:30:00Z',
    ...overrides,
  };
}

describe('HUD Telemetry Formatting, Compass Wrapping & EDR Severity Classification', () => {
  it('formats tabular telemetry units with exact precision and safe non-negative clamping', () => {
    expect(formatWindSpeed(14.24)).toBe('14.2 m/s');
    expect(formatWindSpeed(-3.5)).toBe('0.0 m/s');
    expect(formatWindSpeed(Number.NaN)).toBe('0.0 m/s');

    expect(formatPressureHpa(1013.25)).toBe('1013.3 hPa');
    expect(formatPressureHpa(832.41)).toBe('832.4 hPa');

    expect(formatAirDensity(1.0314)).toBe('1.031 kg/m³');
    expect(formatTemperatureC(-4.26)).toBe('-4.3 °C');
    expect(formatTemperatureC(-0)).toBe('0.0 °C');
    expect(formatAltitudeAgl(65)).toBe('65.0 m AGL');
    expect(formatEdr(0.358)).toBe('0.36 EDR');

    expect(formatDurationPill(5)).toBe('0:05');
    expect(formatDurationPill(10)).toBe('0:10');
    expect(formatDurationPill(15)).toBe('0:15');

    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');

    expect(formatAttitudeDegrees(4.12)).toBe('+4.1°');
    expect(formatAttitudeDegrees(-6.24)).toBe('-6.2°');
    expect(formatAttitudeDegrees(-0)).toBe('0.0°');

    expect(formatEcosystemLabel('urban_canyon')).toBe('Urban Canyon');
    expect(formatCameraModeLabel('nadir_downward')).toContain('-90°');
  });

  it('T2-08: wraps compass bearings strictly into [0, 360) and assigns octant labels', () => {
    expect(normalizeCompassDegrees(0)).toBe(0);
    expect(normalizeCompassDegrees(360)).toBe(0);
    expect(normalizeCompassDegrees(-360)).toBe(0);
    expect(normalizeCompassDegrees(-45)).toBe(315);
    expect(normalizeCompassDegrees(725)).toBe(5);
    expect(normalizeCompassDegrees(Number.POSITIVE_INFINITY)).toBe(0);

    expect(compassDirectionLabel(0)).toBe('N');
    expect(compassDirectionLabel(45)).toBe('NE');
    expect(compassDirectionLabel(90)).toBe('E');
    expect(compassDirectionLabel(135)).toBe('SE');
    expect(compassDirectionLabel(180)).toBe('S');
    expect(compassDirectionLabel(225)).toBe('SW');
    expect(compassDirectionLabel(270)).toBe('W');
    expect(compassDirectionLabel(315)).toBe('NW');
    expect(compassDirectionLabel(-45)).toBe('NW');
  });

  it('T2-08: classifies EDR turbulence thresholds accurately across LIGHT, MODERATE, SEVERE, EXTREME', () => {
    expect(classifyTurbulenceEdr(0.0)).toMatchObject({
      level: 'light',
      badge: 'LIGHT',
      severityColor: '#10B981',
    });
    expect(classifyTurbulenceEdr(0.199)).toMatchObject({
      level: 'light',
      badge: 'LIGHT',
    });
    expect(classifyTurbulenceEdr(0.2)).toMatchObject({
      level: 'moderate',
      badge: 'MODERATE',
      severityColor: '#F59E0B',
    });
    expect(classifyTurbulenceEdr(0.449)).toMatchObject({
      level: 'moderate',
      badge: 'MODERATE',
    });
    expect(classifyTurbulenceEdr(0.45)).toMatchObject({
      level: 'severe',
      badge: 'SEVERE',
      severityColor: '#EF4444',
    });
    expect(classifyTurbulenceEdr(0.699)).toMatchObject({
      level: 'severe',
      badge: 'SEVERE',
    });
    expect(classifyTurbulenceEdr(0.7)).toMatchObject({
      level: 'extreme',
      badge: 'EXTREME',
      severityColor: '#EF4444',
    });
  });

  it('extracts telemetry frames from flattened, telemetry-nested, and data-nested WS envelopes', () => {
    const flattened = extractTelemetryFrame({
      type: 'telemetry',
      wind_speed_mps: 15.4,
      wind_direction_deg: -30,
      air_pressure_hpa: 830.1,
      turbulence_edr: 0.52,
      drone_altitude_agl_m: 80,
    });
    expect(flattened).not.toBeNull();
    expect(flattened?.wind_speed_mps).toBe(15.4);
    expect(flattened?.wind_direction_deg).toBe(330);
    expect(flattened?.turbulence_level).toBe('severe');

    const nestedData = extractTelemetryFrame({
      type: 'telemetry',
      data: {
        wind_speed_mps: 8.2,
        air_pressure_hpa: 1011.5,
        turbulence_edr: 0.11,
        drone_altitude_agl_m: 40,
      },
    });
    expect(nestedData?.wind_speed_mps).toBe(8.2);
    expect(nestedData?.turbulence_level).toBe('light');

    expect(extractTelemetryFrame({ type: 'pong', timestamp_ms: 123 })).toBeNull();
    expect(extractTelemetryFrame(null)).toBeNull();
  });

  it('parses prompt_history_json safely with fallback to initial_prompt on malformed JSON', () => {
    const validJson = JSON.stringify([
      {
        prompt_id: 'prm_1',
        prompt: 'Initial alpine pass',
        compiled_prompt: 'Stabilized UAV camera...',
        passthrough: true,
        chunk_index: 0,
        status: 'applied',
        created_at: '2026-11-14T22:00:00Z',
      },
    ]);
    const parsed = parsePromptHistoryJson(validJson, 'Fallback');
    expect(parsed).toHaveLength(1);
    expect(parsed[0].prompt_id).toBe('prm_1');

    const recovered = parsePromptHistoryJson('{not-valid-json', 'Fallback initial prompt');
    expect(recovered).toHaveLength(1);
    expect(recovered[0].prompt).toBe('Fallback initial prompt');
  });
});

describe('Drive Folder Hierarchy, Breadcrumbs, Multi-Criteria Filtering & Sorting', () => {
  const folders: FolderRecord[] = [
    makeFolder({
      folder_id: 'root',
      name: 'My Aerial Datasets',
      parent_folder_id: null,
      folder_path: '/',
    }),
    makeFolder({
      folder_id: 'coastal-winds',
      name: 'Coastal Winds',
      parent_folder_id: 'root',
      folder_path: '/coastal-winds',
    }),
    makeFolder({
      folder_id: 'mountain-rotors',
      name: 'Mountain Rotors',
      parent_folder_id: 'root',
      folder_path: '/mountain-rotors',
    }),
    makeFolder({
      folder_id: 'gust-runs',
      name: 'Gust Runs',
      parent_folder_id: 'coastal-winds',
      folder_path: '/coastal-winds/gust-runs',
    }),
  ];

  const datasets: DatasetRecord[] = [
    makeDataset({
      video_id: 'vid_coastal_5s',
      folder_id: 'coastal-winds',
      folder_path: '/coastal-winds',
      title: 'Coastal Breakwater 5s',
      ecosystem_type: 'coastal',
      duration_seconds: 5,
      avg_wind_speed_mps: 9.4,
      avg_air_pressure_hpa: 1011.8,
      max_turbulence_edr: 0.15,
      file_size_bytes: 18000,
      initial_prompt: 'Onshore breeze over turquoise marina breakwater',
      created_at: '2026-11-14T22:10:00Z',
    }),
    makeDataset({
      video_id: 'vid_rotor_10s',
      folder_id: 'mountain-rotors',
      folder_path: '/mountain-rotors',
      title: 'Severe Ridge Rotor 10s',
      ecosystem_type: 'alpine',
      duration_seconds: 10,
      avg_wind_speed_mps: 22.5,
      avg_air_pressure_hpa: 826.4,
      max_turbulence_edr: 0.58,
      file_size_bytes: 42000,
      initial_prompt: 'Heavy crosswind storm gusts over granite ridge',
      created_at: '2026-11-14T22:20:00Z',
    }),
    makeDataset({
      video_id: 'vid_gust_15s',
      folder_id: 'gust-runs',
      folder_path: '/coastal-winds/gust-runs',
      title: 'Extreme Squall 15s',
      ecosystem_type: 'coastal',
      duration_seconds: 15,
      avg_wind_speed_mps: 27.1,
      avg_air_pressure_hpa: 1002.1,
      max_turbulence_edr: 0.76,
      file_size_bytes: 64000,
      initial_prompt: 'Gale squall whipping whitecaps across pier',
      created_at: '2026-11-14T22:30:00Z',
    }),
  ];

  it('normalizes folder paths, builds hierarchical trees, and resolves breadcrumbs', () => {
    expect(normalizeFolderPath('')).toBe('/');
    expect(normalizeFolderPath('/')).toBe('/');
    expect(normalizeFolderPath('coastal-winds//gust-runs/')).toBe('/coastal-winds/gust-runs');
    expect(normalizeFolderPath('\\mountain-rotors\\sub\\')).toBe('/mountain-rotors/sub');

    const tree = buildFolderTree(folders);
    expect(tree).toHaveLength(1);
    expect(tree[0].folder_id).toBe('root');
    expect(tree[0].children.map((c) => c.folder_id)).toEqual([
      'coastal-winds',
      'mountain-rotors',
    ]);
    expect(tree[0].children[0].children[0].folder_id).toBe('gust-runs');
    expect(tree[0].children[0].children[0].depth).toBe(2);

    const rootChildren = getChildFolders(folders, 'root');
    expect(rootChildren.map((f) => f.folder_id)).toEqual(['coastal-winds', 'mountain-rotors']);

    const crumbs = buildBreadcrumbs(folders, 'gust-runs');
    expect(crumbs.map((c) => c.folder_id)).toEqual(['root', 'coastal-winds', 'gust-runs']);
    expect(buildBreadcrumbs(folders, 'all')[0].name).toBe('All Datasets');
  });

  it('filters datasets strictly by folder, duration, ecosystem, EDR severity, and keyword search', () => {
    // Folder isolation vs 'all'
    expect(filterDatasets(datasets, { folderId: 'all' })).toHaveLength(3);
    expect(filterDatasets(datasets, { folderId: 'coastal-winds' }).map((d) => d.video_id)).toEqual([
      'vid_coastal_5s',
    ]);
    expect(filterDatasets(datasets, { folderId: 'mountain-rotors' }).map((d) => d.video_id)).toEqual([
      'vid_rotor_10s',
    ]);

    // Duration filter (number and '15s' string)
    expect(filterDatasets(datasets, { durationSeconds: 10 }).map((d) => d.video_id)).toEqual([
      'vid_rotor_10s',
    ]);
    expect(filterDatasets(datasets, { durationSeconds: '15s' }).map((d) => d.video_id)).toEqual([
      'vid_gust_15s',
    ]);

    // Ecosystem + severe_plus EDR filter
    expect(
      filterDatasets(datasets, {
        ecosystemType: 'coastal',
        turbulenceFilter: 'severe_plus',
      }).map((d) => d.video_id)
    ).toEqual(['vid_gust_15s']);

    // Case-insensitive search across initial_prompt & folder_path
    expect(filterDatasets(datasets, { search: 'GRANITE RIDGE' }).map((d) => d.video_id)).toEqual([
      'vid_rotor_10s',
    ]);
    expect(filterDatasets(datasets, { search: '/coastal-winds/gust-runs' }).map((d) => d.video_id)).toEqual([
      'vid_gust_15s',
    ]);
  });

  it('sorts datasets deterministically across telemetry and file metadata columns', () => {
    expect(sortDatasets(datasets, 'avg_wind_speed_mps', 'desc').map((d) => d.video_id)).toEqual([
      'vid_gust_15s',
      'vid_rotor_10s',
      'vid_coastal_5s',
    ]);
    expect(sortDatasets(datasets, 'avg_air_pressure_hpa', 'asc').map((d) => d.video_id)).toEqual([
      'vid_rotor_10s',
      'vid_gust_15s',
      'vid_coastal_5s',
    ]);
    expect(sortDatasets(datasets, 'duration_seconds', 'asc').map((d) => d.video_id)).toEqual([
      'vid_coastal_5s',
      'vid_rotor_10s',
      'vid_gust_15s',
    ]);
    expect(sortDatasets(datasets, 'title', 'asc').map((d) => d.video_id)).toEqual([
      'vid_coastal_5s',
      'vid_gust_15s',
      'vid_rotor_10s',
    ]);
  });
});
