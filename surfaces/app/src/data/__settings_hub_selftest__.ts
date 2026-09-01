// THE ACCEPTANCE TEST for accounts-boards-prd phase 4 ("settings-hub"):
//
//   "a dummy knob with a scope tag appears in the correct door with the
//    correct badge with NO client code change"
//
// Runs under plain node after tsc, same convention as __caps_selftest__.ts:
//   npx tsc -p tsconfig.hubtest.json && node .hubtest-out/data/__settings_hub_selftest__.js
// (both from surfaces/app/). Exits non-zero on the first failed check.
//
// WHY THIS SHAPE, and not a Playwright screenshot. "No client code change" is
// a statement about the PLACEMENT RULE, not about pixels: given a knob the
// client has never heard of, does the renderer put it in the door the knob
// names, under the section the knob names, in the tier the knob names, with
// the badge its scope names? That is a pure function of (schema, door), so it
// is checkable deterministically here - on every machine, with no daemon, no
// browser and no fixture drift. A screenshot proves it rendered ONCE, for
// knobs that already exist; this proves the rule holds for a knob that does
// not exist and never will.
//
// The DUMMY knob below is the point. It is deliberately unlike every shipped
// knob - a door that has no schema rows at all today (team), a scope the
// daemon never emits (device), a group with no i18n entry, a control path
// three levels deep - so nothing about it can be satisfied by a special case
// somebody wrote for the real ones.

import {
  DOOR_IDS, SCOPES, type ConfigItem,
  autosaves, doorsWithRows, nest, placeRows, scopeBadgeKey, writeTargetFor,
} from "./settings_schema";

let failures = 0;
function ok(cond: boolean, msg: string): void {
  if (cond) console.log(`  ok   - ${msg}`);
  else {
    failures++;
    console.log(`  FAIL - ${msg}`);
  }
}

/** A knob no client code has ever seen. */
const DUMMY: ConfigItem = {
  group: "dummySection",
  groupKey: "dummy.section",
  path: "dummy.deeply.nested",
  control: "text",
  labelKey: "dummy.label",
  descKey: "dummy.desc",
  door: "team",
  level: "advanced",
  scope: "device",
  value: "hello",
};

/** A minimal stand-in for the shipped schema, so the dummy has company and
 *  cannot pass by being the only row in the list. */
const SHIPPED: ConfigItem[] = [
  { group: "profile", groupKey: "profile.section", path: "lang", control: "single",
    labelKey: "ui.language", options: ["de", "en"], value: "de",
    door: "general", level: "basic", scope: "profile" },
  { group: "policy", groupKey: "automation.configPolicy", path: "policy.auto_accept_green",
    control: "toggle", labelKey: "cfg.autoAccept", value: false,
    door: "automation", level: "basic", scope: "workspace" },
  { group: "night", groupKey: "automation.nightSection", path: "nightshift.window",
    control: "text", labelKey: "cfg.nightWindow", value: "",
    door: "automation", level: "advanced", scope: "workspace" },
];

console.log("settings-hub placement (accounts-boards-prd phase 4)");

// ---- 1. THE ACCEPTANCE CHECK -----------------------------------------------
{
  const before = placeRows(SHIPPED, "team");
  ok(before.length === 0, "door 'team' has no schema rows before the dummy is added");

  const schema = [...SHIPPED, DUMMY];
  const team = placeRows(schema, "team");
  ok(team.length === 1, "the dummy knob makes door 'team' render exactly one section");
  const sec = team[0];
  ok(sec.group === "dummySection", "the section is the one the KNOB named, not a client-side group");
  ok(sec.groupKey === "dummy.section", "the section heading key comes off the knob too");
  ok(sec.advanced.length === 1 && sec.basic.length === 0,
    "level 'advanced' puts it behind the door's Erweitert fold, not on the front");
  ok(sec.advanced[0].path === "dummy.deeply.nested", "the row IS the dummy");
  ok(scopeBadgeKey(sec.advanced[0].scope) === "hub.scope.device",
    "the row wears the badge its scope names ('Gerät'), chosen by no client table");
  ok(sec.target === "settings" && !sec.autosave,
    "a non-profile scope batches behind Save and posts to /settings");

  // ...and it appears NOWHERE else. A knob that leaks into a second door is
  // worse than one that renders nowhere, because it invites an edit in a
  // place that does not own it.
  const elsewhere = DOOR_IDS.filter((d) => d !== "team")
    .flatMap((d) => placeRows(schema, d))
    .flatMap((s) => s.items)
    .filter((i) => i.path === DUMMY.path);
  ok(elsewhere.length === 0, "the dummy appears in its door and in NO other door");

  // The shipped rows must not have moved because a new knob showed up.
  ok(JSON.stringify(placeRows(schema, "automation")) === JSON.stringify(placeRows(SHIPPED, "automation")),
    "adding a knob to one door leaves every other door byte-identical");
}

// ---- 2. a knob with no door renders nowhere, loudly rather than somewhere ---
{
  const orphan: ConfigItem = { ...DUMMY, path: "orphan.knob", door: undefined };
  const anywhere = DOOR_IDS.flatMap((d) => placeRows([orphan], d));
  ok(anywhere.length === 0, "a knob with no door is dropped, never defaulted into one");
}

// ---- 3. sections and rows keep SCHEMA order (the daemon owns the layout) ----
{
  const a: ConfigItem = { ...DUMMY, group: "gA", groupKey: "k.a", path: "a.one", level: "basic" };
  const b: ConfigItem = { ...DUMMY, group: "gB", groupKey: "k.b", path: "b.one", level: "basic" };
  const a2: ConfigItem = { ...DUMMY, group: "gA", groupKey: "k.a", path: "a.two", level: "basic" };
  const secs = placeRows([a, b, a2], "team");
  ok(secs.map((s) => s.group).join(",") === "gA,gB",
    "sections come out in the order their FIRST row appears in the schema");
  ok(secs[0].basic.map((i) => i.path).join(",") === "a.one,a.two",
    "rows keep schema order inside a section, even split by another section");
}

// ---- 4. the scope vocabulary badges completely, and only what it knows -----
{
  for (const s of SCOPES) ok(scopeBadgeKey(s) === `hub.scope.${s}`, `scope '${s}' has a badge key`);
  ok(scopeBadgeKey("invented") === null,
    "a scope this bundle does not know gets NO badge - a missing badge is honest, "
    + "a wrong one lies about who a change affects");
  ok(scopeBadgeKey(undefined) === null, "an absent scope gets no badge either");
}

// ---- 5. the scope tag decides the write target and the save behaviour ------
{
  ok(writeTargetFor("profile") === "profile", "profile scope writes to PUT /me/config");
  for (const s of ["board", "workspace", "device", "system"] as const)
    ok(writeTargetFor(s) === "settings", `scope '${s}' writes to POST /settings`);
  ok(autosaves("profile") && !autosaves("workspace"),
    "profile rows save on tap; workspace rows batch behind Save");
  const profileSec = placeRows(SHIPPED, "general")[0];
  ok(profileSec.autosave && profileSec.target === "profile",
    "door 1's section is autosaving and account-backed, derived purely from its scope");
}

// ---- 6. nest() at every depth the schema actually uses ---------------------
{
  ok(JSON.stringify(nest("lang", "en")) === '{"lang":"en"}', "nest at one level");
  ok(JSON.stringify(nest("policy.auto_accept_green", true)) === '{"policy":{"auto_accept_green":true}}',
    "nest at two levels");
  ok(JSON.stringify(nest("capacity.tariff.steer", 3)) === '{"capacity":{"tariff":{"steer":3}}}',
    "nest at three levels - the depth that kept the business panel hand-built");
}

// ---- 7. doorsWithRows reflects reality, including the new door -------------
{
  ok(JSON.stringify(doorsWithRows(SHIPPED)) === '["general","automation"]',
    "doorsWithRows lists exactly the doors that have rows, in door order");
  ok(doorsWithRows([...SHIPPED, DUMMY]).includes("team"),
    "and picks up a door the moment a knob names it");
  ok((DOOR_IDS as readonly string[]).indexOf("boards") === 1,
    "the Boards door sits between 'general' and 'automation' (PRD section 5)");
}

console.log(failures ? `FAILED: ${failures}` : "all settings-hub placement checks passed");
process.exit(failures ? 1 : 0);
