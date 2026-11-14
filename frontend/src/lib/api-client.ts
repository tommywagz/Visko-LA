import type {
  CameraMode,
  CreateFolderRequest,
  CreateProjectRequest,
  CreateSessionRequest,
  DatasetDownloadResponse,
  DatasetListResponse,
  DatasetRecord,
  EcosystemType,
  FolderRecord,
  HealthResponse,
  PresetCatalogResponse,
  ProjectRecord,
  ReactorTokenRequest,
  ReactorTokenResponse,
  ReanchorSeedRequest,
  ReanchorSeedResponse,
  RecordClipRequest,
  SeedFromPresetRequest,
  SeedMediaResponse,
  SessionStateResponse,
  SteerPromptRequest,
  SteerPromptResponse,
  SystemPromptResponse,
  UpdateDatasetRequest,
} from '../types/api';

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
).replace(/\/+$/, '');

export const WS_BASE_URL = (
  process.env.NEXT_PUBLIC_WS_BASE_URL || 'ws://localhost:8000'
).replace(/\/+$/, '');

export class ApiHttpError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`);
    this.name = 'ApiHttpError';
    this.status = status;
    this.detail = detail;
  }
}

export function resolveApiAssetUrl(pathOrUrl: string | null | undefined): string {
  if (!pathOrUrl) return '';
  if (/^https?:\/\//i.test(pathOrUrl) || pathOrUrl.startsWith('blob:') || pathOrUrl.startsWith('data:')) {
    return pathOrUrl;
  }
  const normalized = pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`;
  return `${API_BASE_URL}${normalized}`;
}

export function resolveSessionWsUrl(
  sessionId: string,
  wsUrlFromServer?: string | null
): string {
  if (wsUrlFromServer && /^wss?:\/\//i.test(wsUrlFromServer)) {
    return wsUrlFromServer;
  }
  const pathPart =
    wsUrlFromServer && wsUrlFromServer.startsWith('/')
      ? wsUrlFromServer
      : `/ws/orbis/stream/${encodeURIComponent(sessionId)}`;
  return `${WS_BASE_URL}${pathPart}`;
}

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown; message?: string };
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((item) =>
          item && typeof item === 'object' && 'msg' in item
            ? String((item as { msg?: unknown }).msg)
            : JSON.stringify(item)
        )
        .join('; ');
    }
    if (typeof body.message === 'string') return body.message;
  } catch {
    // Ignore JSON parse failure on non-JSON error bodies
  }
  return `Request failed with HTTP ${res.status}`;
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(url, {
    ...init,
    headers,
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await parseErrorDetail(res);
    throw new ApiHttpError(res.status, detail);
  }

  return (await res.json()) as T;
}

// 1. Health & Auth
export async function fetchHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/api/v1/health');
}

export async function mintReactorToken(
  payload: ReactorTokenRequest = {}
): Promise<ReactorTokenResponse> {
  return requestJson<ReactorTokenResponse>('/api/v1/auth/reactor-token', {
    method: 'POST',
    body: JSON.stringify({
      model_id: 'reactor/visko-orbis-stable',
      ...payload,
    }),
  });
}

export async function fetchSystemPrompt(
  cameraMode?: CameraMode
): Promise<SystemPromptResponse> {
  const qs = cameraMode ? `?camera_mode=${encodeURIComponent(cameraMode)}` : '';
  return requestJson<SystemPromptResponse>(`/api/v1/sessions/system-prompt${qs}`);
}

// 2. Seed Media & Presets
export async function fetchMediaPresets(
  limit = 12,
  offset = 0
): Promise<PresetCatalogResponse> {
  return requestJson<PresetCatalogResponse>(
    `/api/v1/media/presets?limit=${limit}&offset=${offset}`
  );
}

export async function createSeedFromPreset(
  payload: SeedFromPresetRequest
): Promise<SeedMediaResponse> {
  return requestJson<SeedMediaResponse>('/api/v1/media/seed/from-preset', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function uploadSeedMedia(
  file: File,
  projectId = 'default-uav-project'
): Promise<SeedMediaResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('project_id', projectId);
  return requestJson<SeedMediaResponse>('/api/v1/media/seed', {
    method: 'POST',
    body: form,
  });
}

// 3. Live Orbis Sessions
export async function createSession(
  payload: CreateSessionRequest = {}
): Promise<SessionStateResponse> {
  return requestJson<SessionStateResponse>('/api/v1/sessions', {
    method: 'POST',
    body: JSON.stringify({
      model_id: 'reactor/visko-orbis-stable',
      ...payload,
    }),
  });
}

export async function getSession(sessionId: string): Promise<SessionStateResponse> {
  return requestJson<SessionStateResponse>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}`
  );
}

export async function closeSession(
  sessionId: string
): Promise<{ session_id: string; status: string }> {
  return requestJson<{ session_id: string; status: string }>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' }
  );
}

export async function steerSessionPrompt(
  sessionId: string,
  payload: SteerPromptRequest
): Promise<SteerPromptResponse> {
  return requestJson<SteerPromptResponse>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/prompt`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  );
}

export async function reanchorSessionSeed(
  sessionId: string,
  payload: ReanchorSeedRequest
): Promise<ReanchorSeedResponse> {
  return requestJson<ReanchorSeedResponse>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/seed`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  );
}

export async function recordSessionClip(
  sessionId: string,
  payload: RecordClipRequest
): Promise<DatasetRecord> {
  return requestJson<DatasetRecord>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/record`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  );
}

// 4. Projects, Folders & Datasets
export async function listProjects(): Promise<{ projects: ProjectRecord[] }> {
  return requestJson<{ projects: ProjectRecord[] }>('/api/v1/projects');
}

export async function createProject(
  payload: CreateProjectRequest
): Promise<ProjectRecord> {
  return requestJson<ProjectRecord>('/api/v1/projects', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function listProjectFolders(
  projectId: string
): Promise<{ project_id: string; folders: FolderRecord[] }> {
  return requestJson<{ project_id: string; folders: FolderRecord[] }>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/folders`
  );
}

export async function createProjectFolder(
  projectId: string,
  payload: CreateFolderRequest
): Promise<FolderRecord> {
  return requestJson<FolderRecord>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/folders`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  );
}

export interface ListDatasetsParams {
  folder_id?: string;
  ecosystem_type?: string;
  duration_seconds?: number;
  min_turbulence_edr?: number;
  max_turbulence_edr?: number;
  search?: string;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}

export async function listProjectDatasets(
  projectId: string,
  params: ListDatasetsParams = {}
): Promise<DatasetListResponse> {
  const qs = new URLSearchParams();
  if (params.folder_id) qs.set('folder_id', params.folder_id);
  if (params.ecosystem_type && params.ecosystem_type !== 'all') {
    qs.set('ecosystem_type', params.ecosystem_type);
  }
  if (params.duration_seconds) {
    qs.set('duration_seconds', String(params.duration_seconds));
  }
  if (typeof params.min_turbulence_edr === 'number') {
    qs.set('min_turbulence_edr', String(params.min_turbulence_edr));
  }
  if (typeof params.max_turbulence_edr === 'number') {
    qs.set('max_turbulence_edr', String(params.max_turbulence_edr));
  }
  if (params.search && params.search.trim()) {
    qs.set('search', params.search.trim());
  }
  if (params.sort_by) qs.set('sort_by', params.sort_by);
  if (params.sort_dir) qs.set('sort_dir', params.sort_dir);

  const queryStr = qs.toString();
  return requestJson<DatasetListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/datasets${queryStr ? `?${queryStr}` : ''}`
  );
}

export interface UploadDatasetFormPayload {
  file: File;
  folder_id?: string;
  title?: string;
  ecosystem_type?: EcosystemType | string;
  duration_seconds?: 5 | 10 | 15;
  initial_prompt?: string;
  avg_wind_speed_mps?: number;
  avg_air_pressure_hpa?: number;
  max_turbulence_edr?: number;
  drone_altitude_agl_m?: number;
}

export async function uploadProjectDataset(
  projectId: string,
  payload: UploadDatasetFormPayload
): Promise<DatasetRecord> {
  const form = new FormData();
  form.append('file', payload.file);
  if (payload.folder_id) form.append('folder_id', payload.folder_id);
  if (payload.title) form.append('title', payload.title);
  if (payload.ecosystem_type) form.append('ecosystem_type', payload.ecosystem_type);
  if (payload.duration_seconds) {
    form.append('duration_seconds', String(payload.duration_seconds));
  }
  if (payload.initial_prompt) form.append('initial_prompt', payload.initial_prompt);
  if (typeof payload.avg_wind_speed_mps === 'number') {
    form.append('avg_wind_speed_mps', String(payload.avg_wind_speed_mps));
  }
  if (typeof payload.avg_air_pressure_hpa === 'number') {
    form.append('avg_air_pressure_hpa', String(payload.avg_air_pressure_hpa));
  }
  if (typeof payload.max_turbulence_edr === 'number') {
    form.append('max_turbulence_edr', String(payload.max_turbulence_edr));
  }
  if (typeof payload.drone_altitude_agl_m === 'number') {
    form.append('drone_altitude_agl_m', String(payload.drone_altitude_agl_m));
  }

  return requestJson<DatasetRecord>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/datasets/upload`,
    {
      method: 'POST',
      body: form,
    }
  );
}

export async function getDataset(videoId: string): Promise<DatasetRecord> {
  return requestJson<DatasetRecord>(
    `/api/v1/datasets/${encodeURIComponent(videoId)}`
  );
}

export async function updateDataset(
  videoId: string,
  payload: UpdateDatasetRequest
): Promise<DatasetRecord> {
  return requestJson<DatasetRecord>(
    `/api/v1/datasets/${encodeURIComponent(videoId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }
  );
}

export async function getDatasetDownloadInfo(
  videoId: string
): Promise<DatasetDownloadResponse> {
  return requestJson<DatasetDownloadResponse>(
    `/api/v1/datasets/${encodeURIComponent(videoId)}/download`
  );
}

export function getDatasetFileStreamUrl(videoId: string): string {
  return `${API_BASE_URL}/api/v1/datasets/${encodeURIComponent(videoId)}/file`;
}
