// Phase 2 of the cell-registry decree (daemon/debt.py order 33): the Process
// cell's Surface. Same pattern as connectors.tsx: the existing (tabs)/
// processes.tsx screen (real api.processes() data-fetching + POST /processes
// mutations) is re-seated as a Surface, no logic moved.

import ProcessesTab from "@/app/(tabs)/processes";
import { KEYS, type Plugin, type Surface } from "@/kernel";

const processes: Surface = {
  id: "surfaces.processes",
  title: "Processes",
  path: "/(tabs)/processes",
  component: ProcessesTab as Surface["component"],
  // No `route` here on purpose (mirrors connectors.tsx): the tab slot for
  // processes is already owned by nav.tabs' "processes" entry (same
  // file-based router route). This Surface exists so the cell registry has a
  // real app-side counterpart to gate/inspect - it is not a second tab.
  nav: { group: "primary", order: 14, icon: "git-network-outline" },
};

export const processesSurface: Plugin = {
  id: "surfaces.processes",
  tier: "plugin",
  inject: [KEYS.SURFACES.id],
  register(scope) {
    const surfaces = scope.require(KEYS.SURFACES);
    scope.use(surfaces.add(processes.id, processes.id, processes));
    scope.emit("surface:changed", { surfaceId: processes.id, present: true });
  },
};
