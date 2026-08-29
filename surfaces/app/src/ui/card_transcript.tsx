import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { memo, useEffect, useState } from "react";
import { Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Markdown } from "./card_markdown";

const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }) as string;

// Rich transcript step — matches daemon/claude_sessions.read_transcript() output.
export interface ToolDetail {
  type: "edit" | "multiedit" | "write";
  file?: string; old?: string; new?: string; content?: string;
  edits?: { old: string; new: string }[];
}
// The clean state models (Phase 3, Paseo parity):
// - a tool call is exactly one of running|completed|failed|canceled
//   (failed <=> error != null; interrupted/abandoned are canceled)
// - the turn lifecycle is its OWN event stream (started/completed/failed/
//   canceled + usage), not inferred from flat steps
export type ToolStatus = "running" | "completed" | "failed" | "canceled";
export type TurnEvent = "started" | "completed" | "failed" | "canceled";
export interface TurnUsage {
  input_tokens?: number; output_tokens?: number;
  cache_creation_input_tokens?: number; cache_read_input_tokens?: number;
}
export interface TStep {
  role?: string;
  kind?: "text" | "thinking" | "tool" | "result" | "todos" | "plan" | "compaction" | "system" | "note" | "turn" | "error" | string;
  cls?: string;
  text?: string; tool?: string; label?: string; result?: string; ok?: boolean; running?: boolean; abandoned?: boolean; ts?: string;
  status?: ToolStatus;           // the 4-state tool-call model
  error?: string | null;         // non-null exactly when status === "failed"
  event?: TurnEvent;             // kind === "turn": which lifecycle edge
  usage?: TurnUsage; cost?: number | null;   // turn-end economics (kind === "turn")
  tokIn?: number; tokOut?: number; cacheRead?: number; cacheWrite?: number; ctx?: number;  // kind === "usage": per-turn tokens
  ta?: number;   // absolute epoch (seconds) — the sound sort/merge key
  agent?: boolean;   // a board-Agent (copilot) message, not a Worker one — legacy,
                      // superseded by byKind but still folded for old timeline rows
  by?: string;        // display name of the sender ("Tien", "Henry")
  byKind?: "human" | "henry" | "worker";
  to?: string;         // on a user step: the resolved recipient ("henry" | "worker")
  streaming?: boolean; detail?: ToolDetail;
  todos?: { content: string; status: string }[];
}

// Legacy rows (older daemon / cached feeds) carry only ok/running/abandoned —
// derive the 4-state status so the UI renders one model, not two.
export function toolStatus(s: TStep): ToolStatus {
  if (s.status) return s.status;
  if (s.running) return "running";
  if (s.abandoned) return "canceled";
  return s.ok === false ? "failed" : "completed";
}

// Display timestamp: the daemon's HH:MM:SS is date-less, so a row from a prior
// day reads as "out of order" (09:45 then 00:06). Prefix the date when the row
// is not from today so the feed's ordering is legible across days.
function tsLabel(s: TStep): string {
  if (!s.ts) return "";
  if (typeof s.ta === "number") {
    const d = new Date(s.ta * 1000), now = new Date();
    if (d.getFullYear() && d.toDateString() !== now.toDateString())
      return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${s.ts}`;
  }
  return s.ts;
}

// Clamps long text and reveals a show-more / show-less toggle only when it
// actually overflows a threshold (mirrors web transcript Collapsible).
const COLLAPSE_LINES = 24;
const COLLAPSE_CHARS = 1600;
// The char cut lands on a WORD boundary, never inside a word. A raw slice() is
// what makes a clamped message read as corrupted rather than folded - the owner
// reported Henry's chat "ending mid-word" (2026-08-28), and a cut that can only
// ever fall in whitespace is the half of that fix the client owns.
export function clampText(text: string): { clamped: string; overflow: boolean } {
  const t = text || "";
  const lines = t.split("\n");
  const overflow = lines.length > COLLAPSE_LINES || t.length > COLLAPSE_CHARS;
  if (!overflow) return { clamped: t, overflow };
  let clamped = lines.slice(0, COLLAPSE_LINES).join("\n");
  if (clamped.length > COLLAPSE_CHARS) {
    const cut = clamped.slice(0, COLLAPSE_CHARS);
    // back off to the last whitespace; if the "word" is longer than a quarter of
    // the budget (a URL, a hash, a minified blob) there is no sensible boundary
    // to find and the hard cut is the honest one.
    const sp = cut.search(/\s\S*$/);
    clamped = sp > COLLAPSE_CHARS * 0.75 ? cut.slice(0, sp) : cut;
  }
  return { clamped, overflow };
}
function Collapsible({ text, style, color }: {
  text: string; style: React.ComponentProps<typeof Text>["style"]; color: string;
}) {
  const tr = useT();
  const [open, setOpen] = useState(false);
  const { clamped, overflow } = clampText(text);
  return (
    <View>
      <Text selectable style={style}>{open || !overflow ? text : clamped + (overflow ? "\n…" : "")}</Text>
      {overflow ? (
        <Pressable hitSlop={6} onPress={() => setOpen((o) => !o)} style={{ marginTop: 4 }}>
          <Text style={{ color, fontSize: 11.5, fontWeight: "600" }}>{tr(open ? "transcript.showLess" : "transcript.showMore")}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

// Same clamp/toggle for rendered markdown: clamps the source string so the
// Markdown renderer only lays out the visible slice until expanded.
function CollapsibleMarkdown({ text, color }: { text: string; color: string }) {
  const tr = useT();
  const [open, setOpen] = useState(false);
  const { clamped, overflow } = clampText(text);
  return (
    <View>
      {/* the "…" is not decoration: without it a folded assistant message is
          indistinguishable from a complete one that happens to stop there. */}
      <Markdown>{open || !overflow ? text : clamped + "\n\n…"}</Markdown>
      {overflow ? (
        <Pressable hitSlop={6} onPress={() => setOpen((o) => !o)} style={{ marginTop: 2 }}>
          <Text style={{ color, fontSize: 11.5, fontWeight: "600" }}>{tr(open ? "transcript.showLess" : "transcript.showMore")}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function CopyBtn({ text, color }: { text: string; color: string }) {
  const t = useTheme();
  const [done, setDone] = useState(false);
  return (
    <Pressable hitSlop={8} onPress={async () => { await Clipboard.setStringAsync(text); setDone(true); setTimeout(() => setDone(false), 1400); }}>
      <Ionicons name={done ? "checkmark" : "copy-outline"} size={13} color={done ? t.ok : color} />
    </Pressable>
  );
}

// minimal line-level diff hunk — common prefix/suffix trimmed to a little context,
// changed middle as -removed / +added. Ported from web transcript.tsx DiffHunk.
function DiffHunk({ oldText, newText, t }: { oldText: string; newText: string; t: ThemeTokens }) {
  const a = (oldText || "").split("\n");
  const b = (newText || "").split("\n");
  let p = 0;
  while (p < a.length && p < b.length && a[p] === b[p]) p++;
  let sa = a.length, sb = b.length;
  while (sa > p && sb > p && a[sa - 1] === b[sb - 1]) { sa--; sb--; }
  const ctx = 2;
  const before = a.slice(Math.max(p - ctx, 0), p);
  const removed = a.slice(p, sa);
  const added = b.slice(p, sb);
  const after = a.slice(sa, Math.min(sa + ctx, a.length));
  const Row = ({ txt, mark, bg, fg, k }: { txt: string; mark: string; bg?: string; fg: string; k: string }) => (
    <View key={k} style={{ flexDirection: "row", backgroundColor: bg }}>
      <Text style={{ width: 14, color: fg, fontFamily: MONO, fontSize: 11.5 }}>{mark}</Text>
      <Text style={{ flex: 1, color: fg, fontFamily: MONO, fontSize: 11.5, lineHeight: 16 }}>{txt || " "}</Text>
    </View>
  );
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}>
      <View style={{ minWidth: "100%" }}>
        {before.map((l, i) => <Row key={"b" + i} k={"b" + i} txt={l} mark=" " fg={t.txtTertiary} />)}
        {removed.map((l, i) => <Row key={"d" + i} k={"d" + i} txt={l} mark="−" fg={t.danger} bg={t.danger + "1A"} />)}
        {added.map((l, i) => <Row key={"a" + i} k={"a" + i} txt={l} mark="+" fg={t.ok} bg={t.ok + "1A"} />)}
        {after.map((l, i) => <Row key={"f" + i} k={"f" + i} txt={l} mark=" " fg={t.txtTertiary} />)}
      </View>
    </ScrollView>
  );
}

function ToolDetailView({ d, t }: { d: ToolDetail; t: ThemeTokens }) {
  return (
    <View style={{ gap: 4 }}>
      {d.file ? <Text style={{ color: t.brand700, fontFamily: MONO, fontSize: 11.5 }}>{d.file}</Text> : null}
      {d.type === "edit" ? <DiffHunk oldText={d.old || ""} newText={d.new || ""} t={t} /> : null}
      {d.type === "multiedit" ? (d.edits || []).map((e, i) => <DiffHunk key={i} oldText={e.old} newText={e.new} t={t} />) : null}
      {d.type === "write" ? <DiffHunk oldText="" newText={d.content || ""} t={t} /> : null}
    </View>
  );
}

const TOOL_ICON: Record<string, keyof typeof Ionicons.glyphMap> = {
  Bash: "terminal", Read: "document-text-outline", Edit: "create-outline", Write: "create-outline",
  MultiEdit: "create-outline", NotebookEdit: "create-outline", Grep: "search", Glob: "search",
  WebFetch: "globe-outline", WebSearch: "globe-outline", Task: "hardware-chip-outline", TodoWrite: "list",
};
const toolIcon = (n: string): keyof typeof Ionicons.glyphMap =>
  TOOL_ICON[n] || (n.startsWith("mcp__") ? "globe-outline" : "settings-outline");

// Live elapsed for a RUNNING tool, so you can tell a slow step from a HUNG one
// (the recurring "läuft ewig / nichts passiert" question). Ticks every 5s and
// escalates colour: grey < 1min, amber < 5min, red after - a stuck bash/edit
// visibly turns amber then red instead of just showing a frozen "…".
function RunningClock({ ta, t }: { ta?: number; t: ThemeTokens }) {
  const [, tick] = useState(0);
  useEffect(() => { const iv = setInterval(() => tick((x) => x + 1), 5000); return () => clearInterval(iv); }, []);
  if (!ta) return <Text style={{ color: t.warn, fontSize: 10.5 }}>…</Text>;
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - ta));
  const label = secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m`;
  const color = secs > 300 ? t.danger : secs > 60 ? t.warn : t.txtTertiary;
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
      <Ionicons name="time-outline" size={11} color={color} />
      <Text style={{ color, fontSize: 10.5, fontWeight: "700" }}>{label}</Text>
    </View>
  );
}

// Per-turn context/token usage (DeepSeek / Claude-Code parity): a compact chip
// showing what THIS turn cost and the context it carried. ctx is everything the
// model saw (input + cache read + cache write); the 200k window drives the %.
const CTX_WINDOW = 200_000;
function tokK(n?: number): string {
  const v = n ?? 0;
  return v >= 1000 ? `${(v / 1000).toFixed(v >= 10_000 ? 0 : 1)}k` : `${v}`;
}
function UsageChip({ s, t }: { s: TStep; t: ThemeTokens }) {
  const ctx = s.ctx ?? 0;
  const pct = Math.min(100, Math.round((ctx / CTX_WINDOW) * 100));
  const cached = (s.cacheRead ?? 0) > 0;
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 3, paddingHorizontal: 2, flexWrap: "wrap" }}>
      <Ionicons name="pulse-outline" size={12} color={t.txtTertiary} />
      <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>
        Kontext {tokK(ctx)} · {pct}%
      </Text>
      <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>
        · ↓{tokK(s.tokIn)} ↑{tokK(s.tokOut)}{cached ? ` · Cache ${tokK(s.cacheRead)}` : ""}
      </Text>
    </View>
  );
}

function ToolCard({ s, t, defaultOpen }: { s: TStep; t: ThemeTokens; defaultOpen?: boolean }) {
  const tr = useT();
  const status = toolStatus(s);
  // Auto-open the running tool and the latest tool so output is visible without
  // a tap (Paseo-style: the tail of the run is expanded, history stays folded).
  const [open, setOpen] = useState(!!defaultOpen || status === "running");
  const hasResult = !!(s.result && s.result.trim());
  const expandable = hasResult || !!s.detail;
  const err = status === "failed";
  return (
    <View style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, backgroundColor: t.surface1, overflow: "hidden" }}>
      <Pressable onPress={() => expandable && setOpen((o) => !o)}
        style={{ flexDirection: "row", alignItems: "center", gap: 7, paddingHorizontal: 9, paddingVertical: 7 }}>
        <Ionicons name={toolIcon(s.tool || "")} size={13} color={err ? t.danger : t.ai} />
        {/* the server's human verb ("Bearbeiten", "Befehl", "PC · Click") reads
            like Paseo's action rows; the raw tool name stays the icon key */}
        <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "700" }}>{s.label || s.tool}</Text>
        <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12, flex: 1 }}>{s.text}</Text>
        {status === "running" ? <RunningClock ta={s.ta} t={t} /> : null}
        {status === "canceled" ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
            <Ionicons name="remove-circle-outline" size={11} color={t.warn} />
            <Text style={{ color: t.warn, fontSize: 10, fontWeight: "600" }}>{tr("transcript.toolCanceled")}</Text>
            {s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>· {tsLabel(s)}</Text> : null}
          </View>
        ) : null}
        {status === "failed" ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
            <Ionicons name="close-circle-outline" size={11} color={t.danger} />
            <Text style={{ color: t.danger, fontSize: 10, fontWeight: "600" }}>{tr("transcript.toolFailed")}</Text>
            {s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>· {tsLabel(s)}</Text> : null}
          </View>
        ) : null}
        {status === "completed" && s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{tsLabel(s)}</Text> : null}
        {expandable ? <Ionicons name={open ? "chevron-down" : "chevron-forward"} size={12} color={t.txtTertiary} /> : null}
      </Pressable>
      {open ? (
        <View style={{ paddingHorizontal: 9, paddingBottom: 9, gap: 6 }}>
          {s.detail ? <ToolDetailView d={s.detail} t={t} /> : null}
          {hasResult ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false}
              style={{ backgroundColor: t.canvas, borderRadius: 6 }}>
              <View style={{ padding: 8 }}>
                <Collapsible text={s.result || ""} color={t.ai}
                  style={{ fontFamily: MONO, fontSize: 11.5, color: t.txtSecondary, lineHeight: 16 }} />
              </View>
            </ScrollView>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const Thought = memo(function Thought({ s, t }: { s: TStep; t: ThemeTokens }) {
  const tr = useT();
  const [open, setOpen] = useState(false);
  return (
    <View style={{ borderLeftWidth: 2, borderLeftColor: t.accent2, paddingLeft: 8 }}>
      <Pressable onPress={() => setOpen((o) => !o)} style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
        <Ionicons name={open ? "chevron-down" : "chevron-forward"} size={11} color={t.accent2} />
        <Text style={{ color: t.accent2, fontSize: 12, fontStyle: "italic" }}>{tr("transcript.thinking")}</Text>
      </Pressable>
      {open ? <View style={{ marginTop: 4 }}><Collapsible text={s.text || ""} color={t.accent2}
        style={{ color: t.txtTertiary, fontSize: 12.5, fontStyle: "italic", lineHeight: 18 }} /></View> : null}
    </View>
  );
});

function Todos({ s, t }: { s: TStep; t: ThemeTokens }) {
  const tr = useT();
  return (
    <View style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, padding: 9, backgroundColor: t.surface1, gap: 3 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", marginBottom: 2 }}>{tr("transcript.todos")}</Text>
      {s.todos?.map((td, i) => (
        <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Ionicons
            name={td.status === "completed" ? "checkmark-circle" : td.status === "in_progress" ? "ellipse" : "ellipse-outline"}
            size={13} color={td.status === "completed" ? t.ok : td.status === "in_progress" ? t.warn : t.txtTertiary} />
          <Text style={{ flex: 1, fontSize: 12.5,
            color: td.status === "completed" ? t.txtTertiary : t.txtPrimary,
            textDecorationLine: td.status === "completed" ? "line-through" : "none" }}>{td.content}</Text>
        </View>
      ))}
    </View>
  );
}

// Turn-end economics label: "in → out" in compact-k form. The usage arrives on
// the turn's OWN lifecycle event (Phase 3.2), not on a flat step.
function usageLabel(u?: TurnUsage): string {
  if (!u) return "";
  const inn = (u.input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0);
  const out = u.output_tokens ?? 0;
  if (!inn && !out) return "";
  const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));
  return `${k(inn)} → ${k(out)}`;
}
function costLabel(cost?: number | null): string {
  return typeof cost === "number" && cost > 0 ? ` · $${cost.toFixed(4)}` : "";
}

// Stable per-row key so React reconciles by identity across each refetch/poll
// instead of remounting the whole list (which collapsed expanded tool cards and
// read as a "strange rebuild"). Derived from the sort epoch + kind + a content
// fingerprint; a per-render counter disambiguates genuine collisions.
function keyFactory() {
  const seen = new Map<string, number>();
  return (s: TStep, i: number): string => {
    const sig = (s.tool || "") + "|" + (s.text || "").slice(0, 40);
    const base = `${s.ta ?? ""}:${s.kind ?? ""}:${sig}`;
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return n ? `${base}#${n}` : base || `row-${i}`;
  };
}

const ASK_OPEN = "<helmdeck-ask";

/** LAST-RESORT RENDER GUARD for the <helmdeck-ask> sentinel.
 *
 *  The block is machine syntax - an interaction, not something anyone reads -
 *  and it is removed at its ONE owner, at event time, on every path that
 *  produces it (cells/copilot/copilot.chat for Henry, cells/engineer/turnrunner
 *  for a card worker, plus the live readers in spine/agent/claude_sessions).
 *  This is the net under all of them, and it lives in the SHARED transcript so
 *  every surface is covered by the same three lines: the board chat, the card
 *  chat, the card-scoped Henry tab. The board chat rendering raw JSON at the
 *  owner (screenshot 2026-08-29 17:56) is the defect it exists to make
 *  unrepeatable - a future feed that forgets to clean its text degrades to a
 *  hidden block instead of a screenful of `{"label": ...`.
 *
 *  It STRIPS and never parses. Reading the JSON here to build options would put
 *  a second copy of the protocol's grammar on the phone, and the two would drift
 *  the first time either changed; spine/ops/ask.py stays the only one that knows
 *  this shape. A block that reaches this function is therefore shown as nothing,
 *  which is also what the brief calls for when the block is malformed - and it
 *  means the daemon-side owner is what wants fixing, not this. */
function stripAsk(text: string): string {
  const out = text.replace(/<helmdeck-ask>[\s\S]*?<\/helmdeck-ask>/gi, "");
  // An UNCLOSED tag - the model is still typing it, or the reply was truncated
  // mid-block. Cut from the tag onward: the half a closing tag never arrives for
  // would otherwise stream in character by character.
  const i = out.toLowerCase().indexOf(ASK_OPEN);
  return (i === -1 ? out : out.slice(0, i)).trim();
}

function readable(steps: TStep[]): TStep[] {
  const out: TStep[] = [];
  for (const s of steps) {
    const raw = s.text ?? "";
    const s2 = raw.toLowerCase().includes(ASK_OPEN) ? { ...s, text: stripAsk(raw) } : s;
    // An empty text row is a blank bubble with a sender line above it. It shows
    // up when a reply was ONLY a block (the watch/glasses briefs invite exactly
    // that) and nothing readable survived cleaning - here or on the daemon.
    // Streaming rows are exempt: theirs is empty for a moment by design.
    if (s2.kind === "text" && !s2.streaming && !(s2.text ?? "").trim()) continue;
    out.push(s2);
  }
  return out;
}

export function Transcript({ steps: rawSteps, onRewind, me }: { steps: TStep[]; onRewind?: (text: string) => void; me?: string }) {
  const t = useTheme();
  const tr = useT();
  const steps = readable(rawSteps);
  const keyFor = keyFactory();
  let lastToolIdx = -1;
  for (let i = steps.length - 1; i >= 0; i--) { if (steps[i].kind === "tool") { lastToolIdx = i; break; } }
  let lastTextSender: string | null = null;   // consecutive-run grouping (Slack-style)
  return (
    <View style={{ gap: 8 }}>
      {steps.map((s, i) => {
        const kind = s.kind;
        const key = keyFor(s, i);
        // Turn lifecycle as first-class items (Phase 3.2/3.3): `started` renders
        // nothing (the owner's message right above it already marks the turn),
        // `completed` is a quiet usage line, `canceled` a centered marker,
        // `failed` a real error card with the error text + usage.
        if (kind === "turn") {
          if (s.event === "failed") return (
            <View key={key} style={{ borderWidth: 1, borderColor: t.danger + "66", borderRadius: 8, padding: 9, backgroundColor: t.danger + "12", gap: 4 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
                <Ionicons name="alert-circle" size={13} color={t.danger} />
                <Text style={{ color: t.danger, fontSize: 12, fontWeight: "700", flex: 1 }}>{tr("transcript.turnFailed")}</Text>
                {s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{tsLabel(s)}</Text> : null}
              </View>
              {s.error ? <Text style={{ color: t.txtSecondary, fontFamily: MONO, fontSize: 11.5, lineHeight: 16 }}>{s.error}</Text> : null}
              {usageLabel(s.usage) ? (
                <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{usageLabel(s.usage)}{costLabel(s.cost)}</Text>
              ) : null}
            </View>);
          if (s.event === "canceled") return (
            <View key={key} style={{ alignItems: "center", paddingVertical: 4 }}>
              <Text style={{ color: t.warn, fontSize: 11 }}>⏹ {tr("transcript.turnCanceled")}{s.ts ? ` · ${tsLabel(s)}` : ""}</Text>
            </View>);
          if (s.event === "completed" && usageLabel(s.usage)) return (
            <View key={key} style={{ flexDirection: "row", justifyContent: "flex-end", alignItems: "center", gap: 4, paddingVertical: 1 }}>
              <Ionicons name="checkmark-circle-outline" size={10} color={t.txtTertiary} />
              <Text style={{ color: t.txtTertiary, fontSize: 10 }}>
                {tr("transcript.turnDone")} · {usageLabel(s.usage)}{costLabel(s.cost)}{s.ts ? ` · ${tsLabel(s)}` : ""}
              </Text>
            </View>);
          return null;   // "started" (and a usage-less completed) add no ink
        }
        // A stream/runtime error as its own item (Phase 3.3), never a prose bubble.
        if (kind === "error") return (
          <View key={key} style={{ borderWidth: 1, borderColor: t.danger + "66", borderRadius: 8, padding: 9, backgroundColor: t.danger + "12" }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
              <Ionicons name="alert-circle" size={13} color={t.danger} />
              <Text style={{ color: t.danger, fontSize: 12, flex: 1 }}>{s.text || s.error || ""}</Text>
              {s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{tsLabel(s)}</Text> : null}
            </View>
          </View>);
        if (kind === "compaction") return (
          <View key={key} style={{ alignItems: "center", paddingVertical: 4 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 11 }}>⟳ {tr("transcript.compacted")}{s.ts ? ` · ${tsLabel(s)}` : ""}</Text>
          </View>);
        if (kind === "system" || kind === "note") {
          const good = /\b(MERGED|ACCEPTED|GATE PASSED|DEPLOY HOOK OK|DISPATCHED|CONNECTOR INSTALLED)\b/.test(s.text || "");
          const bad = /\b(FAILED|BOUNCED|conflict)\b/i.test(s.text || "");
          const c = bad ? t.danger : good ? t.ok : t.txtTertiary;
          return (
            <View key={key} style={{ flexDirection: "row", alignItems: "center", gap: 7, paddingVertical: 2 }}>
              <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: c }} />
              <Text style={{ color: c, fontSize: 11.5, flex: 1 }}>{s.text}</Text>
              {s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{tsLabel(s)}</Text> : null}
              <CopyBtn text={s.text || ""} color={t.txtTertiary} />
            </View>);
        }
        if (kind === "usage") return <UsageChip key={key} s={s} t={t} />;
        if (kind === "tool") return <ToolCard key={key} s={s} t={t} defaultOpen={i === lastToolIdx} />;
        if (kind === "todos") return <Todos key={key} s={s} t={t} />;
        if (kind === "plan") return (
          <View key={key} style={{ borderWidth: 1, borderColor: t.accent + "55", borderRadius: 8, padding: 9, backgroundColor: t.accent + "12" }}>
            <Text style={{ color: t.accent, fontSize: 11, fontWeight: "700", marginBottom: 4 }}>{tr("transcript.plan")}</Text>
            <Markdown>{s.text || ""}</Markdown>
          </View>);
        if (kind === "thinking") return <Thought key={key} s={s} t={t} />;
        if (kind === "result") return <Text key={key} style={{ color: t.txtTertiary, fontSize: 12 }}>{s.text}</Text>;

        const mine = s.by ? s.by === me : (s.role === "user" || s.cls === "user");
        // byKind is authoritative; `agent` is the legacy flag old timeline
        // rows carry (before this field existed) and still maps to "henry".
        const byKind = s.byKind ?? (s.agent ? "henry" : mine ? "human" : "worker");
        const ac = byKind === "henry" ? t.accent2 : byKind === "human" && !mine ? t.human : t.accent;
        const senderKey = mine ? "me" : byKind + ":" + (s.by || "");
        const showHeader = !mine && senderKey !== lastTextSender;
        lastTextSender = senderKey;
        // A worker step normally has no `by` (drivers.py only stamps it on the
        // human's steer) and falls back to the generic "Worker". When one DOES
        // carry it - the board chat's mirrored card events, labelled
        // "Frage · <Kartenname>" - that label must win, or every card in the
        // inbox reads as the same anonymous "Worker" and the owner cannot tell
        // WHICH card is asking.
        const senderLabel = byKind === "henry" ? tr("transcript.boardAgent")
          : byKind === "worker" ? (s.by || tr("transcript.worker")) : (s.by || "?");
        const senderIcon = byKind === "henry" ? "sparkles-outline"
          : byKind === "worker" ? "construct-outline" : "person-outline";
        if (mine) return (
          <View key={key} style={{ alignSelf: "flex-end", maxWidth: "88%", backgroundColor: ac + "22", borderRadius: 10, padding: 10 }}>
            <Collapsible text={s.text || ""} color={ac}
              style={{ color: t.txtPrimary, fontSize: 14, lineHeight: 20 }} />
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10, marginTop: 4, justifyContent: "flex-end" }}>
              {s.to ? <Text style={{ color: s.to === "henry" ? t.accent2 : t.accent, fontSize: 10, fontWeight: "700" }}>
                → {s.to === "henry" ? tr("transcript.boardAgent") : tr("transcript.worker")}</Text> : null}
              {s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{tsLabel(s)}</Text> : null}
              <CopyBtn text={s.text || ""} color={t.txtTertiary} />
              {onRewind ? <Pressable hitSlop={8} onPress={() => onRewind(s.text || "")}><Ionicons name="arrow-undo-outline" size={13} color={t.txtTertiary} /></Pressable> : null}
            </View>
          </View>);
        // not-mine text (Henry, the Worker, or another human) — a sender
        // header only on the first message of a consecutive run from them
        // (Slack-style grouping), colored/badged by who's speaking.
        return (
          <View key={key} style={{ backgroundColor: t.surface1, borderRadius: 10, padding: 10, borderWidth: 1, borderColor: byKind !== "worker" ? ac + "66" : t.borderSubtle }}>
            {showHeader ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginBottom: 4 }}>
                <Ionicons name={senderIcon} size={11} color={ac} />
                <Text style={{ color: ac, fontSize: 10.5, fontWeight: "700" }}>{senderLabel}</Text>
              </View>
            ) : null}
            <CollapsibleMarkdown text={s.text || ""} color={ac} />
            {s.streaming ? <Text style={{ color: t.accent }}>▍</Text> : null}
            {!s.streaming ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 10, marginTop: 4 }}>
                {s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{tsLabel(s)}</Text> : null}
                <View style={{ flex: 1 }} />
                <CopyBtn text={s.text || ""} color={t.txtTertiary} />
              </View>
            ) : null}
          </View>);
      })}
    </View>
  );
}
