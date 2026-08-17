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
  nav: { group: "primary", order: 0, icon: "albums" },
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
