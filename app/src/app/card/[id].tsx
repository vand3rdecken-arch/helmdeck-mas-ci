import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable,
  ScrollView, Text, TextInput, useWindowDimensions, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import EventSource from "react-native-sse";

import { api, type SteerOpts } from "@/data/client";
import { useConfig } from "@/data/config";
import type { Track, Me, EconCard } from "@/data/types";
import { executorLabel, laneColor, statusColor, useTheme } from "@/theme";
import { Chip, Empty, KVRow, Panel, SectionLabel } from "@/ui/kit";
import { cur } from "@/ui/dash_panels";
import { Composer } from "@/ui/card_composer";
import { Transcript, type TStep } from "@/ui/card_transcript";

type Tab = "overview" | "chat";
const isWeb = Platform.OS === "web";

interface Turn { ts?: string; cost?: number; models?: string[];
  usage?: { input_tokens?: number; output_tokens?: number; cache_read_input_tokens?: number; cache_creation_input_tokens?: number } }
interface Ckpt { turn: number; commit: string; ts: string; reply: string }

const SLASH = [
  { name: "plan", hint: "plan before acting", insert: "Make a plan for: " },
  { name: "test", hint: "run tests, report failures", insert: "Run the tests and report any failures." },
  { name: "diff", hint: "summarize current changes", insert: "Summarize the current diff on this branch." },
  { name: "commit", hint: "commit the work", insert: "Commit the current work with a clear message." },
];

// ---- inline field editors -------------------------------------------------

function EditText({ value, onSave, placeholder, multiline, style }: {
  value: string; onSave: (v: string) => void; placeholder?: string; multiline?: boolean; style?: any;
}) {
  const t = useTheme();
  const [v, setV] = useState(value);
  const dirty = useRef(false);
  useEffect(() => { if (!dirty.current) setV(value); }, [value]);
  return (
    <TextInput value={v} multiline={multiline} placeholder={placeholder} placeholderTextColor={t.txtPlaceholder}
      onChangeText={(x) => { dirty.current = true; setV(x); }}
      onBlur={() => { dirty.current = false; if (v.trim() !== value) onSave(v.trim()); }}
      style={[{ color: t.txtPrimary, backgroundColor: t.surface2, borderRadius: 8, borderWidth: 1,
        borderColor: t.borderSubtle, padding: 8, fontSize: 14 }, style]} />
  );
}

function Picker({ label, value, options, onPick }: {
  label: string; value?: string; options: { id: string; label: string }[]; onPick: (id: string) => void;
}) {
  const t = useTheme();
  return (
    <View style={{ gap: 4 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{label}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
        {options.map((o) => {
          const on = (value ?? options[0].id) === o.id;
          return (
            <Pressable key={o.id} onPress={() => onPick(o.id)}
              style={{ backgroundColor: on ? t.accent + "29" : t.surface2, borderColor: on ? t.accent + "80" : t.borderSubtle,
                borderWidth: 1, borderRadius: 6, paddingHorizontal: 10, paddingVertical: 5 }}>
              <Text style={{ color: on ? t.accent : t.txtSecondary, fontSize: 12.5 }}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

// ---- overview / detail column --------------------------------------------

function Overview({ k, edit }: { k: Track; edit: (p: Record<string, unknown>) => void }) {
  const t = useTheme();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const owner = me.data?.role === "owner";
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, enabled: owner });
  const e: EconCard | undefined = metrics?.cards?.find((c) => c.id === k.id);
  const cy = cur(metrics);
  const { data: turns } = useQuery<Turn[]>({ queryKey: ["turns", k.id], queryFn: () => api.turns(k.id) as Promise<Turn[]> });
  const { data: ckpts } = useQuery<Ckpt[]>({
    queryKey: ["ckpts", k.id, owner], queryFn: () => api.get<Ckpt[]>(`/tracks/${k.id}/checkpoints`), enabled: owner });
  const qc = useQueryClient();
  const billing = k.billing ?? "fixed";

  async function rewind(commit: string) {
    const go = async () => {
      try { await api.post(`/tracks/${k.id}/rewind`, { commit }); await qc.invalidateQueries({ queryKey: ["tracks"] }); }
      catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
    };
    Alert.alert("Dateien zurücksetzen?", "Die aktuellen Dateien werden zuerst gesichert (reversibel). Der Verlauf bleibt.",
      [{ text: "Abbrechen", style: "cancel" }, { text: "Restore", onPress: go }]);
  }

  return (
    <View style={{ gap: 10 }}>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
        {k.status ? <Chip text={k.status.replace(/_/g, " ")} dot={statusColor(t, k.status)} /> : null}
        <Chip text={k.lane} dot={laneColor(t, k.lane)} />
        {k.mode ? <Chip text={executorLabel(k.mode)} dot={t.ai} /> : null}
        {k.ai_cost > 0 ? <Chip text={`AI $${k.ai_cost.toFixed(2)}`} /> : null}
      </View>

      <Panel>
        <SectionLabel text="task" />
        <EditText value={k.task} onSave={(v) => v && edit({ task: v })} multiline style={{ fontWeight: "600" }} />
        <View style={{ height: 8 }} />
        <SectionLabel text="description" />
        <EditText value={k.description ?? ""} onSave={(v) => edit({ description: v })} multiline
          placeholder="Kontext, Akzeptanzkriterien, Links… (der Worker liest es)" />
      </Panel>

      <Panel>
        <SectionLabel text="properties" />
        <View style={{ gap: 10 }}>
          <Picker label="Priority" value={k.priority ?? "medium"}
            options={["urgent", "high", "medium", "low"].map((p) => ({ id: p, label: p }))}
            onPick={(p) => edit({ priority: p })} />
          <View style={{ gap: 4 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Due (YYYY-MM-DD)</Text>
            <EditText value={k.due ?? ""} onSave={(v) => edit({ due: v })} placeholder="2026-01-31" />
          </View>
          <Picker label="Billing" value={billing}
            options={[{ id: "fixed", label: "Fixed price" }, { id: "tm", label: "Time & material" }, { id: "none", label: "Internal" }]}
            onPick={(b) => edit({ billing: b })} />
          {billing === "fixed" ? (
            <View style={{ gap: 4 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Price</Text>
              <EditText value={String(k.value ?? "")} onSave={(v) => { const n = parseFloat(v); if (!isNaN(n)) edit({ value: n }); }} placeholder="0" />
            </View>
          ) : null}
          {billing === "tm" ? (
            <View style={{ gap: 4 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Rate /h</Text>
              <EditText value={String(k.rate ?? "")} onSave={(v) => { const n = parseFloat(v); if (!isNaN(n)) edit({ rate: n }); }} placeholder="0" />
            </View>
          ) : null}
          <View style={{ gap: 4 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Client</Text>
            <EditText value={k.client ?? ""} onSave={(v) => edit({ client: v })} placeholder="-" />
          </View>
        </View>
      </Panel>

      {owner && e ? (
        <Panel>
          <SectionLabel text="economics" />
          <KVRow k="Billed" v={`${cy}${(e.billed ?? e.value).toFixed(2)}${e.billing === "tm" ? " ~" : ""}`} />
          <KVRow k="AI cost" v={`$${e.ai_cost.toFixed(2)}`} color={t.ai} />
          <KVRow k="Margin" v={`${cy}${(e.margin ?? ((e.billed ?? e.value) - e.ai_cost)).toFixed(2)}`} color={t.accent} />
          <KVRow k="Touches" v={`${e.touches} touch${e.touches === 1 ? "" : "es"}`} />
          {e.mode ? <KVRow k="Mode" v={e.mode === "auto" ? "auto" : "assisted"} /> : null}
        </Panel>
      ) : null}

      <Panel>
        <SectionLabel text="technical" />
        <KVRow k="Branch" v={k.branch || "—"} />
        <KVRow k="Repo" v={k.repo || "—"} />
        <KVRow k="Session" v={k.session_id ? k.session_id.slice(0, 12) + "…" : "not started"} />
        <KVRow k="Turns" v={`${k.turns}`} />
        <KVRow k="Tokens" v={`${(k.tokens_in ?? 0).toLocaleString()} / ${(k.tokens_out ?? 0).toLocaleString()}`} />
        {k.models?.length ? <KVRow k="Models" v={k.models.join(", ")} /> : null}
      </Panel>

      {turns && turns.length > 0 ? (
        <Panel>
          <SectionLabel text="ai turns" />
          {turns.map((tu, i) => {
            const u = tu.usage ?? {};
            const tin = (u.input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0);
            return (
              <View key={i} style={{ flexDirection: "row", gap: 8, paddingVertical: 2 }}>
                <Text style={{ color: t.txtTertiary, fontSize: 11.5, width: 60 }}>{tu.ts?.slice(5, 16) ?? ""}</Text>
                <Text style={{ color: t.txtSecondary, fontSize: 11.5, width: 90 }} numberOfLines={1}>{(tu.models?.[0] ?? "-").replace("claude-", "")}</Text>
                <Text style={{ color: t.txtSecondary, fontSize: 11.5, flex: 1 }}>{tin.toLocaleString()}/{(u.output_tokens ?? 0).toLocaleString()} · ${(tu.cost ?? 0).toFixed(3)}</Text>
              </View>
            );
          })}
        </Panel>
      ) : null}

      {owner && ckpts && ckpts.length > 0 ? (
        <Panel>
          <SectionLabel text="rewind (files only, reversible)" />
          {ckpts.slice().reverse().map((c, i) => (
            <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11.5, width: 92 }}>turn {c.turn} · {c.ts?.slice(11, 16)}</Text>
              <Text style={{ color: t.txtSecondary, fontSize: 12, flex: 1 }} numberOfLines={1}>{c.reply}</Text>
              <Pressable onPress={() => rewind(c.commit)} hitSlop={6}
                style={{ flexDirection: "row", alignItems: "center", gap: 4, borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 }}>
                <Ionicons name="arrow-undo-outline" size={12} color={t.txtSecondary} />
                <Text style={{ color: t.txtSecondary, fontSize: 11.5 }}>restore</Text>
              </Pressable>
            </View>
          ))}
        </Panel>
      ) : null}
    </View>
  );
}

// ---- chat column ----------------------------------------------------------

function Chat({ k, feed, onSend, onStop, models, modeOptions, seed, setSeed, bottomInset }: {
  k: Track; feed: TStep[]; onSend: (text: string, o: SteerOpts) => Promise<void>; onStop: () => void;
  models: string[]; modeOptions: { id: string; label: string }[];
  seed: { text: string; key: number }; setSeed: (s: { text: string; key: number }) => void; bottomInset: number;
}) {
  const t = useTheme();
  const qc = useQueryClient();
  const running = k.status === "running";
  // card chat mode: "worker" steers the card's own worker (default), "agent" talks
  // to the free board copilot about this card (it can move/delete/archive/steer).
  const [agentMode, setAgentMode] = useState(false);
  // optimistic echo: your just-sent worker message shows instantly, before the
  // session transcript catches up. Reconciled away once the real feed carries it.
  const [pending, setPending] = useState<TStep[]>([]);
  // the free-agent (copilot) conversation about this card
  const [agentMsgs, setAgentMsgs] = useState<TStep[]>([]);
  const scrollRef = useRef<ScrollView>(null);
  const [atBottom, setAtBottom] = useState(true);

  // drop an optimistic echo once the real feed carries that same user text
  useEffect(() => {
    if (!pending.length) return;
    const seen = new Set<string>(feed.filter((s) => s.role === "user").map((s) => (s.text ?? "").trim()));
    setPending((p) => p.filter((e) => !seen.has((e.text ?? "").trim())));
  }, [feed]);   // eslint-disable-line react-hooks/exhaustive-deps

  // the rendered feed = server story + optimistic echoes + copilot conversation
  const steps = useMemo<TStep[]>(() => [...feed, ...pending, ...agentMsgs], [feed, pending, agentMsgs]);

  // auto-pin to newest — but only when the reader is already near the bottom, so
  // scrolling up to read isn't yanked back down.
  useEffect(() => {
    if (atBottom) scrollRef.current?.scrollToEnd({ animated: true });
  }, [steps.length, atBottom]);
  const onScroll = (e: { nativeEvent: { contentOffset: { y: number }; contentSize: { height: number }; layoutMeasurement: { height: number } } }) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    setAtBottom(contentSize.height - contentOffset.y - layoutMeasurement.height < 60);
  };

  const hhmm = () => new Date().toTimeString().slice(0, 5);
  async function handleSend(text: string, o: SteerOpts) {
    if (agentMode) {
      setAgentMsgs((m) => [...m, { role: "user", kind: "text", text, ts: hhmm() }]);
      try {
        const r = await api.chat(text, { ...o, card: k.id });
        setAgentMsgs((m) => [...m, { role: "assistant", kind: "text", text: r.reply || r.error || "(keine Antwort)", ts: hhmm() }]);
      } catch {
        setAgentMsgs((m) => [...m, { role: "assistant", kind: "text", text: "(Agent-Senden fehlgeschlagen)", ts: hhmm() }]);
      }
      // the board agent may have moved/deleted/archived cards — refresh the board
      await qc.invalidateQueries({ queryKey: ["tracks"] });
      return;
    }
    // worker: echo instantly, then steer; retract the echo if the send throws
    const echo: TStep = { role: "user", kind: "text", text, ts: hhmm() };
    setPending((p) => [...p, echo]);
    try { await onSend(text, o); }
    catch { setPending((p) => p.filter((e) => e !== echo)); }
  }

  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
      <View style={{ flex: 1 }}>
        <ScrollView ref={scrollRef} onScroll={onScroll} scrollEventThrottle={64}
          contentContainerStyle={{ padding: 12, paddingBottom: 20 }}>
          {steps.length === 0 ? <Empty text="Noch keine Nachrichten." /> :
            <Transcript steps={steps} onRewind={(txt) => setSeed({ text: txt, key: seed.key + 1 })} />}
        </ScrollView>
        {!atBottom ? (
          <Pressable onPress={() => { scrollRef.current?.scrollToEnd({ animated: true }); setAtBottom(true); }}
            style={{ position: "absolute", right: 14, bottom: 12, flexDirection: "row", alignItems: "center", gap: 4,
              backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 16,
              paddingHorizontal: 12, paddingVertical: 7 }}>
            <Ionicons name="arrow-down" size={14} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>Neueste</Text>
          </Pressable>
        ) : null}
      </View>

      {/* card chat mode toggle: steer the worker, or talk to the board copilot */}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingTop: 8 }}>
        {([["worker", "Worker"], ["agent", "Agent"]] as const).map(([id, label]) => {
          const on = (id === "agent") === agentMode;
          return (
            <Pressable key={id} onPress={() => setAgentMode(id === "agent")}
              style={{ backgroundColor: on ? t.accent + "26" : t.surface2, borderColor: on ? t.accent + "80" : t.borderSubtle,
                borderWidth: 1, borderRadius: 7, paddingHorizontal: 10, paddingVertical: 5 }}>
              <Text style={{ color: on ? t.accent : t.txtSecondary, fontSize: 12 }}>{label}</Text>
            </Pressable>
          );
        })}
        <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 11, flex: 1 }}>
          {agentMode ? "freier Board-Agent — verschieben/löschen/alles (berechtigt)"
            : (k.session_id ? "steuert den Worker — Kontext läuft weiter" : "steuert den Worker — noch nicht gestartet")}
        </Text>
      </View>

      <Composer onSend={handleSend} busy={running && !agentMode} onStop={onStop} models={models} modeOptions={modeOptions}
        slashCommands={SLASH} seed={seed} bottomInset={bottomInset} draftKey={`card:${k.id}`}
        placeholder={agentMode ? "Sag dem Agenten was zu tun ist — z.B. 'verschiebe diese Karte nach done'"
          : k.session_id ? "Worker steuern – Kontext läuft weiter" : "Worker starten…"} />
    </KeyboardAvoidingView>
  );
}

// ---- screen ---------------------------------------------------------------

export default function CardScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;
  const [tab, setTab] = useState<Tab>("overview");
  const [seed, setSeed] = useState({ text: "", key: 0 });

  const relay = useConfig((s) => s.relayMode());
  const baseUrl = useConfig((s) => s.baseUrl);
  const token = useConfig((s) => s.token);

  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks });
  const k: Track | undefined = tracks?.find((x) => x.id === id);
  const running = k?.status === "running";

  // Live transcript. Direct transport → subscribe to the card SSE stream so the
  // feed grows in real time. Relay mode (SSE can't tunnel) keeps the 3s poll.
  const sseActive = !!running && !relay && !!baseUrl && !!k?.session_id;
  const { data: transcript } = useQuery<TStep[]>({
    queryKey: ["transcript", id], queryFn: () => api.transcript(id!) as Promise<TStep[]>,
    enabled: !!id, refetchInterval: running && (relay || !sseActive) ? 3000 : false });
  const { data: hist } = useQuery({ queryKey: ["history", id], queryFn: () => api.history(id!), enabled: !!id });
  const { data: models } = useQuery({ queryKey: ["models"], queryFn: api.models, staleTime: 300000 });
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });

  useEffect(() => {
    if (!sseActive || !id) return;
    const es = new EventSource(`${baseUrl}/tracks/${id}/stream`,
      { headers: token ? { Authorization: `Bearer ${token}` } : undefined, pollingInterval: 0 });
    const pull = () => { qc.invalidateQueries({ queryKey: ["transcript", id] }); };
    es.addEventListener("message", pull);
    return () => { es.removeAllEventListeners(); es.close(); };
  }, [sseActive, id, baseUrl, token, qc]);

  // Weave the actionlog lifecycle 'note' rows into the transcript by timestamp
  // (ported from peek.tsx). Falls back to the steer/reply history until a
  // session transcript exists.
  const feed = useMemo<TStep[]>(() => {
    const trans = (transcript ?? []) as TStep[];
    const rows = (hist ?? []) as TStep[];
    if (!trans.length) {
      return rows.filter((r) => (r.text || (r as any).detail || r.result))
        .map((r) => r.kind === "steer"
          ? { role: "user", kind: "text", text: (r as any).detail, ts: r.ts }
          : r.kind === "reply"
          ? { role: "assistant", kind: "text", text: (r as any).detail, ts: r.ts }
          : { kind: "system", text: (r as any).detail ?? r.text, ts: r.ts });
    }
    const notes: TStep[] = rows.filter((r) => r.kind === "note" && ((r as any).detail ?? "").trim())
      .map((r) => ({ kind: "system", text: (r as any).detail, ts: r.ts }));
    if (!notes.length) return trans;
    let last = "";
    const T = trans.map((s) => { if (s.ts) last = s.ts; return { s, ts: s.ts || last }; });
    const out: TStep[] = []; let i = 0, j = 0;
    while (i < T.length && j < notes.length) {
      if ((notes[j].ts ?? "") && (notes[j].ts ?? "") < T[i].ts) out.push(notes[j++]);
      else out.push(T[i++].s);
    }
    while (i < T.length) out.push(T[i++].s);
    while (j < notes.length) out.push(notes[j++]);
    return out;
  }, [transcript, hist]);

  async function edit(patch: Record<string, unknown>) {
    if (!id) return;
    try { await api.update(id, patch); await qc.invalidateQueries({ queryKey: ["tracks"] }); }
    catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
  }

  async function send(text: string, o: SteerOpts) {
    if (!id) return;
    try {
      await api.steer(id, text, o);
      await qc.invalidateQueries({ queryKey: ["transcript", id] });
      await qc.invalidateQueries({ queryKey: ["tracks"] });
    } catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
  }

  async function stop() {
    if (!id) return;
    try { await api.cancel(id); await qc.invalidateQueries({ queryKey: ["tracks"] }); }
    catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
  }

  function menu() {
    if (!k) return;
    Alert.alert(k.task, undefined, [
      { text: "Fork", onPress: () => api.fork(k.id) },
      { text: "Archivieren", onPress: () => api.archive(k.id).then(() => router.back()) },
      { text: "Löschen", style: "destructive", onPress: () => api.del(k.id).then(() => router.back()) },
      { text: "Abbrechen", style: "cancel" },
    ]);
  }

  // permission modes — bypass ("Full") is owner-only; current perm first
  const modeBase = [{ id: "acceptEdits", label: "Edit" }, { id: "plan", label: "Plan" },
    ...(me?.role === "owner" ? [{ id: "bypassPermissions", label: "Full" }] : [])];
  const modeOptions = k
    ? [...modeBase.filter((m) => m.id === k.perm), ...modeBase.filter((m) => m.id !== k.perm)]
    : modeBase;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 8, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600", flex: 1 }} numberOfLines={1}>{k?.task ?? "Karte"}</Text>
        {running ? <ActivityIndicator size="small" color={t.ai} /> : null}
        <Pressable onPress={menu} hitSlop={10}><Ionicons name="ellipsis-horizontal" size={22} color={t.txtSecondary} /></Pressable>
      </View>

      {!k ? <ActivityIndicator color={t.accent} style={{ marginTop: 30 }} /> : wide ? (
        // desktop: two columns — detail left, live chat right
        <View style={{ flex: 1, flexDirection: "row" }}>
          <ScrollView style={{ flex: 1, borderRightWidth: 1, borderRightColor: t.glassBorder }}
            contentContainerStyle={{ padding: 16, paddingBottom: 40, maxWidth: 620, width: "100%", alignSelf: "center" }}>
            <Overview k={k} edit={edit} />
          </ScrollView>
          <View style={{ flex: 1.2 }}>
            <Chat k={k} feed={feed} onSend={send} onStop={stop} models={models ?? []} modeOptions={modeOptions}
              seed={seed} setSeed={setSeed} bottomInset={insets.bottom} />
          </View>
        </View>
      ) : (
        <>
          <View style={{ flexDirection: "row", borderBottomWidth: 1, borderBottomColor: t.glassBorder }}>
            {(["overview", "chat"] as Tab[]).map((x) => (
              <Pressable key={x} onPress={() => setTab(x)} style={{ flex: 1, paddingVertical: 10, alignItems: "center",
                borderBottomWidth: 2, borderBottomColor: tab === x ? t.accent : "transparent" }}>
                <Text style={{ color: tab === x ? t.accent : t.txtTertiary, fontWeight: "600" }}>
                  {x === "overview" ? "Overview" : `Chat${k.turns ? ` (${k.turns}t)` : ""}`}
                </Text>
              </Pressable>
            ))}
          </View>
          {tab === "overview" ? (
            <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 40 }}>
              <Overview k={k} edit={edit} />
            </ScrollView>
          ) : (
            <Chat k={k} feed={feed} onSend={send} onStop={stop} models={models ?? []} modeOptions={modeOptions}
              seed={seed} setSeed={setSeed} bottomInset={insets.bottom + 8} />
          )}
        </>
      )}
    </View>
  );
}
