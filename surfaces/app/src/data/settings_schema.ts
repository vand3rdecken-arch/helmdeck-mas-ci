// THE SETTINGS SCHEMA, client side (accounts-boards-prd phase 4, "settings-hub").
//
// Pure data + pure functions, deliberately free of react-native/expo imports,
// for two reasons that are the same reason: the placement rules ARE the
// feature, so they must be (a) importable by the plain-node self-test
// (src/data/__settings_hub_selftest__.ts) that proves a knob lands in the
// right door with the right badge, and (b) the one place both the renderer
// and that test read from. A rule that lives inside a .tsx component can only
// be checked by driving a browser.
//
// The vocabularies below MIRROR spine/http/apimeta.py's DOORS and SCOPES.
// ops/tests/test_settings_hub.py parses this file and holds the two halves
// equal - a door or scope on one side and not the other is a knob that
// renders nowhere or badges as nothing, and neither is a type error.

/** The hub's doors, in the order the hub lists them. "boards" sits between
 *  "general" and "automation" per the PRD's section-5 amendment. */
export const DOOR_IDS = ["general", "boards", "automation", "cells", "connections", "team", "system"] as const;
export type DoorId = (typeof DOOR_IDS)[number];

/** PRD section 3's five layers: who OWNS a knob. This tag decides two things
 *  at once - the badge the row wears, and which endpoint the row writes to -
 *  which is exactly why G4 ("one owner, one storage location, one edit
 *  surface") is a property of the data here rather than a convention. */
export const SCOPES = ["profile", "board", "workspace", "device", "system"] as const;
export type Scope = (typeof SCOPES)[number];

/** The control union. Held equal to spine/http/apimeta.py's CONTROLS by
 *  ops/tests/test_harness_layer.py - a control the daemon emits and this
 *  union does not name renders as NOTHING, silently. */
export type Ctl = "toggle" | "multi" | "single" | "text" | "number" | "labels";

export interface ConfigItem {
  /** Section id inside the door. Free-form: a new section costs one daemon
   *  entry, not a client-side group->label table. */
  group: string;
  /** That section's i18n label key. Carried on the knob for the same reason. */
  groupKey?: string;
  path: string;
  control: Ctl;
  labelKey: string;
  descKey?: string;
  level?: "basic" | "advanced";
  door?: string;
  /** OR: the pipeline station whose page renders this knob (harness-config-ui
   *  section 6). Exactly one of door/station - a knob editable in two places is
   *  the duplication G4 forbids, and a knob with neither renders nowhere. */
  station?: string;
  scope?: string;
  value: unknown;
  options?: string[];
  /** {optionValue: i18n key} - lets an option read "Deutsch" without the
   *  client having to know what "de" means. */
  optionLabels?: Record<string, string>;
  keys?: string[];
  placeholder?: string;
}

/** The i18n key for a scope's badge. Unknown scopes (a daemon newer than this
 *  bundle) get NO badge rather than a wrong one - a row with a missing badge
 *  is honest, a row wearing "Workspace" when the daemon meant something else
 *  is a lie about who a change affects. */
export function scopeBadgeKey(scope: string | undefined): string | null {
  return (SCOPES as readonly string[]).includes(scope ?? "") ? `hub.scope.${scope}` : null;
}

/** Which endpoint owns the write, derived from the scope tag alone.
 *
 *  "profile" -> PUT /me/config (self-scoped, every role, the account's own
 *  view). Everything else -> POST /settings (owner-only, the shared daemon).
 *  A board-scoped knob writes to settings today because that is where
 *  policy.lane_labels still lives; PRD section 6 migrates it into the board
 *  row, and when it does, only this function changes. */
export type WriteTarget = "profile" | "settings";
export const writeTargetFor = (scope: string | undefined): WriteTarget =>
  scope === "profile" ? "profile" : "settings";

/** Profile rows save the moment you tap them; workspace rows batch behind a
 *  Save button. DERIVED from the scope, not hand-assigned per door: a profile
 *  write is one whitelisted key on your own account (cheap, private, and
 *  instant is what the language chip did before the hub existed), while a
 *  settings write is a deep-merge onto shared policy where committing four
 *  half-typed fields on every keystroke would be wrong. */
export const autosaves = (scope: string | undefined): boolean => writeTargetFor(scope) === "profile";

/** Build the nested patch for one knob path, at ANY depth.
 *
 *  Was two levels only ("a.b"), which is what kept `default_repo` (one) and
 *  `capacity.tariff.steer` (three) out of the schema and stranded in a
 *  hand-built panel. Depth is not a property the table should have to care
 *  about, so it does not. */
export function nest(path: string, value: unknown): Record<string, unknown> {
  const parts = path.split(".");
  let out: unknown = value;
  for (let i = parts.length - 1; i >= 0; i--) out = { [parts[i]]: out };
  return out as Record<string, unknown>;
}

/** One rendered section of a door. */
export interface Section {
  group: string;
  groupKey: string;
  /** Every row in the section, so a caller can count without flattening. */
  items: ConfigItem[];
  basic: ConfigItem[];
  advanced: ConfigItem[];
  /** True when every row in the section writes itself immediately - the
   *  section then renders without a Save button. Mixed sections (which the
   *  daemon does not currently produce) keep the button and batch the ones
   *  that need it. */
  autosave: boolean;
  /** Which endpoint this section's Save button posts to. */
  target: WriteTarget;
}

/** THE PLACEMENT RULE, and the whole point of the phase: given the full
 *  schema and a door, return that door's sections. Sections come out in the
 *  order their first row appears in the schema, and rows keep schema order
 *  within a section - so the daemon owns the layout end to end and adding a
 *  knob (or a whole new section, or a knob in a door that had none) is a
 *  daemon-side edit with no client change at all.
 *
 *  A row with no `door` is dropped rather than defaulted into some door: a
 *  knob that appears somewhere arbitrary is worse than one that visibly does
 *  not appear, because only the second gets reported. */
export function placeRows(schema: readonly ConfigItem[], door: string): Section[] {
  return groupRows(schema, (it) => it.door === door);
}

/** THE SAME PLACEMENT RULE, keyed on `station` instead of `door`
 *  (harness-config-ui section 6): the knobs that govern one pipeline station,
 *  in schema order, sectioned exactly as a door's are.
 *
 *  Deliberately the same function underneath rather than a parallel one. The
 *  station page and the hub have to agree about what a section IS, what counts
 *  as advanced and which endpoint saves it - and two implementations of that
 *  would agree right up until one of them was edited. */
export function placeStation(schema: readonly ConfigItem[], station: string): Section[] {
  return groupRows(schema, (it) => it.station === station);
}

/** Which stations the schema actually has rows for - the station page uses it
 *  the way the hub uses doorsWithRows, and the pipeline uses it to badge a
 *  station with how many knobs sit behind it. */
export const stationsWithRows = (schema: readonly ConfigItem[]): string[] =>
  Array.from(new Set(schema.map((i) => i.station).filter(Boolean) as string[]));

function groupRows(schema: readonly ConfigItem[], keep: (it: ConfigItem) => boolean): Section[] {
  const order: string[] = [];
  const by = new Map<string, ConfigItem[]>();
  for (const it of schema) {
    if (!keep(it)) continue;
    const g = it.group || "";
    if (!by.has(g)) { by.set(g, []); order.push(g); }
    by.get(g)!.push(it);
  }
  return order.map((g) => {
    const items = by.get(g)!;
    return {
      group: g,
      // Falls back to the group id so an un-labelled section is visibly
      // un-labelled instead of invisible.
      groupKey: items.find((i) => i.groupKey)?.groupKey ?? g,
      items,
      basic: items.filter((i) => i.level !== "advanced"),
      advanced: items.filter((i) => i.level === "advanced"),
      autosave: items.every((i) => autosaves(i.scope)),
      target: writeTargetFor(items[0]?.scope),
    };
  });
}

/** Which doors the schema actually has rows for. The hub uses this to decide
 *  whether a door is worth a chevron. */
export const doorsWithRows = (schema: readonly ConfigItem[]): string[] =>
  DOOR_IDS.filter((d) => schema.some((i) => i.door === d));
