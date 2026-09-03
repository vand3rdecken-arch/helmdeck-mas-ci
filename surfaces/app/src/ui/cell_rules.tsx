import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo } from "react";
import { Alert, Pressable, Text, View } from "react-native";

import { api, type BehaviorRule, type HarnessConfig } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";
import { RuleRow } from "@/ui/harness_rules";

/**
 * A CELL'S OWN RULES, inside the cells door (the cells<->settings seam).
 *
 * Before this, the cells door showed WHICH agents exist and the harness page
 * showed WHICH rules exist - and nothing connected them: a rule knew its cell
 * only as a string reference nobody resolved. The daemon now resolves it
 * (behavior.cell_of, derived from the rule's own `reads`/`source` against the
 * cell registry) and every rule arrives with its `cell`. This component only
 * GROUPS by that field - it holds no rule list and no cell list of its own,
 * the same contract every schema screen already lives under.
 *
 * WHAT IT REUSES, deliberately: RuleRow - the exact row the harness page
 * renders, with the same controls, the same inherit/set badge, the same lock
 * with its reason, and the SAME write path (POST /harness/config). One rule,
 * one row shape, two doors that agree by construction. A second, simplified
 * renderer here would be a second place a rule could lie.
 *
 * The door names no repo, so this shows the WORKSPACE layer - the honest
 * answer for a screen about the cells in general, and the same choice
 * /harness/config makes for a request without ?repo. Per-project values live
 * on the harness page, and the link at the bottom leads there.
 */
export function CellRules() {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const router = useRouter();
  const { data: cfg } = useQuery<HarnessConfig>({
    queryKey: ["harnessConfig", ""], queryFn: () => api.harnessConfig(""),
    staleTime: 30000, retry: false,
  });

  const surfaceLabels = useMemo(() => {
    const by: Record<string, string> = {};
    for (const s of cfg?.surfaces ?? []) by[s.key] = s.label;
    return by;
  }, [cfg]);

  // Rules grouped by their owning cell, in FIRST-SEEN order (which is the
  // table's own order, i.e. the daemon's). Cell-less rules (spine-owned:
  // notices, the charter's house rules) form one shared group at the end -
  // shown, not dropped, because a rule this door hides is a rule the owner
  // has to know a second door for.
  const groups = useMemo(() => {
    const by = new Map<string, BehaviorRule[]>();
    for (const r of cfg?.rules ?? []) {
      const key = r.cell ?? "";
      if (!by.has(key)) by.set(key, []);
      by.get(key)!.push(r);
    }
    const out = [...by.entries()].filter(([k]) => k !== "");
    const shared = by.get("");
    if (shared?.length) out.push(["", shared]);
    return out;
  }, [cfg]);

  /** The one write path - same as the harness page's setRule: the daemon picks
   *  the layer from the rule's own scope, null clears back to inheritance, and
   *  a refusal shows the daemon's own why-sentence instead of a moved switch. */
  async function setRule(path: string, value: unknown) {
    try {
      const res = await api.saveHarnessConfig("", { [path]: value });
      if (res?.error) throw new Error(res.error);
      await qc.invalidateQueries({ queryKey: ["harnessConfig"] });
      await qc.invalidateQueries({ queryKey: ["loopmap"] });
    } catch (e) {
      Alert.alert(tr("harness.saveFailed"), String((e as Error).message));
    }
  }

  if (!cfg || !groups.length) return null;

  return (
    <>
      {groups.map(([cell, rules]) => (
        <Panel key={cell || "shared"}>
          <SectionLabel text={cell ? tr("cells.rules.title", { cell }) : tr("cells.rules.shared")} />
          <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16.5, marginBottom: 4 }}>
            {cell ? tr("cells.rules.hint") : tr("cells.rules.sharedHint")}
          </Text>
          {rules.map((r) => (
            <RuleRow key={r.key} rule={r} surfaces={surfaceLabels} project=""
              onSet={setRule} t={t} tr={tr} />
          ))}
        </Panel>
      ))}
      {/* The same rules in their full context (per project, with the briefs
          they render into) live on the harness page - one tap, not a hunt. */}
      <Pressable onPress={() => router.push("/loopmap" as never)}
        style={{ flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: t.surface2,
          borderColor: t.glassBorder, borderWidth: 1, borderRadius: 12, padding: 11 }}>
        <Ionicons name="git-network-outline" size={16} color={t.accent} />
        <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600", flex: 1 }}>
          {tr("cells.rules.openMap")}
        </Text>
        <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
      </Pressable>
    </>
  );
}
