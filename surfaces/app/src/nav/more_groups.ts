import { TEAM_MEMBER_CAP } from "@/kernel";

// The "More" tab's grouped link list, split out of (tabs)/more.tsx (card 4,
// ops/docs/backlog/rbac-gxp) so a plain-node self-test
// (src/kernel/__caps_selftest__.ts) can import it without pulling in
// react-native/@expo/vector-icons - more.tsx itself does, so a test
// importing IT directly would crash outside the Metro/Expo runtime. `icon`
// is a plain string here (not Ionicons' `keyof typeof glyphMap`); more.tsx
// casts back to its stricter type at the one render call site.
//
// `cap`: replaces the old any/team/owner Tier - checked via `can(me, cap)`
// against /me's live capability list instead of a third, independently-
// hand-maintained role-tier encoding (this list used to render
// unconditionally for EVERY role before the tier split existed, so a client
// saw Automation/Settings and got a 403 on tap). undefined = every
// authenticated role, TEAM_MEMBER_CAP (from @/kernel) = the interim
// stand-in for a route not yet migrated onto permissions.py. Keep this in
// sync with the server gate cited per row - a check exists to hide a route
// that ACTUALLY 403s, never the reverse.
export type Cap = string | undefined;

// Grouped so 9 flat rows become 3 scannable blocks. Every row carries a
// one-line subtitle (more.sub.*) - the labels alone ("Automatik",
// "Prozesse") proved opaque even to the owner - and every icon is UNIQUE
// within the list (three near-identical git glyphs before).
export const GROUPS: readonly [string, readonly (readonly [string, string, string, string, Cap])[]][] = [
  ["more.grp.control", [
    ["automation", "nav.automation", "options-outline", "more.sub.automation", "settings.read"], // routes_settings.py automation_get: owner only (card 2)
    ["processes", "nav.processes", "git-network-outline", "more.sub.processes", undefined],    // no role check in processes.py
    ["connectors", "nav.connectors", "extension-puzzle-outline", "more.sub.connectors", TEAM_MEMBER_CAP], // routes_connectors.py: client blocked, not yet migrated
  ]],
  ["more.grp.logs", [
    ["history", "nav.history", "time-outline", "more.sub.history", TEAM_MEMBER_CAP],                // routes_system.py history_get: client blocked, not yet migrated
    ["escalations", "nav.escalations", "alert-circle-outline", "more.sub.escalations", TEAM_MEMBER_CAP], // routes_info.py escalations_get: "not for clients", not yet migrated
    ["sessions", "nav.sessions", "chatbubbles-outline", "more.sub.sessions", TEAM_MEMBER_CAP],       // routes_system.py sessions_claude_get: client blocked, not yet migrated
    ["recordings", "nav.recordings", "videocam-outline", "more.sub.recordings", "recordings.view"],    // routes_runs.py runs_get: capability-gated (card 2)
    ["audit", "nav.audit", "file-tray-full-outline", "more.sub.audit", "audit.read"],   // routes_audit.py audit_get: capability-gated (card 2), screen built card 5
  ]],
  ["more.grp.system", [
    ["settings", "nav.settings", "settings-outline", "more.sub.settings", "settings.read"],         // routes_settings.py settings_get: owner only (card 2)
    ["repo", "nav.repo", "folder-open-outline", "more.sub.repo", "projects.view"],              // routes_projects.py repo_templates_get: projects.view
    ["loopmap", "nav.loopmap", "map-outline", "more.sub.loopmap", undefined],                   // /loop/map: no role check
  ]],
] as const;
