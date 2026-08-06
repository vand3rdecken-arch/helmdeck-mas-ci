import { QueryClient } from "@tanstack/react-query";

// One client for the app. The daemon pushes a version tick over SSE (web/LAN)
// or we poll (relay); either way we invalidate queries to refetch. Tuned for a
// data surface that changes often but not every second.
export const queryClient = new QueryClient({
  defaultOptions: {
    // refetchOnWindowFocus TRUE + focusManager wired to AppState (see _layout) so
    // returning from the background refetches immediately - over the relay the board
    // would otherwise wait out the 20s interval / a stale long-poll ("paired but takes
    // very long"). On RN "window focus" == the app becoming active.
    queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 2000 },
  },
});
