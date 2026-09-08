import * as Clipboard from "expo-clipboard";
import Constants from "expo-constants";
import * as Updates from "expo-updates";
import { useCallback, useRef, useState } from "react";
import { Platform, Pressable, ScrollView, Text, View } from "react-native";

import { useConfig } from "@/data/config";
import { diagClear, diagEntries, dumpDiag, useDiagSeqValue, type DiagEntry } from "@/data/diag";
import { useDemo } from "@/data/demo";
import { setupAvailable } from "@/data/setup";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

/** Reveal-by-repeat-tap, the standard "hidden until you mean it" affordance
 *  (Android's build-number tap). Hidden rather than a visible menu row on
 *  purpose: this is a support tool, and a normal user finding a wall of HTTP
 *  statuses learns only that their app looks broken.
 *
 *  The count resets if the taps stop for 2s, so ordinary interaction with
 *  whatever it is attached to can never accumulate into a reveal. */
export function useSecretTap(needed = 7): { onPress: () => void; open: boolean; close: () => void } {
  const [open, setOpen] = useState(false);
  const hits = useRef(0);
  const last = useRef(0);
  const onPress = useCallback(() => {
    const now = Date.now();
    hits.current = now - last.current > 2000 ? 1 : hits.current + 1;
    last.current = now;
    if (hits.current >= needed) { hits.current = 0; setOpen(true); }
  }, [needed]);
  return { onPress, open, close: () => setOpen(false) };
}

function color(e: DiagEntry, t: ReturnType<typeof useTheme>): string {
  if (e.kind === "err") return t.danger;
  // A status line's leading number is what decides the colour: "403 · 12ms" is
  // a fault, "200 · 12ms" is not.
  const m = /^(\d{3})/.exec(e.detail);
  if (m) return Number(m[1]) >= 400 ? t.danger : t.ok;
  return e.kind === "net" ? t.danger : t.txtTertiary;
}

/** Environment facts the buffer itself cannot know (diag.ts stays free of expo
 *  imports so the transport layer can depend on it). Identity and reachability
 *  only - never a credential: `token` is reported as a yes/no, never a value. */
function env(): string[] {
  const cfg = useConfig.getState();
  const version = Constants.expoConfig?.version ?? Updates.runtimeVersion ?? "?";
  const build = (Constants.expoConfig as { android?: { versionCode?: number } } | null)?.android?.versionCode;
  return [
    `app       v${version}${build ? ` build ${build}` : ""} · ${Platform.OS}`,
    `bundle    ${Updates.isEmbeddedLaunch ? "embedded" : Updates.updateId?.slice(0, 8) ?? "dev"}`,
    `baseUrl   ${cfg.baseUrl || "(none)"}`,
    `relay     ${cfg.relayUrl || "(none)"}`,
    `token     ${cfg.token ? "present" : "none"}`,
    `setup     ${setupAvailable() ? "available" : "not available"}`,
    `demo      ${useDemo.getState().active ? "on" : "off"}`,
  ];
}

/** The black box, rendered. Newest at the bottom, one line per observation. */
export function DiagPanel({ onClose }: { onClose: () => void }) {
  const t = useTheme();
  const tr = useT();
  useDiagSeqValue();                 // re-render when the buffer changes
  const [copied, setCopied] = useState(false);
  const entries = diagEntries();
  const head = env();
  const scroller = useRef<ScrollView>(null);
  const atEnd = useRef(true);        // start pinned to the newest line

  const copy = async () => {
    await Clipboard.setStringAsync(dumpDiag(head));
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };

  const mono = Platform.OS === "web" ? { fontFamily: "ui-monospace, monospace" } as const : {};

  return (
    <View style={{ backgroundColor: t.surface1, borderRadius: 14, borderWidth: 1,
      borderColor: t.borderSubtle, padding: 14, gap: 10 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
        <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "700", flex: 1 }}>
          {tr("diag.title")}
        </Text>
        <Pressable onPress={copy} style={{ backgroundColor: t.accent, borderRadius: 9,
          paddingHorizontal: 12, paddingVertical: 7 }}>
          <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>
            {copied ? tr("diag.copied") : tr("diag.copy")}
          </Text>
        </Pressable>
        <Pressable onPress={diagClear}>
          <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("diag.clear")}</Text>
        </Pressable>
        <Pressable onPress={onClose}>
          <Text style={{ color: t.txtTertiary, fontSize: 16, paddingHorizontal: 4 }}>×</Text>
        </Pressable>
      </View>

      {head.map((l) => (
        <Text key={l} selectable style={{ color: t.txtTertiary, fontSize: 10.5, lineHeight: 15, ...mono }}>{l}</Text>
      ))}

      {/* Stick to the bottom, because the line you opened this for is the last
          one - but ONLY while the reader is already there. A log that yanks
          itself to the end every time a poll ticks cannot be scrolled back
          through, which is the other half of what it is for. */}
      <ScrollView ref={scroller} style={{ maxHeight: 260 }}
        onScroll={(e) => {
          const { layoutMeasurement, contentOffset, contentSize } = e.nativeEvent;
          atEnd.current = layoutMeasurement.height + contentOffset.y >= contentSize.height - 24;
        }}
        scrollEventThrottle={64}
        onContentSizeChange={() => { if (atEnd.current) scroller.current?.scrollToEnd({ animated: false }); }}
        contentContainerStyle={{ gap: 3, paddingVertical: 4 }}>
        {entries.length === 0 ? (
          <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("diag.empty")}</Text>
        ) : entries.map((e, i) => (
          <Text key={i} selectable style={{ fontSize: 11, lineHeight: 15.5, color: color(e, t), ...mono }}>
            {new Date(e.ts).toISOString().slice(11, 19)}  {e.label}
            {e.detail ? "  → " + e.detail : ""}{e.n > 1 ? `  (x${e.n})` : ""}
          </Text>
        ))}
      </ScrollView>

      <Text style={{ color: t.txtTertiary, fontSize: 10.5, lineHeight: 14 }}>{tr("diag.hint")}</Text>
    </View>
  );
}
