import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef } from "react";
import { Animated, Easing, Text, View } from "react-native";

import { useLang, useT } from "@/i18n";
import { useTheme } from "@/theme";

// The ONE compaction row, shared by the card chat and the Henry chat (both draw
// through card_transcript.tsx) - Paseo's CompactionMarker: a hairline, a label
// with a spinner while it runs or a scissors once it is done, a hairline. The
// daemon writes ONE item per compaction (drivers._compaction_item for cards,
// copilot._compact_row for Henry); foldCompaction() below is Paseo's
// reduceTimelineCompaction - the later state replaces the earlier one in place.

export type CompactionEvent = "loading" | "completed" | "interrupted" | "pruned";

export interface CompactionFields {
  event?: CompactionEvent | string; cid?: string; trigger?: string;
  pre_tokens?: number | null; post_tokens?: number | null; duration_ms?: number | null;
  ta?: number; saved_kb?: number | null;
}

// A compaction is bounded by the daemon's 600s silence watchdog
// (sessions._COMPACT_IDLE_S); a `loading` row older than that is a daemon that
// died mid-compaction, never one still working - it must not spin forever.
const LOADING_MAX_S = 900;

/** Fold a step list so each compaction shows once: rows sharing `cid` collapse
 *  into the FIRST row's position carrying the LAST row's state. Card items are
 *  already folded by the timeline store (same step_id) and pass through. */
export function foldCompaction<T extends CompactionFields & { kind?: string }>(steps: T[]): T[] {
  const at = new Map<string, number>();
  const out: T[] = [];
  for (const s of steps) {
    if (s.kind !== "compaction" || !s.cid) { out.push(s); continue; }
    const i = at.get(s.cid);
    if (i === undefined) { at.set(s.cid, out.length); out.push(s); }
    else out[i] = { ...out[i], ...s, ta: out[i].ta ?? s.ta };
  }
  return out;
}

/** "954k → 4,5k": under 10k one decimal, else whole thousands. */
export function fmtTokens(n: number, comma: boolean): string {
  const k = n / 1000;
  const v = k < 1 ? String(n) : (k < 10 ? k.toFixed(1).replace(/\.0$/, "") : String(Math.round(k))) + "k";
  return comma ? v.replace(".", ",") : v;
}

/** The running cue: a slow breathing of the label and the two hairlines (core
 *  Animated, native driver - the React Compiler mangles reanimated worklets,
 *  see board.tsx RunningPulse). It stops the moment the work is done. */
function useBreath(on: boolean) {
  const v = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    if (!on) { v.setValue(1); return; }
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(v, { toValue: 0.35, duration: 900, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      Animated.timing(v, { toValue: 1, duration: 900, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [on, v]);
  return v;
}

/** The sync glyph turns while the work runs (one revolution per 1.6 s). */
function useSpin(on: boolean) {
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!on) { v.setValue(0); return; }
    const loop = Animated.loop(Animated.timing(v, { toValue: 1, duration: 1600, easing: Easing.linear, useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [on, v]);
  return v.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] });
}

/** One-shot arrival: the finished label fades and settles in (0 -> 1, small rise). */
function useArrive(key: string) {
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    v.setValue(0);
    Animated.timing(v, { toValue: 1, duration: 420, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start();
  }, [key, v]);
  return v;
}

export function CompactionMarker({ s }: { s: CompactionFields }) {
  const t = useTheme();
  const tr = useT();
  const comma = useLang() === "de";
  const stale = s.event === "loading" && typeof s.ta === "number" && Date.now() / 1000 - s.ta > LOADING_MAX_S;
  const event = stale ? "interrupted" : s.event;
  const loading = event === "loading";
  const pruned = event === "pruned";
  const parts = [tr(loading ? "compaction.loading" : event === "interrupted" ? "compaction.interrupted"
    : pruned ? "compaction.pruned" : "compaction.done")];
  if (event === "completed") {
    if (s.pre_tokens && s.post_tokens) parts.push(`${fmtTokens(s.pre_tokens, comma)} → ${fmtTokens(s.post_tokens, comma)}`);
    else if (s.pre_tokens) parts.push(fmtTokens(s.pre_tokens, comma));
    if (s.duration_ms) parts.push(`${Math.max(1, Math.round(s.duration_ms / 1000))} s`);
  }
  if (pruned && s.saved_kb) parts.push(`${s.saved_kb} kb`);
  const breath = useBreath(loading);
  const spin = useSpin(loading);
  const arrive = useArrive(`${s.cid ?? ""}:${event}`);
  const line = <Animated.View style={{ flex: 1, height: 1, backgroundColor: t.borderSubtle, opacity: breath }} />;
  const icon = loading ? "sync-outline" : event === "interrupted" ? "pause-circle-outline" : pruned ? "leaf-outline" : "cut-outline";
  return (
    <View accessibilityRole="text" accessibilityLiveRegion="polite"
      style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: pruned ? 4 : 8 }}>
      {line}
      <Animated.View style={{ flexDirection: "row", alignItems: "center", gap: 6,
        opacity: loading ? breath : arrive,
        transform: loading ? [] : [{ translateY: arrive.interpolate({ inputRange: [0, 1], outputRange: [3, 0] }) }] }}>
        {loading
          ? <Animated.View style={{ transform: [{ rotate: spin }] }}><Ionicons name={icon} size={12} color={t.txtTertiary} /></Animated.View>
          : <Ionicons name={icon} size={12} color={t.txtTertiary} />}
        <Text style={{ color: t.txtTertiary, fontSize: pruned ? 11 : 11.5 }}>{parts.join(" · ")}</Text>
      </Animated.View>
      {line}
    </View>
  );
}
