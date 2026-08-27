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

import { KEYS, type Plugin, type Surface, TEAM_MEMBER_CAP } from "@/kernel";

type NavSurface = Surface & { route: string };

// order = position in the bar; desktopOnly = hidden from the phone bottom bar
// (the old DESKTOP_ONLY set); phoneOnly = the More tab, hidden on the sidebar.
// `cap` (card 4): the daemon capability (spine/auth/permissions.py CAPS) this
// tab's route actually requires - TEAM_MEMBER_CAP is the interim stand-in for
// routes not yet migrated onto the permission registry (ops/docs/backlog/
// rbac-gxp card 2's tracked debt), see kernel/caps.ts.
// Exported (not just used by tabsNav below) so ops/tests-equivalent
// self-tests (src/kernel/__caps_selftest__.ts, card 4) can check its `cap`
// declarations directly against a role's capability set.
export const TABS: NavSurface[] = [
  { id: "tab.index", title: "", path: "index", route: "index", nav: { group: "primary", order: 0, icon: "stats-chart-outline", labelKey: "nav.dashboard" } },
  { id: "tab.needs", title: "", path: "needs", route: "needs", nav: { group: "primary", order: 2, icon: "notifications-outline", labelKey: "nav.needsYou" } },
  { id: "tab.recordings", title: "", path: "recordings", route: "recordings", nav: { group: "more", order: 4, icon: "videocam-outline", labelKey: "nav.recordings", desktopOnly: true } },
  // /sessions/claude (routes_system.py) is NOT yet migrated onto permissions.py.
  { id: "tab.sessions", title: "", path: "sessions", route: "sessions", nav: { group: "more", order: 5, icon: "chatbubbles-outline", labelKey: "nav.sessions", cap: TEAM_MEMBER_CAP, desktopOnly: true } },
  // /history (routes_system.py) is NOT yet migrated onto permissions.py
  // (spine/registry/debt.py's rbac-permission-registry-partial) - team-only
  // is still enforced server-side by its own inline check, just not by a
  // real capability yet.
  { id: "tab.history", title: "", path: "history", route: "history", nav: { group: "more", order: 6, icon: "time-outline", labelKey: "nav.history", cap: TEAM_MEMBER_CAP, desktopOnly: true } },
  // automation/settings are routes_settings.py, now capability-gated for
  // real (settings.read, owner-only in the seeded matrix) - card 2.
  { id: "tab.automation", title: "", path: "automation", route: "automation", nav: { group: "more", order: 8, icon: "git-branch-outline", labelKey: "nav.automation", cap: "settings.read", desktopOnly: true } },
  { id: "tab.settings", title: "", path: "settings", route: "settings", nav: { group: "more", order: 9, icon: "settings-outline", labelKey: "nav.settings", cap: "settings.read", desktopOnly: true } },
  // modules(policy): GET /policy is owner/operator (routes_policy.py, not yet
  // migrated) - team-only via the interim stand-in, same caveat as /history.
  { id: "tab.modules", title: "", path: "modules", route: "modules", nav: { group: "more", order: 10, icon: "cube-outline", labelKey: "nav.modules", sectionKey: "nav.sectionSetup", cap: TEAM_MEMBER_CAP, desktopOnly: true } },
  { id: "tab.more", title: "", path: "more", route: "more", nav: { group: "more", order: 11, icon: "ellipsis-horizontal", labelKey: "nav.more", phoneOnly: true } },
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
