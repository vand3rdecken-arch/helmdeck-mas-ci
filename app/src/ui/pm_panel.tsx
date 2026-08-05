import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Alert, Pressable, Switch, Text, TextInput, View } from "react-native";

import { api, type PmBrief, type PmConfig, type PmData } from "@/data/client";
import { t as tr, useT } from "@/i18n";
import { useTheme } from "@/theme";

const cur = (n?: number) => "€" + (n ?? 0).toFixed(2);
// act.now lines are DAEMON prose (translated daemon-side, see daemon/i18n.py) -
// we don't translate them, we only pick an icon from their leading verb. Match
// both languages so an English workspace keeps its warning/ok icons.
const STUCK = /^(h(ä|ae)ngt|stuck)/i;
const WAITING = /^(wartet|waiting)/i;
const FINISHED = /^(fertig|done|finished)/i;
const fmtDate = (iso?: string) => {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d.getTime())) return "";
  const wd = tr("pm.weekdays").split(",");
  return `${wd[d.getDay()]} ${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;
};

function ActLine({ icon, color, text, t }: { icon: keyof typeof Ionicons.glyphMap; color: string; text: string; t: ReturnType<typeof useTheme> }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 8 }}>
      <Ionicons name={icon} size={14} color={color} style={{ marginTop: 1 }} />
      <Text style={{ color: t.txtSecondary, fontSize: 12.5, flex: 1, lineHeight: 18 }}>{text}</Text>
    </View>
  );
}

function Chip({ icon, label, t }: { icon: keyof typeof Ionicons.glyphMap; label: string; t: ReturnType<typeof useTheme> }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: t.surface2,
      borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 }}>
      <Ionicons name={icon} size={12} color={t.txtTertiary} />
      <Text style={{ color: t.txtSecondary, fontSize: 11.5, fontWeight: "600" }}>{label}</Text>
    </View>
  );
}

export function PMPanel({ defaultRepo }: { defaultRepo?: string }) {
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
  const makeCard = useMutation({
    mutationFn: (task: string) => api.newTrack({ repo: defaultRepo, task, lane: "backlog", priority: "medium" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tracks"] }); Alert.alert("PM", tr("pm.cardCreated")); },
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
  const b = plan?.budget;
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

      {/* LAUNCH metric — the north star up top, so it's unmistakable the PM is
          driving the goal you set (the Android store deploy), on the dashboard. */}
      {plan && (plan.milestones?.length || plan.done_pct != null) ? (() => {
        const ms = plan.milestones ?? [];
        const launchMs = ms.find((m) => /store|play|launch|release|deploy/i.test((m.name || "") + " " + (m.tasks || []).map((x) => x.title).join(" "))) ?? ms[ms.length - 1];
        const launchDate = launchMs?.target_date;
        const days = launchDate ? Math.ceil((new Date(launchDate + "T00:00:00").getTime() - Date.now()) / 86400000) : undefined;
        const pct = Math.max(0, Math.min(100, plan.done_pct ?? 0));
        return (
          <View style={{ backgroundColor: t.accent + "18", borderColor: t.accent + "55", borderWidth: 1, borderRadius: 12, padding: 12, gap: 8 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Ionicons name="rocket" size={16} color={t.accent} />
              <Text style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "800", flex: 1 }}>{tr("pm.launchTitle")}</Text>
              {days != null ? (
                <Text style={{ color: t.accent, fontSize: 12, fontWeight: "800" }}>
                  {days > 0 ? tr("pm.daysLeft", { n: days }) : days === 0 ? tr("pm.today") : tr("pm.daysOver", { n: -days })}
                </Text>
              ) : null}
            </View>
            <View style={{ height: 7, borderRadius: 4, backgroundColor: t.surface2, overflow: "hidden" }}>
              <View style={{ width: `${pct}%`, height: 7, backgroundColor: t.accent }} />
            </View>
            <View style={{ flexDirection: "row", alignItems: "center" }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11 }}>
                {tr("pm.pctToLaunch", { pct })}{launchDate ? tr("pm.targetDate", { date: fmtDate(launchDate) }) : ""}
              </Text>
              {act?.next ? <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 11, flex: 1, textAlign: "right", marginLeft: 8 }}>→ {act.next}</Text> : null}
            </View>
          </View>
        );
      })() : null}

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
          {/* summary + progress */}
          {plan.summary ? <Text style={{ color: t.txtSecondary, fontSize: 13, lineHeight: 19 }}>{plan.summary}</Text> : null}
          <View style={{ gap: 5 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("pm.progress")}</Text>
              <Text style={{ color: t.txtSecondary, fontSize: 11, fontWeight: "700" }}>{plan.done_pct ?? 0}%</Text>
            </View>
            <View style={{ height: 7, borderRadius: 4, backgroundColor: t.surface2, overflow: "hidden" }}>
              <View style={{ width: `${Math.max(0, Math.min(100, plan.done_pct ?? 0))}%`, height: 7, backgroundColor: t.ok }} />
            </View>
          </View>

          {/* budget / quota */}
          {b ? (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
              <Chip icon="time-outline" label={tr("pm.eta", { n: b.eta_days ?? "?" })} t={t} />
              <Chip icon="git-commit-outline" label={tr("pm.turns", { n: b.est_turns_to_goal ?? "?" })} t={t} />
              <Chip icon="speedometer-outline" label={tr("pm.perDay", { n: b.velocity_turns_per_day ?? "?" })} t={t} />
              <Chip icon="cash-outline" label={b.plan === "max" ? tr("pm.flatMonthly", { v: cur(b.fixed_monthly_eur) })
                : tr("pm.cashToGoal", { v: cur(b.cash_to_goal_eur) })} t={t} />
              {b.plan === "max" ? <Chip icon="flash-outline" label={tr("pm.leverage", { v: cur(b.shadow_eur_to_goal) })} t={t} /> : null}
            </View>
          ) : null}
          {b?.note ? <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{b.note}</Text> : null}

          {/* milestones timeline */}
          {plan.milestones?.length ? (
            <View style={{ gap: 0, marginTop: 2 }}>
              {plan.milestones.map((m, i) => (
                <View key={i} style={{ flexDirection: "row", gap: 10 }}>
                  <View style={{ alignItems: "center", width: 16 }}>
                    <View style={{ width: 11, height: 11, borderRadius: 6, backgroundColor: t.accent2, marginTop: 3 }} />
                    {i < (plan.milestones?.length ?? 0) - 1 ? <View style={{ width: 2, flex: 1, backgroundColor: t.borderStrong, marginVertical: 2 }} /> : null}
                  </View>
                  <View style={{ flex: 1, paddingBottom: 12 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "700", flex: 1 }}>{m.name}</Text>
                      <Text style={{ color: t.accent2, fontSize: 11, fontWeight: "700" }}>
                        {m.target_date ? tr("pm.by", { date: fmtDate(m.target_date) })
                          : tr("pm.etaDays", { n: m.cumulative_eta_days ?? m.eta_days ?? 0 })}
                      </Text>
                      {m.card ? (
                        <Pressable onPress={() => router.push(`/card/${m.card}` as never)} hitSlop={6}>
                          <Ionicons name="arrow-forward-circle" size={18} color={t.accent} />
                        </Pressable>
                      ) : null}
                    </View>
                    {m.why_now || m.why ? (
                      <Text style={{ color: t.txtTertiary, fontSize: 11.5, marginTop: 2 }}>{m.why_now ?? m.why}</Text>
                    ) : null}
                    <Text style={{ color: t.txtTertiary, fontSize: 10.5, marginTop: 3 }}>
                      {tr("pm.stepsTurns", { steps: m.steps?.length ?? m.tasks?.length ?? 0, turns: m.est_turns ?? 0 })}
                    </Text>
                  </View>
                </View>
              ))}
            </View>
          ) : null}

          {/* next actions -> card */}
          {plan.next?.length ? (
            <View style={{ gap: 8 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 }}>{tr("pm.nextHeading")}</Text>
              {plan.next.slice(0, 5).map((n, i) => (
                <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: t.surface2, borderRadius: 10, padding: 10 }}>
                  <Text style={{ color: t.accent, fontSize: 12, fontWeight: "800", width: 14 }}>{i + 1}</Text>
                  <View style={{ flex: 1 }}>
                    <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "600" }}>{n.title}</Text>
                    {n.reason ? <Text numberOfLines={2} style={{ color: t.txtTertiary, fontSize: 11 }}>{n.reason}</Text> : null}
                  </View>
                  {n.card ? (
                    <Pressable onPress={() => router.push(`/card/${n.card}` as never)} hitSlop={6}>
                      <Ionicons name="arrow-forward-circle" size={22} color={t.accent} />
                    </Pressable>
                  ) : (
                    <Pressable onPress={() => Alert.alert(tr("pm.createCardTitle"), n.title, [
                      { text: tr("ui.cancel"), style: "cancel" },
                      { text: tr("ui.create"), onPress: () => makeCard.mutate(n.title) }])} hitSlop={6}>
                      <Ionicons name="add-circle" size={22} color={t.ok} />
                    </Pressable>
                  )}
                </View>
              ))}
            </View>
          ) : null}

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
