'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import {
  ArrowUpDown,
  ChevronRight,
  Download,
  Film,
  Folder,
  Gauge,
  LayoutGrid,
  List,
  Loader2,
  Search,
  Sparkles,
  Upload,
  Wind,
} from 'lucide-react';
import {
  createProjectFolder,
  getDatasetFileStreamUrl,
  listProjectDatasets,
  listProjectFolders,
  updateDataset,
  uploadProjectDataset,
} from '../../lib/api-client';
import {
  buildBreadcrumbs,
  filterDatasets,
  getChildFolders,
  sortDatasets,
  type DatasetSortField,
  type SortDirection,
  type TurbulenceFilterOption,
} from '../../lib/drive-filters';
import {
  classifyTurbulenceEdr,
  ECOSYSTEM_LABELS,
  formatBytes,
  formatDurationPill,
  formatEcosystemLabel,
  formatEdr,
  formatPressureHpa,
  formatWindSpeed,
} from '../../lib/telemetry';
import { usePlatform } from '../../context/PlatformContext';
import type { DatasetRecord, EcosystemType, FolderRecord } from '../../types/api';
import { DriveSidebar } from './DriveSidebar';
import { DatasetInspectorDrawer } from './DatasetInspectorDrawer';
import { NewFolderModal, UploadDatasetModal } from './DriveModals';

const DEFAULT_ROOT_FOLDER: FolderRecord = {
  folder_id: 'root',
  project_id: 'default-uav-project',
  parent_folder_id: null,
  name: 'My Aerial Datasets',
  folder_path: '/',
  ecosystem_default: null,
  created_at: new Date().toISOString(),
};

export function DriveWorkspace() {
  const searchParams = useSearchParams();
  const { health, projects, activeProjectId, setActiveProjectId } = usePlatform();

  const queryProjectId = searchParams.get('projectId');
  const queryFolderId = searchParams.get('folderId');
  const querySelectedId = searchParams.get('selected');

  const [folders, setFolders] = useState<FolderRecord[]>([DEFAULT_ROOT_FOLDER]);
  const [allDatasets, setAllDatasets] = useState<DatasetRecord[]>([]);
  const [totalStorageBytes, setTotalStorageBytes] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);

  const [currentFolderId, setCurrentFolderId] = useState<string>(
    queryFolderId || 'root'
  );
  const [smartView, setSmartView] = useState<'folder' | 'all' | 'recent'>(
    queryFolderId ? 'folder' : 'folder'
  );
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');

  // Search, Filter & Sort Controls
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [durationFilter, setDurationFilter] = useState<number | null>(null);
  const [ecosystemFilter, setEcosystemFilter] = useState<string>('all');
  const [turbulenceFilter, setTurbulenceFilter] =
    useState<TurbulenceFilterOption>('all');
  const [sortBy, setSortBy] = useState<DatasetSortField>('created_at');
  const [sortDir, setSortDir] = useState<SortDirection>('desc');

  // Selected Dataset Inspector & Modals
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(
    querySelectedId
  );
  const [newFolderOpen, setNewFolderOpen] = useState<boolean>(false);
  const [uploadModalOpen, setUploadModalOpen] = useState<boolean>(false);

  useEffect(() => {
    if (queryProjectId && queryProjectId !== activeProjectId) {
      setActiveProjectId(queryProjectId);
    }
  }, [queryProjectId, activeProjectId, setActiveProjectId]);

  useEffect(() => {
    if (queryFolderId) {
      setCurrentFolderId(queryFolderId);
      setSmartView('folder');
    }
  }, [queryFolderId]);

  useEffect(() => {
    if (querySelectedId) {
      setSelectedVideoId(querySelectedId);
    }
  }, [querySelectedId]);

  const refreshDriveData = useCallback(async (projId: string) => {
    setLoading(true);
    try {
      const [folderRes, datasetRes] = await Promise.all([
        listProjectFolders(projId),
        listProjectDatasets(projId, { folder_id: 'all' }),
      ]);
      if (Array.isArray(folderRes.folders) && folderRes.folders.length > 0) {
        setFolders(folderRes.folders);
      }
      setAllDatasets(datasetRes.datasets || []);
      setTotalStorageBytes(datasetRes.storage_bytes_total || 0);
    } catch {
      // Retain existing folder/dataset view if backend transiently unavailable
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshDriveData(activeProjectId);
  }, [activeProjectId, refreshDriveData]);

  // Compute folder counts dynamically from allDatasets
  const foldersWithCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const d of allDatasets) {
      counts.set(d.folder_id, (counts.get(d.folder_id) || 0) + 1);
    }
    return folders.map((f) => ({
      ...f,
      dataset_count: counts.get(f.folder_id) ?? f.dataset_count ?? 0,
    }));
  }, [folders, allDatasets]);

  const activeProject = useMemo(
    () =>
      projects.find((p) => p.project_id === activeProjectId) || {
        project_id: activeProjectId,
        name: 'Visko UAV Perception Datasets',
      },
    [projects, activeProjectId]
  );

  const breadcrumbs = useMemo(() => {
    if (smartView === 'all') {
      return buildBreadcrumbs(foldersWithCounts, 'all');
    }
    if (smartView === 'recent') {
      return [
        {
          ...DEFAULT_ROOT_FOLDER,
          folder_id: 'recent',
          name: 'Recent Captures',
        },
      ];
    }
    return buildBreadcrumbs(foldersWithCounts, currentFolderId);
  }, [foldersWithCounts, currentFolderId, smartView]);

  const childFolders = useMemo(() => {
    if (smartView !== 'folder') return [];
    return getChildFolders(foldersWithCounts, currentFolderId);
  }, [foldersWithCounts, currentFolderId, smartView]);

  // Determine effective folder scope for dataset filtering
  const visibleDatasets = useMemo(() => {
    let effectiveFolderScope: string | null = 'all';
    if (smartView === 'folder') {
      effectiveFolderScope = currentFolderId === 'root' ? 'all' : currentFolderId;
    }

    const filtered = filterDatasets(allDatasets, {
      folderId: effectiveFolderScope,
      search: searchQuery,
      durationSeconds: durationFilter,
      ecosystemType: ecosystemFilter,
      turbulenceFilter,
    });

    const sorted = sortDatasets(
      filtered,
      smartView === 'recent' ? 'created_at' : sortBy,
      smartView === 'recent' ? 'desc' : sortDir
    );

    return smartView === 'recent' ? sorted.slice(0, 20) : sorted;
  }, [
    allDatasets,
    smartView,
    currentFolderId,
    searchQuery,
    durationFilter,
    ecosystemFilter,
    turbulenceFilter,
    sortBy,
    sortDir,
  ]);

  const selectedDataset = useMemo(
    () => allDatasets.find((d) => d.video_id === selectedVideoId) || null,
    [allDatasets, selectedVideoId]
  );

  const handleSelectFolder = useCallback((folderId: string) => {
    setCurrentFolderId(folderId);
    setSmartView('folder');
  }, []);

  const handleCreateFolder = useCallback(
    async (payload: {
      name: string;
      parent_folder_id: string | null;
      ecosystem_default: string | null;
    }) => {
      await createProjectFolder(activeProjectId, payload);
      await refreshDriveData(activeProjectId);
    },
    [activeProjectId, refreshDriveData]
  );

  const handleUploadDataset = useCallback(
    async (payload: {
      file: File;
      folder_id: string;
      title: string;
      ecosystem_type: EcosystemType;
      duration_seconds: 5 | 10 | 15;
      initial_prompt?: string;
    }) => {
      const uploaded = await uploadProjectDataset(activeProjectId, payload);
      await refreshDriveData(activeProjectId);
      setSelectedVideoId(uploaded.video_id);
    },
    [activeProjectId, refreshDriveData]
  );

  const handleMoveDataset = useCallback(
    async (videoId: string, targetFolderId: string) => {
      await updateDataset(videoId, { folder_id: targetFolderId });
      await refreshDriveData(activeProjectId);
    },
    [activeProjectId, refreshDriveData]
  );

  const toggleSortColumn = (col: DatasetSortField) => {
    if (sortBy === col) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(col);
      setSortDir('desc');
    }
  };

  const bucketName =
    health?.gcs_bucket_name || health?.gcs_bucket || 'visko-orbis-aerial-datasets';
  const bqDataset = health?.bq_dataset_id || 'visko_aerial_telemetry';
  const targetStudioFolder =
    smartView === 'folder' && currentFolderId !== 'all' ? currentFolderId : 'root';

  return (
    <div className="flex h-full w-full overflow-hidden bg-[#F8FAFC] text-slate-900">
      {/* 1. Left Drive Hierarchy & Storage Sidebar */}
      <DriveSidebar
        projects={projects}
        activeProjectId={activeProjectId}
        onSelectProject={setActiveProjectId}
        folders={foldersWithCounts}
        currentFolderId={currentFolderId}
        smartView={smartView}
        onSelectFolder={handleSelectFolder}
        onSelectSmartView={(view) => setSmartView(view)}
        onOpenNewFolderModal={() => setNewFolderOpen(true)}
        onOpenUploadDatasetModal={() => setUploadModalOpen(true)}
        totalClipsCount={allDatasets.length}
        totalStorageBytes={totalStorageBytes}
        gcsBucketName={bucketName}
        bqDatasetId={bqDataset}
      />

      {/* 2. Center Explorer Content Area */}
      <div className="flex flex-1 min-w-0 flex-col overflow-hidden">
        {/* Top Breadcrumbs + Search + Filter Toolbar */}
        <div className="border-b border-[#E2E8F0] bg-white px-5 py-3.5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {/* Interactive Drive Breadcrumbs */}
            <nav
              data-testid="drive-breadcrumbs"
              aria-label="Drive Folder Breadcrumbs"
              className="flex flex-wrap items-center gap-1 text-sm font-medium text-slate-600"
            >
              <button
                type="button"
                onClick={() => handleSelectFolder('root')}
                className="hover:text-[#1A73E8] transition"
              >
                {activeProject.name}
              </button>
              {breadcrumbs.map((crumb, idx) => {
                const isLast = idx === breadcrumbs.length - 1;
                return (
                  <React.Fragment key={crumb.folder_id}>
                    <ChevronRight className="h-4 w-4 text-slate-400" />
                    <button
                      type="button"
                      onClick={() => {
                        if (crumb.folder_id === 'all') {
                          setSmartView('all');
                        } else if (crumb.folder_id === 'recent') {
                          setSmartView('recent');
                        } else {
                          handleSelectFolder(crumb.folder_id);
                        }
                      }}
                      className={`rounded px-1.5 py-0.5 transition ${
                        isLast
                          ? 'font-bold text-slate-900 bg-slate-100'
                          : 'text-slate-600 hover:bg-slate-100 hover:text-[#1A73E8]'
                      }`}
                    >
                      {crumb.folder_id === 'root' ? 'My Aerial Datasets' : crumb.name}
                    </button>
                  </React.Fragment>
                );
              })}
            </nav>

            {/* Right: Search Input & View Mode Toggle */}
            <div className="flex items-center gap-2.5">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="search"
                  data-testid="drive-search-input"
                  aria-label="Search Datasets"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search title, ID, prompt, path..."
                  className="w-60 sm:w-72 rounded-full border border-slate-300 bg-[#F8FAFC] pl-9 pr-4 py-1.5 text-xs text-slate-900 placeholder-slate-400 focus:border-[#1A73E8] focus:bg-white focus:outline-none"
                />
              </div>

              <button
                type="button"
                data-testid="view-mode-toggle"
                aria-label="Toggle Grid or List View"
                onClick={() =>
                  setViewMode((prev) => (prev === 'grid' ? 'list' : 'grid'))
                }
                className="flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:border-[#1A73E8] hover:text-[#1A73E8] transition"
              >
                {viewMode === 'grid' ? (
                  <>
                    <List className="h-3.5 w-3.5" />
                    <span>List View</span>
                  </>
                ) : (
                  <>
                    <LayoutGrid className="h-3.5 w-3.5" />
                    <span>Grid View</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Filter Chips Row */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-[11px] font-semibold text-slate-500">
              Duration:
            </span>
            {[
              { label: 'All', val: null },
              { label: '5s', val: 5 },
              { label: '10s', val: 10 },
              { label: '15s', val: 15 },
            ].map((item) => {
              const active = durationFilter === item.val;
              return (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => setDurationFilter(item.val)}
                  className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition ${
                    active
                      ? 'border-[#1A73E8] bg-[#E8F0FE] text-[#1A73E8] font-semibold'
                      : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {item.label}
                </button>
              );
            })}

            <div className="h-4 w-px bg-slate-200 mx-1" />

            <span className="text-[11px] font-semibold text-slate-500">
              Ecosystem:
            </span>
            <select
              aria-label="Filter by Ecosystem"
              value={ecosystemFilter}
              onChange={(e) => setEcosystemFilter(e.target.value)}
              className="rounded-full border border-slate-300 bg-white px-2.5 py-0.5 text-[11px] font-medium text-slate-700 focus:border-[#1A73E8] focus:outline-none"
            >
              <option value="all">All Ecosystems</option>
              {Object.entries(ECOSYSTEM_LABELS).map(([slug, label]) => (
                <option key={slug} value={slug}>
                  {label}
                </option>
              ))}
            </select>

            <div className="h-4 w-px bg-slate-200 mx-1" />

            <span className="text-[11px] font-semibold text-slate-500">
              Turbulence:
            </span>
            {(
              [
                { label: 'All', val: 'all' },
                { label: 'Light', val: 'light' },
                { label: 'Moderate', val: 'moderate' },
                { label: 'Severe+', val: 'severe_plus' },
              ] as const
            ).map((item) => {
              const active = turbulenceFilter === item.val;
              return (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => setTurbulenceFilter(item.val)}
                  className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition ${
                    active
                      ? 'border-[#1A73E8] bg-[#E8F0FE] text-[#1A73E8] font-semibold'
                      : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Main Scrollable Folders + Datasets Canvas */}
        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {/* Subfolders Row */}
          {childFolders.length > 0 && (
            <section className="space-y-2.5">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                Folders ({childFolders.length})
              </h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {childFolders.map((folder) => (
                  <button
                    key={folder.folder_id}
                    type="button"
                    onClick={() => handleSelectFolder(folder.folder_id)}
                    className="group flex items-center justify-between rounded-xl border border-[#E2E8F0] bg-white p-3.5 text-left shadow-sm hover:border-[#1A73E8] hover:shadow-md transition"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#E8F0FE] text-[#1A73E8]">
                        <Folder className="h-5 w-5" />
                      </div>
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-slate-900 group-hover:text-[#1A73E8]">
                          {folder.name}
                        </div>
                        <div className="truncate font-telemetry text-[11px] text-slate-500">
                          {folder.folder_path}
                        </div>
                      </div>
                    </div>
                    <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 font-telemetry text-[11px] font-semibold text-slate-600">
                      {folder.dataset_count ?? 0}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {/* Dataset Clips Section */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                Synthetic Aerial Dataset Clips ({visibleDatasets.length})
              </h2>
              {loading && (
                <span className="flex items-center gap-1.5 text-xs text-slate-500">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-[#1A73E8]" />
                  Syncing catalog...
                </span>
              )}
            </div>

            {visibleDatasets.length === 0 ? (
              <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
                <Film className="h-10 w-10 text-slate-300 mb-3" />
                <h3 className="text-sm font-bold text-slate-800">
                  No Aerial Dataset Clips in This View
                </h3>
                <p className="mt-1 max-w-md text-xs text-slate-500">
                  Launch Aerial Studio to generate synchronized 5s/10s/15s Orbis perception clips straight into this folder, or upload an existing .mp4 clip.
                </p>
                <div className="mt-4 flex flex-wrap items-center gap-2.5">
                  <Link
                    href={`/studio?projectId=${encodeURIComponent(
                      activeProjectId
                    )}&folderId=${encodeURIComponent(targetStudioFolder)}`}
                    className="flex items-center gap-1.5 rounded-xl bg-[#1A73E8] px-4 py-2 text-xs font-semibold text-white hover:bg-[#4285F4]"
                  >
                    <Sparkles className="h-4 w-4" />
                    <span>Generate in Studio</span>
                  </Link>
                  <button
                    type="button"
                    onClick={() => setUploadModalOpen(true)}
                    className="flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:border-[#1A73E8] hover:text-[#1A73E8]"
                  >
                    <Upload className="h-4 w-4 text-emerald-600" />
                    <span>Upload .mp4 Clip</span>
                  </button>
                </div>
              </div>
            ) : viewMode === 'grid' ? (
              /* Grid View Cards */
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {visibleDatasets.map((clip) => {
                  const turb = classifyTurbulenceEdr(clip.max_turbulence_edr);
                  const isSelected = selectedVideoId === clip.video_id;
                  return (
                    <div
                      key={clip.video_id}
                      onClick={() => setSelectedVideoId(clip.video_id)}
                      className={`group flex cursor-pointer flex-col overflow-hidden rounded-2xl border bg-white shadow-sm transition hover:shadow-md ${
                        isSelected
                          ? 'border-[#1A73E8] ring-2 ring-[#1A73E8]/25'
                          : 'border-[#E2E8F0] hover:border-slate-300'
                      }`}
                    >
                      {/* Ecosystem Visual Banner */}
                      <div className="relative flex h-32 flex-col justify-between bg-gradient-to-br from-[#0F172A] via-[#131B2E] to-[#1E3A5F] p-3 text-white">
                        <div className="flex items-center justify-between">
                          <span className="rounded-md bg-black/50 px-2 py-0.5 text-[10px] font-semibold text-sky-300 backdrop-blur-sm">
                            {formatEcosystemLabel(clip.ecosystem_type)}
                          </span>
                          <span className="rounded-md bg-[#1A73E8] px-2 py-0.5 font-telemetry text-[11px] font-bold text-white">
                            {formatDurationPill(clip.duration_seconds)}
                          </span>
                        </div>

                        <div className="flex items-center justify-between text-[11px]">
                          <span className="truncate font-telemetry text-slate-300">
                            {clip.folder_path}
                          </span>
                          <span
                            className="rounded px-1.5 py-0.5 font-telemetry text-[10px] font-bold text-white"
                            style={{ backgroundColor: turb.severityColor }}
                          >
                            {turb.badge}
                          </span>
                        </div>
                      </div>

                      {/* Card Body */}
                      <div className="flex flex-1 flex-col justify-between p-3.5 space-y-3">
                        <div>
                          <h3 className="truncate text-sm font-bold text-slate-900 group-hover:text-[#1A73E8]">
                            {clip.title}
                          </h3>
                          <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">
                            {clip.initial_prompt}
                          </p>
                        </div>

                        {/* Telemetry Mini-Pills */}
                        <div className="flex flex-wrap items-center gap-1.5 font-telemetry text-[11px]">
                          <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-slate-700">
                            <Wind className="h-3 w-3 text-sky-600" />
                            {formatWindSpeed(clip.avg_wind_speed_mps)}
                          </span>
                          <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-slate-700">
                            <Gauge className="h-3 w-3 text-emerald-600" />
                            {formatPressureHpa(clip.avg_air_pressure_hpa)}
                          </span>
                          <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-slate-700">
                            {formatEdr(clip.max_turbulence_edr)}
                          </span>
                        </div>

                        <div className="flex items-center justify-between border-t border-slate-100 pt-2 text-[11px] text-slate-500">
                          <span className="font-telemetry">
                            {formatBytes(clip.file_size_bytes)}
                          </span>
                          <div className="flex items-center gap-2">
                            <a
                              href={getDatasetFileStreamUrl(clip.video_id)}
                              download={`${clip.video_id}.mp4`}
                              onClick={(e) => e.stopPropagation()}
                              className="inline-flex items-center gap-1 font-semibold text-[#1A73E8] hover:underline"
                            >
                              <Download className="h-3 w-3" />
                              MP4
                            </a>
                            <span className="font-semibold text-slate-700 group-hover:text-[#1A73E8]">
                              Inspect →
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              /* Dense Sortable Google Cloud / Drive List View Table */
              <div className="overflow-x-auto rounded-2xl border border-[#E2E8F0] bg-white shadow-sm">
                <table className="w-full border-collapse text-left text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 bg-[#F8FAFC] text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                      <th className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => toggleSortColumn('title')}
                          className="inline-flex items-center gap-1 hover:text-slate-900"
                        >
                          Title / Video ID <ArrowUpDown className="h-3 w-3" />
                        </button>
                      </th>
                      <th className="px-3 py-3">Folder</th>
                      <th className="px-3 py-3">Ecosystem</th>
                      <th className="px-3 py-3">
                        <button
                          type="button"
                          onClick={() => toggleSortColumn('duration_seconds')}
                          className="inline-flex items-center gap-1 hover:text-slate-900"
                        >
                          Duration <ArrowUpDown className="h-3 w-3" />
                        </button>
                      </th>
                      <th className="px-3 py-3">
                        <button
                          type="button"
                          onClick={() => toggleSortColumn('avg_wind_speed_mps')}
                          className="inline-flex items-center gap-1 hover:text-slate-900"
                        >
                          Avg Wind <ArrowUpDown className="h-3 w-3" />
                        </button>
                      </th>
                      <th className="px-3 py-3">
                        <button
                          type="button"
                          onClick={() => toggleSortColumn('avg_air_pressure_hpa')}
                          className="inline-flex items-center gap-1 hover:text-slate-900"
                        >
                          Pressure <ArrowUpDown className="h-3 w-3" />
                        </button>
                      </th>
                      <th className="px-3 py-3">
                        <button
                          type="button"
                          onClick={() => toggleSortColumn('max_turbulence_edr')}
                          className="inline-flex items-center gap-1 hover:text-slate-900"
                        >
                          Max EDR <ArrowUpDown className="h-3 w-3" />
                        </button>
                      </th>
                      <th className="px-3 py-3">
                        <button
                          type="button"
                          onClick={() => toggleSortColumn('file_size_bytes')}
                          className="inline-flex items-center gap-1 hover:text-slate-900"
                        >
                          Size <ArrowUpDown className="h-3 w-3" />
                        </button>
                      </th>
                      <th className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => toggleSortColumn('created_at')}
                          className="inline-flex items-center gap-1 hover:text-slate-900"
                        >
                          Created <ArrowUpDown className="h-3 w-3" />
                        </button>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {visibleDatasets.map((clip) => {
                      const turb = classifyTurbulenceEdr(clip.max_turbulence_edr);
                      const isSelected = selectedVideoId === clip.video_id;
                      return (
                        <tr
                          key={clip.video_id}
                          onClick={() => setSelectedVideoId(clip.video_id)}
                          className={`cursor-pointer transition ${
                            isSelected ? 'bg-[#E8F0FE]/70' : 'hover:bg-slate-50'
                          }`}
                        >
                          <td className="px-4 py-3">
                            <div className="font-semibold text-slate-900">
                              {clip.title}
                            </div>
                            <div className="font-telemetry text-[11px] text-slate-500">
                              {clip.video_id}
                            </div>
                          </td>
                          <td className="px-3 py-3 font-telemetry text-slate-600">
                            {clip.folder_path}
                          </td>
                          <td className="px-3 py-3 text-slate-700">
                            {formatEcosystemLabel(clip.ecosystem_type)}
                          </td>
                          <td className="px-3 py-3 font-telemetry font-semibold text-[#1A73E8]">
                            {formatDurationPill(clip.duration_seconds)}
                          </td>
                          <td className="px-3 py-3 font-telemetry text-slate-700">
                            {formatWindSpeed(clip.avg_wind_speed_mps)}
                          </td>
                          <td className="px-3 py-3 font-telemetry text-slate-700">
                            {formatPressureHpa(clip.avg_air_pressure_hpa)}
                          </td>
                          <td className="px-3 py-3 font-telemetry">
                            <span
                              className="rounded px-1.5 py-0.5 text-[10px] font-bold text-white"
                              style={{ backgroundColor: turb.severityColor }}
                            >
                              {formatEdr(clip.max_turbulence_edr)}
                            </span>
                          </td>
                          <td className="px-3 py-3 font-telemetry text-slate-600">
                            {formatBytes(clip.file_size_bytes)}
                          </td>
                          <td className="px-4 py-3 font-telemetry text-[11px] text-slate-500">
                            {clip.created_at.slice(0, 19).replace('T', ' ')}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>

      {/* 3. Right BigQuery Metadata Inspector Drawer (`dataset-inspector-drawer`) */}
      <DatasetInspectorDrawer
        dataset={selectedDataset}
        folders={foldersWithCounts}
        onClose={() => setSelectedVideoId(null)}
        onMoveDataset={handleMoveDataset}
      />

      {/* Modals */}
      <NewFolderModal
        open={newFolderOpen}
        folders={foldersWithCounts}
        defaultParentFolderId={currentFolderId}
        onClose={() => setNewFolderOpen(false)}
        onCreateFolder={handleCreateFolder}
      />

      <UploadDatasetModal
        open={uploadModalOpen}
        folders={foldersWithCounts}
        defaultFolderId={currentFolderId}
        onClose={() => setUploadModalOpen(false)}
        onUploadDataset={handleUploadDataset}
      />
    </div>
  );
}
