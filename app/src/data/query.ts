import { QueryClient } from "@tanstack/react-query";

// One client for the app. The daemon pushes a version tick over SSE (web/LAN)
// or we poll (relay); either way we invalidate queries to refetch. Tuned for a
// data surface that changes often but not every second.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 2000 },
  },
});
