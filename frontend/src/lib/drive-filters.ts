import type { DatasetRecord, FolderRecord } from '../types/api';

export interface FolderTreeNode extends FolderRecord {
  children: FolderTreeNode[];
  depth: number;
}

export type TurbulenceFilterOption =
  | 'all'
  | 'light'
  | 'moderate'
  | 'severe'
  | 'severe_plus'
  | 'severe+'
  | 'extreme';

export interface DatasetFilterOptions {
  folderId?: string | null;
  folder_id?: string | null;
  search?: string | null;
  query?: string | null;
  durationSeconds?: number | string | null;
  duration_seconds?: number | string | null;
  ecosystemType?: string | null;
  ecosystem_type?: string | null;
  turbulenceFilter?: TurbulenceFilterOption | string | null;
  turbulenceSeverity?: TurbulenceFilterOption | string | null;
  minTurbulenceEdr?: number | null;
  min_turbulence_edr?: number | null;
  maxTurbulenceEdr?: number | null;
  max_turbulence_edr?: number | null;
}

export type DatasetSortField =
  | 'created_at'
  | 'title'
  | 'duration_seconds'
  | 'avg_wind_speed_mps'
  | 'avg_air_pressure_hpa'
  | 'max_turbulence_edr'
  | 'file_size_bytes';

export type SortDirection = 'asc' | 'desc';

export function normalizeFolderPath(path: string | null | undefined): string {
  if (!path) return '/';
  const trimmed = path.trim();
  if (!trimmed || trimmed === '/') return '/';

  const segments = trimmed
    .replace(/\\/g, '/')
    .split('/')
    .map((seg) => seg.trim())
    .filter((seg) => seg.length > 0 && seg !== '.');

  if (segments.length === 0) return '/';
  return `/${segments.join('/')}`;
}

export function buildFolderTree(folders: FolderRecord[]): FolderTreeNode[] {
  if (!Array.isArray(folders) || folders.length === 0) {
    return [];
  }

  const nodeMap = new Map<string, FolderTreeNode>();
  for (const folder of folders) {
    nodeMap.set(folder.folder_id, {
      ...folder,
      folder_path: normalizeFolderPath(folder.folder_path),
      children: [],
      depth: 0,
    });
  }

  const rootNode = nodeMap.get('root');
  const topLevelNodes: FolderTreeNode[] = [];

  for (const folder of folders) {
    const node = nodeMap.get(folder.folder_id)!;
    if (folder.folder_id === 'root') {
      topLevelNodes.push(node);
      continue;
    }

    const parentId = folder.parent_folder_id;
    if (parentId && nodeMap.has(parentId) && parentId !== folder.folder_id) {
      nodeMap.get(parentId)!.children.push(node);
    } else if (rootNode) {
      // Attach orphan/null-parent non-root folders under 'root' when a canonical root folder exists
      rootNode.children.push(node);
    } else {
      topLevelNodes.push(node);
    }
  }

  const assignDepthAndSort = (nodes: FolderTreeNode[], depth: number) => {
    nodes.sort((a, b) => {
      if (a.folder_id === 'root') return -1;
      if (b.folder_id === 'root') return 1;
      return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
    });
    for (const n of nodes) {
      n.depth = depth;
      if (n.children.length > 0) {
        assignDepthAndSort(n.children, depth + 1);
      }
    }
  };

  assignDepthAndSort(topLevelNodes, 0);
  return topLevelNodes;
}

export function getChildFolders(
  folders: FolderRecord[],
  parentFolderId: string | null | undefined
): FolderRecord[] {
  if (!Array.isArray(folders) || folders.length === 0) {
    return [];
  }

  const filtered = folders.filter((folder) => {
    if (parentFolderId === 'all') {
      return false;
    }
    if (parentFolderId === 'root') {
      if (folder.folder_id === 'root') return false;
      return (
        folder.parent_folder_id === 'root' ||
        folder.parent_folder_id === null ||
        folder.parent_folder_id === undefined ||
        folder.parent_folder_id === ''
      );
    }
    if (parentFolderId === null || parentFolderId === undefined || parentFolderId === '') {
      return (
        folder.parent_folder_id === null ||
        folder.parent_folder_id === undefined ||
        folder.parent_folder_id === ''
      );
    }
    return folder.parent_folder_id === parentFolderId;
  });

  return [...filtered].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
  );
}

export function buildBreadcrumbs(
  folders: FolderRecord[],
  currentFolderId: string | null | undefined
): FolderRecord[] {
  if (!Array.isArray(folders) || folders.length === 0) {
    return [];
  }

  const byId = new Map<string, FolderRecord>();
  for (const folder of folders) {
    byId.set(folder.folder_id, folder);
  }

  const rootFolder = byId.get('root');

  if (!currentFolderId || currentFolderId === 'root') {
    return rootFolder ? [rootFolder] : [];
  }

  if (currentFolderId === 'all') {
    const virtualAll: FolderRecord = {
      folder_id: 'all',
      project_id: rootFolder?.project_id ?? folders[0].project_id,
      parent_folder_id: null,
      name: 'All Datasets',
      folder_path: '/',
      ecosystem_default: null,
      created_at: rootFolder?.created_at ?? folders[0].created_at,
    };
    return [virtualAll];
  }

  const chain: FolderRecord[] = [];
  const visited = new Set<string>();
  let cursor: FolderRecord | undefined = byId.get(currentFolderId);

  while (cursor && !visited.has(cursor.folder_id)) {
    visited.add(cursor.folder_id);
    chain.unshift(cursor);
    if (cursor.folder_id === 'root') {
      break;
    }
    if (cursor.parent_folder_id && byId.has(cursor.parent_folder_id)) {
      cursor = byId.get(cursor.parent_folder_id);
    } else {
      break;
    }
  }

  if (rootFolder && (chain.length === 0 || chain[0].folder_id !== 'root')) {
    chain.unshift(rootFolder);
  }

  return chain;
}

function parseDurationFilter(raw: number | string | null | undefined): number | null {
  if (raw === null || raw === undefined || raw === '' || raw === 'all' || raw === 0) {
    return null;
  }
  if (typeof raw === 'number') {
    return Number.isFinite(raw) && raw > 0 ? raw : null;
  }
  const cleaned = raw.trim().toLowerCase().replace(/s$/, '');
  const parsed = Number.parseInt(cleaned, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function filterDatasets(
  datasets: DatasetRecord[],
  filters: DatasetFilterOptions = {}
): DatasetRecord[] {
  if (!Array.isArray(datasets) || datasets.length === 0) {
    return [];
  }

  const targetFolderId = filters.folderId ?? filters.folder_id ?? null;
  const searchRaw = (filters.search ?? filters.query ?? '').trim().toLowerCase();
  const targetDuration = parseDurationFilter(
    filters.durationSeconds ?? filters.duration_seconds
  );
  const targetEcosystem = (filters.ecosystemType ?? filters.ecosystem_type ?? '')
    .trim()
    .toLowerCase();
  const turbFilter = (
    filters.turbulenceFilter ??
    filters.turbulenceSeverity ??
    'all'
  )
    .trim()
    .toLowerCase();
  const minEdr = filters.minTurbulenceEdr ?? filters.min_turbulence_edr ?? null;
  const maxEdr = filters.maxTurbulenceEdr ?? filters.max_turbulence_edr ?? null;

  return datasets.filter((dataset) => {
    // 1. Folder isolation ('all' or empty returns all folders; 'root' or specific ID filters strictly)
    if (
      targetFolderId &&
      targetFolderId !== 'all' &&
      dataset.folder_id !== targetFolderId
    ) {
      return false;
    }

    // 2. Duration filter (5, 10, 15)
    if (targetDuration !== null && dataset.duration_seconds !== targetDuration) {
      return false;
    }

    // 3. Ecosystem filter
    if (
      targetEcosystem &&
      targetEcosystem !== 'all' &&
      (dataset.ecosystem_type ?? '').toLowerCase() !== targetEcosystem
    ) {
      return false;
    }

    // 4. Turbulence severity filter
    const edr = dataset.max_turbulence_edr ?? dataset.avg_turbulence_edr ?? 0;
    if (turbFilter && turbFilter !== 'all') {
      if (turbFilter === 'light' && !(edr < 0.2)) return false;
      if (turbFilter === 'moderate' && !(edr >= 0.2 && edr < 0.45)) return false;
      if (turbFilter === 'severe' && !(edr >= 0.45 && edr < 0.7)) return false;
      if (
        (turbFilter === 'severe_plus' || turbFilter === 'severe+') &&
        !(edr >= 0.45)
      ) {
        return false;
      }
      if (turbFilter === 'extreme' && !(edr >= 0.7)) return false;
    }

    if (typeof minEdr === 'number' && Number.isFinite(minEdr) && edr < minEdr) {
      return false;
    }
    if (typeof maxEdr === 'number' && Number.isFinite(maxEdr) && edr > maxEdr) {
      return false;
    }

    // 5. Keyword search across video_id, title, initial_prompt, folder_path, ecosystem_type
    if (searchRaw.length > 0) {
      const haystack = [
        dataset.video_id,
        dataset.title,
        dataset.initial_prompt,
        dataset.folder_path,
        dataset.ecosystem_type,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();

      if (!haystack.includes(searchRaw)) {
        return false;
      }
    }

    return true;
  });
}

export function sortDatasets(
  datasets: DatasetRecord[],
  sortBy: DatasetSortField = 'created_at',
  sortDir: SortDirection = 'desc'
): DatasetRecord[] {
  if (!Array.isArray(datasets) || datasets.length <= 1) {
    return Array.isArray(datasets) ? [...datasets] : [];
  }

  const multiplier = sortDir === 'asc' ? 1 : -1;

  return [...datasets].sort((a, b) => {
    let cmp = 0;
    switch (sortBy) {
      case 'title':
        cmp = (a.title ?? '').localeCompare(b.title ?? '', undefined, {
          sensitivity: 'base',
        });
        break;
      case 'duration_seconds':
        cmp = (a.duration_seconds ?? 0) - (b.duration_seconds ?? 0);
        break;
      case 'avg_wind_speed_mps':
        cmp = (a.avg_wind_speed_mps ?? 0) - (b.avg_wind_speed_mps ?? 0);
        break;
      case 'avg_air_pressure_hpa':
        cmp = (a.avg_air_pressure_hpa ?? 0) - (b.avg_air_pressure_hpa ?? 0);
        break;
      case 'max_turbulence_edr':
        cmp = (a.max_turbulence_edr ?? 0) - (b.max_turbulence_edr ?? 0);
        break;
      case 'file_size_bytes':
        cmp = (a.file_size_bytes ?? 0) - (b.file_size_bytes ?? 0);
        break;
      case 'created_at':
      default: {
        const tA = Date.parse(a.created_at ?? '');
        const tB = Date.parse(b.created_at ?? '');
        if (Number.isFinite(tA) && Number.isFinite(tB)) {
          cmp = tA - tB;
        } else {
          cmp = (a.created_at ?? '').localeCompare(b.created_at ?? '');
        }
        break;
      }
    }

    if (cmp !== 0) return cmp * multiplier;
    return (a.video_id ?? '').localeCompare(b.video_id ?? '');
  });
}
