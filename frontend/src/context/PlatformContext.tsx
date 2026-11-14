'use client';

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  createProject as apiCreateProject,
  fetchHealth,
  listProjects,
} from '../lib/api-client';
import type {
  AdapterMode,
  HealthResponse,
  ProjectRecord,
  SessionLifecycleStatus,
} from '../types/api';

export type ConnectionBadgeState =
  | 'LIVE WEBRTC'
  | 'PRIMING'
  | 'MOCK SIMULATOR'
  | 'DISCONNECTED';

interface StudioConnectionSummary {
  connected: boolean;
  mode: AdapterMode | null;
  status: SessionLifecycleStatus | null;
  chunkIndex: number;
  sessionId: string | null;
}

interface PlatformContextValue {
  health: HealthResponse | null;
  backendReachable: boolean;
  projects: ProjectRecord[];
  activeProjectId: string;
  setActiveProjectId: (projectId: string) => void;
  refreshProjects: () => Promise<ProjectRecord[]>;
  createNewProject: (name: string, description?: string) => Promise<ProjectRecord>;
  studioConnection: StudioConnectionSummary;
  setStudioConnection: React.Dispatch<React.SetStateAction<StudioConnectionSummary>>;
  connectionBadge: ConnectionBadgeState;
}

const DEFAULT_PROJECT: ProjectRecord = {
  project_id: 'default-uav-project',
  name: 'Visko UAV Perception Datasets',
  description: 'Default synthetic aerial perception & atmospheric telemetry catalog',
  created_at: new Date().toISOString(),
};

const PlatformContext = createContext<PlatformContextValue | null>(null);

export function PlatformProvider({ children }: { children: React.ReactNode }) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [backendReachable, setBackendReachable] = useState<boolean>(false);
  const [projects, setProjects] = useState<ProjectRecord[]>([DEFAULT_PROJECT]);
  const [activeProjectId, setActiveProjectId] = useState<string>('default-uav-project');
  const [studioConnection, setStudioConnection] = useState<StudioConnectionSummary>({
    connected: false,
    mode: null,
    status: null,
    chunkIndex: 0,
    sessionId: null,
  });

  const refreshHealth = useCallback(async () => {
    try {
      const h = await fetchHealth();
      setHealth(h);
      setBackendReachable(true);
    } catch {
      setBackendReachable(false);
    }
  }, []);

  const refreshProjects = useCallback(async (): Promise<ProjectRecord[]> => {
    try {
      const res = await listProjects();
      if (Array.isArray(res.projects) && res.projects.length > 0) {
        setProjects(res.projects);
        return res.projects;
      }
    } catch {
      // Retain default project if backend is temporarily unreachable
    }
    return [DEFAULT_PROJECT];
  }, []);

  const createNewProject = useCallback(
    async (name: string, description?: string): Promise<ProjectRecord> => {
      const created = await apiCreateProject({
        name: name.trim(),
        description: description?.trim() || undefined,
      });
      await refreshProjects();
      setActiveProjectId(created.project_id);
      return created;
    },
    [refreshProjects]
  );

  useEffect(() => {
    void refreshHealth();
    void refreshProjects();
    const timer = window.setInterval(() => {
      void refreshHealth();
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [refreshHealth, refreshProjects]);

  const connectionBadge: ConnectionBadgeState = useMemo(() => {
    if (studioConnection.sessionId && studioConnection.connected) {
      if (studioConnection.mode === 'mock') {
        return 'MOCK SIMULATOR';
      }
      if (
        studioConnection.status === 'priming' ||
        studioConnection.status === 'waiting' ||
        studioConnection.status === 'reanchoring' ||
        studioConnection.chunkIndex === 0
      ) {
        return 'PRIMING';
      }
      return 'LIVE WEBRTC';
    }
    if (health && backendReachable) {
      return health.orbis_mode === 'live' ? 'LIVE WEBRTC' : 'MOCK SIMULATOR';
    }
    return 'DISCONNECTED';
  }, [studioConnection, health, backendReachable]);

  const value = useMemo<PlatformContextValue>(
    () => ({
      health,
      backendReachable,
      projects,
      activeProjectId,
      setActiveProjectId,
      refreshProjects,
      createNewProject,
      studioConnection,
      setStudioConnection,
      connectionBadge,
    }),
    [
      health,
      backendReachable,
      projects,
      activeProjectId,
      refreshProjects,
      createNewProject,
      studioConnection,
      connectionBadge,
    ]
  );

  return (
    <PlatformContext.Provider value={value}>{children}</PlatformContext.Provider>
  );
}

export function usePlatform(): PlatformContextValue {
  const ctx = useContext(PlatformContext);
  if (!ctx) {
    throw new Error('usePlatform must be used inside PlatformProvider');
  }
  return ctx;
}
