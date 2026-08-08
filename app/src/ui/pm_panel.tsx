import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Alert, Pressable, Switch, Text, TextInput, View } from "react-native";

import { api, type PmBrief, type PmConfig, type PmData } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// act.now lines are DAEMON prose (translated daemon-side, see daemon/i18n.py) -
// we don't translate them, we only pick an icon from their leading verb. Match
// both languages so an English workspace keeps its warning/ok icons.
const STUCK = /^(h(ä|ae)ngt|stuck)/i;
const WAITING = /^(wartet|waiting)/i;
const FINISHED = /^(fertig|done|finished)/i;

function ActLine({ icon, color, text, t }: { icon: keyof typeof Ionicons.glyphMap; color: string; text: string; t: ReturnType<typeof useTheme> }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 8 }}>
      <Ionicons name={icon} size={14} color={color} style={{ marginTop: 1 }} />
      <Text style={{ color: t.txtSecondary, fontSize: 12.5, flex: 1, lineHeight: 18 }}>{text}</Text>
    </View>
  );
}

/** The PM CONTROL surface: goal, autonomy, consolidate, live activity. All plan
 *  follow-up (launch, milestones, budget, progress, next actions) renders in
 *  TriageFollowUp on the dashboard, keyed to the three triangle corners. */
export function PMPanel() {
  const t = useTheme();
  const tr = useT();          // shadows the module-level static t(): same API, re-renders on switch
  const router = useRouter();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery<PmData>({ queryKey: ["pmPlan"], queryFn: api.pmPlan, staleTime: 30000 });
  const [goal, setGoal] = useState<string | null>(null);
  const [editGoal, setEditGoal] = useState(false);

  const report = useMutation({
    mutationFn: (g?: string) => api.pmReport(g),
    onSuccess: (b: PmBrief) => { qc.setQueryData<PmData>(["pmPlan"], (o) => o ? { ...o, plan: b, goal: b.goal ?? o.goal } : o); setEditGoal(false); },
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
               Alert.alert(tr("pm.consolidatedTitle"), tr("pm.consolidatedMsg",
                 { created: res.created?.length || 0, archived: res.archived?.length || 0 }));
             } catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
           } }]);
    } catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
    finally { setProposing(false); }
  }

  const plan = data?.plan;
  const curGoal = data?.goal ?? "";
  const cfg = data?.config;
  const act = data?.activity;
  const AUTO: { k: "notify" | "ask" | "act"; label: string }[] = [
    { k: "notify", label: tr("pm.notify") }, { k: "ask", label: tr("pm.ask") }, { k: "act", label: tr("pm.act") }];

  const card = { backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 16 } as const;

  return (
    <View style={[card, { padding: 14, gap: 12 }]}>
      {/* header */}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <View style={{ width: 26, height: 26, borderRadius: 8, backgroundColor: t.accent, alignItems: "center", justifyContent: "center" }}>
          <Ionicons name="compass" size={16} color="#fff" />
        </View>
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "700", flex: 1 }}>{tr("pm.title")}</Text>
        <Pressable onPress={() => router.push("/chat")} hitSlop={8} style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Ionicons name="chatbubble-ellipses-outline" size={15} color={t.accent} />
          <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{tr("nav.chat")}</Text>
        </Pressable>
        <Pressable onPress={() => report.mutate(undefined)} disabled={report.isPending} hitSlop={8}
          style={{ flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: t.surface2, borderRadius: 8, paddingHorizontal: 9, paddingVertical: 5 }}>
          {report.isPending ? <ActivityIndicator size="small" color={t.accent} /> : <Ionicons name="refresh" size={14} color={t.txtSecondary} />}
          <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{report.isPending ? tr("pm.planning") : tr("pm.refresh")}</Text>
        </Pressable>
      </View>

      {/* what the PM is doing — plain language, from real board state */}
      {act ? (
        <View style={{ backgroundColor: t.surface2, borderRadius: 10, padding: 11, gap: 7 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "700", flex: 1 }}>{tr("pm.whatPmDoing")}</Text>
            {act.loop_enabled && act.state && act.state !== "IDLE" ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: t.surface1, borderRadius: 999, paddingHorizontal: 7, paddingVertical: 2 }}>
                <View style={{ width: 5, height: 5, borderRadius: 3, backgroundColor: act.state === "WAIT" ? t.warn : t.ai }} />
                <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{act.state}</Text>
              </View>
            ) : null}
          </View>
          {act.state_reason && act.state !== "IDLE" && act.state !== "OFF" ? (
            <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{act.state_reason}</Text>
          ) : null}
          {act.now && act.now.length ? act.now.slice(0, 3).map((s, i) => (
            <ActLine key={i} icon={STUCK.test(s) ? "warning" : WAITING.test(s) ? "time-outline" : FINISHED.test(s) ? "checkmark-circle" : "construct"}
              color={STUCK.test(s) ? t.danger : WAITING.test(s) ? t.warn : FINISHED.test(s) ? t.ok : t.ai} text={s} t={t} />
          )) : (
            <ActLine icon="pause-circle" color={t.txtTertiary}
              text={act.loop_enabled ? tr("pm.nothingRunning") : tr("pm.proactiveOff")} t={t} />
          )}
          {act.next ? <ActLine icon="play-forward" color={t.accent2}
            text={tr("pm.nextUp", { what: act.next })
              + ((act.next_count ?? 0) > 1 ? tr("pm.queued", { n: (act.next_count ?? 1) - 1 }) : "")} t={t} /> : null}
          {act.needs_you && act.needs_you.length ? <ActLine icon="hand-left" color={t.warn}
            text={tr("pm.needsAccept", { n: act.needs_you.length })} t={t} /> : null}
          {act.blockers && act.blockers.length ? <ActLine icon="alert-circle" color={t.danger}
            text={tr("pm.blocker", { what: act.blockers[0] })} t={t} /> : null}
          {act.quota_paused ? <ActLine icon="time" color={t.warn} text={tr("pm.quotaPaused")} t={t} /> : null}
          {act.feed && act.feed.length ? (
            <Text style={{ color: t.txtTertiary, fontSize: 10.5, marginTop: 2 }} numberOfLines={2}>
              {tr("pm.recent", { what: act.feed.slice(-2).map((e) => e.msg).join(" · ") })}
            </Text>
          ) : null}
        </View>
      ) : null}

      {/* goal */}
      {editGoal ? (
        <View style={{ gap: 8 }}>
          <TextInput value={goal ?? curGoal} onChangeText={setGoal} multiline placeholder={tr("pm.goalPh")}
            placeholderTextColor={t.txtPlaceholder}
            style={{ color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 13, minHeight: 60 }} />
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable onPress={() => report.mutate(goal ?? curGoal)} disabled={report.isPending}
              style={{ flex: 1, backgroundColor: t.accent, borderRadius: 8, padding: 10, alignItems: "center" }}>
              <Text style={{ color: "#fff", fontWeight: "600" }}>{tr("pm.setGoal")}</Text>
            </Pressable>
            <Pressable onPress={() => setEditGoal(false)} style={{ backgroundColor: t.surface2, borderRadius: 8, padding: 10, paddingHorizontal: 14, alignItems: "center" }}>
              <Text style={{ color: t.txtSecondary, fontWeight: "600" }}>{tr("ui.cancel")}</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <Pressable onPress={() => { setGoal(curGoal); setEditGoal(true); }}
          style={{ flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: t.surface2, borderRadius: 8, padding: 10 }}>
          <Ionicons name="flag-outline" size={14} color={t.txtTertiary} />
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

      {isLoading && !plan ? <ActivityIndicator color={t.accent} /> : null}

      {plan ? (
        <>
          {/* Phase 3: consolidate the ticket-ocean into stream cards (gated) */}
          <Pressable onPress={consolidate} disabled={proposing}
            style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
              backgroundColor: t.surface2, borderRadius: 10, paddingVertical: 10, marginTop: 2 }}>
            {proposing ? <ActivityIndicator size="small" color={t.accent} /> : <Ionicons name="git-merge-outline" size={15} color={t.txtSecondary} />}
            <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>{proposing ? tr("pm.proposing") : tr("pm.consolidate")}</Text>
          </Pressable>

          {plan.generated_at ? <Text style={{ color: t.txtTertiary, fontSize: 10, textAlign: "right" }}>{tr("pm.asOf", { when: plan.generated_at })}</Text> : null}
        </>
      ) : !isLoading ? (
        <Text style={{ color: t.txtTertiary, fontSize: 12.5 }}>
          {tr("pm.noPlan")}
        </Text>
      ) : null}
    </View>
  );
}
