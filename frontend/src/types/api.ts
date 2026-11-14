export type AdapterMode = 'live' | 'mock';
export type ModelId = 'reactor/visko-orbis-stable';
export type CameraMode =
  | 'forward_downward_oblique'
  | 'nadir_downward'
  | 'forward_fpv';

export type EcosystemType =
  | 'alpine'
  | 'coastal'
  | 'urban_canyon'
  | 'temperate_forest'
  | 'arid_desert'
  | 'wetlands'
  | 'custom';

export type TurbulenceLevel = 'light' | 'moderate' | 'severe' | 'extreme';
export type RecordingDuration = 5 | 10 | 15;
export type RecordingIntervalSetting = '5s' | '10s' | '15s';

export type SessionLifecycleStatus =
  | 'waiting'
  | 'priming'
  | 'generating'
  | 'paused'
  | 'reanchoring'
  | 'closed';

export interface HealthResponse {
  status: 'ok' | string;
  service?: string;
  mode: AdapterMode;
  orbis_mode: AdapterMode;
  gcp_mode: AdapterMode;
  model_id: ModelId;
  gcp_project_id: string;
  gcs_bucket_name: string;
  gcs_bucket: string;
  bq_dataset_id: string;
}

export interface ReactorTokenRequest {
  session_id?: string | null;
  reactor_session_id?: string | null;
  model_id?: ModelId;
  max_sessions?: number;
  expires_after?: number;
}

export interface ReactorTokenResponse {
  jwt: string;
  expires_at: number;
  model_id: ModelId;
  mode: AdapterMode;
  bound_session_id?: string | null;
}

export interface SystemPromptResponse {
  model_id: ModelId;
  default_camera_mode: CameraMode;
  passthrough: boolean;
  supported_camera_modes: CameraMode[];
  templates: Record<CameraMode, string>;
  steering_anchor_prefix: string;
  custom_override_active: boolean;
  active_override?: string | null;
}

export interface PresetTileItem {
  preset_id: string;
  title: string;
  source_dataset: string;
  row_index: number;
  ecosystem_type: EcosystemType;
  recommended_camera_mode: CameraMode;
  suggested_prompt: string;
  preview_url: string;
}

export interface PresetCatalogResponse {
  dataset: string;
  source_dataset: string;
  presets: PresetTileItem[];
}

export interface SeedFromPresetRequest {
  preset_id: string;
  project_id?: string;
}

export interface SeedMediaResponse {
  seed_id: string;
  project_id: string;
  preset_id?: string | null;
  filename?: string;
  mime_type?: string;
  media_kind?: 'image' | 'video';
  seed_media_gcs_uri: string;
  gcs_uri: string;
  preview_url: string;
  width: number;
  height: number;
  aspect_ratio: string;
  ecosystem_type?: EcosystemType | string | null;
  recommended_camera_mode?: CameraMode | string | null;
  suggested_prompt?: string | null;
  created_at?: string;
}

export interface TelemetryFrame {
  timestamp_ms: number;
  chunk_index: number;
  ecosystem_type: EcosystemType | string;
  wind_speed_mps: number;
  wind_gust_mps: number;
  wind_direction_deg: number;
  air_pressure_hpa: number;
  air_density_kgm3: number;
  ambient_temp_c: number;
  turbulence_edr: number;
  turbulence_level: TurbulenceLevel | string;
  drone_altitude_agl_m: number;
  drone_airspeed_mps: number;
  drone_pitch_deg: number;
  drone_roll_deg: number;
  drone_yaw_deg: number;
}

export interface PromptEntry {
  prompt_id: string;
  prompt: string;
  compiled_prompt: string;
  passthrough: boolean;
  chunk_index: number;
  status: 'morphing' | 'applied' | string;
  created_at: string;
}

export interface CreateSessionRequest {
  project_id?: string;
  folder_id?: string;
  model_id?: ModelId;
  camera_mode?: CameraMode;
  ecosystem_type?: EcosystemType;
  drone_altitude_agl_m?: number;
  initial_prompt?: string | null;
  seed_id?: string | null;
  seed_media_gcs_uri?: string | null;
  seed_gcs_uri?: string | null;
  resolution?: '1080p' | '2k' | '4k';
}

export interface SessionStateResponse {
  session_id: string;
  reactor_session_id?: string | null;
  project_id: string;
  folder_id: string;
  model_id: ModelId;
  mode: AdapterMode;
  status: SessionLifecycleStatus;
  chunk_index?: number;
  camera_mode: CameraMode;
  ecosystem_type: EcosystemType;
  passthrough: boolean;
  compiled_system_prompt: string;
  reactor_jwt: string;
  expires_at: number;
  reactor_jwt_expires_at?: number;
  ws_url: string;
  seed_id?: string | null;
  seed_media_gcs_uri?: string | null;
  preview_url?: string | null;
  initial_telemetry: TelemetryFrame;
  latest_telemetry?: TelemetryFrame;
  prompt_history: PromptEntry[];
  created_at: string;
}

export interface SteerPromptRequest {
  prompt: string;
  camera_mode?: CameraMode | string | null;
}

export interface SteerPromptResponse {
  session_id: string;
  status: 'morphing' | 'applied';
  chunk_index: number;
  raw_prompt: string;
  compiled_prompt: string;
  passthrough: boolean;
  prompt_entry: PromptEntry;
  prompt_history: PromptEntry[];
  updated_telemetry_targets: Record<string, unknown>;
  latest_telemetry: TelemetryFrame;
}

export interface ReanchorSeedRequest {
  seed_id?: string | null;
  seed_media_gcs_uri?: string | null;
  seed_gcs_uri?: string | null;
  prompt?: string | null;
}

export interface ReanchorSeedResponse {
  session_id: string;
  status: 'reanchoring' | 'applied';
  seed_id: string | null;
  seed_media_gcs_uri: string;
  gcs_uri?: string;
  preview_url: string | null;
  command_sequence: string[];
  compiled_prompt: string;
  passthrough: boolean;
  chunk_index: number;
}

export interface RecordClipRequest {
  duration_seconds: RecordingDuration;
  interval_setting?: RecordingIntervalSetting;
  project_id?: string | null;
  folder_id?: string | null;
  title?: string | null;
}

export interface ProjectRecord {
  project_id: string;
  name: string;
  description?: string | null;
  created_at: string;
}

export interface CreateProjectRequest {
  name: string;
  project_id?: string | null;
  description?: string | null;
}

export interface FolderRecord {
  folder_id: string;
  project_id: string;
  parent_folder_id: string | null;
  name: string;
  folder_path: string;
  ecosystem_default: string | null;
  dataset_count?: number;
  created_at: string;
}

export interface CreateFolderRequest {
  name: string;
  parent_folder_id?: string | null;
  ecosystem_default?: string | null;
}

export interface DatasetRecord {
  video_id: string;
  project_id: string;
  folder_id: string;
  folder_path: string;
  title: string;
  session_id: string;
  model_id: ModelId | string;
  ecosystem_type: EcosystemType | string;
  duration_seconds: number;
  resolution: string;
  fps: number;
  gcs_video_uri: string;
  seed_media_gcs_uri: string | null;
  initial_prompt: string;
  prompt_history_json: string;
  avg_wind_speed_mps: number;
  max_wind_gust_mps: number;
  wind_direction_deg: number;
  avg_air_pressure_hpa: number;
  avg_air_density_kgm3: number;
  ambient_temp_c: number;
  avg_turbulence_edr: number;
  max_turbulence_edr: number;
  drone_altitude_agl_m: number;
  telemetry_summary_json: string | null;
  file_size_bytes: number;
  created_at: string;
  download_url?: string;
  direct_stream_url?: string;
}

export interface DatasetListResponse {
  project_id: string;
  datasets: DatasetRecord[];
  total: number;
  storage_bytes_total: number;
}

export interface UpdateDatasetRequest {
  folder_id?: string | null;
  title?: string | null;
}

export interface DatasetDownloadResponse {
  video_id: string;
  filename: string;
  gcs_video_uri: string;
  gcs_uri: string;
  signed_url: string;
  direct_stream_url: string;
  expires_in_seconds: number;
}

// WebSocket Envelopes (`WS /ws/orbis/stream/{session_id}`)
export interface WsTelemetryMessage extends Partial<TelemetryFrame> {
  type: 'telemetry';
  session_id: string;
  telemetry?: TelemetryFrame;
  data?: TelemetryFrame;
}

export interface WsOrbisStateMessage {
  type: 'orbis_state';
  session_id: string;
  status: SessionLifecycleStatus;
  mode: AdapterMode;
  model_id?: string;
  chunk_index: number;
  frames_emitted?: number;
  fps?: number;
  chunk_duration_seconds?: number;
  camera_mode?: CameraMode;
  ecosystem_type?: EcosystemType;
  active_prompt?: string;
  timestamp_ms?: number;
}

export interface WsPromptAckMessage {
  type: 'prompt_ack';
  session_id: string;
  prompt_id: string;
  prompt: string;
  raw_prompt?: string;
  compiled_prompt: string;
  passthrough?: boolean;
  chunk_index: number;
  status: 'morphing' | 'applied';
  updated_telemetry_targets?: Record<string, number>;
  timestamp_ms: number;
}

export interface WsRecordingProgressMessage {
  type: 'recording_progress';
  session_id: string;
  recording_id: string;
  video_id?: string;
  duration_seconds: RecordingDuration;
  elapsed_seconds: number;
  progress_pct: number;
  status: 'capturing' | 'remuxing' | 'uploading' | 'completed' | 'failed';
  gcs_video_uri?: string;
  timestamp_ms?: number;
}

export interface WsSyntheticFrameMessage {
  type: 'synthetic_frame';
  session_id: string;
  chunk_index: number;
  frame_index: number;
  ecosystem_type: EcosystemType | string;
  camera_mode: CameraMode | string;
  horizon_pitch_deg: number;
  horizon_roll_deg: number;
  wind_vector_deg: number;
  wind_speed_mps: number;
  turbulence_edr: number;
  terrain_seed: number;
  timestamp_ms: number;
}

export interface WsErrorMessage {
  type: 'error';
  session_id: string;
  code: string;
  message: string;
  recoverable: boolean;
  timestamp_ms?: number;
}

export interface WsPongMessage {
  type: 'pong';
  session_id: string;
  timestamp_ms: number;
}

export type WsServerMessage =
  | WsTelemetryMessage
  | WsOrbisStateMessage
  | WsPromptAckMessage
  | WsRecordingProgressMessage
  | WsSyntheticFrameMessage
  | WsErrorMessage
  | WsPongMessage;

export type WsClientMessage =
  | { type: 'steer_prompt'; prompt: string }
  | {
      type: 'flight_adjust';
      drone_altitude_agl_m?: number;
      drone_airspeed_mps?: number;
      camera_mode?: CameraMode;
      ecosystem_type?: EcosystemType;
    }
  | { type: 'ping'; timestamp_ms: number };
