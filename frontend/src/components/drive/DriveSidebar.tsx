'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import {
  ChevronDown,
  ChevronRight,
  Clock,
  Cloud,
  Database,
  Folder,
  FolderOpen,
  FolderPlus,
  HardDrive,
  Layers,
  Sparkles,
  Upload,
} from 'lucide-react';
import { buildFolderTree, type FolderTreeNode } from '../../lib/drive-filters';
import { formatBytes } from '../../lib/telemetry';
import type { FolderRecord, ProjectRecord } from '../../types/api';

export interface DriveSidebarProps {
  projects: ProjectRecord[];
  activeProjectId: string;
  onSelectProject: (projectId: string) => void;
  folders: FolderRecord[];
  currentFolderId: string;
  smartView: 'folder' | 'all' | 'recent';
  onSelectFolder: (folderId: string) => void;
  onSelectSmartView: (view: 'all' | 'recent') => void;
  onOpenNewFolderModal: () => void;
  onOpenUploadDatasetModal: () => void;
  totalClipsCount: number;
  totalStorageBytes: number;
  gcsBucketName: string;
  bqDatasetId: string;
}

function FolderTreeItem({
  node,
  currentFolderId,
  smartView,
  onSelectFolder,
}: {
  node: FolderTreeNode;
  currentFolderId: string;
  smartView: 'folder' | 'all' | 'recent';
  onSelectFolder: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState<boolean>(true);
  const hasChildren = node.children.length > 0;
  const isSelected = smartView === 'folder' && currentFolderId === node.folder_id;

  return (
    <div>
      <div
        className={`group flex items-center justify-between rounded-lg px-2 py-1.5 text-xs font-medium transition cursor-pointer ${
          isSelected
            ? 'bg-[#E8F0FE] text-[#1A73E8] font-semibold'
            : 'text-slate-700 hover:bg-slate-100'
        }`}
        style={{ paddingLeft: `${8 + node.depth * 14}px` }}
        onClick={() => onSelectFolder(node.folder_id)}
      >
        <div className="flex items-center gap-1.5 min-w-0">
          {hasChildren ? (
            <button
              type="button"
              aria-label={`Toggle ${node.name} subfolders`}
              onClick={(e) => {
                e.stopPropagation();
                setExpanded((v) => !v);
              }}
              className="text-slate-400 hover:text-slate-700"
            >
              {expanded ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
            </button>
          ) : (
            <span className="w-3.5 shrink-0" />
          )}

          {isSelected ? (
            <FolderOpen className="h-4 w-4 shrink-0 text-[#1A73E8]" />
          ) : (
            <Folder className="h-4 w-4 shrink-0 text-slate-400 group-hover:text-slate-600" />
          )}

          <span className="truncate">
            {node.folder_id === 'root' ? 'My Aerial Datasets' : node.name}
          </span>
        </div>

        {typeof node.dataset_count === 'number' && node.dataset_count > 0 && (
          <span className="ml-1 rounded-full bg-slate-200/80 px-1.5 py-0.5 font-telemetry text-[10px] text-slate-600">
            {node.dataset_count}
          </span>
        )}
      </div>

      {hasChildren && expanded && (
        <div className="mt-0.5 space-y-0.5">
          {node.children.map((child) => (
            <FolderTreeItem
              key={child.folder_id}
              node={child}
              currentFolderId={currentFolderId}
              smartView={smartView}
              onSelectFolder={onSelectFolder}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function DriveSidebar({
  projects,
  activeProjectId,
  onSelectProject,
  folders,
  currentFolderId,
  smartView,
  onSelectFolder,
  onSelectSmartView,
  onOpenNewFolderModal,
  onOpenUploadDatasetModal,
  totalClipsCount,
  totalStorageBytes,
  gcsBucketName,
  bqDatasetId,
}: DriveSidebarProps) {
  const tree = buildFolderTree(folders);
  const targetStudioFolder =
    currentFolderId && currentFolderId !== 'all' ? currentFolderId : 'root';

  return (
    <aside
      data-testid="drive-sidebar"
      className="flex h-full w-full flex-col justify-between overflow-y-auto border-r border-[#E2E8F0] bg-white p-3.5 text-slate-800 md:w-72 shrink-0"
    >
      <div className="space-y-4">
        {/* Directly Visible Google Drive-Style `+ New` Action Cluster */}
        <div className="space-y-2 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-2.5">
          <div className="px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            + New Dataset & Folder Actions
          </div>

          <button
            type="button"
            data-testid="new-folder-button"
            onClick={onOpenNewFolderModal}
            className="flex w-full items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 shadow-sm hover:border-[#1A73E8] hover:text-[#1A73E8] transition"
          >
            <FolderPlus className="h-4 w-4 text-[#1A73E8]" />
            <span>New Folder</span>
          </button>

          <Link
            href={`/studio?projectId=${encodeURIComponent(
              activeProjectId
            )}&folderId=${encodeURIComponent(targetStudioFolder)}`}
            data-testid="generate-in-folder-button"
            className="flex w-full items-center gap-2 rounded-lg bg-[#1A73E8] px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-[#4285F4] transition"
          >
            <Sparkles className="h-4 w-4 shrink-0" />
            <span>Generate Aerial Dataset in Folder</span>
          </Link>

          <button
            type="button"
            data-testid="upload-dataset-button"
            onClick={onOpenUploadDatasetModal}
            className="flex w-full items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 shadow-sm hover:border-[#1A73E8] hover:text-[#1A73E8] transition"
          >
            <Upload className="h-4 w-4 text-emerald-600" />
            <span>Upload Dataset Clip to Folder</span>
          </button>
        </div>

        {/* Project Switcher */}
        <div className="space-y-1">
          <label className="flex items-center gap-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            <Layers className="h-3 w-3 text-[#1A73E8]" />
            Active Project
          </label>
          <select
            aria-label="Drive Project Selector"
            value={activeProjectId}
            onChange={(e) => onSelectProject(e.target.value)}
            className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-800 focus:border-[#1A73E8] focus:outline-none"
          >
            {projects.map((p) => (
              <option key={p.project_id} value={p.project_id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {/* Smart Views */}
        <div className="space-y-0.5">
          <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Views
          </div>
          <button
            type="button"
            onClick={() => onSelectSmartView('all')}
            className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-medium transition ${
              smartView === 'all'
                ? 'bg-[#E8F0FE] text-[#1A73E8] font-semibold'
                : 'text-slate-700 hover:bg-slate-100'
            }`}
          >
            <HardDrive className="h-4 w-4 text-[#1A73E8]" />
            <span>All Datasets</span>
          </button>
          <button
            type="button"
            onClick={() => onSelectSmartView('recent')}
            className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-medium transition ${
              smartView === 'recent'
                ? 'bg-[#E8F0FE] text-[#1A73E8] font-semibold'
                : 'text-slate-700 hover:bg-slate-100'
            }`}
          >
            <Clock className="h-4 w-4 text-slate-500" />
            <span>Recent Captures</span>
          </button>
        </div>

        {/* Expandable Folder Hierarchy Tree */}
        <div className="space-y-1">
          <div className="px-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Folder Hierarchy
          </div>
          <div className="space-y-0.5">
            {tree.map((node) => (
              <FolderTreeItem
                key={node.folder_id}
                node={node}
                currentFolderId={currentFolderId}
                smartView={smartView}
                onSelectFolder={onSelectFolder}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Bottom GCS Bucket + BigQuery Storage Summary Card */}
      <div className="mt-4 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
            <Cloud className="h-4 w-4 text-[#1A73E8]" />
            Cloud Storage & BQ
          </span>
          <span className="font-telemetry text-xs font-bold text-[#1A73E8]">
            {formatBytes(totalStorageBytes)}
          </span>
        </div>

        <div className="flex items-center justify-between text-[11px] text-slate-600">
          <span>Indexed Clips:</span>
          <span className="font-telemetry font-semibold text-slate-900">
            {totalClipsCount}
          </span>
        </div>

        <div className="border-t border-slate-200 pt-2 space-y-1 font-telemetry text-[10px] text-slate-500">
          <div className="truncate" title={`gs://${gcsBucketName}`}>
            Bucket: gs://{gcsBucketName}
          </div>
          <div className="flex items-center gap-1 truncate">
            <Database className="h-3 w-3 text-emerald-600 shrink-0" />
            <span className="truncate">{bqDatasetId}.aerial_datasets</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
