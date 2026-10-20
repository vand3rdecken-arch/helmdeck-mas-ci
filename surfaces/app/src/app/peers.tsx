import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import type { PeerLink } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Empty, ScreenHeader } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

const fmt = (epoch?: number) => {
  if (!epoch) return "";
  const d = new Date(epoch * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}. ${p(d.getHours())}:${p(d.getMinutes())}`;
};

// Connections to OTHER HelmDeck instances (spine/comms/peers.py) - the other
// side of Agent access: someone else's instance shared rooms/cards with me,
// I paste the link here once. The daemon redeems it end-to-end, keeps the
// token encrypted for my account, and from then on the rooms list shows those
// rooms and Henry gets the connection as tools.
export default function PeersScreen() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const { data } = useQuery({ queryKey: ["peers"], queryFn: api.peers });
  const list: PeerLink[] = Array.isArray(data?.peers) ? data!.peers : [];
  const [link, setLink] = useState("");
  const [label, setLabel] = useState("");
  const [err, setErr] = useState("");
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["peers"] });
    void qc.invalidateQueries({ queryKey: ["rooms"] });
  };
  const add = useMutation({
    mutationFn: () => api.peerAdd(link.trim(), label.trim()),
    onSuccess: () => { setLink(""); setLabel(""); setErr(""); refresh(); },
    onError: (e: Error) => setErr(e.message),
  });
  const remove = useMutation({ mutationFn: (id: string) => api.peerRemove(id), onSuccess: refresh });
  const recheck = useMutation({ mutationFn: (id: string) => api.peerRefresh(id), onSuccess: refresh });

  const card = { backgroundColor: t.surface1, borderWidth: 1, borderColor: t.glassBorder, borderRadius: 14, padding: 12, gap: 8 } as const;
  const cap = { color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6 } as const;
  const ok = link.trim().includes("#c=") && !add.isPending;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr("nav.peers")} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 14, gap: 12, paddingBottom: insets.bottom + 24,
        width: "100%", maxWidth: wide ? 720 : undefined, alignSelf: "center" }}>
        <Text style={{ color: t.txtTertiary, fontSize: 12.5, lineHeight: 18 }}>{tr("peers.sub")}</Text>

        <View style={card}>
          <TextInput value={link} onChangeText={setLink} placeholder={tr("peers.link")} placeholderTextColor={t.txtTertiary}
            autoCapitalize="none" autoCorrect={false}
            style={{ color: t.txtPrimary, fontSize: 13.5, borderBottomWidth: 1, borderBottomColor: t.borderSubtle, paddingVertical: 6 }} />
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <TextInput value={label} onChangeText={setLabel} placeholder={tr("peers.label")} placeholderTextColor={t.txtTertiary}
              maxLength={60} style={{ flex: 1, color: t.txtPrimary, fontSize: 14, borderBottomWidth: 1,
                borderBottomColor: t.borderSubtle, paddingVertical: 6 }} />
            <Pressable disabled={!ok} onPress={() => add.mutate()}
              style={{ paddingHorizontal: 14, paddingVertical: 8, borderRadius: 10, backgroundColor: ok ? t.accent : t.surface2 }}>
              <Text style={{ color: ok ? "#fff" : t.txtTertiary, fontWeight: "600", fontSize: 13 }}>{tr("peers.connect")}</Text>
            </Pressable>
          </View>
          {err ? <Text style={{ color: t.danger, fontSize: 12 }}>{err}</Text> : null}
        </View>

        <Text style={cap}>{tr("peers.mine").toUpperCase()}</Text>
        {list.length === 0 ? <Empty text={tr("peers.none")} /> : list.map((p) => (
          <View key={p.id} style={card}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Ionicons name="git-merge-outline" size={16} color={p.err ? t.danger : t.ok} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{p.label}</Text>
                <Text style={{ color: t.txtTertiary, fontSize: 11.5 }} numberOfLines={1}>
                  {p.err ? tr("peers.unreachable", { msg: p.err })
                    : [p.info.as ? tr("peers.youAre", { as: p.info.as, who: p.info.for ?? "?" }) : "",
                       p.info.expires ? tr("peers.until", { t: fmt(p.info.expires) }) : ""].filter(Boolean).join(" · ")}
                </Text>
              </View>
              <Pressable onPress={() => recheck.mutate(p.id)} accessibilityLabel={tr("peers.refresh")} style={{ padding: 6 }}>
                <Ionicons name="refresh" size={16} color={t.txtSecondary} />
              </Pressable>
              <Pressable onPress={() => remove.mutate(p.id)} style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 10, backgroundColor: t.danger + "22" }}>
                <Text style={{ color: t.danger, fontSize: 12.5, fontWeight: "600" }}>{tr("peers.remove")}</Text>
              </Pressable>
            </View>
            {(p.info.scope ?? []).map((s) => (
              <Pressable key={s.kind + s.id} disabled={s.kind !== "room"}
                onPress={() => router.push({ pathname: "/peer_room", params: { peer: p.id, room: s.id, name: s.name } } as never)}
                style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 }}>
                <Ionicons name={s.kind === "room" ? "chatbubbles-outline" : "albums-outline"} size={15} color={t.txtSecondary} />
                <Text style={{ color: t.txtPrimary, fontSize: 13.5, flex: 1 }} numberOfLines={1}>{s.name || s.id}</Text>
                <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>
                  {tr(s.code ? "access.code" : s.write ? "access.write" : "access.read")}
                </Text>
                {s.kind === "room" ? <Ionicons name="chevron-forward" size={14} color={t.txtTertiary} /> : null}
              </Pressable>
            ))}
          </View>
        ))}
      </ScrollView>
    </View>
  );
}
