'use client';

import React, { useRef, useState } from 'react';
import {
  Camera,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FolderPlus,
  Image as ImageIcon,
  Loader2,
  RefreshCw,
  Sliders,
  Sparkles,
  UploadCloud,
} from 'lucide-react';
import { resolveApiAssetUrl } from '../../lib/api-client';
import {
  CAMERA_MODE_LABELS,
  ECOSYSTEM_LABELS,
  formatEcosystemLabel,
} from '../../lib/telemetry';
import type {
  CameraMode,
  EcosystemType,
  FolderRecord,
  PresetTileItem,
  ProjectRecord,
  SeedMediaResponse,
  SystemPromptResponse,
} from '../../types/api';

const QUICK_ECOSYSTEMS: EcosystemType[] = [
  'alpine',
  'coastal',
  'urban_canyon',
  'temperate_forest',
  'arid_desert',
  'wetlands',
];

const GIMBAL_MODES: CameraMode[] = [
  'forward_downward_oblique',
  'nadir_downward',
  'forward_fpv',
];

export interface StudioLeftConditioningPanelProps {
  projects: ProjectRecord[];
  activeProjectId: string;
  onSelectProject: (projectId: string) => void;
  folders: FolderRecord[];
  targetFolderId: string;
  onSelectFolder: (folderId: string) => void;
  onQuickCreateFolder: (name: string) => Promise<void>;
  cameraMode: CameraMode;
  onChangeCameraMode: (mode: CameraMode) => void;
  systemPromptInfo: SystemPromptResponse | null;
  compiledSystemPrompt: string;
  ecosystemType: EcosystemType;
  onChangeEcosystem: (eco: EcosystemType) => void;
  altitudeAglM: number;
  onChangeAltitude: (meters: number) => void;
  presets: PresetTileItem[];
  loadingPresetId: string | null;
  onSelectPreset: (preset: PresetTileItem) => Promise<void>;
  activeSeed: SeedMediaResponse | null;
  localSeedPreviewUrl: string | null;
  seedUploading: boolean;
  seedUploadProgress: number;
  seedConditioningStatus: string | null;
  seedError: string | null;
  onUploadSeedFile: (file: File) => Promise<void>;
  onReapplySeed: () => Promise<void>;
}

export function StudioLeftConditioningPanel({
  projects,
  activeProjectId,
  onSelectProject,
  folders,
  targetFolderId,
  onSelectFolder,
  onQuickCreateFolder,
  cameraMode,
  onChangeCameraMode,
  systemPromptInfo,
  compiledSystemPrompt,
  ecosystemType,
  onChangeEcosystem,
  altitudeAglM,
  onChangeAltitude,
  presets,
  loadingPresetId,
  onSelectPreset,
  activeSeed,
  localSeedPreviewUrl,
  seedUploading,
  seedUploadProgress,
  seedConditioningStatus,
  seedError,
  onUploadSeedFile,
  onReapplySeed,
}: StudioLeftConditioningPanelProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [showSystemPrompt, setShowSystemPrompt] = useState(false);
  const [showQuickFolder, setShowQuickFolder] = useState(false);
  const [quickFolderName, setQuickFolderName] = useState('');
  const [quickFolderBusy, setQuickFolderBusy] = useState(false);
  const [quickFolderErr, setQuickFolderErr] = useState<string | null>(null);

  const handleQuickFolderSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!quickFolderName.trim()) return;
    setQuickFolderBusy(true);
    setQuickFolderErr(null);
    try {
      await onQuickCreateFolder(quickFolderName.trim());
      setQuickFolderName('');
      setShowQuickFolder(false);
    } catch (err) {
      setQuickFolderErr(
        err instanceof Error ? err.message : 'Failed to create folder'
      );
    } finally {
      setQuickFolderBusy(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (file) {
      void onUploadSeedFile(file);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      void onUploadSeedFile(file);
    }
  };

  const effectivePreviewUrl =
    localSeedPreviewUrl ||
    (activeSeed?.preview_url ? resolveApiAssetUrl(activeSeed.preview_url) : '');

  const promptTextToInspect =
    compiledSystemPrompt ||
    systemPromptInfo?.templates?.[cameraMode] ||
    'Stabilized nose-mounted autonomous UAV perception camera pitched 35 degrees downward cruising steadily forward.';

  return (
    <aside className="flex h-full w-full flex-col overflow-y-auto border-r border-slate-400/15 bg-[#0F172A] p-3.5 space-y-4 lg:w-80 xl:w-[340px] shrink-0">
      {/* 1. Target Destination Selector */}
      <section className="rounded-xl border border-slate-800 bg-[#131B2E] p-3 space-y-2.5">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Target Capture Destination
          </span>
          <button
            type="button"
            onClick={() => setShowQuickFolder((v) => !v)}
            className="flex items-center gap-1 text-[11px] font-medium text-[#38BDF8] hover:text-sky-300"
          >
            <FolderPlus className="h-3 w-3" />
            <span>+ Quick New Folder</span>
          </button>
        </div>

        <div className="grid grid-cols-1 gap-2">
          <div>
            <label className="block text-[10px] font-medium text-slate-400 mb-0.5">
              Project
            </label>
            <select
              aria-label="Studio Target Project"
              value={activeProjectId}
              onChange={(e) => onSelectProject(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-[#0F172A] px-2.5 py-1.5 text-xs text-slate-100 focus:border-[#1A73E8] focus:outline-none"
            >
              {projects.map((p) => (
                <option key={p.project_id} value={p.project_id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-medium text-slate-400 mb-0.5">
              Target Folder
            </label>
            <select
              aria-label="Studio Target Folder"
              value={targetFolderId}
              onChange={(e) => onSelectFolder(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-[#0F172A] px-2.5 py-1.5 text-xs text-slate-100 focus:border-[#1A73E8] focus:outline-none"
            >
              {folders.length === 0 && (
                <option value={targetFolderId}>
                  {targetFolderId === 'root'
                    ? '/ (My Aerial Datasets)'
                    : targetFolderId}
                </option>
              )}
              {folders.map((f) => (
                <option key={f.folder_id} value={f.folder_id}>
                  {f.folder_path === '/'
                    ? '/ (My Aerial Datasets)'
                    : `${f.folder_path} — ${f.name}`}
                </option>
              ))}
            </select>
            <div
              data-testid="studio-target-folder-badge"
              className="mt-1.5 flex items-center justify-between rounded-md border border-slate-800 bg-[#0F172A]/80 px-2 py-1 text-[11px]"
            >
              <span className="text-slate-400">Saving to:</span>
              <span className="font-medium text-sky-300 truncate ml-1.5">
                {(() => {
                  const matched = folders.find(
                    (f) => f.folder_id === targetFolderId
                  );
                  if (!matched) {
                    return targetFolderId === 'root'
                      ? 'My Aerial Datasets (/)'
                      : targetFolderId;
                  }
                  return `${matched.name} (${matched.folder_path})`;
                })()}
              </span>
            </div>
          </div>
        </div>

        {showQuickFolder && (
          <form
            onSubmit={handleQuickFolderSubmit}
            className="rounded-lg border border-slate-700/80 bg-[#0F172A] p-2 space-y-2"
          >
            <input
              type="text"
              value={quickFolderName}
              onChange={(e) => setQuickFolderName(e.target.value)}
              placeholder="New folder name (e.g., ridge-gusts)"
              className="w-full rounded border border-slate-700 bg-[#131B2E] px-2 py-1 text-xs text-white placeholder-slate-500 focus:border-[#1A73E8] focus:outline-none"
            />
            {quickFolderErr && (
              <p className="text-[11px] text-red-400">{quickFolderErr}</p>
            )}
            <div className="flex justify-end gap-1.5">
              <button
                type="button"
                onClick={() => setShowQuickFolder(false)}
                className="rounded px-2 py-1 text-[11px] text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={quickFolderBusy || !quickFolderName.trim()}
                className="rounded bg-[#1A73E8] px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-[#4285F4] disabled:opacity-50"
              >
                {quickFolderBusy ? 'Saving...' : 'Create'}
              </button>
            </div>
          </form>
        )}
      </section>

      {/* 2. UAV Gimbal Perspective Selector */}
      <section className="rounded-xl border border-slate-800 bg-[#131B2E] p-3 space-y-2.5">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <Camera className="h-3.5 w-3.5 text-[#38BDF8]" />
            UAV Gimbal Perspective
          </span>
        </div>

        <div className="space-y-1.5">
          {GIMBAL_MODES.map((mode) => {
            const active = cameraMode === mode;
            return (
              <button
                key={mode}
                type="button"
                aria-pressed={active}
                onClick={() => onChangeCameraMode(mode)}
                className={`w-full rounded-lg border px-2.5 py-2 text-left text-xs font-medium transition ${
                  active
                    ? 'border-[#38BDF8]/60 bg-[#1A73E8]/20 text-white shadow-sm'
                    : 'border-slate-800 bg-[#0F172A]/80 text-slate-300 hover:border-slate-700 hover:text-white'
                }`}
              >
                {CAMERA_MODE_LABELS[mode]}
              </button>
            );
          })}
        </div>

        {/* Expandable Active Orbis System Prompt Inspector */}
        <button
          type="button"
          onClick={() => setShowSystemPrompt((v) => !v)}
          className="flex w-full items-center justify-between rounded-lg border border-slate-700/70 bg-[#0F172A] px-2.5 py-1.5 text-[11px] font-medium text-sky-300 hover:border-sky-500/40"
        >
          <span>View Active Orbis System Prompt</span>
          {showSystemPrompt ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </button>

        {showSystemPrompt && (
          <div className="rounded-lg border border-slate-800 bg-[#070B12] p-2.5 space-y-1.5">
            <div className="flex items-center justify-between font-telemetry text-[10px] text-emerald-400">
              <span>passthrough: true</span>
              <span>reactor/visko-orbis-stable</span>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-300">
              {promptTextToInspect}
            </p>
          </div>
        )}
      </section>

      {/* 3. Ecosystem Preset & Altitude Controls */}
      <section className="rounded-xl border border-slate-800 bg-[#131B2E] p-3 space-y-3">
        <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          <Sliders className="h-3.5 w-3.5 text-emerald-400" />
          Ecosystem & Flight Altitude
        </div>

        <div className="grid grid-cols-2 gap-1.5">
          {QUICK_ECOSYSTEMS.map((eco) => {
            const active = ecosystemType === eco;
            return (
              <button
                key={eco}
                type="button"
                aria-pressed={active}
                onClick={() => onChangeEcosystem(eco)}
                className={`rounded-lg border px-2 py-1.5 text-[11px] font-medium transition truncate ${
                  active
                    ? 'border-[#1A73E8] bg-[#1A73E8] text-white'
                    : 'border-slate-800 bg-[#0F172A] text-slate-300 hover:border-slate-700 hover:text-white'
                }`}
              >
                {ECOSYSTEM_LABELS[eco]}
              </button>
            );
          })}
        </div>

        <div className="pt-1">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-slate-400">Drone Altitude (AGL)</span>
            <span className="font-telemetry font-semibold text-sky-300">
              {altitudeAglM.toFixed(0)} m AGL
            </span>
          </div>
          <input
            type="range"
            aria-label="Drone Altitude AGL Slider"
            min={10}
            max={500}
            step={5}
            value={altitudeAglM}
            onChange={(e) => onChangeAltitude(Number(e.target.value))}
            className="w-full accent-[#38BDF8] cursor-pointer"
          />
          <div className="flex justify-between font-telemetry text-[10px] text-slate-500">
            <span>10m</span>
            <span>150m</span>
            <span>500m</span>
          </div>
        </div>
      </section>

      {/* 4. Starter Aerial Seed Gallery (Dubai Aerial Imagery 256x256) */}
      <section className="rounded-xl border border-slate-800 bg-[#131B2E] p-3 space-y-2.5">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <ImageIcon className="h-3.5 w-3.5 text-amber-400" />
            Dubai Starter Seeds (256×256 → 16:9)
          </span>
          <span className="font-telemetry text-[10px] text-slate-500">HF Tiles</span>
        </div>

        {presets.length === 0 ? (
          <p className="text-[11px] text-slate-500">
            Starter aerial tiles load automatically when backend connects.
          </p>
        ) : (
          <div className="grid grid-cols-3 gap-1.5">
            {presets.slice(0, 6).map((tile) => {
              const isLoading = loadingPresetId === tile.preset_id;
              const isSelected = activeSeed?.preset_id === tile.preset_id;
              return (
                <button
                  key={tile.preset_id}
                  type="button"
                  disabled={Boolean(loadingPresetId)}
                  onClick={() => void onSelectPreset(tile)}
                  title={`${tile.title} (${formatEcosystemLabel(tile.ecosystem_type)})`}
                  className={`group relative overflow-hidden rounded-lg border aspect-video bg-[#070B12] transition ${
                    isSelected
                      ? 'border-emerald-400 ring-1 ring-emerald-400/50'
                      : 'border-slate-700/80 hover:border-sky-400/70'
                  }`}
                >
                  <img
                    src={resolveApiAssetUrl(tile.preview_url)}
                    alt={tile.title}
                    className="h-full w-full object-cover opacity-90 group-hover:opacity-100 transition"
                  />
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/40 to-transparent px-1 py-0.5 text-[9px] font-medium text-slate-100 truncate">
                    {tile.title}
                  </div>
                  {isLoading && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/65">
                      <Loader2 className="h-4 w-4 animate-spin text-sky-400" />
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </section>

      {/* 5. Custom Seed Media Dropzone (`seed-upload-dropzone`) */}
      <section className="rounded-xl border border-slate-800 bg-[#131B2E] p-3 space-y-2.5">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <Sparkles className="h-3.5 w-3.5 text-[#38BDF8]" />
            Seed Media Conditioning
          </span>
          <span className="font-telemetry text-[10px] text-sky-400">832×480 16:9</span>
        </div>

        <div
          data-testid="seed-upload-dropzone"
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`relative flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-3.5 text-center transition ${
            isDragging
              ? 'border-[#38BDF8] bg-sky-500/10'
              : 'border-slate-700 bg-[#0F172A]/80 hover:border-sky-500/60 hover:bg-[#0F172A]'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            aria-label="Upload Seed Image or Video"
            accept=".png,.jpg,.jpeg,.webp,.mp4,.webm,image/png,image/jpeg,image/webp,video/mp4,video/webm"
            onChange={handleFileChange}
            onClick={(e) => e.stopPropagation()}
            className="sr-only"
          />

          <UploadCloud className="h-5 w-5 text-[#38BDF8] mb-1.5" />
          <p className="text-xs font-medium text-slate-200">
            Drop aerial seed image/video or click to upload
          </p>
          <p className="mt-0.5 text-[10px] text-slate-400">
            .png, .jpg, .webp, .mp4, .webm → Center-cropped to 832×480 (16:9)
          </p>

          {seedUploading && (
            <div className="mt-2.5 w-full space-y-1">
              <div className="flex items-center justify-between font-telemetry text-[10px] text-sky-300">
                <span>Normalizing & Uploading...</span>
                <span>{seedUploadProgress}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full bg-[#38BDF8] transition-all duration-200"
                  style={{ width: `${seedUploadProgress}%` }}
                />
              </div>
            </div>
          )}

          {effectivePreviewUrl && (
            <div
              onClick={(e) => e.stopPropagation()}
              className="mt-3 w-full space-y-2 text-left"
            >
              <div className="relative aspect-video w-full overflow-hidden rounded-lg border border-emerald-500/40 bg-[#070B12]">
                <img
                  src={effectivePreviewUrl}
                  alt={activeSeed?.filename || 'Normalized 16:9 Seed Preview'}
                  className="h-full w-full object-cover"
                />
                <span className="absolute top-1.5 right-1.5 rounded bg-black/75 px-1.5 py-0.5 font-telemetry text-[10px] font-semibold text-emerald-300">
                  {activeSeed ? `${activeSeed.width}×${activeSeed.height} (${activeSeed.aspect_ratio})` : '16:9 Preview'}
                </span>
              </div>

              {activeSeed?.seed_media_gcs_uri && (
                <div className="rounded border border-slate-700/80 bg-[#070B12] px-2 py-1 font-telemetry text-[10px] text-sky-300 break-all">
                  {activeSeed.seed_media_gcs_uri}
                </div>
              )}

              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1 text-[11px] font-medium text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                  <span>
                    {seedConditioningStatus || 'Conditioned & Applied (16:9)'}
                  </span>
                </span>
                {activeSeed && (
                  <button
                    type="button"
                    onClick={() => void onReapplySeed()}
                    className="flex items-center gap-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[10px] font-semibold text-slate-200 hover:border-sky-400 hover:text-white"
                  >
                    <RefreshCw className="h-3 w-3" />
                    <span>Re-apply Seed</span>
                  </button>
                )}
              </div>
            </div>
          )}

          {seedError && (
            <p className="mt-2 text-[11px] font-medium text-red-400">{seedError}</p>
          )}
        </div>
      </section>
    </aside>
  );
}
