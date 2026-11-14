'use client';

import React from 'react';
import Link from 'next/link';
import {
  ArrowRight,
  CheckCircle2,
  CircleDot,
  Download,
  Film,
  Loader2,
  X,
} from 'lucide-react';
import { getDatasetFileStreamUrl } from '../../lib/api-client';
import { formatDurationPill } from '../../lib/telemetry';
import type {
  DatasetRecord,
  RecordingDuration,
  WsRecordingProgressMessage,
} from '../../types/api';

const INTERVAL_OPTIONS: RecordingDuration[] = [5, 10, 15];

export interface IntervalRecordingDockProps {
  selectedDuration: RecordingDuration;
  onSelectDuration: (duration: RecordingDuration) => void;
  clipTitle: string;
  onChangeClipTitle: (title: string) => void;
  defaultTitlePlaceholder: string;
  isRecording: boolean;
  recordingProgress: WsRecordingProgressMessage | null;
  lastCapturedDataset: DatasetRecord | null;
  recordError: string | null;
  onCaptureClip: () => Promise<void>;
  onDismissToast: () => void;
  sessionReady: boolean;
}

export function IntervalRecordingDock({
  selectedDuration,
  onSelectDuration,
  clipTitle,
  onChangeClipTitle,
  defaultTitlePlaceholder,
  isRecording,
  recordingProgress,
  lastCapturedDataset,
  recordError,
  onCaptureClip,
  onDismissToast,
  sessionReady,
}: IntervalRecordingDockProps) {
  const progressPct = recordingProgress?.progress_pct ?? (isRecording ? 45 : 0);

  return (
    <div className="relative z-20 shrink-0 border-t border-slate-800 bg-[#0F172A] px-4 py-3">
      {/* Completion Toast Banner */}
      {lastCapturedDataset && (
        <div
          role="status"
          aria-live="polite"
          className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-500/40 bg-emerald-950/60 px-4 py-2.5 text-xs text-emerald-100 shadow-lg"
        >
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
            <div>
              <span className="font-semibold text-white">
                Clip Captured & Indexed ({formatDurationPill(lastCapturedDataset.duration_seconds)}):{' '}
              </span>
              <span className="font-medium text-emerald-200">
                {lastCapturedDataset.title}
              </span>
              <span className="ml-2 font-telemetry text-[11px] text-sky-300">
                {lastCapturedDataset.gcs_video_uri}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <a
              href={getDatasetFileStreamUrl(lastCapturedDataset.video_id)}
              download={`${lastCapturedDataset.video_id}.mp4`}
              className="flex items-center gap-1 rounded-lg border border-slate-700 bg-[#0F172A] px-2.5 py-1.5 text-xs font-medium text-slate-200 hover:border-sky-400 hover:text-white transition"
            >
              <Download className="h-3.5 w-3.5 text-sky-400" />
              <span>Download MP4</span>
            </a>

            <Link
              href={`/drive?projectId=${encodeURIComponent(
                lastCapturedDataset.project_id
              )}&folderId=${encodeURIComponent(
                lastCapturedDataset.folder_id
              )}&selected=${encodeURIComponent(lastCapturedDataset.video_id)}`}
              className="flex items-center gap-1 rounded-lg bg-[#1A73E8] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#4285F4] transition"
            >
              <span>View in Dataset Drive</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>

            <button
              type="button"
              onClick={onDismissToast}
              aria-label="Dismiss capture notification"
              className="text-slate-400 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {recordError && (
        <div className="mb-2 rounded-lg border border-red-500/40 bg-red-950/60 px-3 py-1.5 text-xs text-red-200">
          {recordError}
        </div>
      )}

      {/* Main Dock Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Left: Segmented Interval Selector (`5s`, `10s`, `15s`) */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
            <Film className="h-4 w-4 text-[#38BDF8]" />
            <span>Fixed Capture Interval:</span>
          </div>

          <div
            data-testid="interval-selector"
            role="group"
            aria-label="Clip Recording Duration Selector"
            className="inline-flex items-center rounded-xl border border-slate-700 bg-[#131B2E] p-1"
          >
            {INTERVAL_OPTIONS.map((sec) => {
              const isSelected = selectedDuration === sec;
              const testId =
                sec === 5
                  ? 'interval-5s'
                  : sec === 10
                    ? 'interval-10s'
                    : 'interval-15s';
              return (
                <button
                  key={sec}
                  type="button"
                  data-testid={testId}
                  aria-pressed={isSelected}
                  data-active={isSelected ? 'true' : 'false'}
                  disabled={isRecording}
                  onClick={() => onSelectDuration(sec)}
                  className={`rounded-lg px-3.5 py-1.5 font-telemetry text-xs font-semibold transition ${
                    isSelected
                      ? 'bg-[#1A73E8] text-white shadow-sm'
                      : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                  }`}
                >
                  {sec}s
                </button>
              );
            })}
          </div>

          {/* Optional Clip Title Input */}
          <input
            type="text"
            aria-label="Optional Clip Title"
            value={clipTitle}
            onChange={(e) => onChangeClipTitle(e.target.value)}
            placeholder={defaultTitlePlaceholder}
            className="w-56 sm:w-64 rounded-xl border border-slate-700 bg-[#131B2E] px-3 py-1.5 text-xs text-white placeholder-slate-500 focus:border-[#1A73E8] focus:outline-none"
          />
        </div>

        {/* Right: Capture Progress + Record Clip CTA */}
        <div className="flex items-center gap-3">
          {isRecording && (
            <div className="flex items-center gap-2.5 rounded-xl border border-red-500/40 bg-red-950/40 px-3 py-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-[#EF4444] animate-ping" />
              <div className="w-32">
                <div className="flex justify-between font-telemetry text-[10px] text-red-200">
                  <span>{recordingProgress?.status?.toUpperCase() || 'CAPTURING'}</span>
                  <span>{Math.round(progressPct)}%</span>
                </div>
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full bg-[#EF4444] transition-all duration-200"
                    style={{ width: `${Math.max(12, progressPct)}%` }}
                  />
                </div>
              </div>
            </div>
          )}

          <button
            type="button"
            data-testid="record-clip-button"
            disabled={isRecording || !sessionReady}
            onClick={() => void onCaptureClip()}
            className="flex items-center gap-2 rounded-xl bg-[#EF4444] px-4 py-2 text-xs font-semibold text-white shadow-md shadow-red-500/20 hover:bg-red-500 disabled:opacity-50 transition"
          >
            {isRecording ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Archiving {selectedDuration}s Clip...</span>
              </>
            ) : (
              <>
                <CircleDot className="h-4 w-4" />
                <span>Capture Synthetic Clip ({selectedDuration}s)</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
