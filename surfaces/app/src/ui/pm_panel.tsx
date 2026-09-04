import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Alert, Pressable, Switch, Text, TextInput, View } from "react-native";

import { api, type PmConfig, type PmData } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

/** Kick an async re-scope with NO waiting UI at all (pm-lean-advisor,
 *  2026-09-04: "kein Warte-Knopf" is UX rule 1 - re-scoping is event-driven
 *  now - goal changed, a card landed in Done and a triangle corner flipped -
 *  not something the owner ever watches happen). /nightshift/plan answers
 *  instantly; the one remaining model turn runs server-side, and the next
 *  ordinary poll of ["pmPlan"] (staleTime 30s) just shows the new result
 *  whenever it lands - no local "planning" state, no spinner, nothing to
 *  time out. Errors are silent on purpose: this is a background nudge, not
 *  a user action with a result to report.*/
function replanSilently() {
  api.pmReplan().catch(() => {});
}

/** SETTINGS: the PM CONTROL surface - goal, proactive on/off + escalation ladder
 *  (notify/ask/act), consolidate, manual replan. Moved off the dashboard so the
 *  overview stays "sehr clean": the board shows what the loop is DOING, the
 *  steering of it lives here. */
export function PMControls() {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery<PmData>({ queryKey: ["pmPlan"], queryFn: api.pmPlan, staleTime: 30000 });
  const [goal, setGoal] = useState<string | null>(null);
  const [editGoal, setEditGoal] = useState(false);

  // Setting the goal used to POST /pm/report directly - a synchronous,
  // full-model-turn endpoint. Over the relay that request is bounded by
  // REPLY_TIMEOUT (surfaces/relay/relay.py, 120s), so most goal edits died
  // with an unread 504 before the turn ever finished - "kann das nicht
  // bearbeiten" (bug found 2026-09-04). set_goal() itself is a plain settings
  // write, no LLM call; persist it instantly through /pm/config (already the
  // fast, whitelisted path setCfg below uses) and nudge a silent background
  // re-scope (replanSilently) - no waiting UI, see its own docstring.
  const saveGoal = useMutation({
    mutationFn: (g: string) => api.pmConfig({ goal: g }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pmPlan"] });
      setEditGoal(false);
      replanSilently();
    },
    onError: (e: unknown) => Alert.alert("PM", String((e as Error).message)),
  });
  const setCfg = useMutation({
    mutationFn: (patch: Partial<PmConfig>) => api.pmConfig(patch),
    onSuccess: (c: PmConfig) => qc.setQueryData<PmData>(["pmPlan"], (o) => o ? { ...o, config: c } : o),
    onError: (e: unknown) => Alert.alert("PM", String((e as Error).message)),
  });

  const [proposing, setProposing] = useState(false);
  async function consolidate() {
    setProposing(true);
    try {
      const p = await api.pmConsolidatePropose();
      const repos = p.repos || [];
      const nStreams = repos.reduce((a, r) => a + (r.streams?.length || 0), 0);
      const nCards = repos.reduce((a, r) => a + (r.streams || []).reduce((c, s) => c + (s.members?.length || 0), 0), 0);
      if (!nStreams) { Alert.alert(tr("pm.consolidateTitle"), tr("pm.noRollup")); return; }
      const lines = repos.flatMap((r) => (r.streams || []).map((s) => `• ${s.title} (${s.members?.length || 0})`)).join("\n");
      Alert.alert(tr("pm.consolidateHead", { streams: nStreams, tickets: nCards }),
        lines + "\n\n" + tr("pm.consolidateBody"),
        [{ text: tr("ui.cancel"), style: "cancel" },
         { text: tr("pm.apply"), onPress: async () => {
             try {
               const res = await api.pmConsolidateApply(repos);
               qc.invalidateQueries({ queryKey: ["tracks"] });
               qc.invalidateQueries({ queryKey: ["pmPlan"] });
               // The daemon refuses to archive members that are not in backlog
               // (an active card must never be swept off the board) - say so,
               // otherwise the count silently disagreeing with the proposal
               // reads as "all of it landed".
               const refused = res.refused?.length || 0;
               Alert.alert(tr("pm.consolidatedTitle"),
                 tr("pm.consolidatedMsg", { created: res.created?.length || 0, archived: res.archived?.length || 0 })
                 + (refused ? "\n" + tr("pm.consolidatedRefused", { n: String(refused) }) : ""));
             } catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
           } }]);
    } catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
    finally { setProposing(false); }
  }

  const plan = data?.plan;
  const curGoal = data?.goal ?? "";
  const cfg = data?.config;
  const AUTO: { k: "notify" | "ask" | "act"; label: string }[] = [
    { k: "notify", label: tr("pm.notify") }, { k: "ask", label: tr("pm.ask") }, { k: "act", label: tr("pm.act") }];

  return (
    <View style={{ gap: 12 }}>
      {/* goal */}
      {editGoal ? (
        <View style={{ gap: 8 }}>
          <TextInput value={goal ?? curGoal} onChangeText={setGoal} multiline placeholder={tr("pm.goalPh")}
            placeholderTextColor={t.txtPlaceholder}
            style={{ color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 13, minHeight: 60 }} />
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable onPress={() => saveGoal.mutate(goal ?? curGoal)} disabled={saveGoal.isPending}
              style={{ flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
                backgroundColor: t.accent, borderRadius: 8, padding: 10, opacity: saveGoal.isPending ? 0.7 : 1 }}>
              {saveGoal.isPending ? <ActivityIndicator size="small" color="#fff" /> : null}
              <Text style={{ color: "#fff", fontWeight: "600" }}>{saveGoal.isPending ? tr("pm.saving") : tr("pm.setGoal")}</Text>
            </Pressable>
            <Pressable onPress={() => setEditGoal(false)} disabled={saveGoal.isPending}
              style={{ backgroundColor: t.surface2, borderRadius: 8, padding: 10, paddingHorizontal: 14, alignItems: "center" }}>
              <Text style={{ color: t.txtSecondary, fontWeight: "600" }}>{tr("ui.cancel")}</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <Pressable onPress={() => { setGoal(curGoal); setEditGoal(true); }}
          style={{ flexDirection: "row", alignItems: "center", gap: 6,
            backgroundColor: t.surface2, borderRadius: 8, padding: 10 }}>
          <Ionicons name={curGoal ? "flag" : "flag-outline"} size={14} color={t.txtTertiary} />
          <Text numberOfLines={2} style={{ color: curGoal ? t.txtSecondary : t.txtTertiary, fontSize: 12.5, flex: 1 }}>
            {curGoal || tr("pm.noGoal")}
          </Text>
          <Ionicons name="pencil" size={13} color={t.txtTertiary} />
        </Pressable>
      )}

      {/* proactive control: on/off + escalation ladder (notify/ask/act) */}
      <View style={{ backgroundColor: t.surface2, borderRadius: 10, padding: 10, gap: 10 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Ionicons name="pulse" size={15} color={cfg?.loop_enabled ? t.ok : t.txtTertiary} />
          <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600", flex: 1 }}>{tr("pm.proactive")}</Text>
          <Switch value={!!cfg?.loop_enabled} onValueChange={(v) => setCfg.mutate({ loop_enabled: v })}
            trackColor={{ true: t.accent, false: t.borderStrong }} />
        </View>
        {cfg?.loop_enabled ? (
          <View style={{ flexDirection: "row", backgroundColor: t.surface1, borderRadius: 8, padding: 3 }}>
            {AUTO.map((a) => {
              const on = (cfg?.autonomy ?? "act") === a.k;
              return (
                <Pressable key={a.k} onPress={() => setCfg.mutate({ autonomy: a.k })}
                  style={{ flex: 1, paddingVertical: 7, borderRadius: 6, alignItems: "center", backgroundColor: on ? t.accent : "transparent" }}>
                  <Text style={{ color: on ? "#fff" : t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{a.label}</Text>
                </Pressable>
              );
            })}
          </View>
        ) : null}
        <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>
          {!cfg?.loop_enabled ? tr("pm.desc.off")
            : cfg?.autonomy === "notify" ? tr("pm.desc.notify")
            : cfg?.autonomy === "ask" ? tr("pm.desc.ask")
            : tr("pm.desc.act")}
        </Text>
      </View>

      {/* consolidate only - manual replan removed (pm-lean-advisor,
          2026-09-04, UX rule 1: no UI element ever waits on a model turn).
          Re-scoping now happens on its own: goal changed (above) or a card
          landing in Done flips a triangle corner (pm_triangle.on_card_done). */}
      <Pressable onPress={consolidate} disabled={proposing}
        style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
          backgroundColor: t.surface2, borderRadius: 10, paddingVertical: 10 }}>
        {proposing ? <ActivityIndicator size="small" color={t.accent} /> : <Ionicons name="git-merge-outline" size={15} color={t.txtSecondary} />}
        <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>{proposing ? tr("pm.proposing") : tr("pm.consolidate")}</Text>
      </Pressable>
      {isLoading && !plan ? <ActivityIndicator color={t.accent} /> : null}
      {plan?.generated_at ? <Text style={{ color: t.txtTertiary, fontSize: 10, textAlign: "right" }}>{tr("pm.asOf", { when: plan.generated_at })}</Text> : null}
    </View>
  );
}
