"use strict";
// Phase 2 of the cell-registry decree (daemon/debt.py order 33): the Process
// cell's Surface. Same pattern as connectors.tsx: the existing (tabs)/
// processes.tsx screen (real api.processes() data-fetching + POST /processes
// mutations) is re-seated as a Surface, no logic moved.
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.processesSurface = void 0;
const processes_1 = __importDefault(require("@/app/(tabs)/processes"));
const kernel_1 = require("@/kernel");
const processes = {
    id: "surfaces.processes",
    title: "Processes",
    path: "/(tabs)/processes",
    component: processes_1.default,
    // route + nav merged from nav.tabs' former "tab.processes" entry (dual-nav
    // cutover, daemon/debt.py plugin-kernel-dual-nav): this Surface is now
    // BOTH what renders (component) and where it lives in nav (route/nav).
    // tabs.ts's matching entry is removed in the same change.
    route: "processes",
    nav: { group: "more", order: 3, icon: "git-network-outline", labelKey: "nav.processes",
        sectionKey: "nav.sectionWorkflow", desktopOnly: true },
};
exports.processesSurface = {
    id: "surfaces.processes",
    tier: "plugin",
    inject: [kernel_1.KEYS.SURFACES.id],
    register(scope) {
        const surfaces = scope.require(kernel_1.KEYS.SURFACES);
        scope.use(surfaces.add(processes.id, processes.id, processes));
        scope.emit("surface:changed", { surfaceId: processes.id, present: true });
    },
};
