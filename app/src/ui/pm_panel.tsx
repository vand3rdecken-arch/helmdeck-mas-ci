import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Alert, Pressable, Switch, Text, TextInput, View } from "react-native";

import { api, type PmBrief, type PmConfig, type PmData } from "@/data/client";
import { useTheme } from "@/theme";

const cur = (n?: number) => "€" + (n ?? 0).toFixed(2);

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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tracks"] }); Alert.alert("PM", "Als Karte angelegt (Backlog)."); },
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
      if (!nStreams) { Alert.alert("Konsolidieren", "Kein sinnvolles Roll-up gefunden."); return; }
      const lines = repos.flatMap((r) => (r.streams || []).map((s) => `• ${s.title} (${s.members?.length || 0})`)).join("\n");
      Alert.alert(`${nStreams} Stream-Karten aus ${nCards} Tickets`,
        lines + "\n\nDie Tickets werden reversibel archiviert und in die Stream-Karten gerollt.",
        [{ text: "Abbrechen", style: "cancel" },
         { text: "Anwenden", onPress: async () => {
             try {
               const res = await api.pmConsolidateApply(repos);
               qc.invalidateQueries({ queryKey: ["tracks"] });
               qc.invalidateQueries({ queryKey: ["pmPlan"] });
               Alert.alert("Konsolidiert", `${res.created?.length || 0} Stream-Karten, ${res.archived?.length || 0} Tickets archiviert.`);
             } catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
           } }]);
    } catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
    finally { setProposing(false); }
  }

  const plan = data?.plan;
  const curGoal = data?.goal ?? "";
  const b = plan?.budget;
  const cfg = data?.config;
  const AUTO: { k: "notify" | "ask" | "act"; label: string }[] = [
    { k: "notify", label: "Melden" }, { k: "ask", label: "Fragen" }, { k: "act", label: "Handeln" }];

  const card = { backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 16 } as const;

  return (
    <View style={[card, { padding: 14, gap: 12 }]}>
      {/* header */}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <View style={{ width: 26, height: 26, borderRadius: 8, backgroundColor: t.accent, alignItems: "center", justifyContent: "center" }}>
          <Ionicons name="compass" size={16} color="#fff" />
        </View>
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "700", flex: 1 }}>PM / CTO</Text>
        <Pressable onPress={() => router.push("/chat")} hitSlop={8} style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Ionicons name="chatbubble-ellipses-outline" size={15} color={t.accent} />
          <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>Chat</Text>
        </Pressable>
        <Pressable onPress={() => report.mutate(undefined)} disabled={report.isPending} hitSlop={8}
          style={{ flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: t.surface2, borderRadius: 8, paddingHorizontal: 9, paddingVertical: 5 }}>
          {report.isPending ? <ActivityIndicator size="small" color={t.accent} /> : <Ionicons name="refresh" size={14} color={t.txtSecondary} />}
          <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{report.isPending ? "Plant…" : "Aktualisieren"}</Text>
        </Pressable>
      </View>

      {/* goal */}
      {editGoal ? (
        <View style={{ gap: 8 }}>
          <TextInput value={goal ?? curGoal} onChangeText={setGoal} multiline placeholder="Ziel / MVP-Definition…"
            placeholderTextColor={t.txtPlaceholder}
            style={{ color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 13, minHeight: 60 }} />
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable onPress={() => report.mutate(goal ?? curGoal)} disabled={report.isPending}
              style={{ flex: 1, backgroundColor: t.accent, borderRadius: 8, padding: 10, alignItems: "center" }}>
              <Text style={{ color: "#fff", fontWeight: "600" }}>Ziel setzen &amp; planen</Text>
            </Pressable>
            <Pressable onPress={() => setEditGoal(false)} style={{ backgroundColor: t.surface2, borderRadius: 8, padding: 10, paddingHorizontal: 14, alignItems: "center" }}>
              <Text style={{ color: t.txtSecondary, fontWeight: "600" }}>Abbrechen</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <Pressable onPress={() => { setGoal(curGoal); setEditGoal(true); }}
          style={{ flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: t.surface2, borderRadius: 8, padding: 10 }}>
          <Ionicons name="flag-outline" size={14} color={t.txtTertiary} />
          <Text numberOfLines={2} style={{ color: curGoal ? t.txtSecondary : t.txtTertiary, fontSize: 12.5, flex: 1 }}>
            {curGoal || "Kein Ziel gesetzt — tippen, um das MVP-Ziel zu definieren."}
          </Text>
          <Ionicons name="pencil" size={13} color={t.txtTertiary} />
        </Pressable>
      )}

      {/* proactive control: on/off + escalation ladder (notify/ask/act) */}
      <View style={{ backgroundColor: t.surface2, borderRadius: 10, padding: 10, gap: 10 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Ionicons name="pulse" size={15} color={cfg?.loop_enabled ? t.ok : t.txtTertiary} />
          <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600", flex: 1 }}>Proaktiv arbeiten</Text>
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
          {!cfg?.loop_enabled ? "Aus — der PM plant nur auf Anfrage."
            : cfg?.autonomy === "notify" ? "Melden — plant still, ändert nichts; meldet nur Blocker."
            : cfg?.autonomy === "ask" ? "Fragen — legt Karten an (reversibel), startet nichts ohne dich."
            : "Handeln — legt an & startet im WIP/Quota-Rahmen, während du weg bist. Merge/Accept bleiben bei dir."}
        </Text>
      </View>

      {isLoading && !plan ? <ActivityIndicator color={t.accent} /> : null}

      {plan ? (
        <>
          {/* summary + progress */}
          {plan.summary ? <Text style={{ color: t.txtSecondary, fontSize: 13, lineHeight: 19 }}>{plan.summary}</Text> : null}
          <View style={{ gap: 5 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11 }}>Fortschritt zum Ziel</Text>
              <Text style={{ color: t.txtSecondary, fontSize: 11, fontWeight: "700" }}>{plan.done_pct ?? 0}%</Text>
            </View>
            <View style={{ height: 7, borderRadius: 4, backgroundColor: t.surface2, overflow: "hidden" }}>
              <View style={{ width: `${Math.max(0, Math.min(100, plan.done_pct ?? 0))}%`, height: 7, backgroundColor: t.ok }} />
            </View>
          </View>

          {/* budget / quota */}
          {b ? (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
              <Chip icon="time-outline" label={`ETA ~${b.eta_days ?? "?"} Tage`} t={t} />
              <Chip icon="git-commit-outline" label={`${b.est_turns_to_goal ?? "?"} Turns`} t={t} />
              <Chip icon="speedometer-outline" label={`${b.velocity_turns_per_day ?? "?"}/Tag`} t={t} />
              <Chip icon="cash-outline" label={b.plan === "max" ? `Flat ${cur(b.fixed_monthly_eur)}/Mon` : `${cur(b.cash_to_goal_eur)} bis Ziel`} t={t} />
              {b.plan === "max" ? <Chip icon="flash-outline" label={`Leverage ~${cur(b.shadow_eur_to_goal)}`} t={t} /> : null}
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
                      <Text style={{ color: t.accent2, fontSize: 11, fontWeight: "700" }}>~{m.cumulative_eta_days ?? m.eta_days}d</Text>
                    </View>
                    {m.why ? <Text style={{ color: t.txtTertiary, fontSize: 11.5, marginTop: 2 }}>{m.why}</Text> : null}
                    <Text style={{ color: t.txtTertiary, fontSize: 10.5, marginTop: 3 }}>{m.tasks?.length ?? 0} Tasks · {m.est_turns ?? 0} Turns</Text>
                  </View>
                </View>
              ))}
            </View>
          ) : null}

          {/* next actions -> card */}
          {plan.next?.length ? (
            <View style={{ gap: 8 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", letterSpacing: 0.5 }}>ALS NÄCHSTES</Text>
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
                    <Pressable onPress={() => Alert.alert("Karte anlegen?", n.title, [
                      { text: "Abbrechen", style: "cancel" },
                      { text: "Anlegen", onPress: () => makeCard.mutate(n.title) }])} hitSlop={6}>
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
            <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>{proposing ? "Schlägt vor…" : "Karten konsolidieren"}</Text>
          </Pressable>

          {plan.generated_at ? <Text style={{ color: t.txtTertiary, fontSize: 10, textAlign: "right" }}>Stand: {plan.generated_at}</Text> : null}
        </>
      ) : !isLoading ? (
        <Text style={{ color: t.txtTertiary, fontSize: 12.5 }}>
          Noch kein Plan. Ziel setzen und „Aktualisieren" — der PM erstellt Milestones, Timeline und Prioritäten.
        </Text>
      ) : null}
    </View>
  );
}
