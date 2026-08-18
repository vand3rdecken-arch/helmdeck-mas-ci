// Shared cell-enable read for components that gate themselves directly rather
// than through a nav tab (PM's widgets are embedded in index.tsx/settings.tsx,
// Copilot's entry point is a FAB, not a route - neither has a nav.tabs entry to
// hide, so the tab-level gating in (tabs)/_layout.tsx doesn't reach them). Same
// query key as _layout.tsx's local useDisabledCellSurfaces, so react-query
// dedupes the network call - this is not a second fetch.
import { useQuery } from "@tanstack/react-query";
import { api, type CellInfo } from "@/data/client";

/** True while loading/on error (fail-open, matches _layout.tsx's empty-Set
 * default) or when the daemon doesn't know the cell id - a cell flag turning a
 * screen OFF should never be able to accidentally turn everything off. */
export function useCellEnabled(cellId: string): boolean {
  const { data } = useQuery({ queryKey: ["cells"], queryFn: api.cells, staleTime: 30000, retry: false });
  const cells = (data?.cells ?? []) as CellInfo[];
  const c = cells.find((x) => x.id === cellId);
  return c ? c.enabled : true;
}
