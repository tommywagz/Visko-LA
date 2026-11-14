import type { ReactorTokenResponse } from '../types/api';

interface CachedJwtEntry {
  jwt: string;
  expiresAtSeconds: number;
  sessionKey: string;
}

const JWT_REFRESH_SAFETY_WINDOW_MS = 60_000;
const jwtCache = new Map<string, CachedJwtEntry>();
const inflightRequests = new Map<string, Promise<string>>();

/**
 * Memoizes Reactor session-scoped JWTs in memory until `expires_at * 1000 - 60_000`
 * per SKILL.md §2 so internal SDK uploads/clip requests reuse the session-owning token
 * instead of minting unbound tokens that trigger 403 Forbidden.
 */
export function primeCachedReactorJwt(
  sessionKey: string,
  jwt: string,
  expiresAtSeconds: number
): void {
  if (!jwt) return;
  jwtCache.set(sessionKey || '__default__', {
    jwt,
    expiresAtSeconds,
    sessionKey: sessionKey || '__default__',
  });
}

export function getCachedReactorJwt(
  sessionKey: string,
  nowMs = Date.now()
): string | null {
  const key = sessionKey || '__default__';
  const entry = jwtCache.get(key);
  if (!entry) return null;
  const validUntilMs = entry.expiresAtSeconds * 1000 - JWT_REFRESH_SAFETY_WINDOW_MS;
  if (nowMs < validUntilMs) {
    return entry.jwt;
  }
  jwtCache.delete(key);
  return null;
}

export function clearCachedReactorJwt(sessionKey?: string): void {
  if (!sessionKey) {
    jwtCache.clear();
    inflightRequests.clear();
    return;
  }
  jwtCache.delete(sessionKey);
  inflightRequests.delete(sessionKey);
}

export function createMemoizedJwtResolver(
  sessionKey: string,
  mintFn: (sessionId?: string) => Promise<ReactorTokenResponse>,
  initialJwt?: string,
  initialExpiresAt?: number
): () => Promise<string> {
  const key = sessionKey || '__default__';
  if (initialJwt && typeof initialExpiresAt === 'number' && initialExpiresAt > 0) {
    primeCachedReactorJwt(key, initialJwt, initialExpiresAt);
  }

  return async () => {
    const cached = getCachedReactorJwt(key);
    if (cached) {
      return cached;
    }

    const existingPromise = inflightRequests.get(key);
    if (existingPromise) {
      return existingPromise;
    }

    const reqPromise = (async () => {
      try {
        const res = await mintFn(sessionKey === '__default__' ? undefined : sessionKey);
        primeCachedReactorJwt(key, res.jwt, res.expires_at);
        return res.jwt;
      } finally {
        inflightRequests.delete(key);
      }
    })();

    inflightRequests.set(key, reqPromise);
    return reqPromise;
  };
}
