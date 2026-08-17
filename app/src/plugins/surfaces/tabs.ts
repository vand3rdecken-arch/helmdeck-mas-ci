// Production tab set as registry data (nav cutover). One nav-only surface per
// expo-router (tabs) route file — the router owns the component; this owns the
// PRESENTATION (label, icon, order, which surface it shows on). (tabs)/_layout
// renders both the bottom bar and the desktop sidebar FROM these, falling back
// to its hard-coded arrays if the registry is empty (never bricks).
//
// Values mirror the previous hard-coded <Tabs.Screen> list + NAV array exactly;
// this is a mechanical move of that data behind the kernel, not a redesign.

import { KEYS, type Plugin, type Surface } from "@/kernel";

type NavSurface = Surface & { route: string };

// order = position in the bar; desktopOnly = hidden from the phone bottom bar
// (the old DESKTOP_ONLY set); phoneOnly = the More tab, hidden on the sidebar.
const TABS: NavSurface[] = [
  { id: "tab.index", title: "", path: "index", route: "index", nav: { group: "primary", order: 0, icon: "stats-chart-outline", labelKey: "nav.dashboard" } },
  { id: "tab.board", title: "", path: "board", route: "board", nav: { group: "primary", order: 1, icon: "grid-outline", labelKey: "nav.board" } },
  { id: "tab.needs", title: "", path: "needs", route: "needs", nav: { group: "primary", order: 2, icon: "notifications-outline", labelKey: "nav.needsYou" } },
  { id: "tab.processes", title: "", path: "processes", route: "processes", nav: { group: "more", order: 3, icon: "git-network-outline", labelKey: "nav.processes", sectionKey: "nav.sectionWorkflow", desktopOnly: true } },
  { id: "tab.recordings", title: "", path: "recordings", route: "recordings", nav: { group: "more", order: 4, icon: "videocam-outline", labelKey: "nav.recordings", desktopOnly: true } },
  { id: "tab.sessions", title: "", path: "sessions", route: "sessions", nav: { group: "more", order: 5, icon: "chatbubbles-outline", labelKey: "nav.sessions", teamOnly: true, desktopOnly: true } },
  { id: "tab.history", title: "", path: "history", route: "history", nav: { group: "more", order: 6, icon: "time-outline", labelKey: "nav.history", desktopOnly: true } },
  { id: "tab.connectors", title: "", path: "connectors", route: "connectors", nav: { group: "more", order: 7, icon: "sync-outline", labelKey: "nav.connectors", sectionKey: "nav.sectionSetup", teamOnly: true, desktopOnly: true } },
  { id: "tab.automation", title: "", path: "automation", route: "automation", nav: { group: "more", order: 8, icon: "git-branch-outline", labelKey: "nav.automation", teamOnly: true, desktopOnly: true } },
  { id: "tab.settings", title: "", path: "settings", route: "settings", nav: { group: "more", order: 9, icon: "settings-outline", labelKey: "nav.settings", teamOnly: true, desktopOnly: true } },
  { id: "tab.more", title: "", path: "more", route: "more", nav: { group: "more", order: 10, icon: "ellipsis-horizontal", labelKey: "nav.more", phoneOnly: true } },
];

export const tabsNav: Plugin = {
  id: "nav.tabs",
  tier: "plugin",
  inject: [KEYS.SURFACES.id],
  register(scope) {
    const surfaces = scope.require(KEYS.SURFACES);
    for (const s of TABS) scope.use(surfaces.add(s.id, s.id, s));
  },
};
