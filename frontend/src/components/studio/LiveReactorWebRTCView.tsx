'use client';

import React, { useCallback, useMemo } from 'react';
import {
  ReactorProvider,
  ReactorView,
  useReactor,
} from '@reactor-team/js-sdk';
import { Loader2, Radio, Sparkles } from 'lucide-react';
import { mintReactorToken } from '../../lib/api-client';
import { createMemoizedJwtResolver } from '../../lib/jwt-cache';
import type { SessionLifecycleStatus } from '../../types/api';

export interface LiveReactorWebRTCViewProps {
  sessionId: string;
  reactorSessionId?: string | null;
  initialJwt: string;
  initialExpiresAt: number;
  chunkIndex: number;
  sessionStatus: SessionLifecycleStatus;
  isReanchoring: boolean;
}

function InnerWebRTCStage({
  chunkIndex,
  sessionStatus,
  isReanchoring,
}: {
  chunkIndex: number;
  sessionStatus: SessionLifecycleStatus;
  isReanchoring: boolean;
}) {
  const { reactorStatus, lastError } = useReactor((state) => ({
    reactorStatus: state.status,
    lastError: state.lastError,
  }));

  const isPriming =
    chunkIndex === 0 ||
    sessionStatus === 'priming' ||
    sessionStatus === 'waiting' ||
    reactorStatus === 'connecting' ||
    reactorStatus === 'waiting';

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#070B12]">
      <ReactorView
        track="main_video"
        videoObjectFit="cover"
        muted
        className="h-full w-full object-cover"
      />

      {isPriming && (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center bg-[#070B12]/85 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3 rounded-2xl border border-sky-500/30 bg-[#0F172A]/90 px-6 py-5 text-center shadow-2xl">
            <Loader2 className="h-7 w-7 animate-spin text-[#38BDF8]" />
            <div className="text-sm font-semibold text-white">
              Priming Orbis World Stream (Chunk 0)...
            </div>
            <p className="max-w-sm text-xs text-slate-400">
              Visko Orbis Stable (<span className="font-telemetry text-sky-300">reactor/visko-orbis-stable</span>) warms up on 33-frame Chunk 0 (~1.833s at 18 fps) before emitting live optical frames.
            </p>
            <div className="flex items-center gap-2 rounded-full border border-slate-700 bg-slate-900/90 px-3 py-1 font-telemetry text-[11px] text-sky-300">
              <Radio className="h-3 w-3 animate-pulse" />
              <span>WebRTC: {reactorStatus.toUpperCase()}</span>
            </div>
          </div>
        </div>
      )}

      {(isReanchoring || sessionStatus === 'reanchoring') && (
        <div className="pointer-events-none absolute top-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 rounded-full border border-amber-400/50 bg-[#0F172A]/95 px-4 py-1.5 text-xs font-medium text-amber-200 shadow-lg">
          <Sparkles className="h-3.5 w-3.5 animate-spin text-amber-400" />
          <span>Re-anchoring Orbis World to New Seed...</span>
        </div>
      )}

      {lastError && (
        <div className="absolute bottom-3 left-3 z-20 rounded-lg border border-red-500/40 bg-red-950/85 px-3 py-1.5 text-[11px] text-red-200">
          WebRTC Notice ({lastError.code}): {lastError.message}
        </div>
      )}
    </div>
  );
}

export default function LiveReactorWebRTCView({
  sessionId,
  reactorSessionId,
  initialJwt,
  initialExpiresAt,
  chunkIndex,
  sessionStatus,
  isReanchoring,
}: LiveReactorWebRTCViewProps) {
  const resolver = useMemo(
    () =>
      createMemoizedJwtResolver(
        reactorSessionId || sessionId,
        (boundId) =>
          mintReactorToken({
            session_id: boundId ?? reactorSessionId ?? sessionId,
            model_id: 'reactor/visko-orbis-stable',
          }),
        initialJwt,
        initialExpiresAt
      ),
    [sessionId, reactorSessionId, initialJwt, initialExpiresAt]
  );

  const jwtCallback = useCallback(() => resolver(), [resolver]);

  const connectOptions = useMemo(
    () => ({
      autoConnect: true,
      sessionId: reactorSessionId || undefined,
    }),
    [reactorSessionId]
  );

  return (
    <ReactorProvider
      modelName="reactor/visko-orbis-stable"
      jwtToken={jwtCallback}
      connectOptions={connectOptions}
    >
      <InnerWebRTCStage
        chunkIndex={chunkIndex}
        sessionStatus={sessionStatus}
        isReanchoring={isReanchoring}
      />
    </ReactorProvider>
  );
}
