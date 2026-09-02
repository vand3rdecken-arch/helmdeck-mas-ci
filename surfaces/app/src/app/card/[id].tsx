import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Keyboard, Pressable,
  ScrollView, Text, TextInput, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, neverDelivered, type SteerOpts } from "@/data/client";
import * as outbox from "@/data/outbox";
import { usePresence } from "@/data/presence";
import { useModels } from "@/data/use_models";
import type { Track, Me, EconCard } from "@/data/types";
import { useT } from "@/i18n";
import { executorLabel, laneColor, statusColor, useTheme } from "@/theme";
import { Chip, Empty, KVRow, Panel, SectionLabel } from "@/ui/kit";
import { fmtPlanPct, fmtTok, planLabel, useAiFlat } from "@/ui/billing";
import { cur } from "@/ui/dash_panels";
import { Composer, type Recipient } from "@/ui/card_composer";
import { BackgroundTasks } from "@/ui/card_background";
import { ContextMeter } from "@/ui/context_meter";
import { QuestionPanel } from "@/ui/card_question";
import { Transcript, type TStep } from "@/ui/card_transcript";
import { ChatScroll, type ChatScrollHandle } from "@/ui/chat_scroll";
import { UnsentStrip } from "@/ui/outbox_strip";
import { SignOff } from "@/ui/sign_off";
import { useActionSheet } from "@/ui/action_sheet";
import { isWeb, useResponsive } from "@/ui/responsive";

type Tab = "overview" | "chat";

interface Turn { ts?: string; cost?: number; models?: string[];
  usage?: { input_tokens?: number; output_tokens?: number; cache_read_input_tokens?: number; cache_creation_input_tokens?: number } }
interface Ckpt { turn: number; commit: string; ts: string; reply: string }

// Slash commands, built per render: the hint AND the text they type for the
// owner are their prose, so both follow the workspace language. A module-level
// const would freeze whatever language was current at import time.
type Tr = (key: string, vars?: Record<string, string | number>) => string;
const slashCommands = (tr: Tr) => ["plan", "test", "diff", "commit"].map((name) => ({
  name, hint: tr(`card.slash.${name}Hint`), insert: tr(`card.slash.${name}Insert`),
}));

// daemon status / lane words have shared keys in chrome.ts; map explicitly so an
// unknown value from the daemon falls back to its raw text, never to a key.
const STATUS_KEY: Record<string, string> = {
  queued: "status.queued", running: "status.running", gating: "status.gating",
  needs_you: "status.needsYou", bounced: "status.bounced",
  submitted: "status.submitted", accepted: "status.accepted",
};
const LANE_KEY: Record<string, string> = {
  backlog: "lane.backlog", working: "lane.working", review: "lane.review", done: "lane.done",
};

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
  const tr = useT();
  const [editing, setEditing] = useState(false);
  const text = value ?? "";

  if (editing || !text.trim()) {
    return (
      <EditText value={text} onSave={onSave} multiline autoFocus={editing}
        onDone={() => setEditing(false)}
        placeholder={tr("card.descPlaceholder")}
        style={{ minHeight: 200, textAlignVertical: "top", lineHeight: 20 }} />
    );
  }
  const isHead = (l: string) => {
    const s = l.trim();
    return s.length > 2 && s.length <= 40 && s === s.toUpperCase() && /[A-ZÄÖÜ]/.test(s);
  };
  return (
    <Pressable onPress={() => setEditing(true)} accessibilityLabel={tr("card.editDescription")}
      style={{ backgroundColor: t.surface2, borderRadius: 8, borderWidth: 1,
        borderColor: t.borderSubtle, padding: 10, gap: 2 }}>
      {text.split("\n").map((line, i) => {
        const s = line.trim();
        if (!s) return <View key={i} style={{ height: 8 }} />;
        if (isHead(line)) {
          return (
            <Text key={i} selectable style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700",
              letterSpacing: 0.6, marginTop: i ? 6 : 0 }}>{s}</Text>
          );
        }
        if (s.startsWith("- ")) {
          return (
            <View key={i} style={{ flexDirection: "row", gap: 6 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 14, lineHeight: 20 }}>•</Text>
              <Text selectable style={{ color: t.txtPrimary, fontSize: 14, lineHeight: 20, flex: 1 }}>{s.slice(2)}</Text>
            </View>
          );
        }
        return <Text key={i} selectable style={{ color: t.txtPrimary, fontSize: 14, lineHeight: 20 }}>{s}</Text>;
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
  const tr = useT();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["attachments", id], queryFn: () => api.attachments(id) });
  const files = data ?? [];
  if (!files.length) return null;
  const kb = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
  return (
    <>
      <View style={{ height: 8 }} />
      <SectionLabel text={tr("card.sec.attachments")} />
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
            <Pressable hitSlop={8} accessibilityLabel={tr("card.removeAttachment", { name: f.name })}
              onPress={() => api.removeAttachment(id, f.name)
                .then(() => qc.invalidateQueries({ queryKey: ["attachments", id] }))
                .catch((e) => Alert.alert(tr("card.attachment"), String((e as Error).message)))}>
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
  const tr = useT();
  const flat = useAiFlat();
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
      catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
    };
    Alert.alert(tr("card.rewind.title"), tr("card.rewind.body"),
      [{ text: tr("ui.cancel"), style: "cancel" }, { text: tr("card.rewind.restore"), onPress: go }]);
  }

  return (
    <View style={{ gap: 10 }}>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
        {k.status ? <Chip text={STATUS_KEY[k.status] ? tr(STATUS_KEY[k.status]) : k.status.replace(/_/g, " ")}
          dot={statusColor(t, k.status)} /> : null}
        <Chip text={LANE_KEY[k.lane] ? tr(LANE_KEY[k.lane]) : k.lane} dot={laneColor(t, k.lane)} />
        {k.mode ? <Chip text={executorLabel(k.mode)} dot={t.ai} /> : null}
        {k.ai_cost > 0 ? <Chip text={flat
          ? planLabel(tr, e?.plan_pct, (k.tokens_in ?? 0) + (k.tokens_out ?? 0))
          : `AI $${k.ai_cost.toFixed(2)}`} /> : null}
      </View>

      <Panel>
        <SectionLabel text={tr("card.sec.task")} />
        <EditText value={k.task} onSave={(v) => v && edit({ task: v })} multiline style={{ fontWeight: "600" }} />
        <View style={{ height: 8 }} />
        <SectionLabel text={tr("card.sec.description")} />
        <DescriptionField value={k.description ?? ""} onSave={(v) => edit({ description: v })} />
        <AttachmentList id={k.id} />
      </Panel>

      <Panel>
        <SectionLabel text={tr("card.sec.properties")} />
        <View style={{ gap: 10 }}>
          <Picker label={tr("card.prop.priority")} value={k.priority ?? "medium"}
            options={["urgent", "high", "medium", "low"].map((p) => ({ id: p, label: tr(`prio.${p}`) }))}
            onPick={(p) => edit({ priority: p })} />
          <View style={{ gap: 4 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("card.prop.due")}</Text>
            <EditText value={k.due ?? ""} onSave={(v) => edit({ due: v })} placeholder="2026-01-31" />
          </View>
          <Picker label={tr("card.prop.billing")} value={billing}
            options={[{ id: "fixed", label: tr("card.billing.fixed") }, { id: "tm", label: tr("card.billing.tm") },
                      { id: "none", label: tr("card.billing.none") }]}
            onPick={(b) => edit({ billing: b })} />
          {billing === "fixed" ? (
            <View style={{ gap: 4 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("card.prop.price")}</Text>
              <EditText value={String(k.value ?? "")} onSave={(v) => { const n = parseFloat(v); if (!isNaN(n)) edit({ value: n }); }} placeholder="0" />
            </View>
          ) : null}
          {billing === "tm" ? (
            <View style={{ gap: 4 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("card.prop.rate")}</Text>
              <EditText value={String(k.rate ?? "")} onSave={(v) => { const n = parseFloat(v); if (!isNaN(n)) edit({ rate: n }); }} placeholder="0" />
            </View>
          ) : null}
          <View style={{ gap: 4 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("card.prop.client")}</Text>
            <EditText value={k.client ?? ""} onSave={(v) => edit({ client: v })} placeholder="-" />
          </View>
        </View>
      </Panel>

      {owner && e ? (
        <Panel>
          <SectionLabel text={tr("card.sec.economics")} />
          <KVRow k={tr("card.econ.billed")} v={`${cy}${(e.billed ?? e.value).toFixed(2)}${e.billing === "tm" ? " ~" : ""}`} />
          {flat
            ? <KVRow k={tr("card.econ.aiUse")}
                v={e.plan_pct != null && e.plan_pct > 0
                  ? tr("card.econ.aiUsePlan", { pct: fmtPlanPct(e.plan_pct),
                      tok: fmtTok((e.tokens_in ?? 0) + (e.tokens_out ?? 0)) })
                  : tr("card.econ.aiUseVal", { tok: fmtTok((e.tokens_in ?? 0) + (e.tokens_out ?? 0)) })}
                color={t.ai} />
            : <KVRow k={tr("card.econ.aiCost")} v={`$${e.ai_cost.toFixed(2)}`} color={t.ai} />}
          <KVRow k={tr("card.econ.margin")} v={`${cy}${(e.margin ?? ((e.billed ?? e.value) - (flat ? 0 : e.ai_cost))).toFixed(2)}`} color={t.accent} />
          <KVRow k={tr("card.econ.touches")}
            v={tr(e.touches === 1 ? "card.econ.touchOne" : "card.econ.touchMany", { n: e.touches })} />
          {e.mode ? <KVRow k={tr("card.econ.mode")} v={tr(e.mode === "auto" ? "card.mode.auto" : "card.mode.assisted")} /> : null}
        </Panel>
      ) : null}

      <Panel>
        <SectionLabel text={tr("card.sec.technical")} />
        <KVRow k={tr("card.tech.branch")} v={k.branch || "—"} />
        <KVRow k={tr("card.tech.repo")} v={k.repo || "—"} />
        <KVRow k={tr("card.tech.session")} v={k.session_id ? k.session_id.slice(0, 12) + "…" : tr("card.notStarted")} />
        <KVRow k={tr("card.tech.turns")} v={`${k.turns}`} />
        <KVRow k={tr("card.tech.tokens")} v={`${(k.tokens_in ?? 0).toLocaleString()} / ${(k.tokens_out ?? 0).toLocaleString()}`} />
        {k.models?.length ? <KVRow k={tr("card.tech.models")} v={k.models.join(", ")} /> : null}
      </Panel>

      {turns && turns.length > 0 ? (
        <Panel>
          <SectionLabel text={tr("card.sec.aiTurns")} />
          {turns.map((tu, i) => {
            const u = tu.usage ?? {};
            const tin = (u.input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0);
            return (
              <View key={i} style={{ flexDirection: "row", gap: 8, paddingVertical: 2 }}>
                <Text style={{ color: t.txtTertiary, fontSize: 11.5, width: 60 }}>{tu.ts?.slice(5, 16) ?? ""}</Text>
                <Text style={{ color: t.txtSecondary, fontSize: 11.5, width: 90 }} numberOfLines={1}>{(tu.models?.[0] ?? "-").replace("claude-", "")}</Text>
                <Text style={{ color: t.txtSecondary, fontSize: 11.5, flex: 1 }}>{tin.toLocaleString()}/{(u.output_tokens ?? 0).toLocaleString()}{flat ? "" : ` · $${(tu.cost ?? 0).toFixed(3)}`}</Text>
              </View>
            );
          })}
        </Panel>
      ) : null}

      {owner && ckpts && ckpts.length > 0 ? (
        <Panel>
          <SectionLabel text={tr("card.sec.rewind")} />
          {ckpts.slice().reverse().map((c, i) => (
            <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11.5, width: 92 }}>{tr("card.rewind.turn", { n: c.turn })} · {c.ts?.slice(11, 16)}</Text>
              <Text style={{ color: t.txtSecondary, fontSize: 12, flex: 1 }} numberOfLines={1}>{c.reply}</Text>
              <Pressable onPress={() => rewind(c.commit)} hitSlop={6}
                style={{ flexDirection: "row", alignItems: "center", gap: 4, borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 }}>
                <Ionicons name="arrow-undo-outline" size={12} color={t.txtSecondary} />
                <Text style={{ color: t.txtSecondary, fontSize: 11.5 }}>{tr("card.rewind.restore")}</Text>
              </Pressable>
            </View>
          ))}
        </Panel>
      ) : null}
    </View>
  );
}

// ---- chat column ----------------------------------------------------------

function Chat({ k, feed, onSend, onStop, models, modeOptions, seed, setSeed, bottomInset, me }: {
  k: Track; feed: TStep[]; onSend: (text: string, o: SteerOpts) => Promise<void>; onStop: () => void;
  models: (string | { id: string; label?: string; desc?: string })[]; modeOptions: { id: string; label: string }[];
  seed: { text: string; key: number }; setSeed: (s: { text: string; key: number }) => void; bottomInset: number;
  me?: string;
}) {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const running = k.status === "running";
  // Team-chat roster: an unaddressed message goes to the Worker while the
  // card has an active/live session, else to Henry (steering a backlog card
  // still auto-dispatches it - the @mention chip is what makes the choice
  // legible instead of the old silent tab state).
  const recipients: Recipient[] = useMemo(() => [
    { id: "henry", label: tr("transcript.boardAgent"), color: t.accent2, icon: "sparkles-outline",
      hint: tr("card.chat.mentionHenry") },
    { id: "worker", label: tr("transcript.worker"), color: t.accent, icon: "construct-outline",
      hint: tr("card.chat.mentionWorker") },
  ], [tr, t]);
  const defaultTo = k.session_id || k.status === "running" || k.lane !== "done" ? "worker" : "henry";
  // Henry is working on THIS card's turn (set by our own send, below).
  const [henryBusy, setHenryBusy] = useState(false);
  // ...and what he has typed so far. copilot.chat streams its prose into the
  // per-user live feed for EVERY turn, card-scoped ones included - the card
  // was simply the surface that never read it (debt
  // card-henry-reply-not-streamed), so a slow Henry turn showed a bare spinner
  // while the board chat streamed the identical text. Scoped twice over: only
  // while OUR send is in flight, and only when the daemon says the running
  // turn belongs to this card (r.card) - the feed is per user, and turns are
  // serialised, so an unscoped read could paint a board-chat answer in here.
  const [henryStream, setHenryStream] = useState("");
  useEffect(() => {
    if (!henryBusy) { setHenryStream(""); return; }
    let alive = true, to: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await api.chatLive();
        // `card` absent = a daemon that predates the field: stay with the
        // spinner rather than risk attributing another surface's prose.
        if (alive && r) setHenryStream(r.card === k.id ? (r.text || "") : "");
      } catch { /* keep polling - a dropped poll must not end the stream */ }
      if (alive) to = setTimeout(poll, 500);
    };
    poll();
    return () => { alive = false; clearTimeout(to); };
  }, [henryBusy, k.id]);
  // optimistic echo: your just-sent message shows instantly, before the
  // session transcript catches up. Reconciled away once the real feed carries it.
  const [pending, setPending] = useState<TStep[]>([]);
  // ui/chat_scroll.tsx - shared with the board chat, so "follow the newest
  // message" and the "↓ Neueste" pill have ONE implementation to be right in.
  const scrollRef = useRef<ChatScrollHandle>(null);
  // edge-to-edge (SDK 57) breaks Android adjustResize -> lift the composer above
  // the keyboard by measuring its height (same fix as the board chat).
  const [kb, setKb] = useState(0);
  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", (e) => setKb(e.endCoordinates.height));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(0));
    return () => { show.remove(); hide.remove(); };
  }, []);

  // drop an optimistic echo once the real feed carries that same user text.
  // Dedup by TEXT ALONE breaks on a repeated message (e.g. "continue" sent
  // twice): the moment the feed refetches, the OLD occurrence already matches
  // the new echo's text and it's stripped instantly, before the real steer
  // even lands - the message silently "vanishes". Instead each echo carries
  // its position among same-text occurrences (feed + already-pending, at the
  // moment it was queued) and is only dropped once the feed's count for that
  // text has actually caught up past that position.
  useEffect(() => {
    if (!pending.length) return;
    const counts = new Map<string, number>();
    for (const s of feed) {
      if (s.role !== "user") continue;
      const key = (s.text ?? "").trim();
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    setPending((p) => p.filter((e) => {
      const key = (e.text ?? "").trim();
      const feedCount = counts.get(key) ?? 0;
      return feedCount <= ((e as unknown as { baseline?: number }).baseline ?? 0);
    }));
  }, [feed]);   // eslint-disable-line react-hooks/exhaustive-deps

  // ONE real chronological stream: Henry's card-scoped exchange now folds
  // server-side into this same card's timeline (cells/copilot/copilot.py),
  // so it arrives through `feed` exactly like the worker's own turns -
  // identity (by/byKind/to) is what tells them apart in the transcript, not
  // a client-side divider.
  // Henry's live prose rides along as a STREAMING step, so it renders through
  // the same bubble the worker's own stream uses instead of a second widget.
  // It is replaced (not appended to) by the real timeline entry the server
  // folds in when the turn lands - henryBusy goes false in the same breath.
  const steps = useMemo<TStep[]>(() => {
    const base = [...feed, ...pending];
    if (henryBusy && henryStream.trim()) {
      // time inlined, not hhmm(): that helper is declared BELOW this memo and
      // a useMemo factory runs during the same render pass (temporal dead zone).
      base.push({ role: "assistant", kind: "text", text: henryStream,
                  by: "Henry", byKind: "henry",
                  ts: new Date().toTimeString().slice(0, 5), streaming: true });
    }
    return base;
  }, [feed, pending, henryBusy, henryStream]);

  // The turn is still PRODUCING while the transcript streams. The machine-card
  // driver can flip status->needs_you on a first/quick reply while claude keeps
  // producing the real answer, so the "waiting for you" cue (and the question
  // panel) would fire on the FIRST message, not the final one. Suppress them while
  // a streaming step is present - once the stream settles they show correctly.
  const streaming = steps.some((s) => s.streaming);

  // Auto-pin to newest (only when the reader is already near the bottom, so
  // scrolling up to read isn't yanked back down) is ChatScroll's job now, and it
  // keys on the scroll view's own geometry instead of `steps.length` - a worker
  // STREAMING into the last bubble grows the content without growing the count.

  const hhmm = () => new Date().toTimeString().slice(0, 5);
  // `retryOf` = the outbox row being re-attempted (see ui/outbox_strip.tsx).
  async function handleSend(text: string, o: SteerOpts, retryOf?: string) {
    const to = o.to ?? defaultTo;
    // echo instantly, then send; retract the echo if it throws. baseline =
    // this occurrence's rank among same-text messages already in feed +
    // already-pending, so the reconcile effect can tell THIS repeat apart
    // from an earlier identical one (see the effect above `steps`).
    const key = text.trim();
    const baseline = feed.filter((s) => s.role === "user" && (s.text ?? "").trim() === key).length
      + pending.filter((e) => (e.text ?? "").trim() === key).length;
    const echo = { role: "user", kind: "text", text, ts: hhmm(), by: me, byKind: "human", to, baseline } as TStep & { baseline: number };
    setPending((p) => [...p, echo]);
    if (to === "henry") {
      setHenryBusy(true);
      try {
        await api.chat(text, { ...o, card: k.id });
        if (retryOf) await outbox.settle(retryOf);
      } catch (e) {
        // Retract the echo (it was never sent) but keep the TEXT - parked on
        // disk, where closing the card can't take it with it. An Alert alone
        // left the owner with a dismissed dialog and no message anywhere.
        setPending((p) => p.filter((x) => x !== echo));
        const msg = String((e as Error).message) || tr("card.chat.sendFailed");
        if (neverDelivered(e)) {
          if (retryOf) await outbox.retried(retryOf, msg);
          else await outbox.park(`card:${k.id}`, text, o, msg, Date.now());
        } else {
          Alert.alert(tr("ui.error"), msg);   // the daemon answered - just report it
        }
      } finally {
        setHenryBusy(false);
      }
      // Henry's reply already landed server-side (cells/copilot/copilot.py
      // folds it before returning) - pull it in, and the board agent may
      // have moved/deleted/archived cards too, so refresh the board.
      await qc.invalidateQueries({ queryKey: ["transcript", k.id] });
      await qc.invalidateQueries({ queryKey: ["tracks"] });
      return;
    }
    // Worker branch. `onSend` (the screen's send) RETHROWS, so this rollback is
    // live code again - it used to be unreachable because send swallowed the
    // error into an Alert, leaving a ghost message that had never been sent.
    try {
      await onSend(text, o);
      if (retryOf) await outbox.settle(retryOf);
    } catch (e) {
      setPending((p) => p.filter((x) => x !== echo));
      const msg = String((e as Error).message) || tr("card.chat.sendFailed");
      if (neverDelivered(e)) {
        if (retryOf) await outbox.retried(retryOf, msg);
        else await outbox.park(`card:${k.id}`, text, o, msg, Date.now());
      } else {
        Alert.alert(tr("ui.error"), msg);   // the daemon answered - just report it
      }
    }
  }

  return (
    <View style={{ flex: 1, paddingBottom: kb }}>
      <View style={{ flex: 1 }}>
        <ChatScroll ref={scrollRef} label={tr("card.chat.latest")}
          contentContainerStyle={{ padding: 12, paddingBottom: 20 }}>
          {steps.length === 0 ? (
            <Empty text={k.turns > 0 ? tr("card.chat.historyLost", { n: k.turns }) : tr("card.chat.noMessages")} />
          ) :
            <Transcript steps={steps} ctxWindow={k.ctx_window} onRewind={(txt) => setSeed({ text: txt, key: seed.key + 1 })} />}
        </ChatScroll>
      </View>

      {/* What the parked card is waiting on. Two distinct cases:
            - a typed question  -> real option buttons; answering CONTINUES the
              same session (Phase 2.4), so it replaces the generic cue entirely
            - a background task -> not your move at all; the compact task line
              below carries that (Paseo parity: ONE line, not pill + list) -
              the pill stays only for pre-registry cards with no bg_tasks
          The plain "your move, steering resumes" cue was dropped (owner
          feedback): it's redundant with the status badge above and the
          background-tasks line below, and just added clutter. */}
      {!running && !streaming && k.question ? (
        <QuestionPanel question={k.question}
          // the card door: settles the question AND resumes the parked session
          onSubmit={(answers, rid) => api.answer(k.id, answers, rid)}
          onAnswered={async () => {
            // the answer starts a turn: pull the card (status->running, question
            // cleared) and the feed so the panel gives way to the live turn.
            await qc.invalidateQueries({ queryKey: ["tracks"] });
            await qc.invalidateQueries({ queryKey: ["transcript", k.id] });
          }} />
      ) : !running && !streaming && (k.status === "needs_you" || k.status === "bounced")
          && k.waiting_on === "background"
          && !(k.bg_tasks && Object.keys(k.bg_tasks).length > 0) ? (
        <View style={{ paddingHorizontal: 12, paddingTop: 8, alignItems: "center" }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 7,
            backgroundColor: t.ai + "1A", borderColor: t.ai + "66", borderWidth: 1, borderRadius: 10,
            paddingHorizontal: 12, paddingVertical: 7 }}>
            <Ionicons name="hourglass-outline" size={14} color={t.ai} />
            <Text style={{ color: t.txtSecondary, fontSize: 12 }}>
              {tr("card.chat.awaitingBackground", { n: k.background?.n ?? 1 })}
            </Text>
          </View>
        </View>
      ) : null}

      {/* Background tasks as ONE compact expandable line (Paseo SubagentsTrack):
          shown whenever the card has task descriptors, so finished/canceled
          ones stay inspectable inside the expansion - and it carries the
          "waiting, not your move" state itself when the card is parked on
          them, replacing a second blocker pill. */}
      {k.bg_tasks && Object.keys(k.bg_tasks).length > 0 ? (
        <BackgroundTasks tasks={k.bg_tasks} waiting={k.waiting_on === "background"} />
      ) : null}

      {/* The pre-output cue only. Once Henry's prose starts arriving it streams
          into the transcript as a normal bubble (see the steps memo), so this
          row stands down instead of sitting under a reply that is already
          being written. */}
      {henryBusy && !henryStream.trim() ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingTop: 6 }}>
          <ActivityIndicator size="small" color={t.accent2} />
          <Text style={{ color: t.accent2, fontSize: 11.5 }}>{tr("card.chat.henryThinking")}</Text>
        </View>
      ) : null}

      {/* Context meter (Paseo-parity): the worker's window fills over a long card
          and it just STOPS with "Kontext ist am Ende" - now you SEE it coming.
          Shared with the board/PM chat - see ui/context_meter.tsx. */}
      <View style={{ paddingHorizontal: 12, paddingTop: 8 }}>
        <ContextMeter tokens={k.ctx_tokens} window={k.ctx_window} />
      </View>

      <UnsentStrip scope={`card:${k.id}`} onRetry={(m) => handleSend(m.text, m.opts, m.id)} />
      <Composer onSend={handleSend} busy={running} onStop={onStop} models={models} modeOptions={modeOptions}
        slashCommands={slashCommands(tr)} seed={seed} bottomInset={kb > 0 ? bottomInset + 10 : bottomInset} draftKey={`card:${k.id}`}
        recipients={recipients} defaultTo={defaultTo}
        placeholder={tr(k.session_id ? "card.chat.phWorkerLive" : "card.chat.phWorkerIdle")} />
    </View>
  );
}

// ---- screen ---------------------------------------------------------------

export default function CardScreen() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { id, tab: tabParam } = useLocalSearchParams<{ id: string; tab?: string }>();
  const { wide } = useResponsive();
  // A push about a message (question/needs_you/bounced) deep-links here with
  // ?tab=chat so the owner lands where the news actually is, not the overview
  // tab he'd have to click past every time.
  const [tab, setTab] = useState<Tab>(tabParam === "chat" ? "chat" : "overview");
  const [seed, setSeed] = useState({ text: "", key: 0 });
  const sheet = useActionSheet();
  const [toast, setToast] = useState<{ text: string; ok: boolean } | null>(null);
  const [signing, setSigning] = useState<Track | null>(null);   // GxP sign-off
  const showToast = (text: string, ok = true) => { setToast({ text, ok }); setTimeout(() => setToast(null), 3800); };

  // Presence (Phase 2.1): while this screen is mounted the owner is LOOKING at
  // this card, so the daemon must not push about it (notify.should_push).
  // Clearing on unmount is what makes leaving the card resume notifications.
  useEffect(() => {
    if (!id) return;
    usePresence.getState().setFocusedCard(id);
    return () => usePresence.getState().setFocusedCard(null);
  }, [id]);

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
  const { data: models } = useModels();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 10000 });

  useEffect(() => {
    if (!id) return;
    let alive = true;
    let v = "";
    let have = 0;
    (async () => {
      while (alive) {
        try {
          const r = await api.transcriptLive(id, v, have);
          if (!alive) break;
          if (r && Array.isArray(r.steps)) {
            // DELTA merge: keep the settled prefix [0, base) and replace the tail
            // with what the daemon sent (new steps + overlap). base===0 -> full.
            const base = typeof r.base === "number" ? r.base : 0;
            const prev = (qc.getQueryData<TStep[]>(["transcript", id]) ?? []);
            const merged = base > 0 ? prev.slice(0, base).concat(r.steps) : r.steps;
            qc.setQueryData(["transcript", id], merged);
            have = merged.length;
            if (r.v !== v) qc.invalidateQueries({ queryKey: ["history", id] });   // notes too
          }
          // Unchanged version = the poll returned WITHOUT news: the daemon's
          // ~22s hold expired, or demo mode answered instantly (it cannot hold
          // a request open). Pause before re-polling - without this the demo
          // seam turned the loop into a zero-delay spin that pegged the main
          // thread and froze every card screen. On a version CHANGE the next
          // poll fires immediately, so live streaming latency is untouched.
          const nv = r?.v ?? v;
          if (nv === v && alive) await new Promise((res) => setTimeout(res, 1500));
          v = nv;
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
    // Turn lifecycle rows (Phase 3.2) are their own typed items, woven in by
    // epoch like the notes - turn failure/cancel/usage shows in the feed even
    // though it never appears in the session .jsonl (it is daemon knowledge).
    const asTurn = (r: TStep): TStep => ({
      kind: "turn", event: (r as any).event, error: (r as any).error,
      usage: (r as any).usage, cost: (r as any).cost, ts: r.ts, ta: (r as any).ta });
    if (!trans.length) {
      return rows.filter((r) => r.kind === "turn" || (r.text || (r as any).detail || r.result))
        .map((r) => r.kind === "steer"
          ? { role: "user", kind: "text", text: (r as any).detail, ts: r.ts, ta: (r as any).ta }
          : r.kind === "reply"
          ? { role: "assistant", kind: "text", text: (r as any).detail, ts: r.ts, ta: (r as any).ta }
          : r.kind === "turn"
          ? asTurn(r)
          : { kind: "system", text: (r as any).detail ?? r.text, ts: r.ts, ta: (r as any).ta });
    }
    // A cancel is recorded TWICE: the CLI writes the interrupt sentinel into
    // the session .jsonl (a transcript turn-canceled item) and the daemon logs
    // its own turn-canceled row. When both exist near the same moment, keep
    // the transcript's - the actionlog row still shows alone for cancels the
    // .jsonl never saw (timeout kills, daemon restarts).
    const canceledAt = trans.filter((s) => s.kind === "turn" && (s as any).event === "canceled")
      .map((s) => s.ta ?? 0);
    const twin = (r: TStep) => (r as any).event === "canceled" &&
      canceledAt.some((ta) => Math.abs(((r as any).ta ?? 0) - ta) < 120);
    const notes: TStep[] = rows.filter((r) => r.kind === "note" && ((r as any).detail ?? "").trim())
      .map((r): TStep => ({ kind: "system", text: (r as any).detail, ts: r.ts, ta: (r as any).ta }))
      .concat(rows.filter((r) => r.kind === "turn" && !twin(r)).map(asTurn));
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

  async function edit(patch: Record<string, unknown>, okToast?: string) {
    if (!id) return;
    try {
      await api.update(id, patch);
      await qc.invalidateQueries({ queryKey: ["tracks"] });
      if (okToast) showToast(okToast);
    }
    catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
  }

  // RETHROWS. handleSend is the only caller and it owns the failure (retract the
  // echo, park the text in the outbox) - swallowing here made that rollback dead
  // code, so a failed worker send left a ghost message in the transcript that had
  // never been sent (owner report 2026-08-28).
  async function send(text: string, o: SteerOpts) {
    if (!id) return;
    await api.steer(id, text, o);
    await qc.invalidateQueries({ queryKey: ["transcript", id] });
    await qc.invalidateQueries({ queryKey: ["tracks"] });
  }

  async function stop() {
    if (!id) return;
    try { await api.cancel(id); await qc.invalidateQueries({ queryKey: ["tracks"] }); }
    catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
  }

  // Lane flow, Jira-style: the header status pill is the primary "move" control,
  // the 3-dots carries a one-tap "advance to next" + admin actions.
  const LANES = ["backlog", "working", "review", "done"] as const;
  const laneLabel = (l: string) =>
    ((metrics as { settings?: { policy?: { lane_labels?: Record<string, string> } } })?.settings?.policy?.lane_labels ?? {})[l]
    ?? (LANE_KEY[l] ? tr(LANE_KEY[l]) : l.charAt(0).toUpperCase() + l.slice(1));
  const laneIdx = k ? LANES.indexOf(k.lane as (typeof LANES)[number]) : -1;
  const nextLane = laneIdx >= 0 && laneIdx < LANES.length - 1 ? LANES[laneIdx + 1] : null;

  async function moveTo(lane: string) {
    if (!k) return;
    // GxP: a card in the regulated scope needs a signature before it can land.
    // Same gate as the board's four entry points, so the card detail cannot
    // become the one way around it.
    if (lane === "done" && k.gxp_scope) { setSigning(k); return; }
    try {
      const res = await api.moveLane(k.id, lane);
      await qc.invalidateQueries({ queryKey: ["tracks"] });
      // Review/Done are backgrounded by the daemon (gate subprocess + merge +
      // deploy hook), so there is no verdict to report yet — say what STARTED.
      // The outcome arrives on the card, woven into this feed as a lifecycle
      // note, and in the board chat; it is no longer toast-only.
      if (res.gxp_refused) {
        showToast(res.gxp_refused, false);
      } else if (res.gating) {
        showToast(tr(lane === "done" ? "card.toast.gateMerge" : "card.toast.gate"));
      } else if (lane === "working") {
        showToast(tr("card.toast.started", { lane: laneLabel(lane) }));
      } else {
        const bad = res.status === "bounced" || !!res.gate_failed;
        showToast(tr(bad ? "card.toast.bounced" : "card.toast.moved", { lane: laneLabel(lane) }), !bad);
      }
    } catch (e) { showToast(tr("card.toast.moveFailed", { err: String((e as Error).message) }), false); }
  }
  function moveSheet() {
    if (!k) return;
    sheet.show({
      title: k.task,
      message: tr("card.move.to"),
      // next step first + labelled, then the rest — like Jira's transition list
      options: LANES.filter((l) => l !== k.lane)
        .sort((a, b) => (a === nextLane ? -1 : b === nextLane ? 1 : 0))
        .map((l) => ({ label: (l === nextLane ? "→ " : "") + laneLabel(l)
                         + (l === nextLane ? `   · ${tr("card.move.nextStep")}` : ""),
                       onPress: () => moveTo(l) })),
    });
  }
  // Split the conversation into a new card (keeps context - unlike code Fork,
  // which starts a fresh session). The button must show what happened: a bare
  // fire-and-forget call here would repeat the "stucked here" silent-failure
  // class from the new-card form (Alert.alert is a no-op on desktop web).
  async function forkChat() {
    if (!k) return;
    try {
      const res = await api.forkChat(k.id);
      if (res?.error) { showToast(res.error, false); return; }
      if (res?.id) router.push(`/card/${res.id}` as never);
    } catch (e) { showToast(String((e as Error).message), false); }
  }
  async function forkCode() {
    if (!k) return;
    try {
      const res = await api.fork(k.id) as { id?: string; error?: string };
      if (res?.error) { showToast(res.error, false); return; }
      if (res?.id) router.push(`/card/${res.id}` as never);
    } catch (e) { showToast(String((e as Error).message), false); }
  }
  // Archive is a TOGGLE, not a one-way door. The daemon has accepted
  // {on:false} since archive_track was written ("Reversible: hides the card
  // from work views"), and copilot._snapshot even tells the owner a card is
  // ARCHIVED so he "can ask for it back" - but no surface ever sent it, so
  // there was nothing to ask. Unarchiving stays ON the card (the board is
  // still showing the Archive scope behind it, and leaving would just drop
  // him into a list the card is no longer part of); archiving leaves, because
  // the card is now hidden from the view he came from.
  async function toggleArchive() {
    if (!k) return;
    const on = !k.archived;
    try {
      await api.archive(k.id, on);
      await qc.invalidateQueries({ queryKey: ["tracks"] });
      if (on) router.back(); else showToast(tr("card.menu.unarchived"));
    } catch (e) { showToast(String((e as Error).message), false); }
  }
  function menu() {
    if (!k) return;
    sheet.show({
      title: k.task,
      options: [
        ...(nextLane ? [{ label: `${tr("card.move.advance")}  →  ${laneLabel(nextLane)}`, onPress: () => moveTo(nextLane) }] : []),
        { label: tr("card.move.to"), onPress: moveSheet },
        { label: tr(k.fast_track ? "card.fastTrack.disable" : "card.fastTrack.enable")
                  + tr("card.fastTrack.hint"), onPress: () => edit({ fast_track: !k.fast_track }) },
        // capability grant (mouse/keyboard/screen), same admin-only rule the
        // daemon enforces server-side (policy.chat_admin_roles) - the button
        // is just a discoverable path to the driver swap that already existed
        // via raw API/board-Agent chat only. The daemon itself refuses a
        // second desktop-capable turn while one is already running, so no
        // client-side "is it busy" check is needed here.
        ...(me?.role === "owner" || me?.role === "operator"
          ? [{ label: tr(k.driver === "claude-desktop" ? "card.desktop.disable" : "card.desktop.enable")
                        + tr("card.desktop.hint"),
               // The grant is bound at process spawn, so the flip lands on the
               // next message, not the running turn - say so instead of silently
               // toggling and leaving the owner guessing (the daemon drops the
               // idle old-grant process so the very next turn respawns fresh).
               onPress: () => edit(
                 { driver: k.driver === "claude-desktop" ? "claude" : "claude-desktop" },
                 tr(k.driver === "claude-desktop" ? "card.desktop.toastOff" : "card.desktop.toastOn")) }]
          : []),
        ...(k.session_id ? [{ label: tr("card.menu.forkChat"), onPress: forkChat }] : []),
        { label: tr("card.menu.fork"), onPress: forkCode },
        { label: tr(k.archived ? "card.menu.unarchive" : "card.menu.archive"), onPress: toggleArchive },
        { label: tr("ui.delete"), destructive: true, onPress: () => api.del(k.id).then(() => router.back()) },
      ],
    });
  }

  // permission modes — bypass ("Full") is owner-only; current perm first
  const modeBase = [{ id: "acceptEdits", label: tr("card.perm.edit") }, { id: "plan", label: tr("card.perm.plan") },
    ...(me?.role === "owner" ? [{ id: "bypassPermissions", label: tr("card.perm.full") }] : [])];
  const modeOptions = k
    ? [...modeBase.filter((m) => m.id === k.perm), ...modeBase.filter((m) => m.id !== k.perm)]
    : modeBase;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 8, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600", flex: 1 }} numberOfLines={2}>{k?.task ?? tr("card.card")}</Text>
        {running ? <ActivityIndicator size="small" color={t.ai} /> : null}
        {k?.fast_track ? (
          <Pressable onPress={() => edit({ fast_track: false })} hitSlop={6} accessibilityLabel={tr("card.fastTrack.off")}
            style={{ flexDirection: "row", alignItems: "center", gap: 3, backgroundColor: t.accent + "22",
              borderColor: t.accent + "80", borderWidth: 1, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 4 }}>
            <Ionicons name="flash" size={12} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 11, fontWeight: "700" }}>Fast-Track</Text>
          </Pressable>
        ) : null}
        {k ? (
          // tappable status pill (Jira-style): shows the lane, opens the move sheet
          <Pressable onPress={moveSheet} hitSlop={8} accessibilityLabel={tr("card.changeStatus")}
            style={{ flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: t.surface2,
              borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 }}>
            <View style={{ width: 7, height: 7, borderRadius: 3.5, backgroundColor: laneColor(t, k.lane) }} />
            <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{laneLabel(k.lane)}</Text>
            <Ionicons name="chevron-down" size={12} color={t.txtTertiary} />
          </Pressable>
        ) : null}
        <Pressable onPress={menu} hitSlop={10} accessibilityRole="button" accessibilityLabel={tr("board.card.menu")}>
          <Ionicons name="ellipsis-horizontal" size={22} color={t.txtSecondary} />
        </Pressable>
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
              seed={seed} setSeed={setSeed} bottomInset={insets.bottom} me={me?.name} />
          </View>
        </View>
      ) : (
        <>
          <View style={{ flexDirection: "row", borderBottomWidth: 1, borderBottomColor: t.glassBorder }}>
            {(["overview", "chat"] as Tab[]).map((x) => (
              <Pressable key={x} onPress={() => setTab(x)} style={{ flex: 1, paddingVertical: 10, alignItems: "center",
                borderBottomWidth: 2, borderBottomColor: tab === x ? t.accent : "transparent" }}>
                <Text style={{ color: tab === x ? t.accent : t.txtTertiary, fontWeight: "600" }}>
                  {x === "overview" ? tr("card.tab.overview") : `${tr("nav.chat")}${k.turns ? ` (${k.turns}t)` : ""}`}
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
              seed={seed} setSeed={setSeed} bottomInset={insets.bottom + 8} me={me?.name} />
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
      {signing ? (
        <SignOff
          card={signing}
          onClose={() => setSigning(null)}
          onSigned={async (msg) => {
            showToast(msg, true);
            // Signing authorises the accept, it does not perform it - the lane
            // machine verifies independently before merging.
            try {
              const res = await api.moveLane(signing.id, "done");
              if (res.gxp_refused) showToast(res.gxp_refused, false);
            } catch (e) { showToast(String((e as Error).message), false); }
            await qc.invalidateQueries({ queryKey: ["tracks"] });
          }}
        />
      ) : null}
      {sheet.node}
    </View>
  );
}
