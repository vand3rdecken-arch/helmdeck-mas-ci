import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Keyboard, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { usePresence } from "@/data/presence";
import { chatFallbackInterval, useStreamCaps } from "@/data/stream";
import type { RoomMessage } from "@/data/types";
import { useT } from "@/i18n";
import { can } from "@/kernel";
import { useTheme } from "@/theme";
import { Empty, ScreenHeader } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

const MENTION = /(@[A-Za-z0-9_.-]+)/g;
const HENRY_WAIT_MS = 3 * 60 * 1000;     // a pending @henry stops reading as "answering" after this

// One team room (backlog/team-rooms-member, stages 3-6). Everyone in the room
// reads everything; every message carries its author. @henry asks Henry (and
// only that wakes him), @name addresses a member. Opening the room advances
// MY read cursor server-side (GET /rooms/messages), so there is nothing to
// "mark read" from here.
export default function RoomScreen() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const { id } = useLocalSearchParams<{ id: string }>();
  const roomId = String(id ?? "");
  const chatEvents = useStreamCaps((s) => s.chatEvents);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const { data, isError, isLoading } = useQuery({
    queryKey: ["room", roomId], queryFn: () => api.roomMessages(roomId), enabled: !!roomId,
    refetchInterval: chatFallbackInterval(chatEvents), retry: false,
  });
  const room = data?.room ?? null;
  const messages: RoomMessage[] = Array.isArray(data?.messages) ? data!.messages : [];
  const members = room?.members ?? [];
  const admin = can(me, "rooms.manage");

  // keyboard: same manual spacer as chat.tsx (works on both platforms, no native lib)
  const [kb, setKb] = useState(0);
  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", (e) => setKb(e.endCoordinates.height));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(0));
    return () => { show.remove(); hide.remove(); };
  }, []);
  // announce this room as the screen being read, so a push for it does not buzz
  // over it (data/push_present.ts decideChatPush)
  useEffect(() => {
    usePresence.getState().setFocusedCard("room:" + roomId);
    return () => usePresence.getState().setFocusedCard(null);
  }, [roomId]);

  const scroller = useRef<ScrollView>(null);
  useEffect(() => { const h = setTimeout(() => scroller.current?.scrollToEnd({ animated: true }), 60); return () => clearTimeout(h); },
    [messages.length]);

  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const [info, setInfo] = useState(false);
  const post = useMutation({
    mutationFn: (body: string) => api.roomPost(roomId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["room", roomId] });
      void qc.invalidateQueries({ queryKey: ["rooms"] });
    },
    onError: (e: Error, body) => { setText(body); setErr(tr("rooms.sendFailed", { msg: e.message })); },
  });
  const send = () => {
    const body = text.trim();
    if (!body || post.isPending) return;
    setErr(""); setText("");
    post.mutate(body);
  };

  // @-suggestions: members + henry, filtered by what is typed after the last @
  const m = /(?:^|\s)@([A-Za-z0-9_.-]*)$/.exec(text);
  const suggestions = useMemo(() => {
    if (!m) return [] as string[];
    const q = m[1].toLowerCase();
    return ["henry", ...members.filter((x) => x !== me?.name)].filter((x) => x.toLowerCase().startsWith(q));
  }, [m?.[1], members.join(","), me?.name]);   // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (name: string) => setText(text.replace(/@([A-Za-z0-9_.-]*)$/, "@" + name + " "));

  // Henry is "answering" while the last @henry has no Henry message after it
  const pendingHenry = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const x = messages[i];
      if (x.byKind === "henry") return false;
      if (x.byKind === "human" && /(^|\s)@henry\b/i.test(x.text)) {
        const at = x.date && x.ts ? Date.parse(`${x.date}T${x.ts}:00`) : NaN;
        return Number.isNaN(at) ? true : Date.now() - at < HENRY_WAIT_MS;
      }
    }
    return false;
  }, [messages]);

  const palette = [t.accent2, t.ok, t.warn, t.human, t.ai];
  const colorOf = (who: string) => {
    let h = 0; for (const c of who) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return palette[h % palette.length];
  };

  // A mention is drawn in the accent colour - except inside MY OWN bubble, which
  // IS the accent colour (it vanished there: found in the screenshot review), so
  // there it is bold and underlined in the bubble's own text colour.
  const renderText = (s: string, color: string, own = false) => (
    <Text selectable style={{ color, fontSize: 14.5, lineHeight: 20 }}>
      {s.split(MENTION).map((part, i) => {
        const hit = part.startsWith("@") && (part.slice(1).toLowerCase() === "henry" || members.some((x) => x.toLowerCase() === part.slice(1).toLowerCase()));
        if (!hit) return part;
        return own
          ? <Text key={i} style={{ fontWeight: "800", textDecorationLine: "underline" }}>{part}</Text>
          : <Text key={i} style={{ fontWeight: "700", color: t.accent }}>{part}</Text>;
      })}
    </Text>
  );

  // members panel + card filing
  const [task, setTask] = useState("");
  const [note, setNote] = useState("");
  const { data: accounts } = useQuery({ queryKey: ["roomAccounts"], queryFn: api.roomAccounts, enabled: admin && info });
  const addable = (Array.isArray(accounts) ? accounts : []).filter((a) => !members.includes(a.name));
  const change = useMutation({
    mutationFn: (v: { add: string[]; remove: string[] }) => api.roomMembers(roomId, v.add, v.remove),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["room", roomId] }); void qc.invalidateQueries({ queryKey: ["rooms"] }); },
    onError: (e: Error) => setNote(e.message),
  });
  const file = useMutation({
    mutationFn: () => api.roomCard(roomId, task.trim()),
    onSuccess: () => { setTask(""); setNote(tr("rooms.cardFiled")); void qc.invalidateQueries({ queryKey: ["room", roomId] }); },
    onError: (e: Error) => setNote(e.message),
  });

  if (isError || (!isLoading && !room)) {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
        <ScreenHeader title={tr("nav.rooms")} onBack={() => router.back()} />
        <View style={{ padding: 20 }}><Empty text={tr("rooms.notFound")} /></View>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: wide ? 0 : insets.top }}>
      <ScreenHeader title={room?.name ?? ""} onBack={() => router.back()} />
      <Pressable onPress={() => setInfo(!info)} style={{ flexDirection: "row", alignItems: "center", gap: 6,
        paddingHorizontal: 16, paddingBottom: 8 }}>
        <Ionicons name="people-outline" size={14} color={t.txtTertiary} />
        <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12, flex: 1 }}>{members.join(", ")}</Text>
        <Ionicons name={info ? "chevron-up" : "chevron-down"} size={14} color={t.txtTertiary} />
      </Pressable>

      {info ? (
        <View style={{ marginHorizontal: 12, marginBottom: 8, padding: 12, gap: 10, borderRadius: 14, borderWidth: 1,
          borderColor: t.glassBorder, backgroundColor: t.surface1 }}>
          <Text style={{ color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6 }}>{tr("rooms.members").toUpperCase()}</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
            {members.map((n) => (
              <View key={n} style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 5,
                borderRadius: 999, backgroundColor: t.surface2 }}>
                <Text style={{ color: t.txtPrimary, fontSize: 12.5 }}>{n}</Text>
                {admin && members.length > 1 ? (
                  <Pressable accessibilityLabel={tr("rooms.remove")} onPress={() => change.mutate({ add: [], remove: [n] })}>
                    <Ionicons name="close-circle" size={14} color={t.txtTertiary} />
                  </Pressable>
                ) : null}
              </View>
            ))}
          </View>
          {admin && addable.length > 0 ? (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {addable.map((a) => (
                <Pressable key={a.name} onPress={() => change.mutate({ add: [a.name], remove: [] })}
                  style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 5,
                    borderRadius: 999, borderWidth: 1, borderColor: t.accent + "88" }}>
                  <Ionicons name="add" size={13} color={t.accent} />
                  <Text style={{ color: t.accent, fontSize: 12.5 }}>{a.name}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
          <Text style={{ color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6, paddingTop: 4 }}>{tr("rooms.cardNew").toUpperCase()}</Text>
          <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
            <TextInput value={task} onChangeText={setTask} placeholder={tr("rooms.cardTask")} maxLength={200}
              placeholderTextColor={t.txtPlaceholder}
              style={{ flex: 1, color: t.txtPrimary, fontSize: 14, borderBottomWidth: 1, borderBottomColor: t.borderSubtle, paddingVertical: 6 }} />
            <Pressable disabled={!task.trim() || file.isPending} onPress={() => file.mutate()}
              style={{ paddingHorizontal: 12, paddingVertical: 7, borderRadius: 10, backgroundColor: task.trim() ? t.accent : t.surface2 }}>
              <Text style={{ color: task.trim() ? "#fff" : t.txtTertiary, fontWeight: "600", fontSize: 12.5 }}>{tr("rooms.cardFile")}</Text>
            </Pressable>
          </View>
          {note ? <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{note}</Text> : null}
          <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("rooms.everyone")}</Text>
        </View>
      ) : null}

      <ScrollView ref={scroller} style={{ flex: 1 }} keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingHorizontal: 12, paddingBottom: 12, gap: 8,
          width: "100%", maxWidth: wide ? 760 : undefined, alignSelf: "center" }}>
        {messages.length === 0 && !isLoading ? <Empty text={tr("rooms.noMessages")} /> : null}
        {messages.map((x) => {
          if (x.byKind === "system") {
            return (
              <Pressable key={x.seq} disabled={!x.card}
                onPress={() => x.card && router.push({ pathname: "/card/[id]", params: { id: x.card } } as never)}
                style={{ alignSelf: "center", flexDirection: "row", alignItems: "center", gap: 6, maxWidth: "92%",
                  paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: t.surface2 }}>
                <Ionicons name="document-text-outline" size={14} color={t.accent} />
                <Text numberOfLines={2} style={{ color: t.txtSecondary, fontSize: 12.5, flexShrink: 1 }}>{x.by} {x.text}</Text>
                {x.card ? <Ionicons name="chevron-forward" size={13} color={t.txtTertiary} /> : null}
              </Pressable>
            );
          }
          const mine = x.byKind === "human" && x.by === me?.name;
          const henry = x.byKind === "henry";
          const bg = mine ? t.accent : henry ? (x.error ? t.warn + "30" : t.ai + "26") : t.surface2;
          return (
            <View key={x.seq} style={{ alignSelf: mine ? "flex-end" : "flex-start", maxWidth: "86%", gap: 3 }}>
              {!mine ? (
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingLeft: 4 }}>
                  {henry ? <Ionicons name="sparkles" size={12} color={t.ai} /> : null}
                  <Text style={{ color: henry ? t.ai : colorOf(x.by), fontSize: 12, fontWeight: "700" }}>
                    {henry ? tr("rooms.henry") : x.by}
                  </Text>
                  {henry && x.to ? <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("rooms.henryTo", { name: x.to })}</Text> : null}
                  <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{x.ts ?? ""}</Text>
                </View>
              ) : null}
              <View style={{ backgroundColor: bg, borderRadius: 16, borderTopRightRadius: mine ? 4 : 16,
                borderTopLeftRadius: mine ? 16 : 4, paddingHorizontal: 12, paddingVertical: 8 }}>
                {renderText(x.text, mine ? "#fff" : t.txtPrimary, mine)}
              </View>
            </View>
          );
        })}
        {pendingHenry ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingLeft: 4 }}>
            <Ionicons name="sparkles" size={12} color={t.ai} />
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("rooms.henryWorking")}</Text>
          </View>
        ) : null}
      </ScrollView>

      {suggestions.length > 0 ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, paddingHorizontal: 12, paddingBottom: 6 }}>
          {suggestions.map((s) => (
            <Pressable key={s} onPress={() => pick(s)} style={{ flexDirection: "row", alignItems: "center", gap: 4,
              paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, borderWidth: 1,
              borderColor: s === "henry" ? t.ai : t.accent + "88", backgroundColor: t.surface1 }}>
              {s === "henry" ? <Ionicons name="sparkles" size={12} color={t.ai} /> : null}
              <Text style={{ color: t.txtPrimary, fontSize: 12.5 }}>@{s}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
      {err ? <Text style={{ color: t.danger, fontSize: 12, paddingHorizontal: 16, paddingBottom: 4 }}>{err}</Text> : null}
      <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 8, paddingHorizontal: 12,
        paddingTop: 8, paddingBottom: kb > 0 ? insets.bottom + 10 : insets.bottom + 8,
        borderTopWidth: 1, borderTopColor: t.glassBorder, backgroundColor: t.surface1 }}>
        <TextInput value={text} onChangeText={setText} placeholder={tr("rooms.placeholder")} multiline
          placeholderTextColor={t.txtPlaceholder}
          style={{ flex: 1, maxHeight: 120, color: t.txtPrimary, fontSize: 15, backgroundColor: t.surface2, borderRadius: 18,
            paddingHorizontal: 14, paddingTop: 9, paddingBottom: 9 }} />
        <Pressable onPress={send} disabled={!text.trim() || post.isPending} accessibilityLabel={tr("rooms.send")}
          style={{ width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center",
            backgroundColor: text.trim() ? t.accent : t.surface2 }}>
          <Ionicons name="send" size={17} color={text.trim() ? "#fff" : t.txtTertiary} />
        </Pressable>
      </View>
      {kb > 0 ? <View style={{ height: kb }} /> : null}
    </View>
  );
}
