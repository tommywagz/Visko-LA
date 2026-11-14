'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Activity,
  Cloud,
  Compass,
  Database,
  FolderKanban,
  HardDrive,
  Layers,
  Plus,
  Radio,
  Video,
  X,
} from 'lucide-react';
import { usePlatform } from '../../context/PlatformContext';

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || '/studio';
  const {
    health,
    projects,
    activeProjectId,
    setActiveProjectId,
    createNewProject,
    connectionBadge,
    studioConnection,
  } = usePlatform();

  const [showNewProjectModal, setShowNewProjectModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [creatingProject, setCreatingProject] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);

  const isStudio = pathname.startsWith('/studio');
  const isDrive = pathname.startsWith('/drive');

  const bucketName = health?.gcs_bucket_name || health?.gcs_bucket || 'visko-orbis-aerial-datasets';
  const gcpProject = health?.gcp_project_id || 'visko-cloud-local';
  const bqDataset = health?.bq_dataset_id || 'visko_aerial_telemetry';

  const badgeStyle = (() => {
    switch (connectionBadge) {
      case 'LIVE WEBRTC':
        return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40';
      case 'PRIMING':
        return 'bg-amber-500/15 text-amber-300 border-amber-500/40';
      case 'MOCK SIMULATOR':
        return 'bg-sky-500/15 text-sky-300 border-sky-500/40';
      case 'DISCONNECTED':
      default:
        return 'bg-red-500/15 text-red-300 border-red-500/40';
    }
  })();

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    setCreatingProject(true);
    setProjectError(null);
    try {
      await createNewProject(newProjectName.trim());
      setNewProjectName('');
      setShowNewProjectModal(false);
    } catch (err) {
      setProjectError(err instanceof Error ? err.message : 'Failed to create project');
    } finally {
      setCreatingProject(false);
    }
  };

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-[#0F172A] text-slate-100">
      {/* Persistent Global Top Bar */}
      <header className="z-30 flex h-14 shrink-0 items-center justify-between border-b border-slate-400/15 bg-[#0F172A] px-4">
        <div className="flex items-center gap-3">
          <Link
            href={`/studio?projectId=${encodeURIComponent(activeProjectId)}`}
            className="flex items-center gap-2.5 rounded-md px-1.5 py-1 transition hover:bg-slate-800/70"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[#1A73E8] to-[#38BDF8] shadow-sm shadow-sky-500/20">
              <Compass className="h-4 w-4 text-white" />
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold tracking-tight text-white">
                  Visko-LA
                </span>
                <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] font-medium text-sky-300 border border-slate-700">
                  Orbis Stable
                </span>
              </div>
              <span className="text-[10px] text-slate-400 leading-none">
                Google Cloud × Synthetic Aerial World
              </span>
            </div>
          </Link>

          <div className="hidden h-5 w-px bg-slate-700/70 md:block" />

          {/* Active Project Selector */}
          <div className="flex items-center gap-1.5">
            <div className="flex items-center gap-1.5 rounded-md border border-slate-700/80 bg-[#131B2E] px-2.5 py-1 text-xs">
              <Layers className="h-3.5 w-3.5 text-[#4285F4]" />
              <span className="hidden text-slate-400 sm:inline">Project:</span>
              <select
                aria-label="Active Project Selector"
                value={activeProjectId}
                onChange={(e) => setActiveProjectId(e.target.value)}
                className="bg-transparent font-medium text-slate-100 focus:outline-none cursor-pointer"
              >
                {projects.map((p) => (
                  <option
                    key={p.project_id}
                    value={p.project_id}
                    className="bg-[#0F172A] text-slate-100"
                  >
                    {p.name} ({p.project_id})
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              onClick={() => setShowNewProjectModal(true)}
              title="Create New UAV Dataset Project"
              className="flex h-7 w-7 items-center justify-center rounded-md border border-slate-700/80 bg-[#131B2E] text-slate-300 hover:border-sky-500/50 hover:text-white transition"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          {/* GCP Bucket + BigQuery Pill */}
          <div className="hidden xl:flex items-center gap-2 rounded-full border border-slate-700/80 bg-[#131B2E]/90 px-3 py-1 text-[11px] text-slate-300">
            <Cloud className="h-3.5 w-3.5 text-[#4285F4]" />
            <span className="font-telemetry text-sky-300">gs://{bucketName}</span>
            <span className="text-slate-600">•</span>
            <Database className="h-3 w-3 text-emerald-400" />
            <span className="font-telemetry text-slate-300">
              {gcpProject}.{bqDataset}
            </span>
          </div>
        </div>

        {/* Right: Route Switcher & Connection Health Badge */}
        <div className="flex items-center gap-3">
          <nav
            aria-label="Primary Workspace Switcher"
            className="flex items-center rounded-lg border border-slate-700/80 bg-[#131B2E] p-0.5"
          >
            <Link
              href={`/studio?projectId=${encodeURIComponent(activeProjectId)}`}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
                isStudio
                  ? 'bg-[#1A73E8] text-white shadow-sm'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
              }`}
            >
              <Video className="h-3.5 w-3.5" />
              <span>Aerial Studio</span>
            </Link>
            <Link
              href={`/drive?projectId=${encodeURIComponent(activeProjectId)}`}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
                isDrive
                  ? 'bg-[#1A73E8] text-white shadow-sm'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
              }`}
            >
              <HardDrive className="h-3.5 w-3.5" />
              <span>Dataset Drive</span>
            </Link>
          </nav>

          {/* Live Connection Health Badge */}
          <div
            data-testid="connection-health-badge"
            className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-telemetry text-[11px] font-semibold tracking-wide ${badgeStyle}`}
          >
            <Radio className="h-3 w-3 animate-pulse" />
            <span>{connectionBadge}</span>
            {isStudio && studioConnection.sessionId && (
              <span className="hidden sm:inline text-[10px] opacity-80">
                #{studioConnection.chunkIndex}
              </span>
            )}
          </div>
        </div>
      </header>

      {/* Main Content Body with Left Navigation Rail */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <aside
          aria-label="Global Navigation Rail"
          className="hidden md:flex w-14 shrink-0 flex-col items-center justify-between border-r border-slate-400/15 bg-[#131B2E] py-3"
        >
          <div className="flex flex-col items-center gap-2">
            <Link
              href={`/studio?projectId=${encodeURIComponent(activeProjectId)}`}
              title="Aerial Studio (/studio)"
              className={`flex h-10 w-10 items-center justify-center rounded-lg transition ${
                isStudio
                  ? 'bg-[#1A73E8]/20 text-[#38BDF8] border border-[#38BDF8]/40'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
              }`}
            >
              <Video className="h-4 w-4" />
            </Link>
            <Link
              href={`/drive?projectId=${encodeURIComponent(activeProjectId)}`}
              title="Dataset Drive (/drive)"
              className={`flex h-10 w-10 items-center justify-center rounded-lg transition ${
                isDrive
                  ? 'bg-[#1A73E8]/20 text-[#38BDF8] border border-[#38BDF8]/40'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
              }`}
            >
              <FolderKanban className="h-4 w-4" />
            </Link>
          </div>

          <div className="flex flex-col items-center gap-2 text-slate-500">
            <div
              title={`Model: ${health?.model_id || 'reactor/visko-orbis-stable'}`}
              className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-900/80 border border-slate-800 text-emerald-400"
            >
              <Activity className="h-3.5 w-3.5" />
            </div>
          </div>
        </aside>

        <main className="flex-1 min-w-0 min-h-0 overflow-hidden">{children}</main>
      </div>

      {/* Create New Project Modal */}
      {showNewProjectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-xl border border-slate-700 bg-[#0F172A] p-5 text-slate-100 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-sm font-semibold">Create UAV Dataset Project</h3>
              <button
                type="button"
                onClick={() => setShowNewProjectModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <form onSubmit={handleCreateProject} className="mt-4 space-y-3">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Project Name
                </label>
                <input
                  type="text"
                  autoFocus
                  required
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  placeholder="e.g., Autonomous eVTOL Crosswind Eval"
                  className="w-full rounded-lg border border-slate-700 bg-[#131B2E] px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-[#1A73E8] focus:outline-none"
                />
              </div>
              {projectError && (
                <p className="text-xs text-red-400">{projectError}</p>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowNewProjectModal(false)}
                  className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingProject || !newProjectName.trim()}
                  className="rounded-lg bg-[#1A73E8] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#4285F4] disabled:opacity-50"
                >
                  {creatingProject ? 'Creating...' : 'Create Project'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
