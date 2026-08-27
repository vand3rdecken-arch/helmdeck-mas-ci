// Reference cell surface (Phase 1 of the cell-registry decree, daemon/debt.py
// order 33): the Connectors cell conformed end-to-end first because it is the
// cleanest of the 5 - one screen, one daemon route family (/connectors), no
// cross-cell event hooks to guard yet. Strangler-wrap like board.tsx: the
// EXISTING (tabs)/connectors.tsx screen (real api.connectors()/runConnector()/
// rollbackConnector() data-fetching) is re-seated as a Surface, no logic moved.
//
// This fills the dead "surfaces.connectors" reference already present in
// surfaces/app/profiles/owner.json (AVAILABLE_PLUGINS had no entry for it before this).
// It mirrors cells.py's connectors Cell.surface = "surfaces.connectors"
// exactly, so the nav-gate filter in (tabs)/_layout.tsx can match this id
// against the /cells manifest generically.

import ConnectorsTab from "@/app/(tabs)/connectors";
import { KEYS, type Plugin, type Surface, TEAM_MEMBER_CAP } from "@/kernel";

const connectors: Surface = {
  id: "surfaces.connectors",
  title: "Connectors",
  path: "/(tabs)/connectors",
  component: ConnectorsTab as Surface["component"],
  // route + nav merged from nav.tabs' former "tab.connectors" entry (dual-nav
  // cutover, daemon/debt.py plugin-kernel-dual-nav): this Surface is now
  // BOTH what renders (component) and where it lives in nav (route/nav).
  // tabs.ts's matching entry is removed in the same change.
  // cap (card 4, ops/docs/backlog/rbac-gxp): routes_connectors.py is not yet
  // migrated onto permissions.py (client blocked server-side, no capability
  // backs it yet) - TEAM_MEMBER_CAP is the interim stand-in, see kernel/caps.ts.
  route: "connectors",
  nav: { group: "more", order: 7, icon: "sync-outline", labelKey: "nav.connectors",
        sectionKey: "nav.sectionSetup", cap: TEAM_MEMBER_CAP, desktopOnly: true },
};

export const connectorsSurface: Plugin = {
  id: "surfaces.connectors",
  tier: "plugin",
  inject: [KEYS.SURFACES.id],
  register(scope) {
    const surfaces = scope.require(KEYS.SURFACES);
    scope.use(surfaces.add(connectors.id, connectors.id, connectors));
    scope.emit("surface:changed", { surfaceId: connectors.id, present: true });
  },
};
