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
  // The HUB (accounts-boards-prd phase 4). ONE row instead of the three
  // near-synonyms it replaced ("Automatik" / "Einstellungen" / "Module") -
  // the redundancy settings-ia-redesign phase 3 was filed to remove.
  //
  // NO `cap`, and that is a deliberate change from card 2's settings.read.
  // This screen stopped being owner-only the moment door 1 became the
  // ACCOUNT's profile: a `client` has two real doors here (Mein Profil,
  // Boards) and must be able to set their own language. Gating the ROUTE
  // would make the screen unreachable for them - measured, not assumed: with
  // the cap in place a client navigating to /settings silently landed back on
  // the dashboard, because _layout.tsx registers only the tabs a role passes.
  // The owner-only DOORS are hidden inside the hub instead (settings.tsx's
  // DOOR_META carries the caps), which is the plan's "Nicht-Owner sehen nur
  // Tür 1 - Rest unsichtbar statt 403", and every owner-only ROUTE the hub
  // calls is still gated server-side exactly as before.
  { id: "tab.settings", title: "", path: "settings", route: "settings", nav: { group: "more", order: 9, icon: "settings-outline", labelKey: "nav.settings", desktopOnly: true } },
  // The REDIRECT route (see (tabs)/automation.tsx).
  // Still registered, deliberately: _layout.tsx's navigator is built with
  // useOnlyUserDefinedScreens=true, so dropping them here would make
  // /automation and /modules UNREACHABLE rather than merely unlisted, and
  // this card's brief keeps them alive for deep links and chat references.
  // `hidden` is what says "route yes, nav no". `cap` deliberately stays off:
  // a redirect must resolve for whoever follows the link, and the hub it
  // lands on does the role gating one screen later.
  { id: "tab.automation", title: "", path: "automation", route: "automation", nav: { group: "more", order: 8, icon: "git-branch-outline", labelKey: "nav.automation", hidden: true } },
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
