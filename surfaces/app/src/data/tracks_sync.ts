import type { QueryClient } from "@tanstack/react-query";
import type { Track } from "./types";

// Delta sync for the board, the Replicache pull shape (rocicorp/mono
// packages/replicache/src/puller.ts PullResponseOKV1, patch-operation.ts,
// sync/patch.ts): the client sends the opaque `cookie` of its last pull, the
// server answers {cookie, patch:[{op:"put",key,value} | {op:"del",key} |
// {op:"clear"}]}, and the patch is applied to the local copy in one step.
// `clear` is how the server forces a re-baseline (unknown/foreign cookie).
// The board lives in the persisted query cache (data/query.ts); the cookie
// lives there too (["tracksCookie"]), so both are hydrated together. A failed
// pull throws: React Query then keeps the last-known rows and only flips
// `error`, so the screen shows the cache with an offline hint, never nothing.
//
// No React/expo imports: the node self-test drives it with a real QueryClient.
export type PatchOp =
  | { op: "put"; key: string; value: Track }
  | { op: "del"; key: string }
  | { op: "clear" };
/** `older_done`: how many done cards the server holds back (past its window).
 *  Sent on a full baseline only; the client keeps the last value. */
export interface PullResponse { cookie: string; patch: PatchOp[]; older_done?: number }

export const TRACKS_KEY = ["tracks"] as const;
export const OLDER_KEY = ["tracksOlder"] as const;
const COOKIE_KEY = ["tracksCookie"] as const;

export async function syncTracks(
  qc: Pick<QueryClient, "getQueryData" | "setQueryData">,
  get: (path: string) => Promise<PullResponse | Track[]>,
): Promise<Track[]> {
  const prev = qc.getQueryData<Track[]>(TRACKS_KEY);
  const cookie = Array.isArray(prev) ? qc.getQueryData<string>(COOKIE_KEY) : undefined;
  let r = await get(`/tracks?cookie=${cookie ?? ""}`);
  // A plain array = the whole list (demo board, an older daemon): re-baseline.
  if (Array.isArray(r)) r = { cookie: "", patch: [{ op: "clear" }, ...r.map((t): PatchOp => ({ op: "put", key: t.id, value: t }))] };
  if (!Array.isArray(r?.patch)) throw new Error(String((r as { error?: unknown } | undefined)?.error ?? "bad /tracks reply"));
  const byId = new Map((cookie ? prev! : []).map((t) => [t.id, t] as const));
  for (const p of r.patch) {
    if (p.op === "clear") byId.clear();
    else if (p.op === "del") byId.delete(p.key);
    else byId.set(p.key, p.value);
  }
  qc.setQueryData(COOKIE_KEY, r.cookie);
  if (typeof r.older_done === "number") qc.setQueryData(OLDER_KEY, r.older_done);
  return [...byId.values()].sort((a, b) => (a.id < b.id ? 1 : -1));   // daemon order: id DESC
}
