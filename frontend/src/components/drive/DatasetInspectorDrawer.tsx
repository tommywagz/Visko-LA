'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import {
  Activity,
  Compass,
  Database,
  Download,
  FolderInput,
  Gauge,
  MessageSquare,
  Sparkles,
  Wind,
  X,
} from 'lucide-react';
import { getDatasetDownloadInfo, getDatasetFileStreamUrl } from '../../lib/api-client';
import {
  classifyTurbulenceEdr,
  compassDirectionLabel,
  formatAirDensity,
  formatAltitudeAgl,
  formatBytes,
  formatDurationPill,
  formatEcosystemLabel,
  formatEdr,
  formatPressureHpa,
  formatTemperatureC,
  formatWindSpeed,
  normalizeCompassDegrees,
  parsePromptHistoryJson,
} from '../../lib/telemetry';
import type { DatasetRecord, FolderRecord } from '../../types/api';

export interface DatasetInspectorDrawerProps {
  dataset: DatasetRecord | null;
  folders: FolderRecord[];
  onClose: () => void;
  onMoveDataset: (videoId: string, targetFolderId: string) => Promise<void>;
}

export function DatasetInspectorDrawer({
  dataset,
  folders,
  onClose,
  onMoveDataset,
}: DatasetInspectorDrawerProps) {
  const [moveTargetFolderId, setMoveTargetFolderId] = useState<string>(
    dataset?.folder_id || 'root'
  );
  const [moving, setMoving] = useState<boolean>(false);
  const [moveNotice, setMoveNotice] = useState<string | null>(null);

  React.useEffect(() => {
    if (dataset) {
      setMoveTargetFolderId(dataset.folder_id);
      setMoveNotice(null);
    }
  }, [dataset]);

  if (!dataset) return null;

  const streamUrl = getDatasetFileStreamUrl(dataset.video_id);
  const turb = classifyTurbulenceEdr(dataset.max_turbulence_edr);
  const windDeg = normalizeCompassDegrees(dataset.wind_direction_deg);
  const promptTimeline = parsePromptHistoryJson(
    dataset.prompt_history_json,
    dataset.initial_prompt
  );

  const handleMove = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!moveTargetFolderId || moveTargetFolderId === dataset.folder_id) return;
    setMoving(true);
    setMoveNotice(null);
    try {
      await onMoveDataset(dataset.video_id, moveTargetFolderId);
      setMoveNotice('Dataset moved successfully.');
    } catch (err) {
      setMoveNotice(
        err instanceof Error ? err.message : 'Failed to move dataset'
      );
    } finally {
      setMoving(false);
    }
  };

  return (
    <aside
      data-testid="dataset-inspector-drawer"
      aria-label="BigQuery Dataset Metadata Inspector"
      className="flex h-full w-full max-w-md flex-col border-l border-[#E2E8F0] bg-white text-slate-900 shadow-2xl xl:max-w-lg shrink-0 overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 bg-[#F8FAFC]">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded bg-[#E8F0FE] px-2 py-0.5 font-telemetry text-[11px] font-semibold text-[#1A73E8]">
              {formatDurationPill(dataset.duration_seconds)} ({dataset.duration_seconds}s)
            </span>
            <span className="rounded bg-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-700">
              {formatEcosystemLabel(dataset.ecosystem_type)}
            </span>
          </div>
          <h2 className="mt-1.5 truncate text-sm font-bold text-slate-900">
            {dataset.title}
          </h2>
          <p className="font-telemetry text-[11px] text-slate-500">
            ID: {dataset.video_id}
          </p>
        </div>

        <button
          type="button"
          onClick={onClose}
          aria-label="Close Inspector Drawer"
          className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Scrollable Body */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {/* Inline HTML5 Video Player */}
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-[#070B12] shadow-sm">
          <video
            key={dataset.video_id}
            controls
            playsInline
            preload="metadata"
            src={streamUrl}
            className="aspect-video w-full bg-[#070B12]"
          >
            Your browser does not support HTML5 MP4 video playback.
          </video>
        </div>

        {/* Primary Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={streamUrl}
            download={`${dataset.video_id}.mp4`}
            data-testid="direct-download-button"
            onClick={() => {
              // Fire-and-forget audit call to /download while letting native attachment link download immediately
              void getDatasetDownloadInfo(dataset.video_id).catch(() => {});
            }}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-[#1A73E8] px-4 py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-[#4285F4] transition"
          >
            <Download className="h-4 w-4" />
            <span>Direct Download (.mp4)</span>
          </a>

          <Link
            href={`/studio?projectId=${encodeURIComponent(
              dataset.project_id
            )}&folderId=${encodeURIComponent(
              dataset.folder_id
            )}&seedUrl=${encodeURIComponent(
              dataset.seed_media_gcs_uri || dataset.gcs_video_uri
            )}&ecosystem=${encodeURIComponent(dataset.ecosystem_type)}`}
            className="flex items-center justify-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-xs font-semibold text-slate-800 hover:border-[#1A73E8] hover:text-[#1A73E8] transition"
          >
            <Sparkles className="h-4 w-4 text-[#1A73E8]" />
            <span>Use as Seed in Studio</span>
          </Link>
        </div>

        {/* Move to Folder Form */}
        <form
          onSubmit={handleMove}
          className="rounded-xl border border-slate-200 bg-[#F8FAFC] p-3 space-y-2"
        >
          <label className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            <FolderInput className="h-3.5 w-3.5 text-[#1A73E8]" />
            Move Dataset to Folder
          </label>
          <div className="flex items-center gap-2">
            <select
              aria-label="Move Dataset Target Folder"
              value={moveTargetFolderId}
              onChange={(e) => setMoveTargetFolderId(e.target.value)}
              className="flex-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:border-[#1A73E8] focus:outline-none"
            >
              {folders.map((f) => (
                <option key={f.folder_id} value={f.folder_id}>
                  {f.folder_path === '/'
                    ? '/ (My Aerial Datasets)'
                    : `${f.folder_path} (${f.name})`}
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={moving || moveTargetFolderId === dataset.folder_id}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-800 hover:border-[#1A73E8] hover:text-[#1A73E8] disabled:opacity-50"
            >
              {moving ? 'Moving...' : 'Move'}
            </button>
          </div>
          {moveNotice && (
            <p className="text-[11px] font-medium text-emerald-700">{moveNotice}</p>
          )}
        </form>

        {/* Atmospheric Physics Summary Cards */}
        <section className="space-y-2">
          <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">
            <Activity className="h-3.5 w-3.5 text-[#1A73E8]" />
            Atmospheric & Flight Telemetry Aggregates
          </h3>
          <div className="grid grid-cols-2 gap-2.5">
            <div className="rounded-xl border border-slate-200 bg-[#F8FAFC] p-3">
              <div className="flex items-center gap-1 text-[11px] font-medium text-slate-500">
                <Wind className="h-3.5 w-3.5 text-sky-600" />
                Wind & Gusts
              </div>
              <div className="mt-1 font-telemetry text-sm font-bold text-slate-900">
                {formatWindSpeed(dataset.avg_wind_speed_mps)}
              </div>
              <div className="font-telemetry text-[11px] text-slate-500">
                Max Gust: {formatWindSpeed(dataset.max_wind_gust_mps)} ·{' '}
                {windDeg.toFixed(0)}° {compassDirectionLabel(windDeg)}
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-[#F8FAFC] p-3">
              <div className="flex items-center gap-1 text-[11px] font-medium text-slate-500">
                <Gauge className="h-3.5 w-3.5 text-emerald-600" />
                ISA Barometer
              </div>
              <div className="mt-1 font-telemetry text-sm font-bold text-slate-900">
                {formatPressureHpa(dataset.avg_air_pressure_hpa)}
              </div>
              <div className="font-telemetry text-[11px] text-slate-500">
                {formatAirDensity(dataset.avg_air_density_kgm3)} ·{' '}
                {formatTemperatureC(dataset.ambient_temp_c)}
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-[#F8FAFC] p-3">
              <div className="flex items-center justify-between text-[11px] font-medium text-slate-500">
                <span>Turbulence EDR</span>
                <span
                  className="rounded px-1.5 py-0.5 font-telemetry text-[10px] font-bold text-white"
                  style={{ backgroundColor: turb.severityColor }}
                >
                  {turb.badge}
                </span>
              </div>
              <div className="mt-1 font-telemetry text-sm font-bold text-slate-900">
                Max {formatEdr(dataset.max_turbulence_edr)}
              </div>
              <div className="font-telemetry text-[11px] text-slate-500">
                Mean {formatEdr(dataset.avg_turbulence_edr)}
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-[#F8FAFC] p-3">
              <div className="flex items-center gap-1 text-[11px] font-medium text-slate-500">
                <Compass className="h-3.5 w-3.5 text-indigo-600" />
                UAV Altitude
              </div>
              <div className="mt-1 font-telemetry text-sm font-bold text-slate-900">
                {formatAltitudeAgl(dataset.drone_altitude_agl_m)}
              </div>
              <div className="font-telemetry text-[11px] text-slate-500">
                {dataset.resolution} @ {dataset.fps} fps
              </div>
            </div>
          </div>
        </section>

        {/* BigQuery 27-Column Record Breakdown */}
        <section className="space-y-2">
          <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">
            <Database className="h-3.5 w-3.5 text-emerald-600" />
            BigQuery Catalog Record (aerial_datasets)
          </h3>
          <div className="rounded-xl border border-slate-200 bg-[#F8FAFC] divide-y divide-slate-200 text-xs">
            {[
              ['video_id', dataset.video_id],
              ['project_id', dataset.project_id],
              ['folder_path', `${dataset.folder_path} (${dataset.folder_id})`],
              ['session_id', dataset.session_id],
              ['model_id', dataset.model_id],
              ['ecosystem_type', dataset.ecosystem_type],
              ['duration_seconds', `${dataset.duration_seconds}s`],
              ['resolution / fps', `${dataset.resolution} / ${dataset.fps} fps`],
              ['file_size_bytes', `${formatBytes(dataset.file_size_bytes)} (${dataset.file_size_bytes} B)`],
              ['gcs_video_uri', dataset.gcs_video_uri],
              ['seed_media_gcs_uri', dataset.seed_media_gcs_uri || 'None (Text-to-World)'],
              ['created_at', dataset.created_at],
            ].map(([label, val]) => (
              <div
                key={label}
                className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 px-3 py-2"
              >
                <span className="font-mono text-[11px] text-slate-500 shrink-0">
                  {label}
                </span>
                <span className="font-telemetry text-[11px] font-medium text-slate-900 break-all sm:text-right">
                  {val}
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* Prompt Steering History Timeline */}
        <section className="space-y-2">
          <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">
            <MessageSquare className="h-3.5 w-3.5 text-[#1A73E8]" />
            Prompt Steering History ({promptTimeline.length})
          </h3>
          <div className="space-y-2">
            {promptTimeline.map((entry, idx) => (
              <div
                key={`${entry.prompt_id}_${idx}`}
                className="rounded-xl border border-slate-200 bg-[#F8FAFC] p-3 space-y-1"
              >
                <div className="flex items-center justify-between font-telemetry text-[10px] text-slate-500">
                  <span>
                    {idx === 0 ? 'Initial World Stake' : `Steering Update #${idx}`} ·
                    Chunk #{entry.chunk_index}
                  </span>
                  <span className="uppercase text-emerald-700 font-semibold">
                    {entry.status}
                  </span>
                </div>
                <p className="text-xs text-slate-800">{entry.prompt}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </aside>
  );
}
