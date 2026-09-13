import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState, type ComponentProps } from "react";
import { Animated, Pressable, ScrollView, Text, View } from "react-native";
import { api, type ChatThread, type ChatThreads } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

/**
 * CONVERSATIONS - a copy of Paseo's sidebar in STATUS grouping (owner rule
 * 2026-09-13: "kopieren von Paseo und anderen etablierten Apps, nicht das Rad
 * neu erfinden"). Read from packages/app/src/components/left-sidebar.tsx,
 * sidebar-workspace-list.tsx, sidebar/sidebar-workspace-row-content.tsx and
 * hooks/sidebar-status-view-model.ts:
 *
 *   header rows      "+ New workspace" / "History"        -> "+ New thread" / "Henry · Inbox"
 *   groups           needs_input, failed, attention ("Ready to review"),
 *                    running ("Working"), done            -> same, plus "Planned" (backlog)
 *   per group        20 rows, then a "Show more" row styled like a row
 *   row              minHeight 36, leading 20px status slot, title base
 *                    at opacity 0.76 (1.0 selected), meta line under it,
 *                    trailing compact time-ago in extra-muted
 *   status indicator needs_input = alert 12px warning; failed = 6px danger
 *                    dot; running = animated ring; attention = 6px success
 *                    dot; done = 6px dot at 0.3 opacity
 *
 * The thread IS a card (cells/copilot/chat/threads.py); the "project" of
 * Paseo's meta line is our process (the PMBOK epic).
 */
type Props = {
  current?: string;
  onPick: (id: string) => void;     // "inbox" | card id
  onClose?: () => void;             // phone drawer: the X / back
  embedded?: boolean;               // desktop sidebar
};

const GROUP_ORDER: ChatThread["bucket"][] = ["needs_input", "failed", "attention", "running", "backlog", "done"];
const INITIAL_VISIBLE_ITEMS = 20;   // Paseo: sidebar/use-limited-sidebar-group.ts

/** Paseo utils/time.ts formatTimeAgo, compact: now / 45s / 5m / 2h / 3d / 15.01. */
function timeAgo(at: number, nowS: number, nowLabel: string): string {
  if (!at) return "";
  const s = Math.max(0, nowS - at);
  if (s < 10) return nowLabel;
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d`;
  const d = new Date(at * 1000);
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.`;
}

/** Paseo's StatusRing: a 9px ring rotating with a 900ms period. */
function StatusRing({ color }: { color: string }) {
  const spin = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const a = Animated.loop(Animated.timing(spin, { toValue: 1, duration: 900, useNativeDriver: true }));
    a.start();
    return () => a.stop();
  }, [spin]);
  const rotate = spin.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] });
  return (
    <Animated.View style={{ width: 9, height: 9, borderRadius: 4.5, borderWidth: 1.5, borderColor: color,
      borderTopColor: "transparent", opacity: 0.9, transform: [{ rotate }] }} />
  );
}

function StatusIndicator({ bucket, t }: { bucket: ChatThread["bucket"]; t: ReturnType<typeof useTheme> }) {
  if (bucket === "needs_input") return <Ionicons name="alert-circle" size={12} color={t.warn} />;
  if (bucket === "failed") return <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: t.danger }} />;
  if (bucket === "running") return <StatusRing color={t.accent} />;
  if (bucket === "attention") return <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: t.ok }} />;
  if (bucket === "backlog") return <View style={{ width: 6, height: 6, borderRadius: 3, borderWidth: 1, borderColor: t.txtTertiary, opacity: 0.6 }} />;
  return <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: t.txtTertiary, opacity: 0.3 }} />;
}

export function ThreadList({ current, onPick, onClose, embedded }: Props) {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const { data, isLoading } = useQuery<ChatThreads>({
    queryKey: ["chatThreads"], queryFn: api.chatThreads, staleTime: 5000, refetchOnMount: "always",
  });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const nowS = Math.floor(Date.now() / 1000);

  const groups = useMemo(() => {
    const threads = data?.threads ?? [];
    return GROUP_ORDER
      .map((b) => ({ key: b, title: tr("chat.threads." + b), items: threads.filter((th) => th.bucket === b) }))
      .filter((g) => g.items.length > 0);
  }, [data, tr]);

  // Paseo sidebar-header-row: minHeight 36, radius lg, icon + label
  const HeaderRow = ({ icon, label, onPress, active, sub, trailing }: { icon: ComponentProps<typeof Ionicons>["name"]; label: string; onPress: () => void; active?: boolean; sub?: string; trailing?: string }) => (
    <Pressable onPress={onPress} accessibilityLabel={label}
      style={({ pressed }) => ({ minHeight: 36, flexDirection: "row", alignItems: "center", gap: 10, marginHorizontal: 8, paddingLeft: 8, paddingRight: 12, paddingVertical: 8,
        borderRadius: 10, backgroundColor: active ? t.surface2 : pressed ? t.surface1 : "transparent" })}>
      <View style={{ width: 20, alignItems: "center" }}><Ionicons name={icon} size={16} color={active ? t.txtPrimary : t.txtSecondary} /></View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 14, lineHeight: 20, fontWeight: "500" }}>{label}</Text>
        {sub ? <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12 }}>{sub}</Text> : null}
      </View>
      {trailing ? <Text style={{ color: t.txtTertiary, fontSize: 12, opacity: 0.8 }}>{trailing}</Text> : null}
    </Pressable>
  );

  // Paseo sidebar-workspace-row-content: 20px status slot, title 0.76, meta, trailing time
  const Row = ({ th }: { th: ChatThread }) => {
    const selected = current === th.id;
    return (
      <Pressable onPress={() => onPick(th.id)} accessibilityLabel={th.title}
        style={({ pressed }) => ({ minHeight: 36, flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: 8, paddingLeft: 8, paddingRight: 12, paddingVertical: 8,
          borderRadius: 10, backgroundColor: selected || pressed ? t.surface2 : "transparent" })}>
        <View style={{ width: 20, alignItems: "center", justifyContent: "center" }}><StatusIndicator bucket={th.bucket} t={t} /></View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 14, lineHeight: 20, opacity: selected ? 1 : 0.76 }}>{th.title}</Text>
          {th.process_title ? (
            <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12, lineHeight: 16 }}>{th.process_title}</Text>
          ) : null}
        </View>
        <Text style={{ color: t.txtTertiary, fontSize: 12, opacity: 0.8 }}>{timeAgo(th.at, nowS, tr("chat.threads.now"))}</Text>
      </Pressable>
    );
  };

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      {onClose ? (
        <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingTop: 8, paddingBottom: 2 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600", flex: 1 }}>{tr("chat.threads")}</Text>
          <Pressable onPress={onClose} hitSlop={10} accessibilityLabel={tr("chat.close")}><Ionicons name="close" size={22} color={t.txtSecondary} /></Pressable>
        </View>
      ) : <View style={{ height: 8 }} />}
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <HeaderRow icon="add" label={tr("chat.threads.new")} onPress={() => router.push("/new")} />
        <HeaderRow icon="sparkles" label={tr("chat.threads.inbox")} active={current === "inbox"} onPress={() => onPick("inbox")}
          sub={data?.inbox?.preview} trailing={timeAgo(data?.inbox?.at ?? 0, nowS, tr("chat.threads.now"))} />

        {isLoading && !data ? <Text style={{ color: t.txtTertiary, fontSize: 12, padding: 16 }}>…</Text> : null}
        {data && groups.length === 0 ? <Text style={{ color: t.txtTertiary, fontSize: 13, padding: 16, lineHeight: 18 }}>{tr("chat.threads.empty")}</Text> : null}

        {groups.map((g) => {
          const open = expanded.has(g.key);
          const shown = open ? g.items : g.items.slice(0, INITIAL_VISIBLE_ITEMS);
          const hidden = g.items.length - shown.length;
          return (
            <View key={g.key} style={{ marginTop: 12 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 12, fontWeight: "500", paddingHorizontal: 16, paddingBottom: 4 }}>{g.title}</Text>
              {shown.map((th) => <Row key={th.id} th={th} />)}
              {hidden > 0 || open ? (
                <Pressable onPress={() => setExpanded((s) => { const n = new Set(s); if (n.has(g.key)) n.delete(g.key); else n.add(g.key); return n; })}
                  style={({ pressed }) => ({ minHeight: 36, flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: 8, paddingLeft: 8, paddingRight: 12, paddingVertical: 8,
                    borderRadius: 10, backgroundColor: pressed ? t.surface1 : "transparent" })}>
                  <View style={{ width: 20, alignItems: "center" }}><Ionicons name={open ? "chevron-up" : "chevron-down"} size={14} color={t.txtTertiary} /></View>
                  <Text style={{ color: t.txtSecondary, fontSize: 14 }}>{open ? tr("chat.threads.less") : `${tr("chat.threads.more")} (${hidden})`}</Text>
                </Pressable>
              ) : null}
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}
