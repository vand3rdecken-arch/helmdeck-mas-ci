import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState, type ReactNode } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { api, type ChatThread, type ChatThreads } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

/**
 * CONVERSATIONS, the way chat apps list them (Claude, Paseo, ChatGPT): one
 * row per thread, grouped - but the thread IS a card (owner decree
 * 2026-09-13: "es macht eine Conversation und eine Karte"). Nothing new is
 * stored: the daemon derives the list from the cards' own timelines and the
 * process (epic) each card belongs to (cells/copilot/chat/threads.py).
 *
 * WHAT THE OWNER SEES, top to bottom (his verdict on the first cut, 13:11:
 * "grafisch schwer zu verdauen, sehr unübersichtlich" - 192 cards, every
 * folder open, worker banners as titles):
 *   - the INBOX (the flat board chat)
 *   - AKTIV: what runs or waits for him, wherever it lives - with a status
 *     word, never a bare dot
 *   - ORDNER: one collapsed card per process with its roll-up; open to see
 *     its threads. Finished folders hide behind one line.
 *   - ZULETZT: the last few threads by recency, the rest behind "mehr".
 *
 * "New thread" opens the card composer: a new conversation is a new card.
 */
type Props = {
  current?: string;                 // "inbox" or a card id - highlighted
  onPick: (id: string) => void;     // "inbox" | card id
  onClose?: () => void;             // phone: the list is a full-screen sheet
  embedded?: boolean;               // desktop sidebar: no close, compact header
};

const RECENT_N = 8;

function timeLabel(at: number, now: Date): string {
  if (!at) return "";
  const d = new Date(at * 1000);
  if (d.toDateString() === now.toDateString())
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.`;
}

export function ThreadList({ current, onPick, onClose, embedded }: Props) {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const { data, isLoading } = useQuery<ChatThreads>({
    queryKey: ["chatThreads"], queryFn: api.chatThreads, staleTime: 5000, refetchOnMount: "always",
  });
  const [open, setOpen] = useState<Set<string>>(new Set());      // opened folders
  const [showDone, setShowDone] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const toggle = (k: string) => setOpen((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const now = new Date();

  const model = useMemo(() => {
    const threads = data?.threads ?? [];
    const procs = data?.processes ?? [];
    const active = threads.filter((th) => th.active);
    const byProc = new Map<string, ChatThread[]>();
    const loose: ChatThread[] = [];
    for (const th of threads) {
      if (th.process) { const l = byProc.get(th.process) ?? []; l.push(th); byProc.set(th.process, l); }
      else if (!th.active) loose.push(th);
    }
    const folders = [...byProc.entries()].map(([pid, items]) => {
      const p = procs.find((x) => x.id === pid);
      const done = !!p && p.total > 0 && p.done >= p.total;
      return { id: pid, title: p?.title || items[0].process_title || pid, done,
        sub: p ? tr("chat.threads.rollup", { done: p.done, total: p.total }) : "",
        items: items.sort((a, b) => b.at - a.at), at: items[0]?.at ?? 0 };
    }).sort((a, b) => b.at - a.at);
    const recent = loose.filter((th) => th.has_chat).sort((a, b) => b.at - a.at);
    return { active, openFolders: folders.filter((f) => !f.done), doneFolders: folders.filter((f) => f.done), recent };
  }, [data, tr]);   // eslint-disable-line react-hooks/exhaustive-deps

  const statusOf = (th: ChatThread): { label: string; color: string } | null => {
    if (th.status === "needs_you") return { label: tr("chat.threads.needsYou"), color: t.warn };
    if (th.lane === "review") return { label: tr("chat.threads.review"), color: t.warn };
    if (th.lane === "working") return { label: tr("chat.threads.running"), color: t.accent };
    return null;
  };

  const Section = ({ title, right, onPress, children }: { title: string; right?: ReactNode; onPress?: () => void; children?: ReactNode }) => (
    <View style={{ marginTop: 14 }}>
      <Pressable onPress={onPress} disabled={!onPress}
        style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 14, paddingBottom: 6, gap: 6 }}>
        <Text style={{ color: t.txtTertiary, fontSize: 11.5, fontWeight: "700", letterSpacing: 0.8, textTransform: "uppercase", flex: 1 }}>{title}</Text>
        {right}
      </Pressable>
      {children}
    </View>
  );

  const Row = ({ th, indent }: { th: ChatThread; indent?: boolean }) => {
    const active = current === th.id;
    const st = statusOf(th);
    return (
      <Pressable onPress={() => onPick(th.id)} accessibilityLabel={th.title}
        style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", gap: 10,
          paddingLeft: indent ? 26 : 14, paddingRight: 14, paddingVertical: 10,
          backgroundColor: active || pressed ? t.surface1 : "transparent" })}>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 14.5, fontWeight: st ? "600" : "400" }}>{th.title}</Text>
          {st ? (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 }}>
              <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: st.color }} />
              <Text numberOfLines={1} style={{ color: st.color, fontSize: 12, fontWeight: "600" }}>{st.label}</Text>
              {th.preview ? <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12, flex: 1 }}>· {th.preview}</Text> : null}
            </View>
          ) : th.preview ? (
            <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12.5, marginTop: 2 }}>{th.preview}</Text>
          ) : null}
        </View>
        <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{timeLabel(th.at, now)}</Text>
      </Pressable>
    );
  };

  const Folder = ({ f }: { f: { id: string; title: string; sub: string; items: ChatThread[]; done: boolean } }) => {
    const isOpen = open.has(f.id);
    return (
      <View style={{ marginHorizontal: 10, marginBottom: 6, borderRadius: 12, backgroundColor: t.surface1, overflow: "hidden" }}>
        <Pressable onPress={() => toggle(f.id)}
          style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, paddingVertical: 11 }}>
          <Ionicons name={isOpen ? "folder-open-outline" : "folder-outline"} size={17} color={f.done ? t.txtTertiary : t.accent} />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 14.5, fontWeight: "600" }}>{f.title}</Text>
            <Text style={{ color: t.txtTertiary, fontSize: 12, marginTop: 2 }}>{f.sub}</Text>
          </View>
          <Ionicons name={isOpen ? "chevron-up" : "chevron-down"} size={15} color={t.txtTertiary} />
        </Pressable>
        {isOpen ? (
          <View style={{ borderTopWidth: 1, borderColor: t.borderSubtle, paddingVertical: 2 }}>
            {f.items.map((th) => <Row key={th.id} th={th} indent />)}
          </View>
        ) : null}
      </View>
    );
  };

  const recentShown = showAll ? model.recent : model.recent.slice(0, RECENT_N);
  const more = model.recent.length - recentShown.length;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 10, gap: 8 }}>
        {onClose ? <Pressable onPress={onClose} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable> : null}
        <Text style={{ color: t.txtPrimary, fontSize: 17, fontWeight: "700", flex: 1 }}>{tr("chat.threads")}</Text>
        <Pressable onPress={() => router.push("/new")} hitSlop={10} accessibilityLabel={tr("chat.threads.new")}
          style={{ flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: t.surface1 }}>
          <Ionicons name="add" size={18} color={t.accent} />
          {embedded ? null : <Text style={{ color: t.accent, fontSize: 13, fontWeight: "600" }}>{tr("chat.threads.new")}</Text>}
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: 28 }}>
        <Pressable onPress={() => onPick("inbox")}
          style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", gap: 12, marginHorizontal: 10, paddingHorizontal: 12, paddingVertical: 12,
            borderRadius: 12, backgroundColor: current === "inbox" || pressed ? t.surface1 : "transparent" })}>
          <View style={{ width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center", backgroundColor: t.surface1 }}>
            <Ionicons name="sparkles" size={16} color={t.accent2} />
          </View>
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "600" }}>{tr("chat.threads.inbox")}</Text>
            {data?.inbox?.preview ? <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12.5, marginTop: 2 }}>{data.inbox.preview}</Text> : null}
          </View>
          <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{timeLabel(data?.inbox?.at ?? 0, now)}</Text>
        </Pressable>

        {isLoading && !data ? <Text style={{ color: t.txtTertiary, fontSize: 12, padding: 14 }}>…</Text> : null}
        {data && !model.active.length && !model.openFolders.length && !model.recent.length && !model.doneFolders.length
          ? <Text style={{ color: t.txtTertiary, fontSize: 13, padding: 14, lineHeight: 18 }}>{tr("chat.threads.empty")}</Text> : null}

        {model.active.length ? (
          <Section title={tr("chat.threads.active")}>
            {model.active.map((th) => <Row key={th.id} th={th} />)}
          </Section>
        ) : null}

        {model.openFolders.length || model.doneFolders.length ? (
          <Section title={tr("chat.threads.folders")}>
            {model.openFolders.map((f) => <Folder key={f.id} f={f} />)}
            {model.doneFolders.length ? (
              <Pressable onPress={() => setShowDone((v) => !v)}
                style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 14, paddingVertical: 8 }}>
                <Ionicons name={showDone ? "chevron-up" : "chevron-forward"} size={13} color={t.txtTertiary} />
                <Text style={{ color: t.txtSecondary, fontSize: 13 }}>{tr("chat.threads.doneFolders", { n: model.doneFolders.length })}</Text>
              </Pressable>
            ) : null}
            {showDone ? model.doneFolders.map((f) => <Folder key={f.id} f={f} />) : null}
          </Section>
        ) : null}

        {model.recent.length ? (
          <Section title={tr("chat.threads.recent")}>
            {recentShown.map((th) => <Row key={th.id} th={th} />)}
            {more > 0 ? (
              <Pressable onPress={() => setShowAll(true)} style={{ paddingHorizontal: 14, paddingVertical: 10 }}>
                <Text style={{ color: t.accent, fontSize: 13, fontWeight: "600" }}>{tr("chat.threads.more", { n: more })}</Text>
              </Pressable>
            ) : null}
          </Section>
        ) : null}
      </ScrollView>
    </View>
  );
}
