import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useModels } from "@/data/use_models";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";
import { Caption, ChipPick, fieldStyle } from "@/ui/settings_sections";
import { useResponsive } from "@/ui/responsive";

// Shape of one entry from claude_sessions.list_sessions (daemon/claude_sessions.py).
type ClaudeSession = {
  id: string; cwd: string; project: string; first: string; last_active: string;
  /** set by the daemon (claude_sessions.list_sessions) when this session is
   *  already bound to a card - continuing it would only bounce at submit. */
  card?: string;
};

// Ported from archive/web/components/modal.tsx (EXAMPLES). Tapping a chip seeds
// the task text and, where the web example set one, the driver. Both the chip
// label and the seeded prose are owner-facing, so both live in the dict; the
// driver id is technical and stays as-is.
const EXAMPLES = [
  { key: "bugfix", driver: "claude" },
  { key: "feature", driver: "claude" },
  { key: "desktop", driver: "claude-desktop" },
  { key: "browser", driver: "claude-desktop" },
  { key: "research", driver: "claude" },
] as const;

// urgent was missing here (the card edit picker had it) - a card could not be
// filed as "dringend". Order + labels match the edit picker; localized via prio.*
const PRIORITIES = ["urgent", "high", "medium", "low"] as const;

export default function NewCard() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const [task, setTask] = useState("");
  const [repo, setRepo] = useState(metrics?.settings?.default_repo ?? "");
  const [priority, setPriority] = useState<string>("medium");
  const [due, setDue] = useState("");
  const [value, setValue] = useState("");
  const [client, setClient] = useState("");
  const [driver, setDriver] = useState("");
  // "auto" here means "send no model at all" - the card then re-routes live
  // every turn off its own signals (turnrunner._turn), same as today's
  // default. Only an explicit pick becomes the card's STICKY model (stored
  // once at creation, cells/engineer/dispatch.py:new_track) - without
  // this field cards could only ever get a sticky model via a chat steer,
  // and that pick used to not even persist onto the card (see steer() fix).
  const [model, setModel] = useState("auto");
  const { data: modelList } = useModels();
  const [busy, setBusy] = useState(false);
  // Inline error: Alert.alert is a NO-OP on react-native-web (desktop), so a
  // rejected create/adopt used to fail completely silently - the owner clicked
  // and nothing visible happened ("stucked here"). Show it in the form instead.
  const [err, setErr] = useState("");
  // Adopt-an-existing-Claude-session flow (ported from archive/web modal). The
  // list is only fetched once the section is opened; picking a session flips the
  // submit action from "create card" to "continue session".
  const [showSess, setShowSess] = useState(false);
  const [adoptId, setAdoptId] = useState<string | null>(null);
  const [adoptCwd, setAdoptCwd] = useState("");
  // Set when the picked session is ALREADY bound to a card (s.card, from the
  // daemon's track-derived annotation). Picking one used to just link away to
  // that card - a dead end for "ich will hier weiterarbeiten". The logical
  // action is the same fork_conversation the card menu offers: split the
  // existing conversation into THIS new card, source untouched.
  const [adoptCard, setAdoptCard] = useState<string | null>(null);
  const { data: sessions, isLoading: sessLoading } = useQuery<ClaudeSession[]>({
    queryKey: ["claude-sessions"], queryFn: api.claudeSessions, enabled: showSess,
  });

  const field = fieldStyle(t);
  const { wide } = useResponsive();
  // Engines come from GET /engines (spine/agent/engines.py), the Paseo
  // provider-snapshot shape: every driver a card may carry, each CLI probed
  // live. Used to be the KEYS of settings.drivers - which only ever named
  // claude and claude-desktop, so an installed Codex/OMP/OpenCode never
  // showed up here and the daemon refused it as unknown. A missing CLI stays
  // visible but disabled with the reason; an unverified driver says so.
  const { data: engineData, refetch: refetchEngines, isFetching: enginesFetching } =
    useQuery({ queryKey: ["engines"], queryFn: () => api.engines(), staleTime: 60_000 });
  // switched-off engines stay out of the picker (they are refused at filing
  // anyway); they are managed in Settings > Agents & autonomy
  const engines = (engineData?.engines ?? []).filter((e) => e.enabled);
  const drivers = engines.map((e) => e.id);
  const engineOf = (id: string) => engines.find((e) => e.id === id);
  // Default = the first READY engine (claude on any box that got past
  // onboarding). Only fills an empty pick, never overrides a user's choice.
  useEffect(() => {
    if (driver || engines.length === 0) return;
    const first = engines.find((e) => e.status === "ready");
    if (first) setDriver(first.id);
  }, [engines, driver]);

  // Close the form DETERMINISTICALLY on success. router.back() is a no-op when
  // /new was reached without back-history (common on desktop), which left the
  // card created but the form still open - the owner saw "nothing happened" and
  // clicked again, filing duplicates. Navigate to a concrete destination
  // instead: the adopted/created card, or the board.
  function done(dest: string) {
    void qc.invalidateQueries({ queryKey: ["tracks"] });
    router.replace(dest as never);
  }

  async function file() {
    setBusy(true);
    setErr("");
    try {
      // A session already bound to a card -> fork ITS CONVERSATION into a new
      // card (sessions.fork_conversation) instead of adopting: adopting would
      // just bounce with "session already on the board", and forking is the
      // logical move anyway - a fresh card that keeps the context but grows
      // independently, exactly what picking an in-progress conversation means.
      if (adoptCard) {
        const res = await api.forkChat(adoptCard, task.trim());
        if (res?.error) { setErr(res.error); return; }
        done(res?.id ? `/card/${res.id}` : "/");
        return;
      }
      // An UNBOUND session -> adopt it as a card (mode "continue"), with any
      // typed text carried as the first steer. Same one button either way.
      if (adoptId) {
        const res = await api.adoptClaude({
          session_id: adoptId, cwd: adoptCwd, mode: "continue", first: task.trim(),
        });
        if (res?.error) { setErr(res.error); return; }
        done(res?.id ? `/card/${res.id}` : "/");
        return;
      }
      if (!task.trim()) { setErr(tr("new.taskRequired")); return; }
      const body: Record<string, unknown> = {
        task: task.trim(), repo: repo.trim(), lane: "backlog", priority,
      };
      if (due.trim()) body.due = due.trim();
      if (value.trim()) body.value = parseFloat(value);
      if (client.trim()) body.client = client.trim();
      if (driver.trim()) body.driver = driver.trim();
      if (model && model !== "auto") body.model = model;
      // The daemon can reject with a 200-body {error} (bad repo, WIP limit…),
      // so inspect it rather than assuming success.
      const res = await api.newTrack(body) as { error?: string };
      if (res?.error) { setErr(res.error); return; }
      done("/");
    } catch (e) { setErr(String((e as Error).message)); }
    finally { setBusy(false); }
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <Text style={{ color: t.txtPrimary, fontSize: 20, fontWeight: "700", padding: 16 }}>{tr("new.title")}</Text>
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10, width: "100%", maxWidth: wide ? 560 : undefined, alignSelf: "center" }}>
        <Panel>
          <Caption text={tr("new.examples")} />
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
            {EXAMPLES.map((ex) => (
              <Pressable key={ex.key} onPress={() => { setTask(tr(`new.ex.${ex.key}Task`)); setDriver(ex.driver); }}
                style={{ backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1,
                  borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 }}>
                <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "500" }}>{tr(`new.ex.${ex.key}`)}</Text>
              </Pressable>
            ))}
          </View>
          <Pressable onPress={() => setShowSess((v) => !v)}
            style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: showSess ? 8 : 4 }}>
            <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{showSess ? "▾" : "▸"}</Text>
            <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "500" }}>{tr("new.adoptSession")}</Text>
          </Pressable>
          {showSess && (
            <View style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 10, marginBottom: 10, overflow: "hidden" }}>
              {sessLoading && <Text style={{ color: t.txtTertiary, fontSize: 12, padding: 10 }}>{tr("new.readingSessions")}</Text>}
              {!sessLoading && (sessions?.length ?? 0) === 0 && (
                <Text style={{ color: t.txtTertiary, fontSize: 12, padding: 10 }}>{tr("new.noSessions")}</Text>
              )}
              {sessions?.map((s) => {
                // Already bound to a card (daemon-derived from the track store):
                // selecting it FORKS that card's conversation into this new one
                // (adoptCard, handled in file()) instead of adopting - adopting
                // would just bounce with "session already on the board", and a
                // fork is what picking an in-progress conversation actually
                // means. Still one uniform tap-to-select row, not a dead-end
                // link; a small badge says what will happen.
                const sel = s.card ? s.id === adoptCard : s.id === adoptId;
                return (
                  <Pressable key={s.id}
                    onPress={() => {
                      if (s.card) {
                        setAdoptCard(sel ? null : s.card);
                        setAdoptId(null); setAdoptCwd("");
                      } else {
                        setAdoptId(sel ? null : s.id); setAdoptCwd(sel ? "" : s.cwd);
                        setAdoptCard(null);
                      }
                    }}
                    style={{ padding: 10, borderBottomWidth: 1, borderBottomColor: t.glassBorder,
                      borderLeftWidth: 2, borderLeftColor: sel ? t.accent : "transparent",
                      backgroundColor: sel ? t.surface2 : "transparent" }}>
                    <View style={{ flexDirection: "row", gap: 8, alignItems: "baseline" }}>
                      <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "600" }} numberOfLines={1}>{s.project || tr("new.session")}</Text>
                      <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{s.last_active}</Text>
                      {s.card ? (
                        <>
                          <View style={{ flex: 1 }} />
                          <Text style={{ color: t.accent, fontSize: 10.5, fontWeight: "600" }}>{tr("new.willFork")}</Text>
                        </>
                      ) : null}
                    </View>
                    <Text style={{ color: t.txtSecondary, fontSize: 11.5 }} numberOfLines={1}>{s.first || tr("new.noText")}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
          <SectionLabel text={tr((adoptId || adoptCard) ? "new.firstInstruction" : "new.taskLabel")} />
          <TextInput value={task} onChangeText={setTask} multiline placeholder={tr("new.taskPlaceholder")}
            placeholderTextColor={t.txtPlaceholder} style={[field, { minHeight: 90 }]} />
          <View style={{ height: 10 }} />
          <SectionLabel text={tr("new.repo")} />
          <TextInput value={repo} onChangeText={setRepo} autoCapitalize="none" placeholder={tr("new.repoPlaceholder")}
            placeholderTextColor={t.txtPlaceholder} style={field} />
        </Panel>
        <Panel>
          <Caption text={tr("new.priority")} />
          <View style={{ marginBottom: 10 }}>
            <ChipPick options={PRIORITIES} selected={[priority]} onToggle={setPriority} single
              labelFor={(p) => tr(`prio.${p}`)} />
          </View>
          <Caption text={tr("new.due")} />
          <TextInput value={due} onChangeText={setDue} autoCapitalize="none" placeholder="2026-07-31"
            placeholderTextColor={t.txtPlaceholder} style={field} />
          <View style={{ height: 10 }} />
          <View style={{ flexDirection: "row", gap: 10 }}>
            <View style={{ flex: 1 }}>
              <Caption text={tr("new.value")} />
              <TextInput value={value} onChangeText={setValue} keyboardType="numeric" placeholder="50"
                placeholderTextColor={t.txtPlaceholder} style={field} />
            </View>
            <View style={{ flex: 1 }}>
              <Caption text={tr("new.client")} />
              <TextInput value={client} onChangeText={setClient} placeholder={tr("new.clientPlaceholder")}
                placeholderTextColor={t.txtPlaceholder} style={field} />
            </View>
          </View>
          <View style={{ height: 10 }} />
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <Caption text={tr("new.driver")} />
            {drivers.length > 0 ? (
              <Pressable onPress={() => { void refetchEngines(); }} disabled={enginesFetching} hitSlop={8}>
                <Text style={{ color: t.accent, fontSize: 11.5, opacity: enginesFetching ? 0.5 : 1 }}>
                  {tr("new.engineRefresh")}
                </Text>
              </Pressable>
            ) : null}
          </View>
          {drivers.length > 0 ? (
            <ChipPick options={drivers} selected={[driver]} onToggle={setDriver} single
              labelFor={(id) => engineOf(id)?.label ?? id}
              disabledFor={(id) => engineOf(id)?.status !== "ready"}
              hintFor={(id) => {
                const e = engineOf(id);
                if (!e) return undefined;
                if (e.status !== "ready") return tr("new.engineMissing");
                // `claude --version` answers "2.1.268 (Claude Code)" - the label
                // already says that, so the hint keeps only the number
                return e.verified ? (e.version.replace(/\s*\(.*\)\s*$/, "") || undefined) : tr("new.engineUntested");
              }} />
          ) : (
            <TextInput value={driver} onChangeText={setDriver} autoCapitalize="none" placeholder="claude"
              placeholderTextColor={t.txtPlaceholder} style={field} />
          )}
          <View style={{ height: 10 }} />
          <Caption text={tr("new.model")} />
          <ChipPick options={["auto", ...(modelList ?? []).map((m) => (typeof m === "string" ? m : m.id))]}
            selected={[model]} onToggle={setModel} single
            labelFor={(id) => id === "auto" ? tr("composer.modelAutoShort") : id.replace("claude-", "").replace(/-\d{8}$/, "")} />
        </Panel>
        {err ? (
          <View style={{ backgroundColor: t.danger + "1A", borderColor: t.danger + "66", borderWidth: 1,
            borderRadius: 8, padding: 10 }}>
            <Text style={{ color: t.danger, fontSize: 12.5 }}>{err}</Text>
          </View>
        ) : null}
        <View style={{ flexDirection: "row", gap: 10 }}>
          <Pressable onPress={() => router.back()} style={{ flex: 1, borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, padding: 12, alignItems: "center" }}>
            <Text style={{ color: t.txtSecondary }}>{tr("ui.cancel")}</Text>
          </Pressable>
          <Pressable onPress={file} disabled={busy || (!adoptId && !adoptCard && !task.trim())}
            style={{ flex: 1, backgroundColor: t.accent, borderRadius: 8, padding: 12, alignItems: "center",
              opacity: busy || (!adoptId && !adoptCard && !task.trim()) ? 0.5 : 1 }}>
            <Text style={{ color: "#fff", fontWeight: "600" }}>{tr(adoptCard ? "card.menu.forkChat" : adoptId ? "new.adopt" : "ui.create")}</Text>
          </Pressable>
        </View>
      </ScrollView>
    </View>
  );
}
