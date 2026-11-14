import { describe, expect, it } from 'vitest';
import {
  classifyTurbulenceEdr,
  compassDirectionLabel,
  extractTelemetryFrame,
  formatAirDensity,
  formatAltitudeAgl,
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
} from '../telemetry';
import {
  buildBreadcrumbs,
  buildFolderTree,
  filterDatasets,
  getChildFolders,
  normalizeFolderPath,
  sortDatasets,
} from '../drive-filters';
import {
  clearCachedReactorJwt,
  createMemoizedJwtResolver,
  getCachedReactorJwt,
  primeCachedReactorJwt,
} from '../jwt-cache';
import type { DatasetRecord, FolderRecord } from '../../types/api';

describe('telemetry.ts pure formatting & classification helpers', () => {
  it('formats tabular telemetry units deterministically', () => {
    expect(formatWindSpeed(14.24)).toBe('14.2 m/s');
    expect(formatWindSpeed(-3)).toBe('0.0 m/s');
    expect(formatPressureHpa(832.44)).toBe('832.4 hPa');
    expect(formatAirDensity(1.0312)).toBe('1.031 kg/m³');
    expect(formatTemperatureC(2.44)).toBe('2.4 °C');
    expect(formatTemperatureC(-0)).toBe('0.0 °C');
    expect(formatAltitudeAgl(65)).toBe('65.0 m AGL');
    expect(formatEdr(0.36)).toBe('0.36 EDR');
  });

  it('formats duration pills and byte counts cleanly', () => {
    expect(formatDurationPill(5)).toBe('0:05');
    expect(formatDurationPill(10)).toBe('0:10');
    expect(formatDurationPill(15)).toBe('0:15');
    expect(formatDurationPill(75)).toBe('1:15');

    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(formatBytes(2 * 1024 * 1024 * 1024)).toBe('2.00 GB');
  });

  it('wraps compass angles strictly into [0, 360) and maps 8-point cardinal labels', () => {
    expect(normalizeCompassDegrees(0)).toBe(0);
    expect(normalizeCompassDegrees(360)).toBe(0);
    expect(normalizeCompassDegrees(-360)).toBe(0);
    expect(normalizeCompassDegrees(-45)).toBe(315);
    expect(normalizeCompassDegrees(-15)).toBe(345);
    expect(normalizeCompassDegrees(725)).toBe(5);
    expect(normalizeCompassDegrees(248.5)).toBe(248.5);

    expect(compassDirectionLabel(0)).toBe('N');
    expect(compassDirectionLabel(45)).toBe('NE');
    expect(compassDirectionLabel(90)).toBe('E');
    expect(compassDirectionLabel(135)).toBe('SE');
    expect(compassDirectionLabel(180)).toBe('S');
    expect(compassDirectionLabel(225)).toBe('SW');
    expect(compassDirectionLabel(270)).toBe('W');
    expect(compassDirectionLabel(-45)).toBe('NW');
  });

  it('classifies turbulence EDR across exact thresholds (<0.20, 0.20..0.449, 0.45..0.699, >=0.70)', () => {
    expect(classifyTurbulenceEdr(0.0)).toMatchObject({
      level: 'light',
      badge: 'LIGHT',
      severityColor: '#10B981',
    });
    expect(classifyTurbulenceEdr(0.199)).toMatchObject({
      level: 'light',
      badge: 'LIGHT',
      severityColor: '#10B981',
    });
    expect(classifyTurbulenceEdr(0.2)).toMatchObject({
      level: 'moderate',
      badge: 'MODERATE',
      severityColor: '#F59E0B',
    });
    expect(classifyTurbulenceEdr(0.449)).toMatchObject({
      level: 'moderate',
      badge: 'MODERATE',
      severityColor: '#F59E0B',
    });
    expect(classifyTurbulenceEdr(0.45)).toMatchObject({
      level: 'severe',
      badge: 'SEVERE',
      severityColor: '#EF4444',
    });
    expect(classifyTurbulenceEdr(0.699)).toMatchObject({
      level: 'severe',
      badge: 'SEVERE',
      severityColor: '#EF4444',
    });
    expect(classifyTurbulenceEdr(0.7)).toMatchObject({
      level: 'extreme',
      badge: 'EXTREME',
      severityColor: '#EF4444',
    });
  });

  it('maps ecosystem slugs, camera modes, WS telemetry envelopes, and prompt history JSON', () => {
    expect(formatEcosystemLabel('alpine')).toBe('Alpine Pass');
    expect(formatEcosystemLabel('coastal')).toBe('Coastal Cliffs');
    expect(formatEcosystemLabel('urban_canyon')).toBe('Urban Canyon');
    expect(formatCameraModeLabel('forward_downward_oblique')).toContain('-35°');

    const extracted = extractTelemetryFrame({
      type: 'telemetry',
      session_id: 'sess_1',
      telemetry: {
        timestamp_ms: 1000,
        chunk_index: 2,
        ecosystem_type: 'alpine',
        wind_speed_mps: 15.4,
        wind_gust_mps: 20.1,
        wind_direction_deg: -10,
        air_pressure_hpa: 830.2,
        air_density_kgm3: 1.02,
        ambient_temp_c: 3.1,
        turbulence_edr: 0.48,
        turbulence_level: 'severe',
        drone_altitude_agl_m: 80,
        drone_airspeed_mps: 12,
        drone_pitch_deg: -5,
        drone_roll_deg: 2,
        drone_yaw_deg: 370,
      },
    });
    expect(extracted).not.toBeNull();
    expect(extracted?.wind_direction_deg).toBe(350);
    expect(extracted?.drone_yaw_deg).toBe(10);

    const history = parsePromptHistoryJson(
      JSON.stringify([
        {
          prompt_id: 'p1',
          prompt: 'Increase crosswind to 20 m/s',
          compiled_prompt: 'Maintaining continuous...',
          passthrough: true,
          chunk_index: 3,
          status: 'applied',
          created_at: '2026-11-14T22:00:00Z',
        },
      ])
    );
    expect(history).toHaveLength(1);
    expect(history[0].chunk_index).toBe(3);
  });
});

describe('drive-filters.ts folder hierarchy & dataset query helpers', () => {
  const sampleFolders: FolderRecord[] = [
    {
      folder_id: 'root',
      project_id: 'default-uav-project',
      parent_folder_id: null,
      name: 'My Aerial Datasets',
      folder_path: '/',
      ecosystem_default: null,
      created_at: '2026-11-14T20:00:00Z',
    },
    {
      folder_id: 'coastal-crosswinds',
      project_id: 'default-uav-project',
      parent_folder_id: 'root',
      name: 'Coastal Crosswinds',
      folder_path: '/coastal-crosswinds',
      ecosystem_default: 'coastal',
      created_at: '2026-11-14T20:01:00Z',
    },
    {
      folder_id: 'storm-gusts',
      project_id: 'default-uav-project',
      parent_folder_id: 'coastal-crosswinds',
      name: 'Storm Gusts',
      folder_path: '/coastal-crosswinds/storm-gusts/',
      ecosystem_default: 'coastal',
      created_at: '2026-11-14T20:02:00Z',
    },
  ];

  const makeDataset = (overrides: Partial<DatasetRecord>): DatasetRecord => ({
    video_id: 'vid_1',
    project_id: 'default-uav-project',
    folder_id: 'root',
    folder_path: '/',
    title: 'Alpine Dawn Run',
    session_id: 'sess_1',
    model_id: 'reactor/visko-orbis-stable',
    ecosystem_type: 'alpine',
    duration_seconds: 5,
    resolution: '1080p',
    fps: 18,
    gcs_video_uri: 'gs://bucket/datasets/default-uav-project/root/vid_1.mp4',
    seed_media_gcs_uri: null,
    initial_prompt: 'Stabilized nose-mounted UAV over alpine pass',
    prompt_history_json: '[]',
    avg_wind_speed_mps: 12.0,
    max_wind_gust_mps: 16.5,
    wind_direction_deg: 240,
    avg_air_pressure_hpa: 835.0,
    avg_air_density_kgm3: 1.03,
    ambient_temp_c: 2.5,
    avg_turbulence_edr: 0.14,
    max_turbulence_edr: 0.18,
    drone_altitude_agl_m: 65,
    telemetry_summary_json: null,
    file_size_bytes: 1_200_000,
    created_at: '2026-11-14T21:00:00Z',
    ...overrides,
  });

  it('normalizes folder paths, builds trees, breadcrumbs, and child folder lists', () => {
    expect(normalizeFolderPath('')).toBe('/');
    expect(normalizeFolderPath('///coastal-crosswinds//storm-gusts/')).toBe(
      '/coastal-crosswinds/storm-gusts'
    );

    const tree = buildFolderTree(sampleFolders);
    expect(tree).toHaveLength(1);
    expect(tree[0].folder_id).toBe('root');
    expect(tree[0].children[0].folder_id).toBe('coastal-crosswinds');
    expect(tree[0].children[0].children[0].folder_id).toBe('storm-gusts');

    const children = getChildFolders(sampleFolders, 'root');
    expect(children.map((f) => f.folder_id)).toEqual(['coastal-crosswinds']);

    const crumbs = buildBreadcrumbs(sampleFolders, 'storm-gusts');
    expect(crumbs.map((c) => c.folder_id)).toEqual([
      'root',
      'coastal-crosswinds',
      'storm-gusts',
    ]);
  });

  it('filters and sorts datasets across folder, search, duration, ecosystem, and EDR', () => {
    const datasets: DatasetRecord[] = [
      makeDataset({
        video_id: 'vid_alpine_5',
        folder_id: 'root',
        title: 'Alpine Pass Calm 5s',
        ecosystem_type: 'alpine',
        duration_seconds: 5,
        avg_wind_speed_mps: 8.5,
        max_turbulence_edr: 0.12,
        created_at: '2026-11-14T21:00:00Z',
      }),
      makeDataset({
        video_id: 'vid_coastal_10',
        folder_id: 'coastal-crosswinds',
        folder_path: '/coastal-crosswinds',
        title: 'Coastal Storm Rotor 10s',
        ecosystem_type: 'coastal',
        duration_seconds: 10,
        avg_wind_speed_mps: 22.4,
        max_turbulence_edr: 0.56,
        created_at: '2026-11-14T21:10:00Z',
      }),
      makeDataset({
        video_id: 'vid_urban_15',
        folder_id: 'coastal-crosswinds',
        folder_path: '/coastal-crosswinds',
        title: 'Urban Moderate Shear 15s',
        ecosystem_type: 'urban_canyon',
        duration_seconds: 15,
        avg_wind_speed_mps: 14.0,
        max_turbulence_edr: 0.31,
        created_at: '2026-11-14T21:05:00Z',
      }),
    ];

    expect(filterDatasets(datasets, { folderId: 'all' })).toHaveLength(3);
    expect(filterDatasets(datasets, { folderId: 'root' })).toHaveLength(1);
    expect(
      filterDatasets(datasets, { folderId: 'coastal-crosswinds', durationSeconds: 10 })
    ).toHaveLength(1);
    expect(
      filterDatasets(datasets, { search: 'rotor' }).map((d) => d.video_id)
    ).toEqual(['vid_coastal_10']);
    expect(
      filterDatasets(datasets, { turbulenceFilter: 'severe_plus' }).map(
        (d) => d.video_id
      )
    ).toEqual(['vid_coastal_10']);

    const sortedByWind = sortDatasets(datasets, 'avg_wind_speed_mps', 'desc');
    expect(sortedByWind.map((d) => d.video_id)).toEqual([
      'vid_coastal_10',
      'vid_urban_15',
      'vid_alpine_5',
    ]);
  });
});

describe('jwt-cache.ts session JWT memoization', () => {
  it('memoizes JWT until expires_at * 1000 - 60_000 and refreshes once inside 60s window', async () => {
    clearCachedReactorJwt();
    const nowSec = Math.floor(Date.now() / 1000);
    primeCachedReactorJwt('sess_abc', 'jwt_initial', nowSec + 3600);
    expect(getCachedReactorJwt('sess_abc')).toBe('jwt_initial');

    // Expired within 60-second safety margin
    primeCachedReactorJwt('sess_expiring', 'jwt_old', nowSec + 30);
    expect(getCachedReactorJwt('sess_expiring')).toBeNull();

    let calls = 0;
    const resolver = createMemoizedJwtResolver('sess_memo', async () => {
      calls += 1;
      return {
        jwt: `jwt_minted_${calls}`,
        expires_at: Math.floor(Date.now() / 1000) + 3600,
        model_id: 'reactor/visko-orbis-stable',
        mode: 'mock',
      };
    });

    const t1 = await resolver();
    const t2 = await resolver();
    expect(t1).toBe('jwt_minted_1');
    expect(t2).toBe('jwt_minted_1');
    expect(calls).toBe(1);
  });
});
