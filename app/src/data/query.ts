import { QueryClient } from "@tanstack/react-query";

// One client for the app. The daemon pushes a version tick over SSE (web/LAN)
// or we poll (relay); either way we invalidate queries to refetch. Tuned for a
// data surface that changes often but not every second.
export const queryClient = new QueryClient({
  defaultOptions: {
    // Resume-refetch is handled explicitly in _layout (AppState "active" ->
    // invalidateQueries) rather than via focus, so this stays false: no
    // focusManager pause-on-background hazard, and desktop web doesn't refetch
    // on every tab focus.
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 2000 },
  },
});
