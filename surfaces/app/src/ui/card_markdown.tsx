import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { useState } from "react";
import { Linking, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";

// Markdown -> React-Native for the card chat, no dependency. Adapted from the
// archived web/components/markdown.tsx (DOM) to RN Views/Text. Covers what a
// coding agent emits: fenced code, inline code, bold/italic/strike, headings,
// bullet & ordered lists (nested, task-list), blockquotes, rules, links, tables,
// paragraphs, line breaks.

const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }) as string;

const INLINE_SRC =
  "(`[^`]+`)|(\\*\\*[^*]+\\*\\*)|(__[^_]+__)|(\\*[^*\\n]+\\*)|((?<![A-Za-z0-9])_[^_\\n]+_(?![A-Za-z0-9]))|(~~[^~]+~~)|(\\[[^\\]]+\\]\\([^)]+\\))|(https?:\\/\\/[^\\s)]+)";

function inline(text: string, kp: string, t: ThemeTokens): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = new RegExp(INLINE_SRC, "g");
  let last = 0, i = 0, m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tk = m[0], k = kp + "i" + i++;
    if (tk.startsWith("`")) out.push(
      <Text key={k} style={{ fontFamily: MONO, fontSize: 12.5, color: t.brand700, backgroundColor: t.surface2 }}>{tk.slice(1, -1)}</Text>);
    else if (tk.startsWith("**") || tk.startsWith("__")) out.push(
      <Text key={k} style={{ fontWeight: "700" }}>{inline(tk.slice(2, -2), k, t)}</Text>);
    else if (tk.startsWith("~~")) out.push(
      <Text key={k} style={{ textDecorationLine: "line-through", color: t.txtTertiary }}>{tk.slice(2, -2)}</Text>);
    else if (tk.startsWith("[")) {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tk)!;
      out.push(<Text key={k} style={{ color: t.accent, textDecorationLine: "underline" }}
        onPress={() => Linking.openURL(mm[2]).catch(() => {})}>{mm[1]}</Text>);
    } else if (tk.startsWith("http")) {
      out.push(<Text key={k} style={{ color: t.accent, textDecorationLine: "underline" }}
        onPress={() => Linking.openURL(tk).catch(() => {})}>{tk}</Text>);
    } else out.push(<Text key={k} style={{ fontStyle: "italic" }}>{inline(tk.slice(1, -1), k, t)}</Text>);
    last = m.index + tk.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

function listRegion(lines: string[], start: number) {
  const items: { indent: number; ordered: boolean; text: string }[] = [];
  let i = start;
  while (i < lines.length) {
    const m = LIST_RE.exec(lines[i]);
    if (!m) {
      if (!lines[i].trim() && i + 1 < lines.length && LIST_RE.test(lines[i + 1])) { i++; continue; }
      break;
    }
    items.push({ indent: m[1].replace(/\t/g, "  ").length, ordered: /\d/.test(m[2]), text: m[3] });
    i++;
  }
  return { items, next: i };
}

// light token highlighting for code, ported minimal from codeblock.tsx
const KEYWORDS = new Set(
  ("const let var function return if else for while do switch case break continue new class extends " +
   "import from export default async await try catch finally throw typeof void delete this super null " +
   "true false undefined def elif lambda pass with as True False None and or not is self print raise " +
   "except in of fn pub use struct enum impl match type interface public private static func go defer range").split(" "));

// langs where `#` starts a line comment (not JS/TS/C); mirrors web codeblock.tsx.
const HASH_COMMENT = /^(py|python|rb|ruby|sh|bash|zsh|yaml|yml|toml|ini|conf|makefile|make|dockerfile|r|pl)$/i;

function CodeBlock({ code, lang }: { code: string; lang: string }) {
  const t = useTheme();
  const tr = useT();
  const [copied, setCopied] = useState(false);
  // `#` is a comment only for hash-comment langs; otherwise use `//` (+ `/* */`).
  // With no language, default to `//`-only so `#` isn't miscolored.
  const hash = !!lang && HASH_COMMENT.test(lang);
  const re = hash
    ? /(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d[\d_.eExXbB]*\b)|([A-Za-z_$][A-Za-z0-9_$]*)/g
    : /(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d[\d_.eExXbB]*\b)|([A-Za-z_$][A-Za-z0-9_$]*)/g;
  const nodes: React.ReactNode[] = [];
  let last = 0, i = 0, m: RegExpExecArray | null;
  while ((m = re.exec(code))) {
    if (m.index > last) nodes.push(code.slice(last, m.index));
    const tk = m[0], k = "c" + i++;
    if (m[1]) nodes.push(<Text key={k} style={{ color: t.txtTertiary, fontStyle: "italic" }}>{tk}</Text>);
    else if (m[2]) nodes.push(<Text key={k} style={{ color: t.ok }}>{tk}</Text>);
    else if (m[3]) nodes.push(<Text key={k} style={{ color: t.warn }}>{tk}</Text>);
    else if (m[4] && KEYWORDS.has(tk)) nodes.push(<Text key={k} style={{ color: t.accent2 }}>{tk}</Text>);
    else nodes.push(tk);
    last = m.index + tk.length;
  }
  if (last < code.length) nodes.push(code.slice(last));
  return (
    <View style={{ backgroundColor: t.canvas, borderRadius: 8, borderWidth: 1, borderColor: t.borderSubtle, marginVertical: 4, overflow: "hidden" }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 5,
        borderBottomWidth: 1, borderBottomColor: t.borderSubtle, backgroundColor: t.surface2 }}>
        {/* `lang` is the fence's own language tag (ts, py, …) - a technical
            token, never translated; only the fallback label is chrome. */}
        <Text style={{ color: t.txtTertiary, fontSize: 10.5, flex: 1 }}>{lang || tr("transcript.code")}</Text>
        <Pressable hitSlop={8} onPress={async () => { await Clipboard.setStringAsync(code); setCopied(true); setTimeout(() => setCopied(false), 1400); }}>
          <Ionicons name={copied ? "checkmark" : "copy-outline"} size={13} color={copied ? t.ok : t.txtTertiary} />
        </Pressable>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ padding: 10 }}>
        <Text selectable style={{ fontFamily: MONO, fontSize: 12, color: t.txtPrimary, lineHeight: 18 }}>{nodes}</Text>
      </ScrollView>
    </View>
  );
}

const cells = (row: string) => row.replace(/^\s*\|?|\|?\s*$/g, "").split("|").map((c) => c.trim());

export function Markdown({ children }: { children: string }) {
  const t = useTheme();
  const lines = (children || "").replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0, b = 0;
  const key = () => "b" + b++;
  const p = { color: t.txtPrimary, fontSize: 14, lineHeight: 20 } as const;

  while (i < lines.length) {
    const line = lines[i];

    const fence = /^\s*```(\w+)?\s*$/.exec(line);
    if (fence) {
      const lang = fence[1] || "";
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++]);
      i++;
      blocks.push(<CodeBlock key={key()} code={buf.join("\n")} lang={lang} />);
      continue;
    }
    if (!line.trim()) { i++; continue; }

    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const lvl = Math.min(h[1].length, 6);
      const size = [0, 19, 17, 15.5, 14.5, 14, 13.5][lvl];
      blocks.push(<Text key={key()} selectable style={{ color: t.txtPrimary, fontSize: size, fontWeight: "700", marginTop: 6, marginBottom: 2 }}>{inline(h[2], key(), t)}</Text>);
      i++; continue;
    }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push(<View key={key()} style={{ height: 1, backgroundColor: t.borderSubtle, marginVertical: 8 }} />); i++; continue;
    }
    if (/^\s*>\s?/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      blocks.push(
        <View key={key()} style={{ borderLeftWidth: 3, borderLeftColor: t.borderStrong, paddingLeft: 10, marginVertical: 4 }}>
          <Text selectable style={{ ...p, color: t.txtSecondary, fontStyle: "italic" }}>{inline(buf.join(" "), key(), t)}</Text>
        </View>); continue;
    }
    // GFM table
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?[\s:-]*-[-\s:|]*\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) { rows.push(cells(lines[i])); i++; }
      blocks.push(
        <View key={key()} style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 6, marginVertical: 4, overflow: "hidden" }}>
          <View style={{ flexDirection: "row", backgroundColor: t.surface2 }}>
            {head.map((c, j) => <Text key={j} selectable style={{ flex: 1, padding: 6, color: t.txtSecondary, fontSize: 12.5, fontWeight: "700" }}>{c}</Text>)}
          </View>
          {rows.map((r, ri) => (
            <View key={ri} style={{ flexDirection: "row", borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
              {head.map((_, j) => <Text key={j} selectable style={{ flex: 1, padding: 6, color: t.txtPrimary, fontSize: 12.5 }}>{inline(r[j] ?? "", key(), t)}</Text>)}
            </View>
          ))}
        </View>); continue;
    }
    // list
    if (LIST_RE.test(line)) {
      const { items, next } = listRegion(lines, i);
      const base = items[0].indent;
      items.forEach((it, idx) => {
        const depth = Math.max(0, Math.round((it.indent - base) / 2));
        const task = /^\[([ xX])\]\s+(.*)$/.exec(it.text);
        const bullet = it.ordered ? `${idx + 1}.` : "•";
        blocks.push(
          <View key={key()} style={{ flexDirection: "row", paddingLeft: 8 + depth * 16, marginVertical: 1 }}>
            {task ? (
              <Ionicons name={task[1].toLowerCase() === "x" ? "checkbox" : "square-outline"} size={14}
                color={task[1].toLowerCase() === "x" ? t.ok : t.txtTertiary} style={{ marginRight: 6, marginTop: 3 }} />
            ) : <Text style={{ color: t.txtTertiary, marginRight: 6, fontSize: 14 }}>{bullet}</Text>}
            <Text selectable style={{ ...p, flex: 1 }}>{inline(task ? task[2] : it.text, key(), t)}</Text>
          </View>);
      });
      i = next; continue;
    }
    // paragraph
    const buf: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,6}\s|>\s?|[-*+]\s|\d+[.)]\s|-{3,}\s*$|\*{3,}\s*$)/.test(lines[i])) {
      buf.push(lines[i++]);
    }
    const k = key();
    blocks.push(
      <Text key={k} selectable style={{ ...p, marginVertical: 2 }}>
        {buf.map((ln, j) => <React.Fragment key={k + "l" + j}>{j > 0 ? "\n" : null}{inline(ln, k + "l" + j, t)}</React.Fragment>)}
      </Text>);
  }
  return <View style={{ gap: 2 }}>{blocks}</View>;
}
