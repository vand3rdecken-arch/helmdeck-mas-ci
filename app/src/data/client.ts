import { useConfig } from "./config";
import type { Track, Metrics, Me } from "./types";

export class AuthRequired extends Error {}

// The daemon speaks Bearer-token auth uniformly (daemon/auth.py); we no longer
// rely on the web's same-origin cookie. Reads baseUrl+token live from the store
// so re-pairing / re-pointing takes effect without reconstructing a client.
function headers(): Record<string, string> {
  const { token } = useConfig.getState();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

async function req<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const { baseUrl } = useConfig.getState();
  const r = await fetch(baseUrl + path, {
    method,
    headers: headers(),
    body: method === "GET" ? undefined : JSON.stringify(body ?? {}),
    signal,
  });
  if (r.status === 401) throw new AuthRequired();
  return (await r.json()) as T;
}

export const api = {
  get: <T,>(path: string) => req<T>("GET", path),
  post: <T,>(path: string, body?: unknown, signal?: AbortSignal) => req<T>("POST", path, body, signal),

  tracks: () => req<Track[]>("GET", "/tracks"),
  metrics: () => req<Metrics>("GET", "/dashboard/data"),
  me: () => req<Me>("GET", "/me"),
  moveLane: (id: string, lane: string) => req("POST", `/tracks/${id}/lane`, { lane }),
};
