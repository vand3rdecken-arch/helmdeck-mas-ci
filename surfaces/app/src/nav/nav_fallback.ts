import { TEAM_MEMBER_CAP } from "@/kernel";

// Fallback nav data, split out of _layout.tsx (card 4, ops/docs/backlog/
// rbac-gxp) so it can be imported by a plain-node self-test
// (src/kernel/__caps_selftest__.ts) without pulling in react-native/expo -
// _layout.tsx itself does, so a test importing IT directly would crash
// outside the Metro/Expo runtime. `icon` is typed as a plain string here
// (not Ionicons' `keyof typeof glyphMap`) for the same reason; _layout.tsx
// casts back to its stricter IconName at the one render call site.
//
// labelKey / sectionKey are i18n keys, not prose - the nav renders them
// through the translator so the shell speaks the workspace language.
// `cap`: the daemon capability (spine/auth/permissions.py CAPS) this item's
// route actually requires - checked via `can(me, cap)` (src/kernel/caps.ts).
export type NavItem = { name: string; labelKey: string; icon: string; sectionKey?: string; cap?: string };

// Desktop left-sidebar FALLBACK nav - used ONLY when the kernel registry is
// empty (boot failed). Must mirror the registry (tabs.ts + the 3 cell
// surfaces) 1:1, or a kernel failure silently changes the shell.
export const NAV: NavItem[] = [
  { name: "index", labelKey: "nav.dashboard", icon: "stats-chart-outline" },
  { name: "board", labelKey: "nav.board", icon: "grid-outline" },
  { name: "needs", labelKey: "nav.needsYou", icon: "notifications-outline" },
  { name: "processes", labelKey: "nav.processes", icon: "git-network-outline", sectionKey: "nav.sectionWorkflow" },
  // recordings (/runs) is capability-gated server-side (routes_runs.py,
  // recordings.view - card 2).
  { name: "recordings", labelKey: "nav.recordings", icon: "videocam-outline", cap: "recordings.view" },
  { name: "sessions", labelKey: "nav.sessions", icon: "chatbubbles-outline", cap: TEAM_MEMBER_CAP },
  { name: "history", labelKey: "nav.history", icon: "time-outline", cap: TEAM_MEMBER_CAP },
  { name: "connectors", labelKey: "nav.connectors", icon: "sync-outline", sectionKey: "nav.sectionSetup", cap: TEAM_MEMBER_CAP },
  // automation/settings are routes_settings.py, capability-gated for real now
  // (settings.read, owner-only in the seeded matrix - card 2).
  { name: "automation", labelKey: "nav.automation", icon: "git-branch-outline", cap: "settings.read" },
  { name: "settings", labelKey: "nav.settings", icon: "settings-outline", cap: "settings.read" },
  { name: "modules", labelKey: "nav.modules", icon: "cube-outline", sectionKey: "nav.sectionSetup", cap: TEAM_MEMBER_CAP },
];

// The bottom-bar / tab set, matching the hard-coded list 1:1. Used as the
// FALLBACK when the kernel registry is empty (no KernelProvider / boot
// failed), so the shell renders identically with or without the plugin
// kernel. `cap` closed a real gap here (card 4): this list previously had
// NO role gating fields at all, so a kernel failure (or, before the
// registry path was fixed, even the normal registry path) showed every
// tab, owner-only ones included, to every role on the phone bottom bar.
export type TabItem = { name: string; labelKey: string; icon: string; desktopOnly?: boolean; phoneOnly?: boolean; cap?: string };
export const TAB_FALLBACK: TabItem[] = [
  { name: "index", labelKey: "nav.dashboard", icon: "stats-chart-outline" },
  { name: "board", labelKey: "nav.board", icon: "grid-outline" },
  { name: "needs", labelKey: "nav.needsYou", icon: "notifications-outline" },
  { name: "processes", labelKey: "nav.processes", icon: "git-network-outline", desktopOnly: true },
  { name: "recordings", labelKey: "nav.recordings", icon: "videocam-outline", desktopOnly: true, cap: "recordings.view" },
  { name: "sessions", labelKey: "nav.sessions", icon: "chatbubbles-outline", desktopOnly: true, cap: TEAM_MEMBER_CAP },
  { name: "history", labelKey: "nav.history", icon: "time-outline", desktopOnly: true, cap: TEAM_MEMBER_CAP },
  { name: "connectors", labelKey: "nav.connectors", icon: "sync-outline", desktopOnly: true, cap: TEAM_MEMBER_CAP },
  { name: "automation", labelKey: "nav.automation", icon: "git-branch-outline", desktopOnly: true, cap: "settings.read" },
  { name: "settings", labelKey: "nav.settings", icon: "settings-outline", desktopOnly: true, cap: "settings.read" },
  { name: "modules", labelKey: "nav.modules", icon: "cube-outline", desktopOnly: true, cap: TEAM_MEMBER_CAP },
  { name: "more", labelKey: "nav.more", icon: "ellipsis-horizontal", phoneOnly: true },
];
