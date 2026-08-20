import { useQuery } from "@tanstack/react-query";

import { api } from "./client";

// The one models query, shared by every composer. A picker showing only
// "Auto" is ALWAYS wrong (the daemon guarantees a non-empty list via the
// manifest fallback), so this never settles for nothing: a fetch that failed
// - most commonly because it raced a daemon restart or a relay hiccup - keeps
// re-polling every 15s until the list arrives, instead of leaving the screen
// model-less until remount (the 2026-08-20 "cannot select model" report).
export function useModels(enabled = true) {
  return useQuery({
    queryKey: ["models"],
    queryFn: api.models,
    enabled,
    staleTime: 300000,
    retry: 3,
    refetchInterval: (q) => ((q.state.data?.length ?? 0) > 0 ? false : 15000),
  });
}
