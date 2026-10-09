import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { usePresence } from "@/data/presence";
import { chatFallbackInterval, useStreamCaps } from "@/data/stream";
import type { RoomMessage } from "@/data/types";
import { useT } from "@/i18n";
import { can } from "@/kernel";
import { useTheme } from "@/theme";
import type { Recipient } from "@/ui/card_composer";
import type { TStep } from "@/ui/card_transcript";
import { ChatSurface } from "@/ui/chat_surface";
import { Empty, ScreenHeader } from "@/ui/kit";
import { RoomProjects } from "@/ui/room_projects";
import { useResponsive } from "@/ui/responsive";

const HENRY_WAIT_MS = 3 * 60 * 1000;     // a pending @henry stops reading as "answering" after this

// One team room (backlog/team-rooms-member, stages 3-6). Everyone in the room
// reads everything; every message carries its author. @henry asks Henry (and
// only that wakes him), @name addresses a member. Opening the room advances
// MY read cursor server-side (GET /rooms/messages), so there is nothing to
// "mark read" from here.
//
// The conversation is drawn by the Henry chat's own Transcript and Composer
// (owner 2026-10-09: "UI/UX gleich") - a room is one more thread kind, never a
// second chat UI. Only the roster (members + Henry as recipients) differs.
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

  // announce this room as the screen being read, so a push for it does not buzz
  // over it (data/push_present.ts decideChatPush)
  useEffect(() => {
    usePresence.getState().setFocusedCard("room:" + roomId);
    return () => usePresence.getState().setFocusedCard(null);
  }, [roomId]);

  const [err, setErr] = useState("");
  const [info, setInfo] = useState(false);
  const post = useMutation({
    mutationFn: (body: string) => api.roomPost(roomId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["room", roomId] });
      void qc.invalidateQueries({ queryKey: ["rooms"] });
    },
    onError: (e: Error) => setErr(tr("rooms.sendFailed", { msg: e.message })),
  });
  // The composer is the Henry chat's own: a recipient picked in its @ popover
  // becomes the @name the daemon reads - @henry is what wakes Henry.
  const send = (body: string, o: { to?: string }) => {
    const v = body.trim();
    if (!v) return;
    setErr("");
    post.mutate(o.to ? "@" + o.to + " " + v : v);
  };

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
  const recipients: Recipient[] = [
    { id: "henry", label: "henry", color: t.ai, icon: "sparkles", hint: tr("rooms.henry") },
    ...members.filter((x) => x !== me?.name).map((x): Recipient => ({ id: x, label: x, color: colorOf(x), icon: "person-outline" })),
  ];

  // The room's messages as the Henry chat's own transcript steps: one row
  // model, one renderer.
  const steps: TStep[] = messages.map((x): TStep => {
    if (x.byKind === "system") {
      return x.card
        ? { role: "assistant", kind: "card", card: x.card, label: x.by + " " + x.text, text: x.by + " " + x.text, ts: x.ts, seq: x.seq }
        : { role: "assistant", kind: "note", text: x.by + " " + x.text, ts: x.ts, seq: x.seq };
    }
    if (x.byKind === "henry") {
      return { role: "assistant", kind: x.error ? "error" : "text", text: x.text, ts: x.ts, seq: x.seq,
               by: "Henry", byKind: "henry", to: x.to };
    }
    return { role: "user", kind: "text", text: x.text, ts: x.ts, seq: x.seq, by: x.by, byKind: "human" };
  });
  if (pendingHenry) {
    steps.push({ role: "assistant", kind: "text", text: tr("rooms.henryWorking"), streaming: true, by: "Henry", byKind: "henry" });
  }

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

      <RoomProjects members={members} me={me?.name} owner={me?.role === "owner"} />

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

      <ChatSurface steps={steps} me={me?.name} loading={isLoading} empty={<Empty text={tr("rooms.noMessages")} />}
        onSend={(txt, o) => send(txt, o)} placeholder={tr("rooms.placeholder")} draftKey={"room:" + roomId}
        recipients={recipients} error={err} minimal />
    </View>
  );
}
