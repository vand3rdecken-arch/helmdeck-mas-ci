"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.pmSurface = void 0;
const jsx_runtime_1 = require("react/jsx-runtime");
// Phase 2 of the cell-registry decree (daemon/debt.py order 33): the PM cell's
// Surface. Same strangler-wrap pattern as connectors.tsx/board.tsx - no data-
// fetching logic rewritten, only composed and registered. Unlike Connectors
// (one existing screen), PM's working UI is split across two existing pieces:
// the status readout (ui/pm_panel.tsx's PMStatusPanel, also embedded in the
// dashboard tile) and the loop map (app/loopmap.tsx's LoopMapScreen, the
// pipeline/build-loop/laws view). This surface composes both into one PM
// dashboard component, reusing each unmodified - the daemon PM cell
// (cells.py, surface="surfaces.pm") owns /pm/* routes that both pull
// from (api.pmPlan / api.loopMap), so nothing here duplicates that fetching.
const react_native_1 = require("react-native");
const react_native_safe_area_context_1 = require("react-native-safe-area-context");
const loopmap_1 = __importDefault(require("@/app/loopmap"));
const pm_panel_1 = require("@/ui/pm_panel");
const theme_1 = require("@/theme");
const kernel_1 = require("@/kernel");
/** PM dashboard: the status readout on top, the full loop map below. Both
 *  pieces already scroll/fetch on their own; PMStatusPanel is short and
 *  renders nothing when the loop is quiet, so stacking it above the loop map
 *  in one screen reads as "status, then the machine that produces it". */
function PmDashboard() {
    const t = (0, theme_1.useTheme)();
    const insets = (0, react_native_safe_area_context_1.useSafeAreaInsets)();
    return ((0, jsx_runtime_1.jsxs)(react_native_1.View, { style: { flex: 1, backgroundColor: t.canvas }, children: [(0, jsx_runtime_1.jsx)(react_native_1.ScrollView, { contentContainerStyle: { paddingTop: insets.top + 10, paddingHorizontal: 12, paddingBottom: 4 }, children: (0, jsx_runtime_1.jsx)(pm_panel_1.PMStatusPanel, {}) }), (0, jsx_runtime_1.jsx)(react_native_1.View, { style: { flex: 1 }, children: (0, jsx_runtime_1.jsx)(loopmap_1.default, {}) })] }));
}
const pm = {
    id: "surfaces.pm",
    title: "PM",
    path: "/(tabs)/pm",
    component: PmDashboard,
    // No `route` here on purpose (mirrors connectors.tsx): today PM has no
    // standalone nav.tabs slot of its own (loopmap is reached from Automation),
    // so this Surface is deliberately not wired into the tab bar yet - it exists
    // so the cell registry has a real app-side counterpart to gate/inspect. A
    // future nav.tabs entry can add `route` without touching this file.
    nav: { group: "primary", order: 13, icon: "compass-outline" },
};
exports.pmSurface = {
    id: "surfaces.pm",
    tier: "plugin",
    inject: [kernel_1.KEYS.SURFACES.id],
    register(scope) {
        const surfaces = scope.require(kernel_1.KEYS.SURFACES);
        scope.use(surfaces.add(pm.id, pm.id, pm));
        scope.emit("surface:changed", { surfaceId: pm.id, present: true });
    },
};
