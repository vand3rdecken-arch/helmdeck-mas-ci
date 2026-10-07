import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, Text, View } from "react-native";

import { useLang, useT } from "@/i18n";
import { useTheme } from "@/theme";

// The ONE compaction row, shared by the card chat and the Henry chat (both draw
// through card_transcript.tsx) - Paseo's CompactionMarker: a hairline, a label
// with a spinner while it runs or a scissors once it is done, a hairline. The
// daemon writes ONE item per compaction (drivers._compaction_item for cards,
// copilot._compact_row for Henry); foldCompaction() below is Paseo's
// reduceTimelineCompaction - the later state replaces the earlier one in place.

export type CompactionEvent = "loading" | "completed" | "interrupted";

export interface CompactionFields {
  event?: CompactionEvent | string; cid?: string; trigger?: string;
  pre_tokens?: number | null; post_tokens?: number | null; duration_ms?: number | null;
  ta?: number;
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

export function CompactionMarker({ s }: { s: CompactionFields }) {
  const t = useTheme();
  const tr = useT();
  const comma = useLang() === "de";
  const stale = s.event === "loading" && typeof s.ta === "number" && Date.now() / 1000 - s.ta > LOADING_MAX_S;
  const event = stale ? "interrupted" : s.event;
  const loading = event === "loading";
  const parts = [tr(loading ? "compaction.loading" : event === "interrupted" ? "compaction.interrupted" : "compaction.done")];
  if (event === "completed") {
    if (s.pre_tokens && s.post_tokens) parts.push(`${fmtTokens(s.pre_tokens, comma)} → ${fmtTokens(s.post_tokens, comma)}`);
    else if (s.pre_tokens) parts.push(fmtTokens(s.pre_tokens, comma));
    if (s.duration_ms) parts.push(`${Math.max(1, Math.round(s.duration_ms / 1000))} s`);
  }
  const line = <View style={{ flex: 1, height: 1, backgroundColor: t.borderSubtle }} />;
  return (
    <View accessibilityRole="text" accessibilityLiveRegion="polite"
      style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8 }}>
      {line}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        {loading
          ? <ActivityIndicator size="small" color={t.txtTertiary} style={{ transform: [{ scale: 0.7 }] }} />
          : <Ionicons name={event === "interrupted" ? "pause-circle-outline" : "cut-outline"} size={12} color={t.txtTertiary} />}
        <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{parts.join(" · ")}</Text>
      </View>
      {line}
    </View>
  );
}
