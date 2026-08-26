// Nav-only surfaces NOT owned by any cell (dual-nav cutover, daemon/debt.py
// plugin-kernel-dual-nav): board/processes/connectors used to be duplicated
// here as separate nav-only entries AND as their own cell Surface
// (surfaces/{board,processes,connectors}.tsx). Those 3 now carry route+nav
// directly on the real Surface object - one source of truth, not two - so
// they're removed from this list. What remains here is genuinely spine/
// app-shell: no cell owns a dashboard, "needs you", recordings, sessions,
// history, automation, settings, or modules tab.
//
// (tabs)/_layout renders both the bottom bar and the desktop sidebar from the
// FULL surface registry (this list + the 3 cell surfaces), falling back to
// its hard-coded arrays if the registry is empty (never bricks).

import { KEYS, type Plugin, type Surface } from "@/kernel";

type NavSurface = Surface & { route: string };

// order = position in the bar; desktopOnly = hidden from the phone bottom bar
// (the old DESKTOP_ONLY set); phoneOnly = the More tab, hidden on the sidebar.
const TABS: NavSurface[] = [
  { id: "tab.index", title: "", path: "index", route: "index", nav: { group: "primary", order: 0, icon: "stats-chart-outline", labelKey: "nav.dashboard" } },
  { id: "tab.needs", title: "", path: "needs", route: "needs", nav: { group: "primary", order: 2, icon: "notifications-outline", labelKey: "nav.needsYou" } },
  { id: "tab.recordings", title: "", path: "recordings", route: "recordings", nav: { group: "more", order: 4, icon: "videocam-outline", labelKey: "nav.recordings", desktopOnly: true } },
  { id: "tab.sessions", title: "", path: "sessions", route: "sessions", nav: { group: "more", order: 5, icon: "chatbubbles-outline", labelKey: "nav.sessions", teamOnly: true, desktopOnly: true } },
  // history is /history in server.py: owner/operator only (client 403s) -
  // teamOnly was missing here entirely until this fix, so a client saw the
  // sidebar link and hit a dead end.
  { id: "tab.history", title: "", path: "history", route: "history", nav: { group: "more", order: 6, icon: "time-outline", labelKey: "nav.history", teamOnly: true, desktopOnly: true } },
  // automation/settings are GET-owner-only server-side (routes_settings.py) -
  // teamOnly alone only hid these from clients, so an operator saw the link
  // and 403'd on tap. ownerOnly hides from operator too (see kernel/keys.ts).
  { id: "tab.automation", title: "", path: "automation", route: "automation", nav: { group: "more", order: 8, icon: "git-branch-outline", labelKey: "nav.automation", ownerOnly: true, desktopOnly: true } },
  { id: "tab.settings", title: "", path: "settings", route: "settings", nav: { group: "more", order: 9, icon: "settings-outline", labelKey: "nav.settings", ownerOnly: true, desktopOnly: true } },
  // modules(policy): GET /policy is owner/operator (routes_policy.py), only
  // POST /policy/swap is owner-only - teamOnly (client hidden) is correct as
  // is, an operator can read the page even if the write buttons should be
  // disabled for them (page-level concern, not nav-visibility).
  { id: "tab.modules", title: "", path: "modules", route: "modules", nav: { group: "more", order: 10, icon: "cube-outline", labelKey: "nav.modules", sectionKey: "nav.sectionSetup", teamOnly: true, desktopOnly: true } },
  { id: "tab.more", title: "", path: "more", route: "more", nav: { group: "more", order: 11, icon: "ellipsis-horizontal", phoneOnly: true } },
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
