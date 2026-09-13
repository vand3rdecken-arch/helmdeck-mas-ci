import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { api, type ChatThread, type ChatThreads } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

/**
 * CONVERSATIONS, the way chat apps list them (Claude, Paseo, ChatGPT): one
 * row per thread, newest first, grouped - but the thread IS a card (owner
 * decree 2026-09-13: "es macht eine Conversation und eine Karte"). Nothing new
 * is stored: the daemon derives the list from the cards' own timelines and
 * the process (epic) each card belongs to (cells/copilot/chat/threads.py).
 *
 * Groups, top to bottom:
 *   - the INBOX (the flat board chat: quick questions, tiles, roll-ups)
 *   - one folder per PROCESS that has threads, with a done/total roll-up
 *   - the rest by recency: today / yesterday / last 7 days / earlier
 *
 * "New thread" opens the card composer: a new conversation is a new card.
 */
type Props = {
  current?: string;                 // "inbox" or a card id - highlighted
  onPick: (id: string) => void;     // "inbox" | card id
  onClose?: () => void;             // phone: the list is a full-screen sheet
  embedded?: boolean;               // desktop sidebar: no close, no top inset
};

function bucket(at: number, now: Date): "today" | "yesterday" | "week" | "older" {
  if (!at) return "older";
  const d = new Date(at * 1000);
  const day = (x: Date) => Math.floor((x.getTime() - x.getTimezoneOffset() * 60000) / 86400000);
  const diff = day(now) - day(d);
  if (diff <= 0) return "today";
  if (diff === 1) return "yesterday";
  if (diff < 7) return "week";
  return "older";
}

function timeLabel(at: number, now: Date): string {
  if (!at) return "";
  const d = new Date(at * 1000);
  const same = d.toDateString() === now.toDateString();
  const hh = String(d.getHours()).padStart(2, "0"), mm = String(d.getMinutes()).padStart(2, "0");
  if (same) return `${hh}:${mm}`;
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.`;
}

export function ThreadList({ current, onPick, onClose, embedded }: Props) {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const { data, isLoading } = useQuery<ChatThreads>({
    queryKey: ["chatThreads"], queryFn: api.chatThreads, staleTime: 5000, refetchOnMount: "always",
  });
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggle = (k: string) => setCollapsed((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const now = new Date();

  const groups = useMemo(() => {
    const threads = data?.threads ?? [];
    const procs = data?.processes ?? [];
    const byProc = new Map<string, ChatThread[]>();
    const loose: ChatThread[] = [];
    for (const th of threads) {
      if (th.process) { const l = byProc.get(th.process) ?? []; l.push(th); byProc.set(th.process, l); }
      else loose.push(th);
    }
    const out: { key: string; title: string; sub?: string; done?: boolean; items: ChatThread[] }[] = [];
    // processes ordered by their newest thread
    const procOrder = [...byProc.entries()].sort((a, b) => (b[1][0]?.at ?? 0) - (a[1][0]?.at ?? 0));
    for (const [pid, items] of procOrder) {
      const p = procs.find((x) => x.id === pid);
      out.push({ key: "p:" + pid, title: p?.title || items[0].process_title || pid,
        sub: p ? tr("chat.threads.rollup", { done: p.done, total: p.total }) : undefined,
        done: !!p && p.done >= p.total && p.total > 0, items });
    }
    const buckets: Record<string, ChatThread[]> = { today: [], yesterday: [], week: [], older: [] };
    for (const th of loose) buckets[bucket(th.at, now)].push(th);
    for (const k of ["today", "yesterday", "week", "older"] as const) {
      if (buckets[k].length) out.push({ key: "d:" + k, title: tr("chat.threads." + k), items: buckets[k] });
    }
    return out;
  }, [data, tr]);   // eslint-disable-line react-hooks/exhaustive-deps

  const laneColor = (th: ChatThread) =>
    th.lane === "working" ? t.accent : th.lane === "review" ? t.warn : th.lane === "done" ? t.txtTertiary : t.txtSecondary;

  const Row = ({ th }: { th: ChatThread }) => {
    const active = current === th.id;
    return (
      <Pressable onPress={() => onPick(th.id)} accessibilityLabel={th.title}
        style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, paddingVertical: 9,
          backgroundColor: active ? t.surface1 : pressed ? t.surface1 : "transparent" })}>
        <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: laneColor(th) }} />
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 14, fontWeight: th.lane === "working" ? "600" : "400" }}>{th.title}</Text>
          {th.preview ? <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12, marginTop: 1 }}>{th.preview}</Text> : null}
        </View>
        <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{timeLabel(th.at, now)}</Text>
      </Pressable>
    );
  };

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <View style={{ flexDirection: "row", alignItems: "center", padding: 10, gap: 8 }}>
        {onClose ? <Pressable onPress={onClose} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable> : null}
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600", flex: 1 }}>{tr("chat.threads")}</Text>
        <Pressable onPress={() => router.push("/new")} hitSlop={10} accessibilityLabel={tr("chat.threads.new")}
          style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Ionicons name="create-outline" size={20} color={t.accent} />
          {embedded ? null : <Text style={{ color: t.accent, fontSize: 13, fontWeight: "600" }}>{tr("chat.threads.new")}</Text>}
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <Pressable onPress={() => onPick("inbox")}
          style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, paddingVertical: 10,
            backgroundColor: current === "inbox" || pressed ? t.surface1 : "transparent" })}>
          <Ionicons name="sparkles" size={14} color={t.accent2} />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{tr("chat.threads.inbox")}</Text>
            {data?.inbox?.preview ? <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12, marginTop: 1 }}>{data.inbox.preview}</Text> : null}
          </View>
          <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{timeLabel(data?.inbox?.at ?? 0, now)}</Text>
        </Pressable>
        {isLoading && !data ? <Text style={{ color: t.txtTertiary, fontSize: 12, padding: 12 }}>…</Text> : null}
        {!isLoading && groups.length === 0 ? <Text style={{ color: t.txtTertiary, fontSize: 12, padding: 12 }}>{tr("chat.threads.empty")}</Text> : null}
        {groups.map((g) => {
          const closed = collapsed.has(g.key) || (g.done && !collapsed.has("!" + g.key));
          return (
            <View key={g.key} style={{ marginTop: 8 }}>
              <Pressable onPress={() => toggle(g.done ? "!" + g.key : g.key)}
                style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 6 }}>
                {g.key.startsWith("p:") ? <Ionicons name="folder-outline" size={13} color={t.txtSecondary} /> : null}
                <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "700", flex: 1, textTransform: g.key.startsWith("d:") ? "uppercase" : "none", letterSpacing: g.key.startsWith("d:") ? 0.6 : 0 }}>{g.title}</Text>
                {g.sub ? <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{g.sub}</Text> : null}
                <Ionicons name={closed ? "chevron-forward" : "chevron-down"} size={12} color={t.txtTertiary} />
              </Pressable>
              {closed ? null : g.items.map((th) => <Row key={th.id} th={th} />)}
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}
