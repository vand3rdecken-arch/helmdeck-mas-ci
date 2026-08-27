"use strict";
// First migrated surface. Strangler-wrap: the existing BoardTab screen is
// re-seated as a Surface contribution — NO logic rewritten, only registered.
// A registry-driven navigator (later card) reads KEYS.SURFACES instead of the
// hard-coded (tabs) list; until then this proves the composition works.
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.boardSurface = void 0;
const board_1 = __importDefault(require("@/app/(tabs)/board"));
const kernel_1 = require("@/kernel");
const board = {
    id: "surfaces.board",
    title: "Board",
    path: "/(tabs)",
    component: board_1.default,
    // route + nav merged from nav.tabs' former "tab.board" entry (dual-nav
    // cutover, daemon/debt.py plugin-kernel-dual-nav): this Surface is now
    // BOTH what renders (component) and where it lives in nav (route/nav),
    // instead of two separate objects. tabs.ts's matching entry is removed
    // in the same change.
    route: "board",
    nav: { group: "primary", order: 1, icon: "grid-outline", labelKey: "nav.board" },
};
exports.boardSurface = {
    id: "surfaces.board",
    tier: "plugin",
    inject: [kernel_1.KEYS.SURFACES.id],
    register(scope) {
        const surfaces = scope.require(kernel_1.KEYS.SURFACES);
        scope.use(surfaces.add(board.id, board.id, board));
        scope.emit("surface:changed", { surfaceId: board.id, present: true });
    },
};
