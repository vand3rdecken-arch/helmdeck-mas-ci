import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { Platform, Pressable, ScrollView, Share, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import type { AccessGrant, AccessGrantIssued, AccessScope, Track } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { cardTitle } from "@/ui/card_title";
import { Empty, ScreenHeader } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

const fmt = (epoch: number) => {
  const d = new Date(epoch * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}. ${p(d.getHours())}:${p(d.getMinutes())}`;
};

// none -> read -> write -> none: one tap cycles a room/card through the levels
// none -> read -> write -> (cards only) code -> none
type Level = "read" | "write" | "code";
const next = (l: Level | undefined, card: boolean): Level | undefined =>
  l === undefined ? "read" : l === "read" ? "write" : l === "write" && card ? "code" : undefined;

// External-agent access (spine/auth/access_grants.py, the door spine/http/mcp.py).
// The create response carries a ONE-TIME claim code, never a token: the share
// link is <door>#c=<code> (the fragment never reaches a server); the page
// behind it redeems the code once and shows the token only to whoever opened
// it first. A link that leaks later opens nothing.
// Deep link: /agent_access?room=<id> or ?card=<id> preselects that target.
export default function AgentAccessScreen() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const params = useLocalSearchParams<{ room?: string; card?: string }>();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const { data } = useQuery({ queryKey: ["accessGrants"], queryFn: api.accessGrants });
  const { data: roomList } = useQuery({ queryKey: ["rooms"], queryFn: api.rooms });
  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks });
  const grants: AccessGrant[] = Array.isArray(data?.grants) ? data!.grants : [];
  const door = data?.door;
  // the rooms the caller is IN (the owner overview lists every room, but a
  // grant can only carry rooms its issuer is a member of)
  const myRooms = (Array.isArray(roomList) ? roomList : []).filter((r) => !me?.name || (r.members ?? []).includes(me.name));
  const myCards = (Array.isArray(tracks) ? (tracks as Track[]) : [])
    .filter((k) => !k.summary && k.lane !== "done");

  const [label, setLabel] = useState("");
  const [hours, setHours] = useState("24");
  // default ON: only the end-to-end bridge / another HelmDeck may use it
  const [sealedOnly, setSealedOnly] = useState(true);
  const [sel, setSel] = useState<Record<string, Level>>(() => {
    const s: Record<string, Level> = {};
    if (params.room) s["room:" + params.room] = "write";
    if (params.card) s["card:" + params.card] = "write";
    return s;
  });
  const [err, setErr] = useState("");
  const [issued, setIssued] = useState<AccessGrantIssued | null>(null);
  const [copied, setCopied] = useState("");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["accessGrants"] });

  const scope: AccessScope[] = Object.entries(sel).map(([k, l]) => {
    const [kind, ...rest] = k.split(":");
    return { kind: kind as "room" | "card", id: rest.join(":"), write: l !== "read", code: l === "code" };
  });
  const create = useMutation({
    mutationFn: () => api.accessGrantCreate(label.trim(), Math.round(Number(hours) || 0), scope, sealedOnly),
    onSuccess: (g) => { setErr(""); setIssued(g); setLabel(""); setSel({}); refresh(); },
    onError: (e: Error) => setErr(tr("access.failed", { msg: e.message })),
  });
  const revoke = useMutation({ mutationFn: (id: string) => api.accessGrantRevoke(id), onSuccess: refresh });

  const doorUrl = issued?.url || door?.url || "";
  const link = issued && doorUrl
    ? `${doorUrl}#c=${issued.code}${issued.key ? "&k=" + encodeURIComponent(issued.key) : ""}`
      + `${issued.shim_sha ? "&s=" + issued.shim_sha : ""}` : "";
  const shareText = useMemo(() => issued ? tr("access.shareText", {
    label: issued.label, link: link || `${doorUrl || "http://<PC>:8140/mcp"}  (claim: ${issued.code})`,
    issuer: me?.name ?? "",
  }) : "", [issued, link, doorUrl, me?.name, tr]);

  const copy = async (what: string, text: string) => {
    await Clipboard.setStringAsync(text);
    setCopied(what);
    setTimeout(() => setCopied(""), 1500);
  };
  const share = async () => {
    if (Platform.OS === "web") return copy("all", shareText);
    try { await Share.share({ message: shareText }); } catch { /* dismissed */ }
  };

  const name = (s: AccessScope) => s.kind === "room"
    ? tr("access.scopeRoom", { name: myRooms.find((r) => r.id === s.id)?.name ?? s.id })
    : tr("access.scopeCard", { name: (() => { const k = myCards.find((c) => c.id === s.id); return k ? cardTitle(k.task) : s.id; })() });

  // a use row carries the raw id; show the name the scope line shows
  const targetName = (g: AccessGrant, id: string) => {
    if (!id || id === "-") return "";
    const s = g.scope.find((e) => e.id === id);
    return s ? name(s) : id;
  };

  const card = { backgroundColor: t.surface1, borderWidth: 1, borderColor: t.glassBorder, borderRadius: 14, padding: 12, gap: 8 } as const;
  const cap = { color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6 } as const;
  const btn = (on: boolean) => ({ paddingHorizontal: 14, paddingVertical: 8, borderRadius: 10, backgroundColor: on ? t.accent : t.surface2 });

  const Pick = ({ k, text }: { k: string; text: string }) => {
    const l = sel[k];
    return (
      <Pressable onPress={() => setSel((s) => { const n = { ...s }; const v = next(l, k.startsWith("card:")); if (v) n[k] = v; else delete n[k]; return n; })}
        style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 7 }}>
        <Ionicons name={l === "code" ? "code-slash-outline" : l === "write" ? "create-outline" : l === "read" ? "eye-outline" : "ellipse-outline"} size={18}
          color={l ? t.accent : t.txtTertiary} />
        <Text style={{ color: t.txtPrimary, fontSize: 14, flex: 1 }} numberOfLines={1}>{text}</Text>
        <Text style={{ color: l ? t.accent : t.txtTertiary, fontSize: 12 }}>{l ? tr("access." + l) : ""}</Text>
      </Pressable>
    );
  };

  const ok = label.trim().length > 0 && scope.length > 0 && !create.isPending;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr("nav.agentAccess")} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 14, gap: 12, paddingBottom: insets.bottom + 24,
        width: "100%", maxWidth: wide ? 720 : undefined, alignSelf: "center" }}>
        <Text style={{ color: t.txtTertiary, fontSize: 12.5, lineHeight: 18 }}>{tr("access.sub")}</Text>

        {door && !door.url ? (
          <Text style={{ color: t.warn, fontSize: 12.5, lineHeight: 18 }}>{tr("access.noDoor", { url: "http://<PC>:8140/mcp" })}</Text>
        ) : door && grants.some((g) => g.active) ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: door.up ? t.ok : t.txtTertiary }} />
            <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{door.up ? tr("access.doorUp") : tr("access.doorDown")}</Text>
          </View>
        ) : null}

        {issued ? (
          <View style={[card, { borderColor: t.accent }]}>
            <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700" }}>{tr("access.issuedTitle", { label: issued.label })}</Text>
            <Text style={{ color: t.txtSecondary, fontSize: 12.5, lineHeight: 18 }}>{tr("access.issuedHint")}</Text>
            <Text selectable style={{ color: t.txtPrimary, fontSize: 12.5, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
              backgroundColor: t.surface2, borderRadius: 8, padding: 10 }}>{link || issued.code}</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
              <Pressable onPress={share} style={btn(true)}>
                <Text style={{ color: "#fff", fontWeight: "600", fontSize: 13 }}>{Platform.OS === "web" && copied === "all" ? tr("access.copied") : tr("access.share")}</Text>
              </Pressable>
              {link ? (
                <Pressable onPress={() => copy("link", link)} style={btn(false)}>
                  <Text style={{ color: t.txtPrimary, fontWeight: "600", fontSize: 13 }}>{copied === "link" ? tr("access.copied") : tr("access.copyLink")}</Text>
                </Pressable>
              ) : null}
              {Platform.OS !== "web" ? (
                <Pressable onPress={() => copy("all", shareText)} style={btn(false)}>
                  <Text style={{ color: t.txtPrimary, fontWeight: "600", fontSize: 13 }}>{copied === "all" ? tr("access.copied") : tr("access.copyAll")}</Text>
                </Pressable>
              ) : null}
              <View style={{ flex: 1 }} />
              <Pressable onPress={() => setIssued(null)} style={{ paddingHorizontal: 10, paddingVertical: 8 }}>
                <Text style={{ color: t.accent, fontSize: 13 }}>{tr("access.done")}</Text>
              </Pressable>
            </View>
          </View>
        ) : (
          <View style={card}>
            <Text style={cap}>{tr("access.new").toUpperCase()}</Text>
            <TextInput value={label} onChangeText={setLabel} placeholder={tr("access.label")} placeholderTextColor={t.txtTertiary}
              maxLength={60} style={{ color: t.txtPrimary, fontSize: 15, borderBottomWidth: 1, borderBottomColor: t.borderSubtle, paddingVertical: 6 }} />
            <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16 }}>{tr("access.levelsHint")}</Text>
            <Text style={[cap, { marginTop: 6 }]}>{tr("access.rooms").toUpperCase()}</Text>
            {myRooms.length === 0 ? <Text style={{ color: t.txtTertiary, fontSize: 12.5 }}>{tr("access.noRooms")}</Text>
              : myRooms.map((r) => <Pick key={r.id} k={"room:" + r.id} text={r.name} />)}
            <Text style={[cap, { marginTop: 6 }]}>{tr("access.cards").toUpperCase()}</Text>
            {myCards.length === 0 ? <Text style={{ color: t.txtTertiary, fontSize: 12.5 }}>{tr("access.noCards")}</Text>
              : myCards.map((k) => <Pick key={k.id} k={"card:" + k.id} text={cardTitle(k.task)} />)}
            <Pressable onPress={() => setSealedOnly(!sealedOnly)}
              style={{ flexDirection: "row", alignItems: "flex-start", gap: 10, paddingVertical: 6, marginTop: 4 }}>
              <Ionicons name={sealedOnly ? "checkbox" : "square-outline"} size={19} color={sealedOnly ? t.accent : t.txtTertiary} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{tr("access.sealedOnly")}</Text>
                <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16 }}>
                  {tr(sealedOnly ? "access.sealedOnlyOn" : "access.sealedOnlyOff")}
                </Text>
              </View>
            </Pressable>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6 }}>
              <Text style={{ color: t.txtSecondary, fontSize: 13 }}>{tr("access.hours")}</Text>
              <TextInput value={hours} onChangeText={setHours} keyboardType="number-pad" maxLength={3}
                style={{ width: 56, color: t.txtPrimary, fontSize: 15, borderBottomWidth: 1, borderBottomColor: t.borderSubtle, paddingVertical: 4, textAlign: "center" }} />
              <View style={{ flex: 1 }} />
              <Pressable disabled={!ok} onPress={() => create.mutate()} style={btn(ok)}>
                <Text style={{ color: ok ? "#fff" : t.txtTertiary, fontWeight: "600", fontSize: 13 }}>{tr("access.create")}</Text>
              </Pressable>
            </View>
            {err ? <Text style={{ color: t.danger, fontSize: 12 }}>{err}</Text> : null}
          </View>
        )}

        <Text style={cap}>{tr("access.mine").toUpperCase()}</Text>
        {grants.length === 0 ? <Empty text={tr("access.none")} /> : grants.map((g) => (
          <View key={g.id} style={card}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Ionicons name={g.active ? "key-outline" : "lock-closed-outline"} size={16} color={g.active ? t.ok : t.txtTertiary} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{g.label} <Text style={{ color: t.txtTertiary, fontWeight: "400" }}>{g.claimed ? "…" + g.hint : tr("access.unclaimed")}</Text></Text>
                {g.sealed_only ? <Text style={{ color: t.ok, fontSize: 11 }}>{tr("access.sealedOnly")}</Text> : null}
                <Text style={{ color: g.active ? t.ok : t.txtTertiary, fontSize: 11.5 }}>
                  {g.active ? tr("access.activeUntil", { t: fmt(g.expires) }) : g.revoked ? tr("access.revoked") : tr("access.expired")}
                </Text>
              </View>
              {g.active ? (
                <Pressable onPress={() => revoke.mutate(g.id)} style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 10, backgroundColor: t.danger + "22" }}>
                  <Text style={{ color: t.danger, fontSize: 12.5, fontWeight: "600" }}>{tr("access.revoke")}</Text>
                </Pressable>
              ) : null}
            </View>
            {g.scope.map((s) => (
              <Text key={s.kind + s.id} style={{ color: t.txtSecondary, fontSize: 12.5 }}>
                {name(s)}  <Text style={{ color: t.txtTertiary }}>{tr(s.code ? "access.code" : s.write ? "access.write" : "access.read")}</Text>
              </Text>
            ))}
            <Text style={[cap, { marginTop: 4 }]}>{tr("access.uses").toUpperCase()}</Text>
            {(g.uses ?? []).length === 0 ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("access.noUses")}</Text>
              : (g.uses ?? []).slice(0, 8).map((u, i) => (
                <Text key={i} style={{ color: u.ok ? t.txtSecondary : t.danger, fontSize: 12 }}>
                  {tr("access.useLine", { t: fmt(u.ts), tool: u.tool, target: targetName(g, u.target) })}{u.ok ? "" : "  " + tr("access.refused")}
                </Text>
              ))}
          </View>
        ))}
      </ScrollView>
    </View>
  );
}
