import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, Pressable, Switch, Text, TextInput, View } from "react-native";

import { api, type PmBrief, type PmConfig, type PmData } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

/** Shared "Neu planen" trigger for the Dashboard triangle panel + Settings'
 *  PM controls: kicks the async /nightshift/plan (answers instantly, the
 *  model turn runs server-side in a background thread) instead of holding
 *  api.pmReport()'s HTTP request open for the minutes a self-repair + verify
 *  pass can take - over the relay round trip that left a "Plant..." spinner
 *  stuck forever even after the plan had actually landed. Polls pmPlan while
 *  planning and stops the moment plan.generated_at moves past what it was
 *  before the kick; a 5-minute safety bail-out re-arms the button if the
 *  background run genuinely dies, since polling (unlike the old held-open
 *  request) is cheap to just retry. */
export function usePmReplan() {
  const qc = useQueryClient();
  const [planning, setPlanning] = useState(false);
  const baseline = useRef<string | undefined>(undefined);
  const bail = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const { data } = useQuery<PmData>({ queryKey: ["pmPlan"], queryFn: api.pmPlan, staleTime: 30000,
    refetchInterval: planning ? 4000 : false });
  useEffect(() => {
    if (!planning) return;
    if (data?.plan?.generated_at && data.plan.generated_at !== baseline.current) {
      setPlanning(false);
      qc.invalidateQueries({ queryKey: ["tracks"] });
    }
  }, [planning, data?.plan?.generated_at, qc]);
  useEffect(() => () => { if (bail.current) clearTimeout(bail.current); }, []);
  const kick = useMutation({
    mutationFn: api.pmReplan,
    onMutate: () => {
      baseline.current = data?.plan?.generated_at;
      setPlanning(true);
      if (bail.current) clearTimeout(bail.current);
      bail.current = setTimeout(() => setPlanning(false), 5 * 60 * 1000);
    },
    onError: (e: unknown) => { setPlanning(false); Alert.alert("PM", String((e as Error).message)); },
  });
  return { planning, replan: () => kick.mutate() };
}

// act.now lines are DAEMON prose (translated daemon-side, see daemon/i18n.py) -
// we don't translate them, we only pick an icon from their leading verb.
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

/** DASHBOARD: the single planning loop's STATUS + its latest deltas. Read-only -
 *  no goal/autonomy/consolidate controls (those live in Settings now). This is
 *  the "wo stehen wir + was hat sich geändert" surface the owner asked to keep
 *  next to the triangle. Renders nothing while the loop is OFF and idle. */
export function PMStatusPanel() {
  const t = useTheme();
  const tr = useT();
  const { data } = useQuery<PmData>({ queryKey: ["pmPlan"], queryFn: api.pmPlan, staleTime: 30000 });
  const act = data?.activity;
  if (!act) return null;
  const running = act.loop_enabled && act.state && act.state !== "IDLE" && act.state !== "OFF";
  const quiet = !running && !act.now?.length && !act.next && !act.needs_you?.length
    && !act.blockers?.length && !act.quota_paused && !act.feed?.length;
  if (quiet) return null;              // clean board: nothing to say -> show nothing

  const card = { backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 16 } as const;
  return (
    <View style={[card, { padding: 14, gap: 8 }]}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        <Ionicons name="compass" size={15} color={t.accent} />
        <Text style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "700", flex: 1 }}>{tr("pm.whatPmDoing")}</Text>
        {running ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: t.surface2, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 }}>
            <View style={{ width: 5, height: 5, borderRadius: 3, backgroundColor: act.state === "WAIT" ? t.warn : t.ai }} />
            <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{act.state}</Text>
          </View>
        ) : null}
      </View>
      {act.state_reason && running ? (
        <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{act.state_reason}</Text>
      ) : null}
      {act.now && act.now.length ? act.now.slice(0, 3).map((s, i) => (
        <ActLine key={i} icon={STUCK.test(s) ? "warning" : WAITING.test(s) ? "time-outline" : FINISHED.test(s) ? "checkmark-circle" : "construct"}
          color={STUCK.test(s) ? t.danger : WAITING.test(s) ? t.warn : FINISHED.test(s) ? t.ok : t.ai} text={s} t={t} />
      )) : null}
      {act.next ? <ActLine icon="play-forward" color={t.accent2}
        text={tr("pm.nextUp", { what: act.next }) + ((act.next_count ?? 0) > 1 ? tr("pm.queued", { n: (act.next_count ?? 1) - 1 }) : "")} t={t} /> : null}
      {act.needs_you && act.needs_you.length ? <ActLine icon="hand-left" color={t.warn}
        text={tr("pm.needsAccept", { n: act.needs_you.length })} t={t} /> : null}
      {act.blockers && act.blockers.length ? <ActLine icon="alert-circle" color={t.danger}
        text={tr("pm.blocker", { what: act.blockers[0] })} t={t} /> : null}
      {act.quota_paused ? <ActLine icon="time" color={t.warn} text={tr("pm.quotaPaused")} t={t} /> : null}
      {/* the DELTAS: the loop's latest proactive changes (full stream is the chat) */}
      {act.feed && act.feed.length ? (
        <View style={{ borderTopColor: t.borderSubtle, borderTopWidth: 1, paddingTop: 7, gap: 3 }}>
          {act.feed.slice(-3).reverse().map((e, i) => (
            <Text key={i} style={{ color: t.txtTertiary, fontSize: 10.5 }} numberOfLines={1}>· {e.msg}</Text>
          ))}
        </View>
      ) : null}
    </View>
  );
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
  const { planning, replan } = usePmReplan();

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

      {/* manual replan + consolidate */}
      <View style={{ flexDirection: "row", gap: 8 }}>
        <Pressable onPress={replan} disabled={planning}
          style={{ flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
            backgroundColor: t.surface2, borderRadius: 10, paddingVertical: 10 }}>
          {planning ? <ActivityIndicator size="small" color={t.accent} /> : <Ionicons name="refresh" size={15} color={t.txtSecondary} />}
          <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>{planning ? tr("pm.planning") : tr("pm.refresh")}</Text>
        </Pressable>
        <Pressable onPress={consolidate} disabled={proposing}
          style={{ flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
            backgroundColor: t.surface2, borderRadius: 10, paddingVertical: 10 }}>
          {proposing ? <ActivityIndicator size="small" color={t.accent} /> : <Ionicons name="git-merge-outline" size={15} color={t.txtSecondary} />}
          <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>{proposing ? tr("pm.proposing") : tr("pm.consolidate")}</Text>
        </Pressable>
      </View>
      {isLoading && !plan ? <ActivityIndicator color={t.accent} /> : null}
      {plan?.generated_at ? <Text style={{ color: t.txtTertiary, fontSize: 10, textAlign: "right" }}>{tr("pm.asOf", { when: plan.generated_at })}</Text> : null}
    </View>
  );
}
