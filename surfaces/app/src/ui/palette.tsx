// Command palette (Cmd/Ctrl-K) — the surfaces/desktop/web power-nav from the old web UI
// (archive/web/components/palette.tsx). Fuzzy-jumps to any card or view; a ">"
// prefix runs a board-copilot command inline. On web it mounts under a global
// Cmd/Ctrl-K key handler (app/_layout.tsx); on native it's opened via the tab
// bar / a button and renders whenever the `open` state is true.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { create } from "zustand";

import { api } from "@/data/client";
import type { Track } from "@/data/types";
import { useLang, useT } from "@/i18n";
import { statusColor, useTheme } from "@/theme";
import { Dot } from "./kit";

export const isWeb = Platform.OS === "web";

interface PaletteState { open: boolean; toggle: () => void; show: () => void; hide: () => void }
export const usePalette = create<PaletteState>((set) => ({
  open: false,
  toggle: () => set((s) => ({ open: !s.open })),
  show: () => set({ open: true }),
  hide: () => set({ open: false }),
}));

type Row =
  | { kind: "view"; label: string; hint: string; go: string }
  | { kind: "card"; label: string; hint: string; go: string; status?: string };

// Label + hint are dict keys, resolved per render language. The labels reuse the
// nav.* vocabulary the tab bar already speaks, so the palette never invents a
// second name for the same screen.
const VIEWS: { label: string; hint: string; go: string }[] = [
  { label: "nav.board", hint: "palette.hint.board", go: "/(tabs)/board" },
  { label: "nav.needsYou", hint: "status.needsYou", go: "/(tabs)/needs" },
  { label: "nav.dashboard", hint: "palette.hint.dashboard", go: "/(tabs)" },
  { label: "nav.history", hint: "palette.hint.history", go: "/history" },
  { label: "nav.processes", hint: "palette.hint.processes", go: "/processes" },
  { label: "nav.recordings", hint: "nav.recordings", go: "/recordings" },
  { label: "nav.sessions", hint: "palette.hint.sessions", go: "/sessions" },
  { label: "nav.connectors", hint: "nav.connectors", go: "/connectors" },
  { label: "nav.automation", hint: "palette.hint.automation", go: "/automation" },
  { label: "nav.settings", hint: "nav.settings", go: "/settings" },
  { label: "palette.newRequest", hint: "palette.hint.new", go: "/new" },
  { label: "nav.chat", hint: "chat.title", go: "/chat" },
];

function fuzzy(hay: string, needle: string): boolean {
  hay = hay.toLowerCase();
  let i = 0;
  for (const ch of needle.toLowerCase()) { i = hay.indexOf(ch, i); if (i < 0) return false; i++; }
  return true;
}

export function CommandPalette() {
  const t = useTheme();
  const tr = useT();
  const lang = useLang();
  const router = useRouter();
  const open = usePalette((s) => s.open);
  const hide = usePalette((s) => s.hide);
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const [copilot, setCopilot] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<TextInput>(null);
  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks, enabled: open });

  useEffect(() => { if (open) { setQ(""); setSel(0); setCopilot(null); setTimeout(() => inputRef.current?.focus(), 40); } }, [open]);

  const isCmd = q.startsWith(">");
  // resolved once per language, not per keystroke
  const localViews = useMemo(
    () => VIEWS.map((v) => ({ label: tr(v.label), hint: tr(v.hint), go: v.go })),
    [lang],   // eslint-disable-line react-hooks/exhaustive-deps
  );
  const rows: Row[] = useMemo(() => {
    if (isCmd) return [];
    const term = q.trim();
    const views: Row[] = localViews.filter((v) => !term || fuzzy(v.label + " " + v.hint, term)).map((v) => ({ kind: "view", ...v }));
    const cards: Row[] = (tracks ?? [])
      .filter((k: Track) => !term || fuzzy(`${k.task} ${k.branch ?? ""} ${k.client ?? ""}`, term))
      .slice(0, 8)
      .map((k: Track) => ({ kind: "card", label: k.task, hint: k.lane || "", go: `/card/${k.id}`, status: k.status }));
    return [...views.slice(0, 6), ...cards];
  }, [q, tracks, isCmd, localViews]);

  useEffect(() => { if (sel >= rows.length) setSel(0); }, [rows.length, sel]);

  if (!open) return null;

  async function runCopilot() {
    const text = q.slice(1).trim();
    if (!text) return;
    setBusy(true); setCopilot("…");
    try {
      const r = await api.chat(text);
      setCopilot(r.reply || r.error || tr("chat.noReply"));
      // The copilot may have acted on the board — refresh so it reflects any changes.
      await qc.invalidateQueries({ queryKey: ["tracks"] });
    }
    catch (e) { setCopilot(tr("ui.error") + ": " + String((e as Error).message)); }
    finally { setBusy(false); }
  }
  function activate(i: number) {
    const r = rows[i];
    if (!r) return;
    hide();
    router.push(r.go as never);
  }
  // web key handling on the input: arrows move selection, Enter activates/runs
  const onKeyDown = (e: any) => {
    const key = e?.nativeEvent?.key ?? e?.key;
    if (key === "ArrowDown") { e.preventDefault?.(); setSel((s) => Math.min(s + 1, Math.max(rows.length - 1, 0))); }
    else if (key === "ArrowUp") { e.preventDefault?.(); setSel((s) => Math.max(s - 1, 0)); }
    else if (key === "Enter") { e.preventDefault?.(); if (isCmd) runCopilot(); else activate(sel); }
    else if (key === "Escape") { e.preventDefault?.(); hide(); }
  };

  const glass = { backgroundColor: t.glass, backdropFilter: "blur(24px) saturate(1.35)", WebkitBackdropFilter: "blur(24px) saturate(1.35)" } as any;
  return (
    <Pressable onPress={hide}
      style={{ position: "absolute", inset: 0, backgroundColor: t.backdrop, alignItems: "center", justifyContent: "flex-start", zIndex: 50 } as any}>
      <Pressable onPress={() => {}} style={[isWeb
        ? { marginTop: "10vh" as any, width: "min(640px, 92vw)" as any }
        : { marginTop: 80, width: "92%" as any },
        { borderRadius: 16, borderWidth: 1, borderColor: t.glassBorder, overflow: "hidden" }, glass]}>
        <TextInput
          ref={inputRef}
          value={q}
          onChangeText={setQ}
          onKeyPress={onKeyDown}
          placeholder={tr("palette.placeholder")}
          placeholderTextColor={t.txtPlaceholder}
          style={{ color: t.txtPrimary, fontSize: 15, paddingHorizontal: 16, paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: t.glassBorder, outlineStyle: "none" } as any}
        />
        {isCmd ? (
          <View style={{ padding: 16, gap: 8 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr(busy ? "palette.copilotThinking" : "palette.copilotHint")}</Text>
            {copilot ? <Text style={{ color: t.txtPrimary, fontSize: 13.5, lineHeight: 20 }}>{copilot}</Text> : null}
          </View>
        ) : (
          <ScrollView style={{ maxHeight: 380 }} keyboardShouldPersistTaps="handled">
            {rows.length === 0 ? <Text style={{ color: t.txtTertiary, padding: 16 }}>{tr("palette.nothingFound")}</Text> : null}
            {rows.map((r, i) => (
              <Pressable key={r.go + i} onPress={() => activate(i)} onHoverIn={() => setSel(i)}
                style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 11,
                  backgroundColor: i === sel ? t.accent + "22" : "transparent" }}>
                {r.kind === "card" ? <Dot color={statusColor(t, r.status)} /> :
                  <View style={{ width: 18, alignItems: "center" }}><Text style={{ color: t.accent, fontSize: 13 }}>▸</Text></View>}
                <Text style={{ color: t.txtPrimary, fontSize: 13.5, flex: 1 }} numberOfLines={1}>{r.label}</Text>
                <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{r.hint}</Text>
              </Pressable>
            ))}
          </ScrollView>
        )}
        <View style={{ paddingHorizontal: 14, paddingVertical: 8, borderTopWidth: 1, borderTopColor: t.glassBorder }}>
          <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("palette.footer")}</Text>
        </View>
      </Pressable>
    </Pressable>
  );
}
