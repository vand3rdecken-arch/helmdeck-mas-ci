import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { memo, useState } from "react";
import { Platform, Pressable, ScrollView, Text, View } from "react-native";
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
export interface TStep {
  role?: string;
  kind?: "text" | "thinking" | "tool" | "result" | "todos" | "plan" | "compaction" | "system" | "note" | string;
  cls?: string;
  text?: string; tool?: string; result?: string; ok?: boolean; running?: boolean; ts?: string;
  streaming?: boolean; detail?: ToolDetail;
  todos?: { content: string; status: string }[];
}

// Clamps long text and reveals a "Mehr anzeigen" / "Weniger anzeigen" toggle
// only when it actually overflows a threshold (mirrors web transcript Collapsible).
const COLLAPSE_LINES = 24;
const COLLAPSE_CHARS = 1600;
function clampText(text: string): { clamped: string; overflow: boolean } {
  const t = text || "";
  const lines = t.split("\n");
  const overflow = lines.length > COLLAPSE_LINES || t.length > COLLAPSE_CHARS;
  if (!overflow) return { clamped: t, overflow };
  let clamped = lines.slice(0, COLLAPSE_LINES).join("\n");
  if (clamped.length > COLLAPSE_CHARS) clamped = clamped.slice(0, COLLAPSE_CHARS);
  return { clamped, overflow };
}
function Collapsible({ text, style, color }: {
  text: string; style: React.ComponentProps<typeof Text>["style"]; color: string;
}) {
  const [open, setOpen] = useState(false);
  const { clamped, overflow } = clampText(text);
  return (
    <View>
      <Text selectable style={style}>{open || !overflow ? text : clamped + (overflow ? "\n…" : "")}</Text>
      {overflow ? (
        <Pressable hitSlop={6} onPress={() => setOpen((o) => !o)} style={{ marginTop: 4 }}>
          <Text style={{ color, fontSize: 11.5, fontWeight: "600" }}>{open ? "Weniger anzeigen" : "Mehr anzeigen"}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

// Same clamp/toggle for rendered markdown: clamps the source string so the
// Markdown renderer only lays out the visible slice until expanded.
function CollapsibleMarkdown({ text, color }: { text: string; color: string }) {
  const [open, setOpen] = useState(false);
  const { clamped, overflow } = clampText(text);
  return (
    <View>
      <Markdown>{open || !overflow ? text : clamped}</Markdown>
      {overflow ? (
        <Pressable hitSlop={6} onPress={() => setOpen((o) => !o)} style={{ marginTop: 2 }}>
          <Text style={{ color, fontSize: 11.5, fontWeight: "600" }}>{open ? "Weniger anzeigen" : "Mehr anzeigen"}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function CopyBtn({ text, color }: { text: string; color: string }) {
  const [done, setDone] = useState(false);
  return (
    <Pressable hitSlop={8} onPress={async () => { await Clipboard.setStringAsync(text); setDone(true); setTimeout(() => setDone(false), 1400); }}>
      <Ionicons name={done ? "checkmark" : "copy-outline"} size={13} color={done ? "#4CB86A" : color} />
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

function ToolCard({ s, t }: { s: TStep; t: ThemeTokens }) {
  const [open, setOpen] = useState(false);
  const hasResult = !!(s.result && s.result.trim());
  const expandable = hasResult || !!s.detail;
  const err = s.ok === false;
  return (
    <View style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, backgroundColor: t.surface1, overflow: "hidden" }}>
      <Pressable onPress={() => expandable && setOpen((o) => !o)}
        style={{ flexDirection: "row", alignItems: "center", gap: 7, paddingHorizontal: 9, paddingVertical: 7 }}>
        <Ionicons name={toolIcon(s.tool || "")} size={13} color={err ? t.danger : t.ai} />
        <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "700" }}>{s.tool}</Text>
        <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12, flex: 1 }}>{s.text}</Text>
        {s.running ? <Text style={{ color: t.warn, fontSize: 10.5 }}>…</Text> : null}
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
  const [open, setOpen] = useState(false);
  return (
    <View style={{ borderLeftWidth: 2, borderLeftColor: t.accent2, paddingLeft: 8 }}>
      <Pressable onPress={() => setOpen((o) => !o)} style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
        <Ionicons name={open ? "chevron-down" : "chevron-forward"} size={11} color={t.accent2} />
        <Text style={{ color: t.accent2, fontSize: 12, fontStyle: "italic" }}>Thinking</Text>
      </Pressable>
      {open ? <View style={{ marginTop: 4 }}><Collapsible text={s.text || ""} color={t.accent2}
        style={{ color: t.txtTertiary, fontSize: 12.5, fontStyle: "italic", lineHeight: 18 }} /></View> : null}
    </View>
  );
});

function Todos({ s, t }: { s: TStep; t: ThemeTokens }) {
  return (
    <View style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, padding: 9, backgroundColor: t.surface1, gap: 3 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", marginBottom: 2 }}>PLAN / TO-DOS</Text>
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

export function Transcript({ steps, onRewind }: { steps: TStep[]; onRewind?: (text: string) => void }) {
  const t = useTheme();
  return (
    <View style={{ gap: 8 }}>
      {steps.map((s, i) => {
        const kind = s.kind;
        if (kind === "compaction") return (
          <View key={i} style={{ alignItems: "center", paddingVertical: 4 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 11 }}>⟳ Context compacted{s.ts ? ` · ${s.ts}` : ""}</Text>
          </View>);
        if (kind === "system" || kind === "note") {
          const good = /\b(MERGED|ACCEPTED|GATE PASSED|DEPLOY HOOK OK|DISPATCHED|CONNECTOR INSTALLED)\b/.test(s.text || "");
          const bad = /\b(FAILED|BOUNCED|conflict)\b/i.test(s.text || "");
          const c = bad ? t.danger : good ? t.ok : t.txtTertiary;
          return (
            <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 7, paddingVertical: 2 }}>
              <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: c }} />
              <Text style={{ color: c, fontSize: 11.5, flex: 1 }}>{s.text}</Text>
              {s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{s.ts}</Text> : null}
            </View>);
        }
        if (kind === "tool") return <ToolCard key={i} s={s} t={t} />;
        if (kind === "todos") return <Todos key={i} s={s} t={t} />;
        if (kind === "plan") return (
          <View key={i} style={{ borderWidth: 1, borderColor: t.accent + "55", borderRadius: 8, padding: 9, backgroundColor: t.accent + "12" }}>
            <Text style={{ color: t.accent, fontSize: 11, fontWeight: "700", marginBottom: 4 }}>PLAN</Text>
            <Markdown>{s.text || ""}</Markdown>
          </View>);
        if (kind === "thinking") return <Thought key={i} s={s} t={t} />;
        if (kind === "result") return <Text key={i} style={{ color: t.txtTertiary, fontSize: 12 }}>{s.text}</Text>;

        const mine = s.role === "user" || s.cls === "user";
        if (mine) return (
          <View key={i} style={{ alignSelf: "flex-end", maxWidth: "88%", backgroundColor: t.accent + "22", borderRadius: 10, padding: 10 }}>
            <Collapsible text={s.text || ""} color={t.accent}
              style={{ color: t.txtPrimary, fontSize: 14, lineHeight: 20 }} />
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10, marginTop: 4, justifyContent: "flex-end" }}>
              {s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{s.ts}</Text> : null}
              <CopyBtn text={s.text || ""} color={t.txtTertiary} />
              {onRewind ? <Pressable hitSlop={8} onPress={() => onRewind(s.text || "")}><Ionicons name="arrow-undo-outline" size={13} color={t.txtTertiary} /></Pressable> : null}
            </View>
          </View>);
        // assistant text
        return (
          <View key={i} style={{ backgroundColor: t.surface1, borderRadius: 10, padding: 10, borderWidth: 1, borderColor: t.borderSubtle }}>
            <CollapsibleMarkdown text={s.text || ""} color={t.accent} />
            {s.streaming ? <Text style={{ color: t.accent }}>▍</Text> : null}
            {!s.streaming ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 10, marginTop: 4 }}>
                {s.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>{s.ts}</Text> : null}
                <View style={{ flex: 1 }} />
                <CopyBtn text={s.text || ""} color={t.txtTertiary} />
              </View>
            ) : null}
          </View>);
      })}
    </View>
  );
}
