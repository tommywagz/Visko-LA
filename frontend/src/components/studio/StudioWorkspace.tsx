'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import { useSearchParams } from 'next/navigation';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import {
  createProjectFolder,
  createSeedFromPreset,
  createSession,
  fetchMediaPresets,
  fetchSystemPrompt,
  listProjectFolders,
  reanchorSessionSeed,
  recordSessionClip,
  resolveApiAssetUrl,
  resolveSessionWsUrl,
  steerSessionPrompt,
  uploadSeedMedia,
} from '../../lib/api-client';
import { primeCachedReactorJwt } from '../../lib/jwt-cache';
import { extractTelemetryFrame } from '../../lib/telemetry';
import { usePlatform } from '../../context/PlatformContext';
import type {
  AdapterMode,
  CameraMode,
  DatasetRecord,
  EcosystemType,
  FolderRecord,
  PresetTileItem,
  PromptEntry,
  RecordingDuration,
  SeedMediaResponse,
  SessionLifecycleStatus,
  SessionStateResponse,
  SystemPromptResponse,
  TelemetryFrame,
  WsRecordingProgressMessage,
  WsSyntheticFrameMessage,
} from '../../types/api';
import { SyntheticFlightSimulatorCanvas } from './SyntheticFlightSimulatorCanvas';
import { TelemetryHudOverlay } from './TelemetryHudOverlay';
import { StudioLeftConditioningPanel } from './StudioLeftConditioningPanel';
import { SceneChatDrawer } from './SceneChatDrawer';
import { IntervalRecordingDock } from './IntervalRecordingDock';

// SSR-safe dynamic import of browser-only WebRTC / Wasm Reactor viewer
const DynamicLiveReactorWebRTCView = dynamic(
  () => import('./LiveReactorWebRTCView'),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center bg-[#070B12] text-xs text-sky-300">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Priming Orbis World Stream (Chunk 0)...
      </div>
    ),
  }
);

const INITIAL_FALLBACK_TELEMETRY: TelemetryFrame = {
  timestamp_ms: Date.now(),
  chunk_index: 0,
  ecosystem_type: 'alpine',
  wind_speed_mps: 11.4,
  wind_gust_mps: 15.8,
  wind_direction_deg: 245,
  air_pressure_hpa: 834.2,
  air_density_kgm3: 1.032,
  ambient_temp_c: 2.8,
  turbulence_edr: 0.16,
  turbulence_level: 'light',
  drone_altitude_agl_m: 65.0,
  drone_airspeed_mps: 12.0,
  drone_pitch_deg: -6.0,
  drone_roll_deg: 1.2,
  drone_yaw_deg: 248.0,
};

export function StudioWorkspace() {
  const searchParams = useSearchParams();
  const {
    projects,
    activeProjectId,
    setActiveProjectId,
    setStudioConnection,
  } = usePlatform();

  const queryProjectId = searchParams.get('projectId');
  const queryFolderId = searchParams.get('folderId');
  const querySeedUrl = searchParams.get('seedUrl');
  const querySeedId = searchParams.get('seedId');
  const queryEcosystem = searchParams.get('ecosystem') as EcosystemType | null;

  const [folders, setFolders] = useState<FolderRecord[]>([]);
  const [targetFolderId, setTargetFolderId] = useState<string>(
    queryFolderId || 'root'
  );
  const [cameraMode, setCameraMode] = useState<CameraMode>(
    'forward_downward_oblique'
  );
  const [ecosystemType, setEcosystemType] = useState<EcosystemType>(
    queryEcosystem &&
      [
        'alpine',
        'coastal',
        'urban_canyon',
        'temperate_forest',
        'arid_desert',
        'wetlands',
        'custom',
      ].includes(queryEcosystem)
      ? queryEcosystem
      : 'alpine'
  );
  const [altitudeAglM, setAltitudeAglM] = useState<number>(65);

  const [systemPromptInfo, setSystemPromptInfo] =
    useState<SystemPromptResponse | null>(null);
  const [presets, setPresets] = useState<PresetTileItem[]>([]);
  const [loadingPresetId, setLoadingPresetId] = useState<string | null>(null);

  const [session, setSession] = useState<SessionStateResponse | null>(null);
  const [sessionLoading, setSessionLoading] = useState<boolean>(true);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [sessionMode, setSessionMode] = useState<AdapterMode>('mock');
  const [sessionStatus, setSessionStatus] =
    useState<SessionLifecycleStatus>('priming');
  const [chunkIndex, setChunkIndex] = useState<number>(0);
  const [compiledSystemPrompt, setCompiledSystemPrompt] = useState<string>('');

  const [telemetry, setTelemetry] = useState<TelemetryFrame>(
    INITIAL_FALLBACK_TELEMETRY
  );
  const [syntheticFrame, setSyntheticFrame] =
    useState<WsSyntheticFrameMessage | null>(null);
  const [hudVisible, setHudVisible] = useState<boolean>(true);

  // Seed Media state
  const [activeSeed, setActiveSeed] = useState<SeedMediaResponse | null>(null);
  const [localSeedPreviewUrl, setLocalSeedPreviewUrl] = useState<string | null>(
    null
  );
  const [seedUploading, setSeedUploading] = useState<boolean>(false);
  const [seedUploadProgress, setSeedUploadProgress] = useState<number>(0);
  const [seedConditioningStatus, setSeedConditioningStatus] = useState<
    string | null
  >(querySeedUrl ? `Pre-conditioned from ${querySeedUrl}` : null);
  const [seedError, setSeedError] = useState<string | null>(null);
  const [isReanchoring, setIsReanchoring] = useState<boolean>(false);

  // Chat Steering state
  const [promptHistory, setPromptHistory] = useState<PromptEntry[]>([]);
  const [sendingPrompt, setSendingPrompt] = useState<boolean>(false);
  const [chatError, setChatError] = useState<string | null>(null);

  // Recording Dock state
  const [selectedDuration, setSelectedDuration] =
    useState<RecordingDuration>(5);
  const [clipTitle, setClipTitle] = useState<string>('');
  const [isRecording, setIsRecording] = useState<boolean>(false);
  const [recordingProgress, setRecordingProgress] =
    useState<WsRecordingProgressMessage | null>(null);
  const [lastCapturedDataset, setLastCapturedDataset] =
    useState<DatasetRecord | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const mountedRef = useRef<boolean>(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Sync URL ?projectId & ?folderId on mount
  useEffect(() => {
    if (queryProjectId && queryProjectId !== activeProjectId) {
      setActiveProjectId(queryProjectId);
    }
  }, [queryProjectId, activeProjectId, setActiveProjectId]);

  useEffect(() => {
    if (queryFolderId) {
      setTargetFolderId(queryFolderId);
    }
  }, [queryFolderId]);

  // Load project folders whenever activeProjectId changes
  const refreshFolders = useCallback(
    async (projId: string) => {
      try {
        const res = await listProjectFolders(projId);
        if (mountedRef.current) {
          setFolders(res.folders);
          if (
            queryFolderId &&
            res.folders.some((f) => f.folder_id === queryFolderId)
          ) {
            setTargetFolderId(queryFolderId);
          } else if (
            !res.folders.some((f) => f.folder_id === targetFolderId)
          ) {
            setTargetFolderId('root');
          }
        }
      } catch {
        // Keep current folder fallback
      }
    },
    [queryFolderId, targetFolderId]
  );

  useEffect(() => {
    void refreshFolders(activeProjectId);
  }, [activeProjectId, refreshFolders]);

  // Load System Prompt templates & Dubai 256x256 presets
  useEffect(() => {
    void (async () => {
      try {
        const [sysInfo, presetCatalog] = await Promise.allSettled([
          fetchSystemPrompt(cameraMode),
          fetchMediaPresets(12, 0),
        ]);
        if (!mountedRef.current) return;
        if (sysInfo.status === 'fulfilled') {
          setSystemPromptInfo(sysInfo.value);
        }
        if (presetCatalog.status === 'fulfilled') {
          setPresets(presetCatalog.value.presets || []);
        }
      } catch {
        // Non-fatal auxiliary metadata load
      }
    })();
  }, [cameraMode]);

  // Connect WebSocket for an active session
  const connectWebSocket = useCallback(
    (sess: SessionStateResponse) => {
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // Ignore close error on replaced socket
        }
        wsRef.current = null;
      }

      const wsUrl = resolveSessionWsUrl(sess.session_id, sess.ws_url);
      let ws: WebSocket;
      try {
        ws = new WebSocket(wsUrl);
      } catch {
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setStudioConnection({
          connected: true,
          mode: sess.mode,
          status: sess.status,
          chunkIndex: sess.chunk_index ?? 0,
          sessionId: sess.session_id,
        });
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const msg = JSON.parse(String(event.data)) as Record<string, unknown>;
          const msgType = msg.type;

          if (msgType === 'telemetry') {
            const frame = extractTelemetryFrame(msg);
            if (frame) {
              setTelemetry(frame);
              setChunkIndex(frame.chunk_index);
              setPromptHistory((prev) =>
                prev.some(
                  (p) =>
                    p.status === 'morphing' && frame.chunk_index >= p.chunk_index
                )
                  ? prev.map((p) =>
                      p.status === 'morphing' &&
                      frame.chunk_index >= p.chunk_index
                        ? { ...p, status: 'applied' }
                        : p
                    )
                  : prev
              );
              setStudioConnection((prev) => ({
                ...prev,
                connected: true,
                chunkIndex: frame.chunk_index,
                status: frame.chunk_index >= 1 ? 'generating' : prev.status,
              }));
            }
          } else if (msgType === 'orbis_state') {
            const statusVal =
              (msg.status as SessionLifecycleStatus) || 'generating';
            const modeVal = (msg.mode as AdapterMode) || sess.mode;
            const cIdx =
              typeof msg.chunk_index === 'number' ? msg.chunk_index : 0;
            setSessionStatus(statusVal);
            setSessionMode(modeVal);
            setChunkIndex(cIdx);
            if (typeof msg.active_prompt === 'string' && msg.active_prompt) {
              setCompiledSystemPrompt(msg.active_prompt);
            }
            setStudioConnection({
              connected: true,
              mode: modeVal,
              status: statusVal,
              chunkIndex: cIdx,
              sessionId: sess.session_id,
            });
          } else if (msgType === 'prompt_ack') {
            const ackId = typeof msg.prompt_id === 'string' ? msg.prompt_id : '';
            const rawText =
              typeof msg.prompt === 'string'
                ? msg.prompt
                : typeof msg.raw_prompt === 'string'
                  ? msg.raw_prompt
                  : '';
            const compiled =
              typeof msg.compiled_prompt === 'string'
                ? msg.compiled_prompt
                : rawText;
            const ackStatus =
              msg.status === 'morphing' ? 'morphing' : 'applied';
            const ackChunk =
              typeof msg.chunk_index === 'number' ? msg.chunk_index : 0;

            setPromptHistory((prev) => {
              const matchIdx = prev.findIndex(
                (p) =>
                  (ackId && p.prompt_id === ackId) ||
                  (rawText && p.prompt === rawText && p.status === 'morphing')
              );
              if (matchIdx >= 0) {
                const updated = [...prev];
                updated[matchIdx] = {
                  ...updated[matchIdx],
                  prompt_id: ackId || updated[matchIdx].prompt_id,
                  compiled_prompt: compiled || updated[matchIdx].compiled_prompt,
                  chunk_index: ackChunk || updated[matchIdx].chunk_index,
                  status: ackStatus,
                };
                return updated;
              }
              if (!rawText) return prev;
              return [
                ...prev,
                {
                  prompt_id: ackId || `prm_ws_${Date.now()}`,
                  prompt: rawText,
                  compiled_prompt: compiled,
                  passthrough: true,
                  chunk_index: ackChunk,
                  status: ackStatus,
                  created_at: new Date().toISOString(),
                },
              ];
            });
          } else if (msgType === 'recording_progress') {
            setRecordingProgress(msg as unknown as WsRecordingProgressMessage);
          } else if (msgType === 'synthetic_frame') {
            setSyntheticFrame(msg as unknown as WsSyntheticFrameMessage);
          }
        } catch {
          // Ignore malformed WS message frame
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setStudioConnection((prev) =>
          prev.sessionId === sess.session_id
            ? { ...prev, connected: false }
            : prev
        );
      };
    },
    [setStudioConnection]
  );

  // Initialize Live / Mock Session (Auto-Start on Mount!)
  const startOrResetSession = useCallback(
    async (overrides?: {
      cameraMode?: CameraMode;
      ecosystemType?: EcosystemType;
      seedId?: string | null;
      seedGcsUri?: string | null;
    }) => {
      setSessionLoading(true);
      setSessionError(null);
      try {
        const targetProject = queryProjectId || activeProjectId || 'default-uav-project';
        const targetFolder = queryFolderId || targetFolderId || 'root';
        const targetCam = overrides?.cameraMode ?? cameraMode;
        const targetEco = overrides?.ecosystemType ?? ecosystemType;

        const created = await createSession({
          project_id: targetProject,
          folder_id: targetFolder,
          camera_mode: targetCam,
          ecosystem_type: targetEco,
          drone_altitude_agl_m: altitudeAglM,
          seed_id:
            overrides?.seedId !== undefined
              ? overrides.seedId
              : activeSeed?.seed_id ?? querySeedId ?? undefined,
          seed_media_gcs_uri:
            overrides?.seedGcsUri !== undefined
              ? overrides.seedGcsUri
              : activeSeed?.seed_media_gcs_uri ?? querySeedUrl ?? undefined,
        });

        if (!mountedRef.current) return;

        sessionIdRef.current = created.session_id;
        primeCachedReactorJwt(
          created.reactor_session_id || created.session_id,
          created.reactor_jwt,
          created.expires_at
        );

        setSession(created);
        setSessionMode(created.mode);
        setSessionStatus(created.status);
        setChunkIndex(created.chunk_index ?? 0);
        setCompiledSystemPrompt(created.compiled_system_prompt);
        setTelemetry(created.initial_telemetry);
        setPromptHistory(created.prompt_history || []);
        setStudioConnection({
          connected: true,
          mode: created.mode,
          status: created.status,
          chunkIndex: created.chunk_index ?? 0,
          sessionId: created.session_id,
        });

        connectWebSocket(created);
      } catch (err) {
        if (!mountedRef.current) return;
        setSessionError(
          err instanceof Error
            ? err.message
            : 'Unable to initialize Orbis aerial session'
        );
      } finally {
        if (mountedRef.current) {
          setSessionLoading(false);
        }
      }
    },
    [
      queryProjectId,
      activeProjectId,
      queryFolderId,
      targetFolderId,
      cameraMode,
      ecosystemType,
      altitudeAglM,
      activeSeed,
      querySeedId,
      querySeedUrl,
      setStudioConnection,
      connectWebSocket,
    ]
  );

  // Auto-start session once on initial Studio mount
  const didAutoStartRef = useRef(false);
  useEffect(() => {
    if (didAutoStartRef.current) return;
    didAutoStartRef.current = true;
    void startOrResetSession();

    return () => {
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // Ignore unmount WS close error
        }
        wsRef.current = null;
      }
    };
  }, [startOrResetSession]);

  // Send live WS `flight_adjust` helper
  const sendFlightAdjust = useCallback(
    (patch: {
      drone_altitude_agl_m?: number;
      camera_mode?: CameraMode;
      ecosystem_type?: EcosystemType;
    }) => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: 'flight_adjust',
            ...patch,
          })
        );
      }
    },
    []
  );

  const handleChangeCameraMode = useCallback(
    (nextMode: CameraMode) => {
      setCameraMode(nextMode);
      sendFlightAdjust({ camera_mode: nextMode });
    },
    [sendFlightAdjust]
  );

  const handleChangeEcosystem = useCallback(
    (nextEco: EcosystemType) => {
      setEcosystemType(nextEco);
      sendFlightAdjust({ ecosystem_type: nextEco });
    },
    [sendFlightAdjust]
  );

  const handleChangeAltitude = useCallback(
    (meters: number) => {
      setAltitudeAglM(meters);
      setTelemetry((prev) => ({ ...prev, drone_altitude_agl_m: meters }));
      sendFlightAdjust({ drone_altitude_agl_m: meters });
    },
    [sendFlightAdjust]
  );

  const handleQuickCreateFolder = useCallback(
    async (name: string) => {
      const created = await createProjectFolder(activeProjectId, {
        name,
        parent_folder_id:
          targetFolderId && targetFolderId !== 'all' ? targetFolderId : 'root',
        ecosystem_default: ecosystemType,
      });
      await refreshFolders(activeProjectId);
      setTargetFolderId(created.folder_id);
    },
    [activeProjectId, targetFolderId, ecosystemType, refreshFolders]
  );

  // Re-anchor active session to uploaded/preset seed media
  const applySeedToActiveSession = useCallback(
    async (seed: SeedMediaResponse) => {
      if (!session?.session_id) {
        await startOrResetSession({
          seedId: seed.seed_id,
          seedGcsUri: seed.seed_media_gcs_uri,
        });
        setSeedConditioningStatus('Seed Conditioned & Applied (832×480 16:9)');
        return;
      }

      setIsReanchoring(true);
      setSeedConditioningStatus('Re-anchoring Orbis World to New Seed...');
      try {
        const res = await reanchorSessionSeed(session.session_id, {
          seed_id: seed.seed_id,
          seed_media_gcs_uri: seed.seed_media_gcs_uri,
        });
        setCompiledSystemPrompt(res.compiled_prompt);
        setChunkIndex(res.chunk_index);
        setSeedConditioningStatus('Seed Conditioned & Applied (832×480 16:9)');
      } catch (err) {
        setSeedError(
          err instanceof Error
            ? err.message
            : 'Failed to re-anchor session to seed'
        );
      } finally {
        setIsReanchoring(false);
      }
    },
    [session, startOrResetSession]
  );

  const handleUploadSeedFile = useCallback(
    async (file: File) => {
      setSeedError(null);
      setSeedUploading(true);
      setSeedUploadProgress(30);

      if (file.type.startsWith('image/')) {
        const objUrl = URL.createObjectURL(file);
        setLocalSeedPreviewUrl(objUrl);
      }

      try {
        const uploaded = await uploadSeedMedia(file, activeProjectId);
        setSeedUploadProgress(100);
        setActiveSeed(uploaded);
        if (uploaded.preview_url) {
          setLocalSeedPreviewUrl(resolveApiAssetUrl(uploaded.preview_url));
        }
        await applySeedToActiveSession(uploaded);
      } catch (err) {
        setSeedError(
          err instanceof Error ? err.message : 'Seed media upload failed'
        );
      } finally {
        setSeedUploading(false);
      }
    },
    [activeProjectId, applySeedToActiveSession]
  );

  const handleSelectPreset = useCallback(
    async (preset: PresetTileItem) => {
      setSeedError(null);
      setLoadingPresetId(preset.preset_id);
      try {
        const seeded = await createSeedFromPreset({
          preset_id: preset.preset_id,
          project_id: activeProjectId,
        });
        setActiveSeed(seeded);
        setLocalSeedPreviewUrl(resolveApiAssetUrl(seeded.preview_url));
        if (seeded.ecosystem_type) {
          setEcosystemType(seeded.ecosystem_type as EcosystemType);
        }
        if (seeded.recommended_camera_mode) {
          setCameraMode(seeded.recommended_camera_mode as CameraMode);
        }
        await applySeedToActiveSession(seeded);
      } catch (err) {
        setSeedError(
          err instanceof Error
            ? err.message
            : 'Failed to condition from Dubai preset'
        );
      } finally {
        setLoadingPresetId(null);
      }
    },
    [activeProjectId, applySeedToActiveSession]
  );

  const handleReapplySeed = useCallback(async () => {
    if (!activeSeed) return;
    await applySeedToActiveSession(activeSeed);
  }, [activeSeed, applySeedToActiveSession]);

  // Live Scene & Weather Prompt Steering (NO reset!)
  const handleSendPrompt = useCallback(
    async (promptText: string) => {
      setChatError(null);
      setSendingPrompt(true);

      let activeSess = session;
      if (!activeSess) {
        try {
          activeSess = await createSession({
            project_id: activeProjectId,
            folder_id: targetFolderId,
            camera_mode: cameraMode,
            ecosystem_type: ecosystemType,
            drone_altitude_agl_m: altitudeAglM,
          });
          setSession(activeSess);
          connectWebSocket(activeSess);
        } catch (err) {
          setChatError(
            err instanceof Error
              ? err.message
              : 'Session not ready for steering'
          );
          setSendingPrompt(false);
          return;
        }
      }

      const optimisticId = `prm_opt_${Date.now()}`;
      const optimisticEntry: PromptEntry = {
        prompt_id: optimisticId,
        prompt: promptText,
        compiled_prompt: `Maintaining continuous forward-and-downward UAV aerial flight along the same trajectory, ${promptText}`,
        passthrough: true,
        chunk_index: chunkIndex + 1,
        status: 'morphing',
        created_at: new Date().toISOString(),
      };
      setPromptHistory((prev) => [...prev, optimisticEntry]);

      try {
        const res = await steerSessionPrompt(activeSess.session_id, {
          prompt: promptText,
          camera_mode: cameraMode,
        });
        if (Array.isArray(res.prompt_history) && res.prompt_history.length > 0) {
          setPromptHistory(res.prompt_history);
        } else if (res.prompt_entry) {
          setPromptHistory((prev) =>
            prev.map((item) =>
              item.prompt_id === optimisticId ? res.prompt_entry : item
            )
          );
        }
        if (res.latest_telemetry) {
          setTelemetry(res.latest_telemetry);
        }
      } catch (err) {
        setPromptHistory((prev) =>
          prev.filter((item) => item.prompt_id !== optimisticId)
        );
        setChatError(
          err instanceof Error ? err.message : 'Failed to apply steering prompt'
        );
      } finally {
        setSendingPrompt(false);
      }
    },
    [
      session,
      activeProjectId,
      targetFolderId,
      cameraMode,
      ecosystemType,
      altitudeAglM,
      chunkIndex,
      connectWebSocket,
    ]
  );

  // Default clip title placeholder
  const defaultTitlePlaceholder = useMemo(() => {
    const stamp = new Date().toISOString().slice(11, 19).replace(/:/g, '');
    return `${ecosystemType}-${selectedDuration}s-${stamp}`;
  }, [ecosystemType, selectedDuration]);

  // Fixed-Interval Recording (`5s`, `10s`, `15s`)
  const handleCaptureClip = useCallback(async () => {
    setRecordError(null);
    setIsRecording(true);
    setRecordingProgress({
      type: 'recording_progress',
      session_id: session?.session_id || 'pending',
      recording_id: `rec_${Date.now()}`,
      duration_seconds: selectedDuration,
      elapsed_seconds: 0,
      progress_pct: 15,
      status: 'capturing',
    });

    try {
      let activeSess = session;
      if (!activeSess) {
        activeSess = await createSession({
          project_id: activeProjectId,
          folder_id: targetFolderId,
          camera_mode: cameraMode,
          ecosystem_type: ecosystemType,
          drone_altitude_agl_m: altitudeAglM,
        });
        setSession(activeSess);
        connectWebSocket(activeSess);
      }

      const dataset = await recordSessionClip(activeSess.session_id, {
        duration_seconds: selectedDuration,
        interval_setting: `${selectedDuration}s` as '5s' | '10s' | '15s',
        project_id: activeProjectId,
        folder_id: targetFolderId || 'root',
        title: clipTitle.trim() || defaultTitlePlaceholder,
      });

      setLastCapturedDataset(dataset);
      setClipTitle('');
    } catch (err) {
      setRecordError(
        err instanceof Error ? err.message : 'Failed to capture synthetic clip'
      );
    } finally {
      setIsRecording(false);
      setRecordingProgress(null);
    }
  }, [
    session,
    selectedDuration,
    activeProjectId,
    targetFolderId,
    cameraMode,
    ecosystemType,
    altitudeAglM,
    clipTitle,
    defaultTitlePlaceholder,
    connectWebSocket,
  ]);

  const effectiveSeedPreview =
    localSeedPreviewUrl ||
    (activeSeed?.preview_url
      ? resolveApiAssetUrl(activeSeed.preview_url)
      : session?.preview_url
        ? resolveApiAssetUrl(session.preview_url)
        : null);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-[#070B12]">
      {/* Top 3-Column Studio Body */}
      <div className="flex flex-1 min-h-0 flex-col lg:flex-row overflow-hidden">
        {/* Left Conditioning, Gimbal & Seed Uploader */}
        <StudioLeftConditioningPanel
          projects={projects}
          activeProjectId={activeProjectId}
          onSelectProject={setActiveProjectId}
          folders={folders}
          targetFolderId={targetFolderId}
          onSelectFolder={setTargetFolderId}
          onQuickCreateFolder={handleQuickCreateFolder}
          cameraMode={cameraMode}
          onChangeCameraMode={handleChangeCameraMode}
          systemPromptInfo={systemPromptInfo}
          compiledSystemPrompt={compiledSystemPrompt}
          ecosystemType={ecosystemType}
          onChangeEcosystem={handleChangeEcosystem}
          altitudeAglM={altitudeAglM}
          onChangeAltitude={handleChangeAltitude}
          presets={presets}
          loadingPresetId={loadingPresetId}
          onSelectPreset={handleSelectPreset}
          activeSeed={activeSeed}
          localSeedPreviewUrl={localSeedPreviewUrl}
          seedUploading={seedUploading}
          seedUploadProgress={seedUploadProgress}
          seedConditioningStatus={seedConditioningStatus}
          seedError={seedError}
          onUploadSeedFile={handleUploadSeedFile}
          onReapplySeed={handleReapplySeed}
        />

        {/* Center Live Drone-POV Viewport + Toggleable Flight HUD */}
        <section
          aria-label="Live Drone-POV World Viewport"
          className="relative flex-1 min-w-0 min-h-[320px] overflow-hidden bg-[#070B12]"
        >
          {sessionMode === 'live' && session ? (
            <DynamicLiveReactorWebRTCView
              sessionId={session.session_id}
              reactorSessionId={session.reactor_session_id}
              initialJwt={session.reactor_jwt}
              initialExpiresAt={session.expires_at}
              chunkIndex={chunkIndex}
              sessionStatus={sessionStatus}
              isReanchoring={isReanchoring}
            />
          ) : (
            <SyntheticFlightSimulatorCanvas
              telemetry={telemetry}
              cameraMode={cameraMode}
              ecosystemType={ecosystemType}
              syntheticFrame={syntheticFrame}
              seedPreviewUrl={effectiveSeedPreview}
              isReanchoring={isReanchoring}
            />
          )}

          {/* Session Connection Banner if backend wasn't immediately reachable */}
          {sessionError && !session && (
            <div className="absolute top-14 left-3 z-20 flex items-center gap-2 rounded-xl border border-amber-500/40 bg-[#0F172A]/95 px-3 py-2 text-xs text-amber-200 shadow-lg">
              <AlertCircle className="h-4 w-4 text-amber-400 shrink-0" />
              <span>{sessionError}</span>
              <button
                type="button"
                onClick={() => void startOrResetSession()}
                className="ml-2 flex items-center gap-1 rounded bg-[#1A73E8] px-2 py-1 text-[11px] font-semibold text-white hover:bg-[#4285F4]"
              >
                <RefreshCw className="h-3 w-3" />
                <span>Retry</span>
              </button>
            </div>
          )}

          {sessionLoading && !session && (
            <div className="pointer-events-none absolute top-14 left-3 z-20 flex items-center gap-2 rounded-full border border-sky-500/30 bg-[#0F172A]/90 px-3 py-1 text-[11px] text-sky-300">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>Connecting Orbis Aerial Session...</span>
            </div>
          )}

          {/* Toggleable Flight Telemetry HUD (`telemetry-hud`) */}
          <TelemetryHudOverlay
            telemetry={telemetry}
            visible={hudVisible}
            onToggleVisible={() => setHudVisible((v) => !v)}
          />
        </section>

        {/* Right Real-Time Scene & Weather Chat (`scene-chat-panel`) */}
        <SceneChatDrawer
          promptHistory={promptHistory}
          sendingPrompt={sendingPrompt}
          chatError={chatError}
          onSendPrompt={handleSendPrompt}
        />
      </div>

      {/* Bottom Interval Recording Dock (`5s` / `10s` / `15s`) */}
      <IntervalRecordingDock
        selectedDuration={selectedDuration}
        onSelectDuration={setSelectedDuration}
        clipTitle={clipTitle}
        onChangeClipTitle={setClipTitle}
        defaultTitlePlaceholder={defaultTitlePlaceholder}
        isRecording={isRecording}
        recordingProgress={recordingProgress}
        lastCapturedDataset={lastCapturedDataset}
        recordError={recordError}
        onCaptureClip={handleCaptureClip}
        onDismissToast={() => setLastCapturedDataset(null)}
        sessionReady={!sessionLoading || Boolean(session)}
      />
    </div>
  );
}
