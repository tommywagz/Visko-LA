'use client';

import React, { useEffect, useRef, useState } from 'react';
import {
  CheckCircle2,
  Loader2,
  MessageSquare,
  Send,
  Sparkles,
  Zap,
} from 'lucide-react';
import type { PromptEntry } from '../../types/api';

const TACTICAL_CHIPS = [
  {
    label: '+ Crosswind 18 m/s',
    prompt: 'Increase crosswind gusts to 18 m/s bending vegetation laterally across the flight path',
  },
  {
    label: '+ Coastal Fog',
    prompt: 'Dense coastal sea fog rolls across the lower terrain corridor reducing distant visibility',
  },
  {
    label: '+ Ridge Turbulence',
    prompt: 'Severe ridge turbulence with swirling rotor gusts and blowing surface dust',
  },
  {
    label: '+ Golden Hour Dusk',
    prompt: 'Warm golden hour dusk sunlight casts long terrain shadows across ridges below',
  },
  {
    label: '+ Storm Front',
    prompt: 'Heavy storm front rolls in with 24 m/s gale gusts and dark low-pressure clouds',
  },
];

export interface SceneChatDrawerProps {
  promptHistory: PromptEntry[];
  sendingPrompt: boolean;
  chatError: string | null;
  onSendPrompt: (promptText: string) => Promise<void>;
}

export function SceneChatDrawer({
  promptHistory,
  sendingPrompt,
  chatError,
  onSendPrompt,
}: SceneChatDrawerProps) {
  const [inputText, setInputText] = useState('');
  const scrollEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [promptHistory.length]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = inputText.trim();
    if (!trimmed || sendingPrompt) return;
    setInputText('');
    await onSendPrompt(trimmed);
  };

  return (
    <aside
      data-testid="scene-chat-panel"
      className="flex h-full w-full flex-col border-l border-slate-400/15 bg-[#0F172A] lg:w-80 xl:w-[350px] shrink-0"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-[#38BDF8]" />
          <div>
            <h2 className="text-xs font-semibold text-white">
              Live Scene & Weather Steering
            </h2>
            <p className="text-[10px] text-slate-400">
              Hot-swaps at next 1.833s Orbis chunk boundary
            </p>
          </div>
        </div>
        <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 font-telemetry text-[10px] text-emerald-300">
          No Reset
        </span>
      </div>

      {/* Prompt History Timeline */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-2.5">
        {promptHistory.length === 0 ? (
          <div className="rounded-xl border border-slate-800 bg-[#131B2E]/60 p-4 text-center text-xs text-slate-400">
            Initializing Drone-POV world stake prompt...
          </div>
        ) : (
          promptHistory.map((entry, idx) => {
            const isOpening = idx === 0;
            const isMorphing = entry.status === 'morphing';
            return (
              <div
                key={`${entry.prompt_id}_${idx}`}
                className={`rounded-xl border p-3 space-y-1.5 ${
                  isOpening
                    ? 'border-sky-500/30 bg-[#131B2E]'
                    : 'border-slate-800 bg-[#131B2E]/85'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-telemetry text-[10px] font-semibold text-[#38BDF8]">
                    {isOpening
                      ? `Opening World Stake · Chunk #${entry.chunk_index}`
                      : `Live Steer · Chunk #${entry.chunk_index}`}
                  </span>
                  <span
                    className={`flex items-center gap-1 rounded-full px-2 py-0.5 font-telemetry text-[10px] font-medium ${
                      isMorphing
                        ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                        : 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                    }`}
                  >
                    {isMorphing ? (
                      <>
                        <Loader2 className="h-2.5 w-2.5 animate-spin" />
                        <span>Morphing at next chunk boundary...</span>
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="h-2.5 w-2.5" />
                        <span>Applied</span>
                      </>
                    )}
                  </span>
                </div>

                <p className="text-xs font-medium text-slate-100 leading-snug">
                  {entry.prompt}
                </p>

                {entry.compiled_prompt && entry.compiled_prompt !== entry.prompt && (
                  <details className="text-[10px] text-slate-400">
                    <summary className="cursor-pointer hover:text-slate-300">
                      Compiled UAV optical prompt
                    </summary>
                    <p className="mt-1 rounded bg-[#070B12] p-2 font-mono text-[10px] text-slate-300 leading-relaxed">
                      {entry.compiled_prompt}
                    </p>
                  </details>
                )}
              </div>
            );
          })
        )}
        <div ref={scrollEndRef} />
      </div>

      {/* Tactical Quick-Steer Chips */}
      <div className="border-t border-slate-800 bg-[#131B2E]/60 px-3 py-2.5">
        <div className="mb-1.5 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          <Zap className="h-3 w-3 text-amber-400" />
          Tactical Weather & Lighting Injections
        </div>
        <div className="flex flex-wrap gap-1.5">
          {TACTICAL_CHIPS.map((chip) => (
            <button
              key={chip.label}
              type="button"
              disabled={sendingPrompt}
              onClick={() => void onSendPrompt(chip.prompt)}
              className="rounded-full border border-slate-700 bg-[#0F172A] px-2.5 py-1 text-[11px] font-medium text-slate-300 hover:border-[#38BDF8] hover:text-white transition disabled:opacity-50"
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      {/* Live Steering Input Form */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-slate-800 bg-[#0F172A] p-3 space-y-2"
      >
        {chatError && <p className="text-[11px] text-red-400">{chatError}</p>}
        <div className="flex items-center gap-2">
          <input
            type="text"
            data-testid="chat-prompt-input"
            aria-label="Live Scene Steering Prompt"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="Steer weather, crosswinds, fog, or terrain..."
            className="flex-1 rounded-xl border border-slate-700 bg-[#131B2E] px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-[#1A73E8] focus:outline-none"
          />
          <button
            type="submit"
            data-testid="chat-send-button"
            disabled={sendingPrompt || !inputText.trim()}
            className="flex h-9 items-center gap-1.5 rounded-xl bg-[#1A73E8] px-3.5 text-xs font-semibold text-white shadow-sm hover:bg-[#4285F4] disabled:opacity-50 transition"
          >
            {sendingPrompt ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
            <span>Send</span>
          </button>
        </div>
        <div className="flex items-center gap-1 text-[10px] text-slate-500">
          <Sparkles className="h-3 w-3 text-sky-400" />
          <span>Incremental camera-locked delta (`passthrough=True`)</span>
        </div>
      </form>
    </aside>
  );
}
