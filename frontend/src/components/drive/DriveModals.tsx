'use client';

import React, { useEffect, useState } from 'react';
import { FolderPlus, Loader2, Upload, X } from 'lucide-react';
import { ECOSYSTEM_LABELS } from '../../lib/telemetry';
import type { EcosystemType, FolderRecord } from '../../types/api';

const ECOSYSTEM_OPTIONS: EcosystemType[] = [
  'alpine',
  'coastal',
  'urban_canyon',
  'temperate_forest',
  'arid_desert',
  'wetlands',
  'custom',
];

export interface NewFolderModalProps {
  open: boolean;
  folders: FolderRecord[];
  defaultParentFolderId: string;
  onClose: () => void;
  onCreateFolder: (payload: {
    name: string;
    parent_folder_id: string | null;
    ecosystem_default: string | null;
  }) => Promise<void>;
}

export function NewFolderModal({
  open,
  folders,
  defaultParentFolderId,
  onClose,
  onCreateFolder,
}: NewFolderModalProps) {
  const [name, setName] = useState('');
  const [parentId, setParentId] = useState(defaultParentFolderId || 'root');
  const [ecoDefault, setEcoDefault] = useState<string>('');
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName('');
      setParentId(
        defaultParentFolderId && defaultParentFolderId !== 'all'
          ? defaultParentFolderId
          : 'root'
      );
      setEcoDefault('');
      setErrorMsg(null);
    }
  }, [open, defaultParentFolderId]);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setErrorMsg(null);
    try {
      await onCreateFolder({
        name: name.trim(),
        parent_folder_id: parentId || 'root',
        ecosystem_default: ecoDefault || null,
      });
      onClose();
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Failed to create folder'
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Create New Folder"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4"
    >
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 text-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 pb-3">
          <div className="flex items-center gap-2">
            <FolderPlus className="h-5 w-5 text-[#1A73E8]" />
            <h3 className="text-base font-bold text-slate-900">New Folder</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close New Folder Modal"
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label
              htmlFor="new-folder-name"
              className="block text-xs font-semibold text-slate-700 mb-1"
            >
              Folder Name
            </label>
            <input
              id="new-folder-name"
              data-testid="new-folder-name-input"
              type="text"
              autoFocus
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., UAV-Crosswind-Eval"
              className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-[#1A73E8] focus:outline-none"
            />
          </div>

          <div>
            <label
              htmlFor="new-folder-parent"
              className="block text-xs font-semibold text-slate-700 mb-1"
            >
              Parent Folder
            </label>
            <select
              id="new-folder-parent"
              value={parentId}
              onChange={(e) => setParentId(e.target.value)}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#1A73E8] focus:outline-none"
            >
              {folders.map((f) => (
                <option key={f.folder_id} value={f.folder_id}>
                  {f.folder_path === '/'
                    ? '/ (My Aerial Datasets Root)'
                    : `${f.folder_path} — ${f.name}`}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              htmlFor="new-folder-eco"
              className="block text-xs font-semibold text-slate-700 mb-1"
            >
              Default Ecosystem Tag (Optional)
            </label>
            <select
              id="new-folder-eco"
              value={ecoDefault}
              onChange={(e) => setEcoDefault(e.target.value)}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#1A73E8] focus:outline-none"
            >
              <option value="">None (Inherit Session Ecosystem)</option>
              {ECOSYSTEM_OPTIONS.map((eco) => (
                <option key={eco} value={eco}>
                  {ECOSYSTEM_LABELS[eco]} ({eco})
                </option>
              ))}
            </select>
          </div>

          {errorMsg && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
              {errorMsg}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              data-testid="new-folder-submit-button"
              disabled={submitting || !name.trim()}
              className="flex items-center gap-1.5 rounded-xl bg-[#1A73E8] px-4 py-2 text-xs font-semibold text-white hover:bg-[#4285F4] disabled:opacity-50"
            >
              {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              <span>Create Folder</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export interface UploadDatasetModalProps {
  open: boolean;
  folders: FolderRecord[];
  defaultFolderId: string;
  onClose: () => void;
  onUploadDataset: (payload: {
    file: File;
    folder_id: string;
    title: string;
    ecosystem_type: EcosystemType;
    duration_seconds: 5 | 10 | 15;
    initial_prompt?: string;
  }) => Promise<void>;
}

export function UploadDatasetModal({
  open,
  folders,
  defaultFolderId,
  onClose,
  onUploadDataset,
}: UploadDatasetModalProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [folderId, setFolderId] = useState<string>(defaultFolderId || 'root');
  const [title, setTitle] = useState<string>('');
  const [ecosystemType, setEcosystemType] = useState<EcosystemType>('alpine');
  const [durationSeconds, setDurationSeconds] = useState<5 | 10 | 15>(5);
  const [promptDesc, setPromptDesc] = useState<string>('');
  const [uploading, setUploading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      const targetId =
        defaultFolderId && defaultFolderId !== 'all' ? defaultFolderId : 'root';
      setFolderId(targetId);
      const matchedFolder = folders.find((f) => f.folder_id === targetId);
      if (
        matchedFolder?.ecosystem_default &&
        ECOSYSTEM_OPTIONS.includes(matchedFolder.ecosystem_default as EcosystemType)
      ) {
        setEcosystemType(matchedFolder.ecosystem_default as EcosystemType);
      } else {
        setEcosystemType('alpine');
      }
      setSelectedFile(null);
      setTitle('');
      setDurationSeconds(5);
      setPromptDesc('');
      setErrorMsg(null);
    }
  }, [open, defaultFolderId, folders]);

  if (!open) return null;

  const handleFilePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    setSelectedFile(file);
    if (file && !title.trim()) {
      const stem = file.name.replace(/\.[^.]+$/, '');
      setTitle(stem);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      setErrorMsg('Please select an .mp4 dataset clip to upload.');
      return;
    }
    setUploading(true);
    setErrorMsg(null);
    try {
      const cleanTitle =
        title.trim() || selectedFile.name.replace(/\.[^.]+$/, '') || 'Uploaded UAV Clip';
      await onUploadDataset({
        file: selectedFile,
        folder_id: folderId || 'root',
        title: cleanTitle,
        ecosystem_type: ecosystemType,
        duration_seconds: durationSeconds,
        initial_prompt:
          promptDesc.trim() ||
          `Imported UAV aerial perception clip (${cleanTitle}) in ${ecosystemType} conditions.`,
      });
      onClose();
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Dataset MP4 upload failed'
      );
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Upload Dataset Clip to Folder"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4"
    >
      <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 text-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 pb-3">
          <div className="flex items-center gap-2">
            <Upload className="h-5 w-5 text-emerald-600" />
            <h3 className="text-base font-bold text-slate-900">
              Upload Dataset Clip (.mp4)
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close Upload Dataset Modal"
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-3.5">
          <div>
            <label
              htmlFor="upload-dataset-file"
              className="block text-xs font-semibold text-slate-700 mb-1"
            >
              MP4 Video File
            </label>
            <input
              id="upload-dataset-file"
              data-testid="upload-dataset-file-input"
              type="file"
              required
              accept=".mp4,video/mp4"
              onChange={handleFilePick}
              className="w-full rounded-xl border border-slate-300 bg-[#F8FAFC] px-3 py-2 text-xs text-slate-800 file:mr-3 file:rounded-lg file:border-0 file:bg-[#1A73E8] file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-white hover:file:bg-[#4285F4]"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="upload-dataset-folder"
                className="block text-xs font-semibold text-slate-700 mb-1"
              >
                Target Folder
              </label>
              <select
                id="upload-dataset-folder"
                value={folderId}
                onChange={(e) => setFolderId(e.target.value)}
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#1A73E8] focus:outline-none"
              >
                {folders.map((f) => (
                  <option key={f.folder_id} value={f.folder_id}>
                    {f.folder_path === '/'
                      ? '/ (My Aerial Datasets)'
                      : `${f.folder_path} — ${f.name}`}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label
                htmlFor="upload-dataset-duration"
                className="block text-xs font-semibold text-slate-700 mb-1"
              >
                Clip Interval Duration
              </label>
              <select
                id="upload-dataset-duration"
                value={durationSeconds}
                onChange={(e) =>
                  setDurationSeconds(Number(e.target.value) as 5 | 10 | 15)
                }
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#1A73E8] focus:outline-none"
              >
                <option value={5}>5 seconds (0:05)</option>
                <option value={10}>10 seconds (0:10)</option>
                <option value={15}>15 seconds (0:15)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="upload-dataset-title"
                className="block text-xs font-semibold text-slate-700 mb-1"
              >
                Dataset Title
              </label>
              <input
                id="upload-dataset-title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Auto-filled from filename"
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 placeholder-slate-400 focus:border-[#1A73E8] focus:outline-none"
              />
            </div>

            <div>
              <label
                htmlFor="upload-dataset-eco"
                className="block text-xs font-semibold text-slate-700 mb-1"
              >
                Ecosystem Type
              </label>
              <select
                id="upload-dataset-eco"
                value={ecosystemType}
                onChange={(e) => setEcosystemType(e.target.value as EcosystemType)}
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#1A73E8] focus:outline-none"
              >
                {ECOSYSTEM_OPTIONS.map((eco) => (
                  <option key={eco} value={eco}>
                    {ECOSYSTEM_LABELS[eco]}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label
              htmlFor="upload-dataset-prompt"
              className="block text-xs font-semibold text-slate-700 mb-1"
            >
              Scene / Weather Description (Optional)
            </label>
            <input
              id="upload-dataset-prompt"
              type="text"
              value={promptDesc}
              onChange={(e) => setPromptDesc(e.target.value)}
              placeholder="Optional flight corridor & atmospheric notes..."
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 placeholder-slate-400 focus:border-[#1A73E8] focus:outline-none"
            />
          </div>

          {errorMsg && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
              {errorMsg}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              data-testid="upload-dataset-submit-button"
              disabled={uploading || !selectedFile}
              className="flex items-center gap-1.5 rounded-xl bg-[#1A73E8] px-4 py-2 text-xs font-semibold text-white hover:bg-[#4285F4] disabled:opacity-50"
            >
              {uploading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              <span>Upload Clip</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
