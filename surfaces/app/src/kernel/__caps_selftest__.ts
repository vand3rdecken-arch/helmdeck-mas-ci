// Role x screen nav self-test (card 4, ops/docs/backlog/rbac-gxp) - the
// automated test the plan called for and the first ship deferred. Runs
// under plain node after tsc, same convention as ./__selftest__.ts:
//   npx tsc -p tsconfig.capstest.json && node .capstest-out/kernel/__caps_selftest__.js
// (both run from surfaces/app/). Exits non-zero on the first failed check.
//
// This checks CLIENT-SIDE consistency: given a role's capability set, does
// `can()` + each nav table's `cap` declaration produce the visibility this
// repo's UI law promises (a route hidden ⇔ its declared cap is absent,
// never the reverse). It does NOT re-verify the server actually enforces
// that capability for that route - ops/tests/test_permissions.py and
// ops/tests/test_server_routes.py (Python) own that half.
//
// The role->caps snapshot below MIRRORS spine/auth/permissions.py's
// _DEFAULT_MATRIX byte-for-byte - keep the two in sync by hand (there is no
// cross-language import to enforce it automatically); a drift here means
// this test is checking a stale picture of the server, not a real gap.

import { can, TEAM_MEMBER_CAP } from "./caps";
import { TABS } from "../plugins/surfaces/tabs";
import { NAV, TAB_FALLBACK } from "../app/(tabs)/_nav_fallback";
import { GROUPS } from "../app/_more_groups";
import type { Me } from "../data/types";

let failures = 0;
function ok(cond: boolean, msg: string): void {
  if (cond) console.log(`  ok   - ${msg}`);
  else {
    failures++;
    console.log(`  FAIL - ${msg}`);
  }
}

// Mirrors permissions.py's _DEFAULT_MATRIX (2026-08-27).
const ROLE_CAPS: Record<string, string[]> = {
  owner: ["settings.read", "settings.write", "users.manage", "recordings.view",
    "audit.read", "devices.manage", "devices.use", "chat.use", "gxp.activate", "cards.admin"],
  operator: ["recordings.view", "devices.manage", "devices.use", "chat.use", "cards.admin"],
  client: [],
  quality: [],
  auditor: ["settings.read", "recordings.view", "audit.read"],
};
const ROLES = Object.keys(ROLE_CAPS);

function meFor(role: string): Me {
  return { name: role, role, caps: ROLE_CAPS[role] };
}

// Flatteners: each nav source has a different tuple/object shape, reduced
// to {key, cap} pairs so one visibility check covers all four.
function fromNavLike(items: readonly { name: string; cap?: string }[]) {
  return items.map((i) => ({ key: i.name, cap: i.cap }));
}
function fromTabs() {
  return TABS.map((s) => ({ key: s.id, cap: s.nav?.cap }));
}
function fromGroups() {
  const out: { key: string; cap?: string }[] = [];
  for (const [, links] of GROUPS) {
    for (const [route, , , , cap] of links) out.push({ key: route, cap });
  }
  return out;
}

const SOURCES: Record<string, { key: string; cap?: string }[]> = {
  "tabs.ts (TABS)": fromTabs(),
  "_nav_fallback.ts (NAV, desktop sidebar fallback)": fromNavLike(NAV),
  "_nav_fallback.ts (TAB_FALLBACK, phone bottom bar fallback)": fromNavLike(TAB_FALLBACK),
  "_more_groups.ts (GROUPS, More tab)": fromGroups(),
};

console.log("role x screen nav self-test");

// ---------------------------------------------------------------- 1 -------
console.log("\nowner sees every declared nav item, in every source");
for (const [srcName, items] of Object.entries(SOURCES)) {
  const owner = meFor("owner");
  const hidden = items.filter((i) => !can(owner, i.cap)).map((i) => i.key);
  ok(hidden.length === 0, `${srcName}: owner sees all ${items.length} items (hidden: ${hidden.join(",") || "none"})`);
}

// ---------------------------------------------------------------- 2 -------
console.log("\nclient sees ONLY items with no cap declared at all");
for (const [srcName, items] of Object.entries(SOURCES)) {
  const client = meFor("client");
  const wronglyVisible = items.filter((i) => i.cap !== undefined && can(client, i.cap)).map((i) => i.key);
  ok(wronglyVisible.length === 0,
    `${srcName}: client sees no capability-gated item (leaked: ${wronglyVisible.join(",") || "none"})`);
}

// ---------------------------------------------------------------- 3 -------
console.log("\nevery role's visibility set is internally consistent with can()");
// Not "does it match some external truth" (that's the server's job) but
// "does this source's OWN cap declaration actually gate via can() the way
// its comment claims" - i.e. re-deriving visibility twice (once via can(),
// once by hand) must agree, catching a typo'd cap string or an inverted check.
for (const role of ROLES) {
  const me = meFor(role);
  for (const [srcName, items] of Object.entries(SOURCES)) {
    for (const item of items) {
      const viaCanFn = can(me, item.cap);
      const byHand = item.cap === undefined ? true
        : item.cap === TEAM_MEMBER_CAP ? role !== "client"
        : ROLE_CAPS[role].includes(item.cap);
      ok(viaCanFn === byHand,
        `${srcName}/${item.key} for role ${role}: can()=${viaCanFn} matches hand-derived=${byHand}`);
    }
  }
}

// ---------------------------------------------------------------- 4 -------
console.log("\nnamed spot-checks (the concrete cases the plan cares about)");
const operator = meFor("operator");
const auditor = meFor("auditor");
const quality = meFor("quality");

ok(!can(operator, "settings.read"), "operator cannot see settings.read-gated screens (automation/settings)");
ok(can(auditor, "settings.read") && can(auditor, "audit.read") && can(auditor, "recordings.view"),
  "auditor sees settings/audit/recordings (read-only role, but genuinely read-everything by the current seed)");
ok(!can(auditor, "devices.manage"), "auditor cannot see devices.manage-gated screens");
ok(can(quality, TEAM_MEMBER_CAP), "quality is NOT excluded by TEAM_MEMBER_CAP (only literal 'client' is)");
ok(!can(quality, "recordings.view"), "quality has no recordings.view - never granted one implicitly");

// The audit screen specifically (card 5+6's own reason for existing):
const auditRow = fromGroups().find((i) => i.key === "audit");
ok(!!auditRow && auditRow.cap === "audit.read", "the More-tab audit row is gated on audit.read, not left open");
ok(!!auditRow && can(meFor("owner"), auditRow.cap) && can(meFor("auditor"), auditRow.cap)
  && !can(meFor("operator"), auditRow.cap) && !can(meFor("client"), auditRow.cap),
  "audit row: owner+auditor see it, operator+client do not");

console.log();
if (failures > 0) {
  console.log(`FAILED (${failures})`);
  process.exit(1);
}
console.log("all green");
