import AsyncStorage from "@react-native-async-storage/async-storage";
import { QueryClient, dehydrate, hydrate } from "@tanstack/react-query";

// How long a value stays trustworthy without a refetch - the horizon shared by
// BOTH halves of the cache (in-memory gcTime below, persisted blob further
// down). Declared here because the client is constructed at module load and a
// const declared later would be in its temporal dead zone.
const CACHE_MAX_AGE = 24 * 60 * 60 * 1000;   // discard a cache older than a day

// One client for the app. The daemon pushes a version tick over SSE (web/LAN)
// or we poll (relay); either way we invalidate queries to refetch. Tuned for a
// data surface that changes often but not every second.
export const queryClient = new QueryClient({
  defaultOptions: {
    // Resume-refetch is handled explicitly in _layout (AppState "active" ->
    // invalidateQueries) rather than via focus, so this stays false: no
    // focusManager pause-on-background hazard, and desktop web doesn't refetch
    // on every tab focus.
    //
    // gcTime outlives NAVIGATION, deliberately. React Query's 5-minute default
    // is counted from the moment a query loses its LAST OBSERVER, and /chat is a
    // Stack route (_layout.tsx) - closing it unmounts ChatBody, so five minutes
    // later "chatHistory" was evicted and the next open had nothing to paint:
    // empty transcript plus a blocking fetch over the relay, every time (owner
    // report 2026-08-31). It also silently defeated the persisted cache below,
    // which dehydrates whatever is in the cache RIGHT NOW - the eviction was
    // written through to AsyncStorage, so the cold start lost the chat too.
    // Reusing CACHE_MAX_AGE gives both halves ONE horizon: what memory keeps is
    // what disk keeps, and last-known data is always there to show while the
    // refetch runs.
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 2000, gcTime: CACHE_MAX_AGE },
  },
});

// --- Cross-launch cache -----------------------------------------------------
// Within a session the in-memory cache already means navigating never full-
// reloads (served from cache, refetched in the background). The gap was the COLD
// START: process killed -> cache empty -> the whole board loads from scratch over
// the slow relay. So we persist the query cache to AsyncStorage and hydrate it
// before the tree mounts: the last-known board paints instantly and every query
// is then silently revalidated (stale-while-revalidate). Net effect on the wire
// is delta-like - you see data immediately and only changes visibly move.
// AsyncStorage is app-private and holds the same board data already in memory;
// pairing secrets live in the config store, never in the query cache.
const CACHE_KEY = "helmdeck.qcache.v1";

export async function restoreCache(): Promise<void> {
  try {
    const raw = await AsyncStorage.getItem(CACHE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!parsed?.state || typeof parsed.at !== "number") return;
    if (Date.now() - parsed.at > CACHE_MAX_AGE) return;   // too old to trust - start clean
    hydrate(queryClient, parsed.state);
  } catch {
    /* corrupt/absent cache is never fatal - just start empty */
  }
}

// Keep the persisted blob inside Android's AsyncStorage budget (~6MB total,
// and one oversized setItem fails SILENTLY - which would kill the cross-launch
// cache for EVERYTHING, board included). Transcripts are the only unbounded
// entries, so bound them: keep the newest steps per card, and if the whole
// blob is still too big, drop transcript entries largest-first. The board and
// small queries always survive; a clipped transcript just re-fetches its older
// steps from the daemon on open (the feed protocol sends the full list then
// deltas), so nothing is lost - only re-downloaded.
const PERSIST_MAX_BYTES = 3_500_000;   // headroom under the ~6MB Android cap
const PERSIST_STEPS_PER_CARD = 200;    // newest steps kept per transcript

function boundedState() {
  const state = dehydrate(queryClient);   // successful queries only, by default
  interface Q { queryKey: readonly unknown[]; state: { data?: unknown } }
  const qs = state.queries as unknown as Q[];
  for (const q of qs) {
    const d = q.state?.data;
    if (q.queryKey?.[0] === "transcript" && Array.isArray(d) && d.length > PERSIST_STEPS_PER_CARD) {
      q.state.data = d.slice(-PERSIST_STEPS_PER_CARD);
    }
  }
  let out = JSON.stringify({ at: Date.now(), state });
  while (out.length > PERSIST_MAX_BYTES) {
    const idx = qs.reduce((best, q, i) =>
      q.queryKey?.[0] === "transcript" &&
      (best < 0 || JSON.stringify(q.state?.data ?? null).length >
                   JSON.stringify(qs[best].state?.data ?? null).length) ? i : best, -1);
    if (idx < 0) break;                  // nothing droppable left - persist as-is
    qs.splice(idx, 1);
    out = JSON.stringify({ at: Date.now(), state });
  }
  return out;
}

// Persist on cache settle, debounced so a burst of query updates writes once.
let _timer: ReturnType<typeof setTimeout> | null = null;
export function startCachePersist(): () => void {
  const flush = () => {
    _timer = null;
    try {
      AsyncStorage.setItem(CACHE_KEY, boundedState()).catch(() => {});
    } catch {
      /* persistence must never break the app */
    }
  };
  const unsub = queryClient.getQueryCache().subscribe(() => {
    if (_timer) return;
    _timer = setTimeout(flush, 1500);
  });
  return () => {
    if (_timer) { clearTimeout(_timer); _timer = null; }
    unsub();
  };
}

// Drop the persisted board - call on unpair/logout so the next user never sees a
// prior session's cards flash before their own load.
export async function clearCache(): Promise<void> {
  try { await AsyncStorage.removeItem(CACHE_KEY); } catch { /* nothing to clear */ }
}
