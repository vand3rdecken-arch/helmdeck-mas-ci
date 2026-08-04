import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Keyboard, Platform, Pressable,
  ScrollView, Text, TextInput, useWindowDimensions, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type SteerOpts } from "@/data/client";
import type { Track, Me, EconCard } from "@/data/types";
import { executorLabel, laneColor, statusColor, useTheme } from "@/theme";
import { Chip, Empty, KVRow, Panel, SectionLabel } from "@/ui/kit";
import { cur } from "@/ui/dash_panels";
import { Composer } from "@/ui/card_composer";
import { Transcript, type TStep } from "@/ui/card_transcript";
import { useActionSheet } from "@/ui/action_sheet";

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

function EditText({ value, onSave, placeholder, multiline, style, autoFocus, onDone }: {
  value: string; onSave: (v: string) => void; placeholder?: string; multiline?: boolean;
  style?: any; autoFocus?: boolean; onDone?: () => void;
}) {
  const t = useTheme();
  const [v, setV] = useState(value);
  const dirty = useRef(false);
  useEffect(() => { if (!dirty.current) setV(value); }, [value]);
  return (
    <TextInput value={v} multiline={multiline} placeholder={placeholder} placeholderTextColor={t.txtPlaceholder}
      autoFocus={autoFocus}
      onChangeText={(x) => { dirty.current = true; setV(x); }}
      onBlur={() => { dirty.current = false; if (v.trim() !== value) onSave(v.trim()); onDone?.(); }}
      style={[{ color: t.txtPrimary, backgroundColor: t.surface2, borderRadius: 8, borderWidth: 1,
        borderColor: t.borderSubtle, padding: 8, fontSize: 14 }, style]} />
  );
}

/** The card body, READABLE. The PM writes a structured work package
 *  (NUTZERGESCHICHTE / FERTIG, WENN / WARUM JETZT / ENTHÄLT); a multiline
 *  TextInput renders as a ~2-row textarea on web that never grows, so the
 *  acceptance criteria and steps were clipped mid-line and effectively
 *  invisible - the exact opposite of the point. Show the whole thing with the
 *  ALL-CAPS section heads lifted out, and swap to the editor on tap.
 *  Formatting happens HERE, not in the stored text, so the board's two-line
 *  preview and the agent's prompt stay clean (no markdown syntax to leak). */
function DescriptionField({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const t = useTheme();
  const [editing, setEditing] = useState(false);
  const text = value ?? "";

  if (editing || !text.trim()) {
    return (
      <EditText value={text} onSave={onSave} multiline autoFocus={editing}
        onDone={() => setEditing(false)}
        placeholder="Kontext, Akzeptanzkriterien, Links… (der Worker liest es)"
        style={{ minHeight: 200, textAlignVertical: "top", lineHeight: 20 }} />
    );
  }
  const isHead = (l: string) => {
    const s = l.trim();
    return s.length > 2 && s.length <= 40 && s === s.toUpperCase() && /[A-ZÄÖÜ]/.test(s);
  };
  return (
    <Pressable onPress={() => setEditing(true)} accessibilityLabel="Beschreibung bearbeiten"
      style={{ backgroundColor: t.surface2, borderRadius: 8, borderWidth: 1,
        borderColor: t.borderSubtle, padding: 10, gap: 2 }}>
      {text.split("\n").map((line, i) => {
        const s = line.trim();
        if (!s) return <View key={i} style={{ height: 8 }} />;
        if (isHead(line)) {
          return (
            <Text key={i} style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700",
              letterSpacing: 0.6, marginTop: i ? 6 : 0 }}>{s}</Text>
          );
        }
        if (s.startsWith("- ")) {
          return (
            <View key={i} style={{ flexDirection: "row", gap: 6 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 14, lineHeight: 20 }}>•</Text>
              <Text style={{ color: t.txtPrimary, fontSize: 14, lineHeight: 20, flex: 1 }}>{s.slice(2)}</Text>
            </View>
          );
        }
        return <Text key={i} style={{ color: t.txtPrimary, fontSize: 14, lineHeight: 20 }}>{s}</Text>;
      })}
    </Pressable>
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

/** What is actually attached to this card. The agent reads these files off disk
 *  (the daemon appends their paths to its prompt), so the owner needs to see
 *  what it was handed - otherwise an attachment is a black hole after sending.
 *  Silent when the card has none, so it costs nothing on a normal card. */
function AttachmentList({ id }: { id: string }) {
  const t = useTheme();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["attachments", id], queryFn: () => api.attachments(id) });
  const files = data ?? [];
  if (!files.length) return null;
  const kb = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
  return (
    <>
      <View style={{ height: 8 }} />
      <SectionLabel text="anhänge" />
      <View style={{ gap: 6 }}>
        {files.map((f) => (
          <View key={f.name} style={{ flexDirection: "row", alignItems: "center", gap: 8,
            backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1,
            borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8 }}>
            <Ionicons name={/\.(png|jpe?g|gif|webp)$/i.test(f.name) ? "image-outline" : "document-outline"}
              size={15} color={t.txtTertiary} />
            {/* the daemon prefixes saved files with their index (save_attachments
                writes "%d_%s"); show the name the owner recognises, but keep
                f.name for the remove call - that is the on-disk basename. */}
            <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 13, flex: 1 }}>
              {f.name.replace(/^\d+_/, "")}
            </Text>
            <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{kb(f.size)}</Text>
            <Pressable hitSlop={8} accessibilityLabel={`${f.name} entfernen`}
              onPress={() => api.removeAttachment(id, f.name)
                .then(() => qc.invalidateQueries({ queryKey: ["attachments", id] }))
                .catch((e) => Alert.alert("Anhang", String((e as Error).message)))}>
              <Ionicons name="close-circle" size={17} color={t.txtTertiary} />
            </Pressable>
          </View>
        ))}
      </View>
    </>
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
        <DescriptionField value={k.description ?? ""} onSave={(v) => edit({ description: v })} />
        <AttachmentList id={k.id} />
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
  models: (string | { id: string; label?: string; desc?: string })[]; modeOptions: { id: string; label: string }[];
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
  // edge-to-edge (SDK 57) breaks Android adjustResize -> lift the composer above
  // the keyboard by measuring its height (same fix as the board chat).
  const [kb, setKb] = useState(0);
  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", (e) => setKb(e.endCoordinates.height));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(0));
    return () => { show.remove(); hide.remove(); };
  }, []);

  // drop an optimistic echo once the real feed carries that same user text
  useEffect(() => {
    if (!pending.length) return;
    const seen = new Set<string>(feed.filter((s) => s.role === "user").map((s) => (s.text ?? "").trim()));
    setPending((p) => p.filter((e) => !seen.has((e.text ?? "").trim())));
  }, [feed]);   // eslint-disable-line react-hooks/exhaustive-deps

  // the rendered feed = the worker story + optimistic echoes, then (clearly
  // separated) the board-Agent conversation. A divider makes the Worker/Agent
  // boundary unmistakable instead of the two streams blurring together.
  const steps = useMemo<TStep[]>(() => [
    ...feed, ...pending,
    ...(agentMsgs.length ? [{ kind: "agentbreak", ts: "" } as TStep, ...agentMsgs] : []),
  ], [feed, pending, agentMsgs]);

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
      setAgentMsgs((m) => [...m, { role: "user", kind: "text", text, ts: hhmm(), agent: true }]);
      try {
        const r = await api.chat(text, { ...o, card: k.id });
        setAgentMsgs((m) => [...m, { role: "assistant", kind: "text", text: r.reply || r.error || "(keine Antwort)", ts: hhmm(), agent: true }]);
      } catch {
        setAgentMsgs((m) => [...m, { role: "assistant", kind: "text", text: "(Agent-Senden fehlgeschlagen)", ts: hhmm(), agent: true }]);
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
    <View style={{ flex: 1, paddingBottom: kb }}>
      <View style={{ flex: 1 }}>
        <ScrollView ref={scrollRef} onScroll={onScroll} scrollEventThrottle={64} style={{ flex: 1 }}
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

      {/* mode switch: steer the card's Worker, or talk to the board Agent. One
          segmented control (not two loose buttons) so the active target is
          unmistakable; Agent is violet, Worker is accent, matching the chat. */}
      <View style={{ paddingHorizontal: 12, paddingTop: 8, gap: 6 }}>
        <View style={{ flexDirection: "row", backgroundColor: t.surface2, borderRadius: 9, borderWidth: 1, borderColor: t.borderSubtle, padding: 2 }}>
          {([["worker", "Worker", "construct-outline"], ["agent", "Agent", "sparkles-outline"]] as const).map(([id, label, icon]) => {
            const on = (id === "agent") === agentMode;
            const col = id === "agent" ? t.accent2 : t.accent;
            return (
              <Pressable key={id} onPress={() => setAgentMode(id === "agent")}
                style={{ flex: 1, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 5,
                  backgroundColor: on ? col + "22" : "transparent", borderRadius: 7, paddingVertical: 7 }}>
                <Ionicons name={icon} size={14} color={on ? col : t.txtTertiary} />
                <Text style={{ color: on ? col : t.txtSecondary, fontSize: 12.5, fontWeight: on ? "700" : "500" }}>{label}</Text>
              </Pressable>
            );
          })}
        </View>
        <Text numberOfLines={1} style={{ color: agentMode ? t.accent2 : t.txtTertiary, fontSize: 11 }}>
          {agentMode ? "⌘ Board-Agent — verschieben/löschen/steuern (getrennt vom Worker)"
            : (k.session_id ? "Worker — Kontext läuft weiter" : "Worker — noch nicht gestartet")}
        </Text>
      </View>

      <Composer onSend={handleSend} busy={running && !agentMode} onStop={onStop} models={models} modeOptions={modeOptions}
        slashCommands={SLASH} seed={seed} bottomInset={kb > 0 ? bottomInset + 10 : bottomInset} draftKey={`card:${k.id}`}
        placeholder={agentMode ? "Sag dem Agenten was zu tun ist — z.B. 'verschiebe diese Karte nach done'"
          : k.session_id ? "Worker steuern – Kontext läuft weiter" : "Worker starten…"} />
    </View>
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
  const sheet = useActionSheet();
  const [toast, setToast] = useState<{ text: string; ok: boolean } | null>(null);
  const showToast = (text: string, ok = true) => { setToast({ text, ok }); setTimeout(() => setToast(null), 3800); };

  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks });
  // tracks can arrive as a non-array {error} object over the relay (pairing/pin
  // mismatch) — guard before .find so the card screen doesn't white-screen.
  const k: Track | undefined = (Array.isArray(tracks) ? tracks : []).find((x) => x.id === id);
  const running = k?.status === "running";

  // Live transcript via LONG-POLL PUSH (api.transcriptLive): the daemon holds
  // each request open until the transcript changes, so the feed grows with real
  // streaming latency over BOTH the sealed relay and direct — no SSE (which
  // can't tunnel the relay) and no fixed 3s poll. The initial query loads the
  // feed on open; the loop keeps it live, writing into the same cache.
  const { data: transcript } = useQuery<TStep[]>({
    queryKey: ["transcript", id], queryFn: () => api.transcript(id!) as Promise<TStep[]>,
    enabled: !!id, staleTime: Infinity, refetchInterval: false });
  const { data: hist } = useQuery({ queryKey: ["history", id], queryFn: () => api.history(id!), enabled: !!id });
  const { data: models } = useQuery({ queryKey: ["models"], queryFn: api.models, staleTime: 300000 });
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 10000 });

  useEffect(() => {
    if (!id) return;
    let alive = true;
    let v = "";
    (async () => {
      while (alive) {
        try {
          const r = await api.transcriptLive(id, v);
          if (!alive) break;
          if (r && Array.isArray(r.steps)) {
            qc.setQueryData(["transcript", id], r.steps);
            if (r.v !== v) qc.invalidateQueries({ queryKey: ["history", id] });   // notes too
          }
          v = r?.v ?? v;
        } catch {
          if (!alive) break;
          await new Promise((res) => setTimeout(res, 2500));   // backoff, then retry
        }
      }
    })();
    return () => { alive = false; };
  }, [id, qc]);

  // Weave the actionlog lifecycle 'note' rows into the transcript by timestamp
  // (ported from peek.tsx). Falls back to the steer/reply history until a
  // session transcript exists.
  const feed = useMemo<TStep[]>(() => {
    const trans = (transcript ?? []) as TStep[];
    const rows = (hist ?? []) as TStep[];
    if (!trans.length) {
      return rows.filter((r) => (r.text || (r as any).detail || r.result))
        .map((r) => r.kind === "steer"
          ? { role: "user", kind: "text", text: (r as any).detail, ts: r.ts, ta: (r as any).ta }
          : r.kind === "reply"
          ? { role: "assistant", kind: "text", text: (r as any).detail, ts: r.ts, ta: (r as any).ta }
          : { kind: "system", text: (r as any).detail ?? r.text, ts: r.ts, ta: (r as any).ta });
    }
    const notes: TStep[] = rows.filter((r) => r.kind === "note" && ((r as any).detail ?? "").trim())
      .map((r) => ({ kind: "system", text: (r as any).detail, ts: r.ts, ta: (r as any).ta }));
    if (!notes.length) return trans;
    // Weave notes into the transcript by absolute epoch (`ta`) — the only sound
    // key. Display `ts` is date-less HH:MM:SS and string-sorting it scrambled
    // the feed across midnight/days. A stable ord tiebreak preserves source
    // order for legacy rows lacking `ta`.
    const tagged = [
      ...trans.map((s, idx) => ({ s, ta: s.ta, ord: idx * 2 })),
      ...notes.map((s, idx) => ({ s, ta: s.ta, ord: idx * 2 + 1 })),
    ];
    const key = (x: { ta?: number }) => (typeof x.ta === "number" ? x.ta : 0);
    tagged.sort((a, b) => key(a) - key(b) || a.ord - b.ord);
    return tagged.map((x) => x.s);
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

  // Lane flow, Jira-style: the header status pill is the primary "move" control,
  // the 3-dots carries a one-tap "advance to next" + admin actions.
  const LANES = ["backlog", "working", "review", "done"] as const;
  const laneLabel = (l: string) =>
    ((metrics as { settings?: { policy?: { lane_labels?: Record<string, string> } } })?.settings?.policy?.lane_labels ?? {})[l]
    ?? l.charAt(0).toUpperCase() + l.slice(1);
  const laneIdx = k ? LANES.indexOf(k.lane as (typeof LANES)[number]) : -1;
  const nextLane = laneIdx >= 0 && laneIdx < LANES.length - 1 ? LANES[laneIdx + 1] : null;

  async function moveTo(lane: string) {
    if (!k) return;
    try {
      const res = await api.moveLane(k.id, lane);
      await qc.invalidateQueries({ queryKey: ["tracks"] });
      // Review/Done are backgrounded by the daemon (gate subprocess + merge +
      // deploy hook), so there is no verdict to report yet — say what STARTED.
      // The outcome arrives on the card, woven into this feed as a lifecycle
      // note, and in the board chat; it is no longer toast-only.
      if (res.gating) {
        showToast(lane === "done" ? "Gate + Merge laufen… Ergebnis erscheint hier"
                                  : "Gate läuft… Ergebnis erscheint hier");
      } else if (lane === "working") {
        showToast(`Gestartet → ${laneLabel(lane)} · Agent arbeitet`);
      } else {
        const bad = res.status === "bounced" || !!res.gate_failed;
        showToast(bad ? `Abgelehnt → ${laneLabel(lane)} (Gate/Review)`
                      : `Verschoben → ${laneLabel(lane)}`, !bad);
      }
    } catch (e) { showToast("Move fehlgeschlagen: " + String((e as Error).message), false); }
  }
  function moveSheet() {
    if (!k) return;
    sheet.show({
      title: k.task,
      message: "Verschieben nach…",
      // next step first + labelled, then the rest — like Jira's transition list
      options: LANES.filter((l) => l !== k.lane)
        .sort((a, b) => (a === nextLane ? -1 : b === nextLane ? 1 : 0))
        .map((l) => ({ label: (l === nextLane ? "→ " : "") + laneLabel(l) + (l === nextLane ? "   · nächster Schritt" : ""),
                       onPress: () => moveTo(l) })),
    });
  }
  function menu() {
    if (!k) return;
    sheet.show({
      title: k.task,
      options: [
        ...(nextLane ? [{ label: "Weiterschieben  →  " + laneLabel(nextLane), onPress: () => moveTo(nextLane) }] : []),
        { label: "Verschieben nach…", onPress: moveSheet },
        { label: "Fork", onPress: () => api.fork(k.id) },
        { label: "Archivieren", onPress: () => api.archive(k.id).then(() => router.back()) },
        { label: "Löschen", destructive: true, onPress: () => api.del(k.id).then(() => router.back()) },
      ],
    });
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
        {k ? (
          // tappable status pill (Jira-style): shows the lane, opens the move sheet
          <Pressable onPress={moveSheet} hitSlop={8} accessibilityLabel="Status ändern"
            style={{ flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: t.surface2,
              borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 }}>
            <View style={{ width: 7, height: 7, borderRadius: 3.5, backgroundColor: laneColor(t, k.lane) }} />
            <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{laneLabel(k.lane)}</Text>
            <Ionicons name="chevron-down" size={12} color={t.txtTertiary} />
          </Pressable>
        ) : null}
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
      {toast ? (
        <View pointerEvents="none" style={{ position: "absolute", left: 0, right: 0, bottom: insets.bottom + 74, alignItems: "center", paddingHorizontal: 16 }}>
          <View style={{ maxWidth: 520, flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: t.surface1,
            borderColor: toast.ok ? t.ok : t.danger, borderWidth: 1, borderRadius: 11, paddingHorizontal: 14, paddingVertical: 11,
            ...(isWeb ? { boxShadow: "0 6px 20px rgba(0,0,0,0.35)" } as object : { elevation: 8 }) }}>
            <Ionicons name={toast.ok ? "checkmark-circle" : "alert-circle"} size={17} color={toast.ok ? t.ok : t.danger} />
            <Text style={{ color: t.txtPrimary, fontSize: 12.5, flexShrink: 1 }}>{toast.text}</Text>
          </View>
        </View>
      ) : null}
      {sheet.node}
    </View>
  );
}
