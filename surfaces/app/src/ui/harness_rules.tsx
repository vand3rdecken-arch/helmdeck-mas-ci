import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Platform, Pressable, Text, TextInput, View } from "react-native";

import type { BehaviorRule, RuleSurface } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Caption, ChipPick, fieldStyle, Hint, Toggle } from "@/ui/settings_sections";

/**
 * HENRY'S RULES AS ROWS (harness-config-ui phase 3, design doc sections 4.2 + 7.1).
 *
 * WHY THESE ARE NOT SchemaDoor ROWS. The generic settings renderer takes one
 * path, one control, one value. A behaviour rule holds a value PER SURFACE -
 * the length law is stated four times with four different numbers today (3
 * sentences in chat, 2 spoken, 2 on the watch, 2/240 chars on notices) - and
 * the entire modelling point of the card is that those four stay four and
 * become VISIBLE side by side, not that they get squashed into one. A
 * ConfigItem cannot express that, so forcing it through would either drop three
 * surfaces or invent a fourth table. The row below is the design doc's own
 * shape: ONE rule "Antwortlaenge", with an expandable "pro Oberflaeche" detail
 * under it saying the watch is terser than the chat.
 *
 * What it DOES reuse: the visual primitives every other settings row is built
 * from (Toggle, ChipPick, Caption, Hint, fieldStyle), so a rule row and an
 * automation row read as the same kind of thing - which is the point of
 * section 7.0's "the user has already learned it somewhere else".
 *
 * The client holds NO rule list. Everything rendered here arrives from
 * spine/registry/behavior.py via GET /harness/config.
 */

const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }) as string;

type Tr = (k: string, p?: Record<string, string | number>) => string;

/** Is this surface's value SET, or is it still coming from below?
 *
 *  Compared against the rule's OWN scope, not against `inherited` alone.
 *  `inherited` from the daemon means one specific thing - "this PROJECT did not
 *  set it" - which is exactly right for the chain and wrong for the badge of a
 *  WORKSPACE-scoped rule: the workspace is that rule's home, so a value stored
 *  there is set, not inherited. Reading `inherited` directly badged a rule the
 *  owner had just changed as "Geerbt vom Arbeitsbereich" and offered him no way
 *  back, which is a screen contradicting the click that produced it.
 */
function isSetHere(rule: BehaviorRule, s: RuleSurface): boolean {
  return s.layer === (rule.scope === "project" ? "project" : "workspace");
}

/** The provenance badge + the way back.
 *
 *  GitHub's org->repo settings pattern, which is where the wording comes from:
 *  a row says whether it is inherited or set here, and a set row offers exactly
 *  one way to stop being set. Reset is NOT "write the default" - it CLEARS the
 *  row so the value falls through again. Those are different states, and
 *  conflating them is how an undo silently freezes today's value one layer up.
 */
function LayerBadge({ rule, s, onReset, t, tr }: {
  rule: BehaviorRule; s: RuleSurface; onReset?: () => void; t: ThemeTokens; tr: Tr;
}) {
  const set = isSetHere(rule, s);
  const key = set
    ? (rule.scope === "project" ? "rule.layer.project" : "rule.layer.workspaceSet")
    : "rule.layer." + (s.layer || "default");
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      <View style={{ borderWidth: 1, borderRadius: 5, paddingHorizontal: 5, paddingVertical: 1,
        borderColor: set ? t.accent : t.borderSubtle, backgroundColor: t.surface2 }}>
        <Text style={{ color: set ? t.accent : t.txtTertiary, fontSize: 9.5, fontWeight: "600" }}>
          {tr(key)}
        </Text>
      </View>
      {set && onReset ? (
        <Pressable onPress={onReset} hitSlop={8} testID={"rule-reset-" + s.path}>
          <Text style={{ color: t.accent, fontSize: 10.5, fontWeight: "600" }}>{tr("rule.reset")}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/** A LOCK, with the reason and the file that holds it.
 *
 *  Chrome's "managed by your organization" pattern: locked looks locked AND
 *  says by whom and why. Never a dead switch - the design doc is explicit that
 *  four dummy toggles would be found out the first time one was tapped, and the
 *  same applies to a rule that cannot move. */
export function LockNote({ why, source, t, tr }: {
  why: string; source: string; t: ThemeTokens; tr: Tr;
}) {
  return (
    <View style={{ gap: 5, borderLeftWidth: 2, borderLeftColor: t.borderStrong, paddingLeft: 9 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
        <Ionicons name="lock-closed" size={11} color={t.txtTertiary} />
        <Text style={{ color: t.txtTertiary, fontSize: 10, fontWeight: "700", letterSpacing: 0.4 }}>
          {tr("rule.locked").toUpperCase()}
        </Text>
      </View>
      <Text style={{ color: t.txtSecondary, fontSize: 11.5, lineHeight: 16.5 }}>{why}</Text>
      {source ? (
        <Text selectable style={{ color: t.txtTertiary, fontSize: 10.5, fontFamily: MONO }}>{source}</Text>
      ) : null}
    </View>
  );
}

/** The control for one surface's value. Mirrors behavior.check_value's own
 *  branches - a control the daemon would refuse the value of is a control that
 *  should not be offered. An unknown control renders its value read-only rather
 *  than nothing at all: silence is how the generic renderer loses a knob. */
function RuleControl({ rule, s, onChange, t, tr }: {
  rule: BehaviorRule; s: RuleSurface; onChange: (v: unknown) => void; t: ThemeTokens; tr: Tr;
}) {
  const field = fieldStyle(t);
  const label = tr(rule.labelKey);
  if (rule.control === "toggle")
    return <Toggle label={label} value={!!s.value} onChange={onChange} />;
  if (rule.control === "single")
    return (
      <View>
        <Caption text={label} />
        <ChipPick options={rule.options ?? []} selected={[String(s.value ?? "")]} single
          onToggle={onChange} />
      </View>
    );
  if (rule.control === "number")
    return (
      <View>
        <Caption text={label} />
        <TextInput value={s.value == null ? "" : String(s.value)} style={field} keyboardType="numeric"
          onChangeText={(x) => onChange(Number(x) || 0)} />
      </View>
    );
  if (rule.control === "text")
    return (
      <View>
        <Caption text={label} />
        <TextInput value={s.value == null ? "" : String(s.value)} style={field} multiline
          placeholder={tr("rule.freeTextHint")} placeholderTextColor={t.txtPlaceholder}
          onChangeText={onChange} />
      </View>
    );
  if (rule.control === "list") {
    const arr = Array.isArray(s.value) ? (s.value as string[]) : [];
    return (
      <View style={{ gap: 4 }}>
        <Caption text={label} />
        {arr.map((x) => (
          <Text key={x} selectable style={{ color: t.txtSecondary, fontSize: 11, fontFamily: MONO }}>{x}</Text>
        ))}
        <Hint text={tr("rule.additiveOnly")} />
      </View>
    );
  }
  return (
    <View>
      <Caption text={label} />
      <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16.5 }}>
        {s.value == null ? tr("rule.proseOnly") : String(s.value)}
      </Text>
    </View>
  );
}

/** "Henry fragen" (design doc 5.5): the second, equal way to change a setting.
 *
 *  The point is not a shortcut to the chat - it is that the row travels WITH
 *  the tap, as a context chip over the composer, so Henry never has to guess
 *  which line was meant. That is the VS-Code-Copilot "Attach Context" gesture,
 *  and it is why this is a per-row link rather than one button on the page. */
function AskLink({ rule, onAsk, t, tr }: {
  rule: BehaviorRule; onAsk?: (r: BehaviorRule) => void; t: ThemeTokens; tr: Tr;
}) {
  if (!onAsk) return null;
  return (
    <Pressable testID={"rule-ask-" + rule.key} onPress={() => onAsk(rule)} hitSlop={8}
      style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      <Ionicons name="chatbubble-ellipses-outline" size={11} color={t.txtTertiary} />
      <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "600" }}>
        {tr("rule.askHenry")}
      </Text>
    </Pressable>
  );
}

/** ONE rule: label, control, one sentence, badge - and, when it has more than
 *  one surface, the expandable detail that is the whole reason this screen
 *  exists ("the watch is terser than the chat"). */
export function RuleRow({ rule, surfaces, project, onSet, onAsk, highlight, t, tr }: {
  rule: BehaviorRule;
  /** {key: label} from the daemon, so a surface can be named without the client
   *  learning what a surface IS. */
  surfaces: Record<string, string>;
  /** The project the screen is showing, "" for the workspace view. */
  project: string;
  onSet: (path: string, value: unknown) => void;
  /** "Henry fragen": opens the docked chat carrying THIS row as context
   *  (design doc 5.5). Absent where no chat is mounted. */
  onAsk?: (rule: BehaviorRule) => void;
  /** Arrived here from a chip in the brief view - mark the row so the jump has
   *  a visible landing, instead of dropping the owner into a list of twenty. */
  highlight?: boolean;
  t: ThemeTokens; tr: Tr;
}) {
  const [open, setOpen] = useState(false);
  const rows = rule.surfaces ?? [];
  const primary = rows[0];
  const many = rows.length > 1;
  // A per-project rule with no project selected has nowhere to be written, and
  // the daemon says so with a 400. Saying it HERE instead means the owner reads
  // it before he taps rather than after - the same reason a locked row shows
  // its reason instead of failing on touch.
  const needsProject = rule.scope === "project" && !project;
  // readonly and fixed rules never get a control. `fixed` is the interesting
  // half: those sentences LOOKED like invariants and were only prose until the
  // rule table made them real, so the lock here is the visible half of a
  // genuine guarantee, not decoration.
  const locked = rule.wire === "readonly" || rule.kind === "fixed";

  return (
    <View testID={"rule-" + rule.key}
      style={{ gap: 7, paddingVertical: 11, borderTopWidth: 1, borderTopColor: t.glassBorder,
        ...(highlight ? { borderLeftWidth: 2, borderLeftColor: t.accent, paddingLeft: 9,
          marginLeft: -11, backgroundColor: t.surface2 } : null) }}>
      {locked ? (
        <View style={{ gap: 6 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600" }}>{tr(rule.labelKey)}</Text>
          <Text style={{ color: t.txtSecondary, fontSize: 11.5, lineHeight: 16.5 }}>{tr(rule.descKey)}</Text>
          {rule.control === "list" && primary ? (
            <RuleControl rule={rule} s={primary} onChange={() => {}} t={t} tr={tr} />
          ) : null}
          <LockNote why={rule.why} source={rule.source} t={t} tr={tr} />
          {/* A locked row gets the ask link TOO. Henry is the exception broker -
              "why is this fixed?" is exactly the question worth putting to him,
              and his brief already makes him answer it by name with the route
              that IS open. */}
          <AskLink rule={rule} onAsk={onAsk} t={t} tr={tr} />
        </View>
      ) : (
        <View style={{ gap: 6 }}>
          {primary ? (
            <RuleControl rule={rule} s={primary} onChange={(v) => onSet(primary.path, v)} t={t} tr={tr} />
          ) : null}
          <Text style={{ color: t.txtSecondary, fontSize: 11.5, lineHeight: 16.5 }}>{tr(rule.descKey)}</Text>
          {needsProject ? <Hint text={tr("rule.needsProject")} /> : null}
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            {primary ? (
              <LayerBadge rule={rule} s={primary} t={t} tr={tr}
                onReset={() => onSet(primary.path, null)} />
            ) : null}
            <AskLink rule={rule} onAsk={onAsk} t={t} tr={tr} />
          </View>
        </View>
      )}

      {/* PER SURFACE, collapsed. The card's own answer to four numbers in four
          files: the owner sees ONE rule and, underneath, that the watch is
          terser than the chat - instead of four unconnected values he could
          never have compared. Nothing is unified here; that is an owner
          decision he can only make once he has seen them side by side. */}
      {many ? (
        <View>
          <Pressable testID={"rule-surfaces-" + rule.key} onPress={() => setOpen((o) => !o)}
            style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 5 }}>
            <Ionicons name={open ? "chevron-down" : "chevron-forward"} size={13} color={t.txtTertiary} />
            <Text style={{ color: t.txtSecondary, fontSize: 11.5, fontWeight: "600" }}>
              {tr("rule.perSurface", { n: rows.length })}
            </Text>
          </Pressable>
          {open ? (
            <View style={{ gap: 10, paddingLeft: 19, paddingTop: 2 }}>
              {rows.map((s) => (
                <View key={s.path} style={{ gap: 5 }}>
                  <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700" }}>
                    {surfaces[s.surface] || s.surface}
                  </Text>
                  {locked ? (
                    <Text style={{ color: t.txtSecondary, fontSize: 11.5 }}>{String(s.value)}</Text>
                  ) : (
                    <>
                      <RuleControl rule={rule} s={s} onChange={(v) => onSet(s.path, v)} t={t} tr={tr} />
                      <LayerBadge rule={rule} s={s} t={t} tr={tr}
                        onReset={() => onSet(s.path, null)} />
                    </>
                  )}
                </View>
              ))}
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

/** One of Henry's five blocks: its rules, most-basic first.
 *
 *  The block LIST and its order come from the daemon (behavior.BLOCKS), the
 *  same rule DOORS already lives under - the screen reads the order off the
 *  payload instead of re-declaring it, so a sixth block costs a daemon edit. */
export function RuleBlock({ block, rules, surfaces, project, onSet, onAsk, highlight }: {
  block: { key: string; labelKey: string; descKey: string };
  rules: BehaviorRule[];
  surfaces: Record<string, string>;
  project: string;
  onSet: (path: string, value: unknown) => void;
  onAsk?: (rule: BehaviorRule) => void;
  /** The rule a brief chip jumped to, if any. */
  highlight?: string;
}) {
  const t = useTheme();
  const tr = useT();
  const mine = rules.filter((r) => r.block === block.key);
  if (!mine.length) return null;
  return (
    <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
      borderRadius: 14, padding: 14, gap: 2 }}>
      <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700" }}>{tr(block.labelKey)}</Text>
      <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16.5, marginBottom: 4 }}>
        {tr(block.descKey)}
      </Text>
      {mine.map((r) => (
        <RuleRow key={r.key} rule={r} surfaces={surfaces} project={project}
          onSet={onSet} onAsk={onAsk} highlight={highlight === r.key} t={t} tr={tr} />
      ))}
    </View>
  );
}
