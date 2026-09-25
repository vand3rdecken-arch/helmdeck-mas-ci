import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import type { RunStep } from "@/data/types";
import { useT } from "@/i18n";
import type { ThemeTokens } from "@/theme/tokens";
import { StatusIndicator } from "./chat_threads";

/** What a delegated run looks like RIGHT NOW - derived by the chat screen from
 *  the daemon's own records (a card's thread row, a hands/agent descriptor in
 *  history().followups), never stored on the chat row itself. */
export interface RunLive {
  bucket: "needs_input" | "failed" | "attention" | "running" | "backlog" | "done";
  sub?: string;          // one line: the card's latest line, or the run's last step
  tag?: string;          // project / "eigener Worktree"
  steps?: RunStep[];     // a run's tool steps (tail), expandable
  result?: string;       // a finished run's report
}

/** ONE tile for everything Henry hands off (owner 2026-09-25: "als Subagent-
 *  Prozess, damit man es sehen kann") - Claude Code Projects' thread card
 *  under the coordinator's message: title, live status, one line of what is
 *  happening now. A CARD opens its thread; a RUN (hands / background agent)
 *  unfolds its steps in place. Status marks = the thread list's (Paseo). */
export function RunTile({ kind, title, live, card, t }: {
  kind: "card" | "hands" | "agent"; title: string; live?: RunLive; card?: string; t: ThemeTokens;
}) {
  const tr = useT();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const bucket = live?.bucket ?? (kind === "card" ? "backlog" : "running");
  const icon = kind === "card" ? "chatbubbles-outline" : kind === "hands" ? "hand-left-outline" : "git-branch-outline";
  const kindLabel = tr(kind === "card" ? "chat.run.card" : kind === "hands" ? "chat.run.hands" : "chat.run.agent");
  const expandable = kind !== "card" && !!((live?.steps?.length ?? 0) || live?.result);
  const onPress = () => {
    if (kind === "card" && card) router.push(`/card/${card}?tab=chat`);
    else if (expandable) setOpen((o) => !o);
  };
  const sub = live?.sub || (kind === "card" ? tr("chat.thread.tile") : "");
  return (
    <View testID={`run-tile-${kind}`}
      style={{ borderWidth: 1, borderColor: bucket === "needs_input" ? t.warn + "88" : t.borderSubtle,
        borderRadius: 10, backgroundColor: t.surface1, overflow: "hidden" }}>
      <Pressable onPress={onPress} accessibilityLabel={kind === "card" ? tr("chat.thread.open") : title}
        style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 11,
          paddingVertical: 9, backgroundColor: pressed ? t.surface2 : "transparent" })}>
        <Ionicons name={icon} size={16} color={t.accent} />
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "600" }}>{title}</Text>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 }}>
            <View style={{ width: 12, alignItems: "center" }}><StatusIndicator bucket={bucket} t={t} /></View>
            <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 11.5, flexShrink: 1 }}>
              {tr("chat.threads." + bucket)}{sub ? " · " + sub : ""}
            </Text>
          </View>
        </View>
        <View style={{ alignItems: "flex-end", gap: 2 }}>
          <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{kindLabel}</Text>
          {live?.tag ? <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 10.5, maxWidth: 120 }}>{live.tag}</Text> : null}
        </View>
        {kind === "card" ? <Ionicons name="chevron-forward" size={14} color={t.txtTertiary} />
          : expandable ? <Ionicons name={open ? "chevron-up" : "chevron-down"} size={14} color={t.txtTertiary} /> : null}
      </Pressable>
      {open && expandable ? (
        <View style={{ borderTopWidth: 1, borderTopColor: t.borderSubtle, paddingHorizontal: 11, paddingVertical: 8, gap: 5 }}>
          {(live?.steps ?? []).map((s, i) => (
            <View key={(s.id || "") + i} style={{ flexDirection: "row", alignItems: "center", gap: 7, minHeight: 20 }}>
              <Ionicons size={12}
                name={s.status === "running" ? "ellipse-outline" : s.status === "failed" ? "close-circle" : "checkmark-circle"}
                color={s.status === "running" ? t.accent : s.status === "failed" ? t.danger : t.txtTertiary} />
              <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{s.label}</Text>
              <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12, flex: 1 }}>{s.text}</Text>
            </View>
          ))}
          {live?.result && bucket !== "running" ? (
            <Text selectable numberOfLines={12} style={{ color: t.txtSecondary, fontSize: 12, lineHeight: 17, marginTop: 4 }}>
              {live.result}
            </Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
