import AsyncStorage from "@react-native-async-storage/async-storage";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import { persistQueryClient, removeOldestQuery } from "@tanstack/query-persist-client-core";
import { QueryClient } from "@tanstack/react-query";

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
// The stock TanStack pattern, as Bluesky (social-app src/lib/react-query.tsx)
// runs it in production: persistQueryClient + createAsyncStoragePersister.
// Read from TanStack/query packages/query-persist-client-core/src/persist.ts
// (restore, drop when older than maxAge or when `buster` differs, hydrate;
// then subscribe and save on every cache event) and
// packages/query-async-storage-persister/src (JSON serialize, saves throttled
// to one per `throttleTime`, `retry` on a failed setItem - removeOldestQuery
// is the shipped retryer for a full store). The cold start paints the last-
// known board instantly and every query then revalidates (stale-while-
// revalidate). AsyncStorage is app-private; pairing secrets live in the config
// store, never in the query cache.
//
// CACHE_BUSTER is the schema version (Bluesky uses the app version; here every
// OTA would wipe the cache, so it is bumped by hand when a cached shape changes).
// v3 (2026-10-13): drop every cache written while the demo fixture could answer
// an unmodelled GET with {} (client.ts req()) - the owner's desktop carried a
// {} for ["repoTemplates"] from 2026-10-12 17:18 and crashed at every launch.
const CACHE_BUSTER = "v3";
const persister = createAsyncStoragePersister({
  storage: AsyncStorage,
  key: "helmdeck.qcache",
  throttleTime: 1500,
  retry: removeOldestQuery,   // one oversized setItem must not kill the whole cache
});

// The ONE deliberate difference from Bluesky (status === "success" only): an
// errored refetch flips a query to 'error' while React Query KEEPS its data,
// and 'success' only dropped that data from the next write - so a process kill
// mid-outage woke up to an empty cache (owner report 2026-09-03). Persist any
// query that HAS data.
export function startCachePersist(): [() => void, Promise<void>] {
  return persistQueryClient({
    queryClient,
    persister,
    maxAge: CACHE_MAX_AGE,
    buster: CACHE_BUSTER,
    dehydrateOptions: { shouldDehydrateQuery: (q) => q.state.data !== undefined },
  });
}

// Drop the persisted board - call on unpair/logout so the next user never sees a
// prior session's cards flash before their own load.
export async function clearCache(): Promise<void> {
  try { await persister.removeClient(); } catch { /* nothing to clear */ }
}
