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
  // route + nav merged from nav.tabs' former "tab.processes" entry (dual-nav
  // cutover, daemon/debt.py plugin-kernel-dual-nav): this Surface is now
  // BOTH what renders (component) and where it lives in nav (route/nav).
  // tabs.ts's matching entry is removed in the same change.
  route: "processes",
  nav: { group: "more", order: 3, icon: "git-network-outline", labelKey: "nav.processes",
        sectionKey: "nav.sectionWorkflow", desktopOnly: true },
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
