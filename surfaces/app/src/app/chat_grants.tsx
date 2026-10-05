import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import type { ChatGrant, GrantedChat } from "@/data/types";
import { useT } from "@/i18n";
import { can } from "@/kernel";
import { useTheme } from "@/theme";
import { Empty, ScreenHeader } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

const fmt = (epoch: number) => {
  const d = new Date(epoch * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}. ${p(d.getHours())}:${p(d.getMinutes())}`;
};

// Chat consent (cells/copilot/chat/chat_grants.py): nobody reads my private
// Henry chat unless I let a named admin, for a limited time. "Active" is derived
// by the daemon at every read; every read made under a grant is listed under it
// - who, when, how many entries.
export default function ChatGrantsScreen() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const { data } = useQuery({ queryKey: ["chatGrants"], queryFn: api.chatGrants });
  const given: ChatGrant[] = Array.isArray(data?.given) ? data!.given : [];
  const received: ChatGrant[] = Array.isArray(data?.received) ? data!.received : [];
  // admins to choose from: the member picker route (owner/operator only), minus myself
  const { data: accounts } = useQuery({
    queryKey: ["roomAccounts"], queryFn: api.roomAccounts, enabled: can(me, "rooms.manage"),
  });
  const admins = (Array.isArray(accounts) ? accounts : []).filter((a) => a.name !== me?.name
    && (a.role === "owner" || a.role === "operator"));

  const [grantee, setGrantee] = useState("");
  const [hours, setHours] = useState("24");
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<GrantedChat | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["chatGrants"] });
  const give = useMutation({
    mutationFn: () => api.chatGrantCreate(grantee, Math.round(Number(hours) || 0)),
    onSuccess: () => { setErr(""); setGrantee(""); refresh(); },
    onError: (e: Error) => setErr(tr("grants.failed", { msg: e.message })),
  });
  const revoke = useMutation({ mutationFn: (id: string) => api.chatGrantRevoke(id), onSuccess: refresh });
  const read = useMutation({
    mutationFn: (account: string) => api.chatAdminRead(account),
    onSuccess: (r) => { setErr(""); setOpen(r); },
    onError: (e: Error) => setErr(tr("grants.failed", { msg: e.message })),
  });

  const card = { backgroundColor: t.surface1, borderWidth: 1, borderColor: t.glassBorder, borderRadius: 14, padding: 12, gap: 8 } as const;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr("nav.chatGrants")} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 14, gap: 12, paddingBottom: insets.bottom + 24,
        width: "100%", maxWidth: wide ? 720 : undefined, alignSelf: "center" }}>
        <Text style={{ color: t.txtTertiary, fontSize: 12.5, lineHeight: 18 }}>{tr("grants.sub")}</Text>

        {open ? (
          <View style={card}>
            <View style={{ flexDirection: "row", alignItems: "center" }}>
              <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "700", flex: 1 }}>{tr("grants.readTitle", { name: open.account })}</Text>
              <Pressable onPress={() => setOpen(null)}><Text style={{ color: t.accent, fontSize: 13 }}>{tr("grants.close")}</Text></Pressable>
            </View>
            {open.entries.map((e, i) => (
              <View key={i} style={{ gap: 2 }}>
                <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{e.role === "user" ? open.account : "Henry"} {e.date ?? ""} {e.ts ?? ""}</Text>
                <Text selectable style={{ color: t.txtPrimary, fontSize: 13.5, lineHeight: 19 }}>{e.text ?? ""}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {received.length > 0 ? (
          <View style={card}>
            <Text style={{ color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6 }}>{tr("grants.received").toUpperCase()}</Text>
            {received.map((g) => (
              <View key={g.id} style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Ionicons name="lock-open-outline" size={16} color={t.ok} />
                <View style={{ flex: 1 }}>
                  <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{g.account}</Text>
                  <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("grants.activeUntil", { t: fmt(g.expires) })}</Text>
                </View>
                <Pressable onPress={() => read.mutate(g.account)} style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 10, backgroundColor: t.accent + "26" }}>
                  <Text style={{ color: t.accent, fontSize: 12.5, fontWeight: "600" }}>{tr("grants.read")}</Text>
                </Pressable>
              </View>
            ))}
          </View>
        ) : null}

        <View style={card}>
          <Text style={{ color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6 }}>{tr("grants.give").toUpperCase()}</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
            {admins.map((a) => {
              const on = grantee === a.name;
              return (
                <Pressable key={a.name} onPress={() => setGrantee(on ? "" : a.name)}
                  style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1,
                    borderColor: on ? t.accent : t.borderSubtle, backgroundColor: on ? t.accent + "26" : "transparent" }}>
                  <Text style={{ color: on ? t.txtPrimary : t.txtSecondary, fontSize: 13 }}>{a.name}</Text>
                </Pressable>
              );
            })}
          </View>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text style={{ color: t.txtSecondary, fontSize: 13 }}>{tr("grants.hours")}</Text>
            <TextInput value={hours} onChangeText={setHours} keyboardType="number-pad" maxLength={3}
              style={{ width: 56, color: t.txtPrimary, fontSize: 15, borderBottomWidth: 1, borderBottomColor: t.borderSubtle, paddingVertical: 4, textAlign: "center" }} />
            <View style={{ flex: 1 }} />
            <Pressable disabled={!grantee || give.isPending} onPress={() => give.mutate()}
              style={{ paddingHorizontal: 16, paddingVertical: 8, borderRadius: 10, backgroundColor: grantee ? t.accent : t.surface2 }}>
              <Text style={{ color: grantee ? "#fff" : t.txtTertiary, fontWeight: "600", fontSize: 13 }}>{tr("grants.give")}</Text>
            </Pressable>
          </View>
          {err ? <Text style={{ color: t.danger, fontSize: 12 }}>{err}</Text> : null}
        </View>

        <Text style={{ color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6 }}>{tr("grants.mine").toUpperCase()}</Text>
        {given.length === 0 ? <Empty text={tr("grants.none")} /> : given.map((g) => (
          <View key={g.id} style={card}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Ionicons name={g.active ? "lock-open-outline" : "lock-closed-outline"} size={16} color={g.active ? t.ok : t.txtTertiary} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{g.grantee}</Text>
                <Text style={{ color: g.active ? t.ok : t.txtTertiary, fontSize: 11.5 }}>
                  {g.active ? tr("grants.activeUntil", { t: fmt(g.expires) }) : g.revoked ? tr("grants.revoked") : tr("grants.expired")}
                </Text>
              </View>
              {g.active ? (
                <Pressable onPress={() => revoke.mutate(g.id)} style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 10, backgroundColor: t.danger + "22" }}>
                  <Text style={{ color: t.danger, fontSize: 12.5, fontWeight: "600" }}>{tr("grants.revoke")}</Text>
                </Pressable>
              ) : null}
            </View>
            <Text style={{ color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6 }}>{tr("grants.reads").toUpperCase()}</Text>
            {(g.reads ?? []).length === 0 ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("grants.noReads")}</Text>
              : (g.reads ?? []).map((r, i) => (
                <Text key={i} style={{ color: t.txtSecondary, fontSize: 12.5 }}>{tr("grants.readLine", { who: r.reader, t: fmt(r.ts), n: r.n })}</Text>
              ))}
          </View>
        ))}
      </ScrollView>
    </View>
  );
}
