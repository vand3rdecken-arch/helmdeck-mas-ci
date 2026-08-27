"use strict";
// Phase 2 of the cell-registry decree (daemon/debt.py order 33): the Copilot
// cell's Surface. Same pattern as connectors.tsx: the existing app/chat.tsx
// screen (default export ChatScreen - real api.chat()/api.chatHistory()/
// api.chatLive() data-fetching, phone full-screen route vs desktop overlay
// logic already inside the component) is re-seated as a Surface, no logic
// moved. Mirrors cells.py's copilot Cell.surface = "surfaces.chat"
// exactly, and profiles/store.json's existing "surfaces.chat" reference.
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.copilotSurface = void 0;
const chat_1 = __importDefault(require("@/app/chat"));
const kernel_1 = require("@/kernel");
const copilot = {
    id: "surfaces.chat",
    title: "Copilot",
    path: "/chat",
    component: chat_1.default,
    // No `route` here on purpose (mirrors connectors.tsx): /chat is already a
    // real expo-router route (app/chat.tsx) reached from the board FAB /
    // CopilotOverlay, not a nav.tabs bar slot - this Surface exists so the cell
    // registry has a real app-side counterpart to gate/inspect.
    nav: { group: "primary", order: 15, icon: "chatbubbles-outline" },
};
exports.copilotSurface = {
    id: "surfaces.chat",
    tier: "plugin",
    inject: [kernel_1.KEYS.SURFACES.id],
    register(scope) {
        const surfaces = scope.require(kernel_1.KEYS.SURFACES);
        scope.use(surfaces.add(copilot.id, copilot.id, copilot));
        scope.emit("surface:changed", { surfaceId: copilot.id, present: true });
    },
};
