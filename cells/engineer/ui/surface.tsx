// First migrated surface. Strangler-wrap: the existing BoardTab screen is
// re-seated as a Surface contribution — NO logic rewritten, only registered.
// A registry-driven navigator (later card) reads KEYS.SURFACES instead of the
// hard-coded (tabs) list; until then this proves the composition works.

import BoardTab from "@/app/(tabs)/board";
import { KEYS, type Plugin, type Surface } from "@/kernel";

const board: Surface = {
  id: "surfaces.board",
  title: "Board",
  path: "/(tabs)",
  component: BoardTab as Surface["component"],
  // route + nav merged from nav.tabs' former "tab.board" entry (dual-nav
  // cutover, daemon/debt.py plugin-kernel-dual-nav): this Surface is now
  // BOTH what renders (component) and where it lives in nav (route/nav),
  // instead of two separate objects. tabs.ts's matching entry is removed
  // in the same change.
  route: "board",
  nav: { group: "primary", order: 1, icon: "grid-outline", labelKey: "nav.board" },
};

export const boardSurface: Plugin = {
  id: "surfaces.board",
  tier: "plugin",
  inject: [KEYS.SURFACES.id],
  register(scope) {
    const surfaces = scope.require(KEYS.SURFACES);
    scope.use(surfaces.add(board.id, board.id, board));
    scope.emit("surface:changed", { surfaceId: board.id, present: true });
  },
};
