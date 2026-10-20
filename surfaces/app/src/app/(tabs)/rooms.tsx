import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { chatFallbackInterval, useStreamCaps } from "@/data/stream";
import { useT } from "@/i18n";
import { can } from "@/kernel";
import { useTheme } from "@/theme";
import { Empty } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

// Team rooms (backlog/team-rooms-member): the Slack-channel list. Which rooms
// show up is the daemon's decision from the MEMBER LIST - a guest sees the rooms
// they were put in and nothing else. Unread is derived by the daemon from this
// account's read cursor on every call; the list refreshes from the chat cursor
// (data/stream.ts ensureChatFresh), not from a timer of its own.
export default function RoomsTab() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const chatEvents = useStreamCaps((s) => s.chatEvents);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const { data } = useQuery({ queryKey: ["rooms"], queryFn: api.rooms, refetchInterval: chatFallbackInterval(chatEvents) });
  // never trust the wire to be an array (the models-picker crash class)
  const rooms = Array.isArray(data) ? data : [];
  // rooms OTHER instances shared with me (spine/comms/peers.py): from the cached
  // scope of each connection - listing them costs no remote call
  const { data: peerData } = useQuery({ queryKey: ["peers"], queryFn: api.peers, staleTime: 60000 });
  const peerRooms = (Array.isArray(peerData?.peers) ? peerData!.peers : []).flatMap((p) =>
    (p.info.scope ?? []).filter((s) => s.kind === "room").map((s) => ({ peer: p, room: s })));
  const admin = can(me, "rooms.manage");

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const { data: accounts } = useQuery({
    queryKey: ["roomAccounts"], queryFn: api.roomAccounts, enabled: admin && creating,
  });
  const create = useMutation({
    mutationFn: () => api.roomNew(name.trim(), picked),
    onSuccess: (r) => {
      setCreating(false); setName(""); setPicked([]); setErr("");
      void qc.invalidateQueries({ queryKey: ["rooms"] });
      router.push({ pathname: "/room/[id]", params: { id: r.id } } as never);
    },
    onError: (e: Error) => setErr(e.message),
  });

  const others = (Array.isArray(accounts) ? accounts : []).filter((a) => a.name !== me?.name);

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingTop: insets.top + 10,
        paddingHorizontal: 16, paddingBottom: 6 }}>
        <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", flex: 1 }}>{tr("nav.rooms")}</Text>
        {admin ? (
          <Pressable onPress={() => { setCreating(!creating); setErr(""); }} accessibilityLabel={tr("rooms.new")}
            style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6,
              borderRadius: 999, backgroundColor: t.accent + "26" }}>
            <Ionicons name={creating ? "close" : "add"} size={16} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 12.5, fontWeight: "600" }}>{tr("rooms.new")}</Text>
          </Pressable>
        ) : null}
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 90, gap: 8, paddingHorizontal: 14,
        width: "100%", maxWidth: wide ? 720 : undefined, alignSelf: "center" }}>
        {creating ? (
          <View style={{ backgroundColor: t.surface1, borderWidth: 1, borderColor: t.glassBorder, borderRadius: 14,
            padding: 12, gap: 10 }}>
            <TextInput value={name} onChangeText={setName} placeholder={tr("rooms.name")}
              placeholderTextColor={t.txtPlaceholder} maxLength={60}
              style={{ color: t.txtPrimary, fontSize: 15, borderBottomWidth: 1, borderBottomColor: t.borderSubtle,
                paddingVertical: 6 }} />
            <Text style={{ color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6 }}>{tr("rooms.members").toUpperCase()}</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {others.map((a) => {
                const on = picked.includes(a.name);
                return (
                  <Pressable key={a.name} onPress={() => setPicked(on ? picked.filter((x) => x !== a.name) : [...picked, a.name])}
                    style={{ flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 6,
                      borderRadius: 999, borderWidth: 1, borderColor: on ? t.accent : t.borderSubtle,
                      backgroundColor: on ? t.accent + "26" : "transparent" }}>
                    <Ionicons name={on ? "checkmark-circle" : "ellipse-outline"} size={14} color={on ? t.accent : t.txtTertiary} />
                    <Text style={{ color: on ? t.txtPrimary : t.txtSecondary, fontSize: 12.5 }}>{a.name}</Text>
                  </Pressable>
                );
              })}
            </View>
            {err ? <Text style={{ color: t.danger, fontSize: 12 }}>{err}</Text> : null}
            <Pressable disabled={!name.trim() || create.isPending} onPress={() => create.mutate()}
              style={{ alignSelf: "flex-end", paddingHorizontal: 16, paddingVertical: 8, borderRadius: 10,
                backgroundColor: name.trim() ? t.accent : t.surface2 }}>
              <Text style={{ color: name.trim() ? "#fff" : t.txtTertiary, fontWeight: "600", fontSize: 13 }}>{tr("rooms.create")}</Text>
            </Pressable>
          </View>
        ) : null}

        {rooms.length === 0 && !creating && peerRooms.length === 0 ? (
          <View style={{ paddingTop: 24, alignItems: "center", gap: 10 }}>
            <Ionicons name="people-outline" size={34} color={t.txtTertiary} />
            <Empty text={tr(admin ? "rooms.emptyAdmin" : "rooms.empty")} />
          </View>
        ) : null}

        {rooms.map((r) => (
          <Pressable key={r.id} onPress={() => router.push({ pathname: "/room/[id]", params: { id: r.id } } as never)}
            style={{ flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: t.surface1, borderWidth: 1,
              borderColor: r.unread_mentions > 0 ? t.accent + "88" : t.glassBorder, borderRadius: 14, padding: 12 }}>
            <View style={{ width: 42, height: 42, borderRadius: 13, backgroundColor: t.accent + "26",
              alignItems: "center", justifyContent: "center" }}>
              <Text style={{ color: t.accent, fontSize: 18, fontWeight: "700" }}>{(r.name || "?").charAt(0).toUpperCase()}</Text>
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 15, fontWeight: r.unread > 0 ? "700" : "600", flex: 1 }}>{r.name}</Text>
                <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{(r.last_at || "").trim().slice(-5)}</Text>
              </View>
              <Text numberOfLines={1} style={{ color: r.unread > 0 ? t.txtSecondary : t.txtTertiary, fontSize: 13 }}>
                {r.preview ? `${r.last_by}: ${r.preview}` : tr("rooms.membersN", { n: r.members.length })}
              </Text>
            </View>
            {r.unread > 0 ? (
              <View style={{ minWidth: 22, height: 22, borderRadius: 11, paddingHorizontal: 6, alignItems: "center",
                justifyContent: "center", backgroundColor: r.unread_mentions > 0 ? t.warn : t.accent }}>
                <Text style={{ color: "#fff", fontSize: 11.5, fontWeight: "700" }}>{r.unread_mentions > 0 ? "@" : r.unread}</Text>
              </View>
            ) : null}
          </Pressable>
        ))}

        {peerRooms.length > 0 ? (
          <Text style={{ color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6, paddingTop: 10, paddingHorizontal: 4 }}>
            {tr("peers.section").toUpperCase()}
          </Text>
        ) : null}
        {peerRooms.map(({ peer, room }) => (
          <Pressable key={peer.id + room.id}
            onPress={() => router.push({ pathname: "/peer_room", params: { peer: peer.id, room: room.id, name: room.name } } as never)}
            style={{ flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: t.surface1, borderWidth: 1,
              borderColor: t.glassBorder, borderRadius: 14, padding: 12 }}>
            <View style={{ width: 42, height: 42, borderRadius: 13, backgroundColor: t.accent2 + "26",
              alignItems: "center", justifyContent: "center" }}>
              <Ionicons name="git-merge-outline" size={19} color={t.accent2} />
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "600" }}>{room.name || room.id}</Text>
              <Text numberOfLines={1} style={{ color: peer.err ? t.danger : t.txtTertiary, fontSize: 13 }}>
                {peer.err ? tr("peers.unreachable", { msg: peer.err }) : tr("peers.roomFrom", { name: peer.label })}
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}
