'use client';

import React, { useEffect, useRef } from 'react';
import { Sparkles } from 'lucide-react';
import type {
  CameraMode,
  EcosystemType,
  TelemetryFrame,
  WsSyntheticFrameMessage,
} from '../../types/api';
import { formatCameraModeLabel, formatEcosystemLabel } from '../../lib/telemetry';

interface Palette {
  skyTop: string;
  skyBottom: string;
  groundNear: string;
  groundFar: string;
  gridColor: string;
  ridgeColor: string;
  particleColor: string;
}

const ECOSYSTEM_PALETTES: Record<string, Palette> = {
  alpine: {
    skyTop: '#0B192C',
    skyBottom: '#1E3A5F',
    groundNear: '#0F172A',
    groundFar: '#1E293B',
    gridColor: 'rgba(56, 189, 248, 0.34)',
    ridgeColor: '#334155',
    particleColor: 'rgba(226, 232, 240, 0.65)',
  },
  coastal: {
    skyTop: '#082032',
    skyBottom: '#155E75',
    groundNear: '#042F2E',
    groundFar: '#0F4C5C',
    gridColor: 'rgba(45, 212, 191, 0.35)',
    ridgeColor: '#1E3A4C',
    particleColor: 'rgba(186, 230, 253, 0.65)',
  },
  urban_canyon: {
    skyTop: '#090D16',
    skyBottom: '#1E293B',
    groundNear: '#090D16',
    groundFar: '#111827',
    gridColor: 'rgba(96, 165, 250, 0.38)',
    ridgeColor: '#1F2937',
    particleColor: 'rgba(147, 197, 253, 0.55)',
  },
  temperate_forest: {
    skyTop: '#0A1F1C',
    skyBottom: '#1B4332',
    groundNear: '#071A12',
    groundFar: '#132A1E',
    gridColor: 'rgba(52, 211, 153, 0.32)',
    ridgeColor: '#1E3F2B',
    particleColor: 'rgba(209, 250, 229, 0.5)',
  },
  arid_desert: {
    skyTop: '#271509',
    skyBottom: '#78350F',
    groundNear: '#1C1008',
    groundFar: '#451A03',
    gridColor: 'rgba(251, 191, 36, 0.34)',
    ridgeColor: '#5C2B0E',
    particleColor: 'rgba(253, 230, 138, 0.6)',
  },
  wetlands: {
    skyTop: '#0D1B2A',
    skyBottom: '#1B3B4B',
    groundNear: '#09191F',
    groundFar: '#123138',
    gridColor: 'rgba(56, 189, 248, 0.3)',
    ridgeColor: '#1F3A42',
    particleColor: 'rgba(207, 250, 254, 0.55)',
  },
  custom: {
    skyTop: '#070B12',
    skyBottom: '#1E293B',
    groundNear: '#070B12',
    groundFar: '#0F172A',
    gridColor: 'rgba(56, 189, 248, 0.32)',
    ridgeColor: '#1E293B',
    particleColor: 'rgba(148, 163, 184, 0.6)',
  },
};

export interface SyntheticFlightSimulatorCanvasProps {
  telemetry: TelemetryFrame;
  cameraMode: CameraMode;
  ecosystemType: EcosystemType;
  syntheticFrame?: WsSyntheticFrameMessage | null;
  seedPreviewUrl?: string | null;
  isReanchoring?: boolean;
}

export function SyntheticFlightSimulatorCanvas({
  telemetry,
  cameraMode,
  ecosystemType,
  syntheticFrame,
  seedPreviewUrl,
  isReanchoring = false,
}: SyntheticFlightSimulatorCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const telemetryRef = useRef<TelemetryFrame>(telemetry);
  const cameraModeRef = useRef<CameraMode>(cameraMode);
  const ecosystemRef = useRef<EcosystemType>(ecosystemType);
  const synthRef = useRef<WsSyntheticFrameMessage | null | undefined>(syntheticFrame);
  const seedImageRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    telemetryRef.current = telemetry;
  }, [telemetry]);

  useEffect(() => {
    cameraModeRef.current = cameraMode;
  }, [cameraMode]);

  useEffect(() => {
    ecosystemRef.current = ecosystemType;
  }, [ecosystemType]);

  useEffect(() => {
    synthRef.current = syntheticFrame;
  }, [syntheticFrame]);

  useEffect(() => {
    if (!seedPreviewUrl) {
      seedImageRef.current = null;
      return;
    }
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      seedImageRef.current = img;
    };
    img.onerror = () => {
      seedImageRef.current = null;
    };
    img.src = seedPreviewUrl;
  }, [seedPreviewUrl]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId = 0;
    let phase = 0;
    let lastTs = performance.now();

    const particles = Array.from({ length: 64 }, (_, idx) => ({
      x: ((idx * 97) % 100) / 100,
      y: ((idx * 53) % 100) / 100,
      len: 10 + (idx % 5) * 6,
      speedScale: 0.6 + (idx % 4) * 0.25,
    }));

    const render = (now: number) => {
      const dt = Math.min(0.1, Math.max(0.001, (now - lastTs) / 1000));
      lastTs = now;

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(320, Math.floor(rect.width));
      const height = Math.max(200, Math.floor(rect.height));

      if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr;
        canvas.height = height * dpr;
      }

      ctx.save();
      ctx.scale(dpr, dpr);

      const t = telemetryRef.current;
      const mode = cameraModeRef.current;
      const eco = ecosystemRef.current || (t.ecosystem_type as EcosystemType) || 'alpine';
      const palette = ECOSYSTEM_PALETTES[eco] || ECOSYSTEM_PALETTES.alpine;

      const airspeed = Math.max(2, t.drone_airspeed_mps || 12);
      const windSpeed = Math.max(0, t.wind_speed_mps || 8);
      const windDirRad = ((t.wind_direction_deg || 0) * Math.PI) / 180;
      const edr = Math.max(0, t.turbulence_edr || 0);
      const altitude = Math.max(5, t.drone_altitude_agl_m || 65);

      phase = (phase + dt * (airspeed * 0.08 + 0.4)) % 1;

      const buffetPitch = Math.sin(now * 0.007) * edr * 4.5;
      const buffetRoll = Math.cos(now * 0.0055) * edr * 6.0;
      const pitchDeg =
        (synthRef.current?.horizon_pitch_deg ?? t.drone_pitch_deg ?? -6) + buffetPitch;
      const rollDeg =
        (synthRef.current?.horizon_roll_deg ?? t.drone_roll_deg ?? 0) + buffetRoll;

      if (mode === 'nadir_downward') {
        // Straight-down (-90 deg) overhead mapping projection
        const bgGrad = ctx.createRadialGradient(
          width * 0.5,
          height * 0.5,
          20,
          width * 0.5,
          height * 0.5,
          Math.max(width, height) * 0.7
        );
        bgGrad.addColorStop(0, palette.groundFar);
        bgGrad.addColorStop(1, palette.groundNear);
        ctx.fillStyle = bgGrad;
        ctx.fillRect(0, 0, width, height);

        if (seedImageRef.current) {
          ctx.save();
          ctx.globalAlpha = 0.28;
          ctx.drawImage(seedImageRef.current, 0, 0, width, height);
          ctx.restore();
        }

        const cell = Math.max(28, Math.min(90, 3200 / altitude));
        const offsetY = (phase * cell * 4) % cell;
        ctx.strokeStyle = palette.gridColor;
        ctx.lineWidth = 1;

        for (let x = 0; x <= width; x += cell) {
          ctx.beginPath();
          ctx.moveTo(x, 0);
          ctx.lineTo(x, height);
          ctx.stroke();
        }
        for (let y = -cell + offsetY; y <= height; y += cell) {
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(width, y);
          ctx.stroke();
        }

        // Nadir concentric range rings
        ctx.strokeStyle = 'rgba(56, 189, 248, 0.25)';
        [60, 120, 190].forEach((r) => {
          ctx.beginPath();
          ctx.arc(width / 2, height / 2, r, 0, Math.PI * 2);
          ctx.stroke();
        });
      } else {
        // Oblique (-35 deg) or Forward FPV (-15 deg) perspective flight corridor
        const baseHorizonRatio = mode === 'forward_fpv' ? 0.46 : 0.32;
        const horizonY = Math.max(
          height * 0.12,
          Math.min(height * 0.78, height * baseHorizonRatio - pitchDeg * 3.2)
        );

        ctx.save();
        ctx.translate(width / 2, height / 2);
        ctx.rotate((rollDeg * Math.PI) / 180);
        ctx.translate(-width / 2, -height / 2);

        // Sky gradient
        const skyGrad = ctx.createLinearGradient(0, -height * 0.3, 0, horizonY);
        skyGrad.addColorStop(0, palette.skyTop);
        skyGrad.addColorStop(1, palette.skyBottom);
        ctx.fillStyle = skyGrad;
        ctx.fillRect(-width * 0.4, -height * 0.4, width * 1.8, horizonY + height * 0.4);

        // Ground gradient
        const groundGrad = ctx.createLinearGradient(0, horizonY, 0, height * 1.3);
        groundGrad.addColorStop(0, palette.groundFar);
        groundGrad.addColorStop(1, palette.groundNear);
        ctx.fillStyle = groundGrad;
        ctx.fillRect(
          -width * 0.4,
          horizonY,
          width * 1.8,
          height * 1.5 - horizonY
        );

        // Conditioned Seed subtle ground/world projection
        if (seedImageRef.current) {
          ctx.save();
          ctx.globalAlpha = 0.24;
          ctx.drawImage(seedImageRef.current, 0, 0, width, height);
          ctx.restore();
        }

        // Distant terrain ridge silhouette along horizon
        ctx.fillStyle = palette.ridgeColor;
        ctx.beginPath();
        ctx.moveTo(-width * 0.2, horizonY);
        const ridgePeaks = eco === 'alpine' ? 42 : eco === 'urban_canyon' ? 28 : 16;
        for (let x = -width * 0.2; x <= width * 1.2; x += 28) {
          const h =
            Math.abs(Math.sin(x * 0.013 + 1.2) * ridgePeaks) +
            Math.abs(Math.cos(x * 0.031) * (ridgePeaks * 0.45));
          ctx.lineTo(x, horizonY - h);
        }
        ctx.lineTo(width * 1.2, horizonY);
        ctx.closePath();
        ctx.fill();

        // Perspective forward-moving ground grid
        ctx.strokeStyle = palette.gridColor;
        ctx.lineWidth = 1;
        const vanishX = width / 2;
        for (let i = -14; i <= 14; i += 1) {
          ctx.beginPath();
          ctx.moveTo(vanishX + i * 14, horizonY);
          ctx.lineTo(vanishX + i * (width * 0.14), height * 1.25);
          ctx.stroke();
        }

        const groundSpan = height * 1.2 - horizonY;
        const altitudeFactor = Math.max(0.5, Math.min(2.0, 80 / altitude));
        for (let row = 0; row < 14; row += 1) {
          const progress = ((row + phase) / 14) * altitudeFactor;
          const clamped = progress % 1;
          const y = horizonY + Math.pow(clamped, 2.1) * groundSpan;
          ctx.beginPath();
          ctx.moveTo(-width * 0.25, y);
          ctx.lineTo(width * 1.25, y);
          ctx.stroke();
        }

        ctx.restore();
      }

      // Wind & atmospheric mist vector particles
      const vx = Math.sin(windDirRad) * (windSpeed * 8 + 18);
      const vy = -Math.cos(windDirRad) * (windSpeed * 4) + airspeed * 6;
      ctx.strokeStyle = palette.particleColor;
      ctx.lineWidth = edr >= 0.45 ? 1.8 : 1.2;

      for (const p of particles) {
        p.x = (((p.x + (vx * dt * p.speedScale) / width) % 1) + 1) % 1;
        p.y = (((p.y + (vy * dt * p.speedScale) / height) % 1) + 1) % 1;
        const px = p.x * width;
        const py = p.y * height;
        const angle = Math.atan2(vy, vx);
        const streak = p.len * (1 + windSpeed * 0.05);
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(px - Math.cos(angle) * streak, py - Math.sin(angle) * streak);
        ctx.stroke();
      }

      // Artificial Horizon Pitch Ladder & Center Flight Reticle
      const cx = width / 2;
      const cy = height / 2;
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(((t.drone_roll_deg || 0) * Math.PI) / 180);

      ctx.strokeStyle = 'rgba(56, 189, 248, 0.7)';
      ctx.lineWidth = 1.4;
      // Horizon wings
      ctx.beginPath();
      ctx.moveTo(-64, 0);
      ctx.lineTo(-22, 0);
      ctx.lineTo(-22, 7);
      ctx.moveTo(64, 0);
      ctx.lineTo(22, 0);
      ctx.lineTo(22, 7);
      ctx.stroke();

      // Pitch rungs
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.35)';
      ctx.lineWidth = 1;
      [-36, -18, 18, 36].forEach((offset) => {
        ctx.beginPath();
        ctx.moveTo(-26, offset);
        ctx.lineTo(-10, offset);
        ctx.moveTo(10, offset);
        ctx.lineTo(26, offset);
        ctx.stroke();
      });

      // Center optical boresight dot
      ctx.fillStyle = '#38BDF8';
      ctx.beginPath();
      ctx.arc(0, 0, 2.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      ctx.restore();
      animId = window.requestAnimationFrame(render);
    };

    animId = window.requestAnimationFrame(render);
    return () => window.cancelAnimationFrame(animId);
  }, []);

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#070B12]">
      <canvas
        ref={canvasRef}
        aria-label="Synthetic Drone-POV Flight Simulator Viewport"
        className="block h-full w-full"
      />

      {/* Top-Left Optical Sensor Stamp */}
      <div className="pointer-events-none absolute top-3 left-3 flex flex-wrap items-center gap-2">
        <span className="rounded-md border border-sky-500/30 bg-[#0F172A]/85 px-2.5 py-1 font-telemetry text-[11px] font-medium text-sky-300 backdrop-blur-sm">
          SIMULATOR · {formatEcosystemLabel(ecosystemType).toUpperCase()}
        </span>
        <span className="rounded-md border border-slate-700/80 bg-[#0F172A]/85 px-2.5 py-1 font-telemetry text-[11px] text-slate-300 backdrop-blur-sm">
          {formatCameraModeLabel(cameraMode)}
        </span>
        {seedPreviewUrl && (
          <span className="rounded-md border border-emerald-500/40 bg-emerald-950/80 px-2.5 py-1 font-telemetry text-[11px] text-emerald-300 backdrop-blur-sm">
            SEED ANCHORED · 832×480 (16:9)
          </span>
        )}
      </div>

      {isReanchoring && (
        <div className="pointer-events-none absolute top-12 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 rounded-full border border-amber-400/50 bg-[#0F172A]/95 px-4 py-1.5 text-xs font-medium text-amber-200 shadow-lg">
          <Sparkles className="h-3.5 w-3.5 animate-spin text-amber-400" />
          <span>Re-anchoring Orbis World to New Seed...</span>
        </div>
      )}
    </div>
  );
}
