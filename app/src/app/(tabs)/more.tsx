import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, AuthRequired } from "@/data/client";
import { useConfig } from "@/data/config";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";
import { VersionFooter } from "@/ui/updates_info";

export default function MoreTab() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { baseUrl, token, set, applyPairing, relayMode } = useConfig();
  const qc = useQueryClient();
  const [url, setUrl] = useState(baseUrl);
  const [tok, setTok] = useState(token);
  const [pair, setPair] = useState("");
  const [pairMsg, setPairMsg] = useState("");
  const [pairBusy, setPairBusy] = useState(false);
  const paired = relayMode();

  // Apply the code, then PROVE the connection with a real round-trip before
  // claiming success — a parsed-but-dead code (expired window, relay down,
  // wrong keys) must say what's wrong, not "Gekoppelt" (no silent fallback).
  async function doPair() {
    const applied = applyPairing(pair);
    if (!applied.ok) { setPairMsg(applied.reason); return; }
    setPairBusy(true); setPairMsg("Verbindung prüfen…");
    try {
      await api.me();
      qc.invalidateQueries();   // board/dashboard ran pre-pairing (empty) - reload against the new config
      setPairMsg(applied.mode === "relay"
        ? "Gekoppelt ✓ – verschlüsselt über Relay, Desktop erreichbar."
        : "Verbunden ✓ – direkt (LAN), Desktop erreichbar.");
      setPair("");
    } catch (e) {
      setPairMsg(e instanceof AuthRequired
        ? "Code übernommen, aber der Token wurde abgelehnt – am Desktop neuen Code erzeugen."
        : `Code übernommen, aber der Desktop antwortet nicht: ${String((e as Error).message)}`);
    } finally { setPairBusy(false); }
  }

  const field = { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle,
    borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 13 } as const;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", paddingTop: insets.top + 10, paddingHorizontal: 16, paddingBottom: 6 }}>
        More
      </Text>
      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 120, gap: 10 }}>
        <Panel>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <SectionLabel text="pair with a desktop" />
            <Text style={{ color: paired ? t.ok : t.txtTertiary, fontSize: 11 }}>{paired ? "● gekoppelt (Relay)" : "nicht gekoppelt"}</Text>
          </View>
          <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 8 }}>
            Desktop: Settings → Mobile app → „Telefon koppeln". Den QR scannen — oder den Code unten einfügen.
          </Text>
          <Pressable onPress={() => router.push("/scan" as never)}
            style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
              backgroundColor: t.accent, borderRadius: 8, padding: 12, marginBottom: 10 }}>
            <Ionicons name="qr-code-outline" size={18} color="#fff" />
            <Text style={{ color: "#fff", fontWeight: "700" }}>QR-Code scannen</Text>
          </Pressable>
          <Text style={{ color: t.txtTertiary, fontSize: 11, marginBottom: 6 }}>oder Code / Link einfügen:</Text>
          <TextInput value={pair} onChangeText={setPair} autoCapitalize="none" multiline
            placeholder="Pairing-Code / Link" placeholderTextColor={t.txtPlaceholder} style={[field, { minHeight: 60 }]} />
          <View style={{ height: 8 }} />
          <Pressable onPress={doPair} disabled={pairBusy}
            style={{ backgroundColor: t.accent, borderRadius: 8, padding: 11, alignItems: "center", opacity: pairBusy ? 0.6 : 1 }}>
            <Text style={{ color: "#fff", fontWeight: "600" }}>{pairBusy ? "Prüfe…" : "Pair"}</Text>
          </Pressable>
          {pairMsg ? <Text style={{ color: /✓/.test(pairMsg) ? t.ok : pairMsg.startsWith("Verbindung") ? t.txtSecondary : t.danger, fontSize: 12, marginTop: 6 }}>{pairMsg}</Text> : null}
        </Panel>
        <Panel>
          <SectionLabel text="direct lan (optional)" />
          <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 6 }}>Nur im selben Netz ohne Relay. Daemon URL + Device-Token.</Text>
          <TextInput value={url} onChangeText={setUrl} autoCapitalize="none" placeholder="http://10.0.2.2:8140"
            placeholderTextColor={t.txtPlaceholder} style={field} />
          <View style={{ height: 8 }} />
          <TextInput value={tok} onChangeText={setTok} autoCapitalize="none" placeholder="Bearer token (optional)"
            placeholderTextColor={t.txtPlaceholder} style={field} />
          <View style={{ height: 10 }} />
          <Pressable onPress={() => set({ baseUrl: url.replace(/\/+$/, ""), token: tok.trim() })}
            style={{ backgroundColor: t.accent, borderRadius: 8, padding: 11, alignItems: "center" }}>
            <Text style={{ color: "#fff", fontWeight: "600" }}>Speichern</Text>
          </Pressable>
        </Panel>
        <Panel style={{ padding: 0 }}>
          {([
            ["loopmap", "Loop & Harness", "git-network-outline"],
            ["automation", "Automation & loop", "git-branch-outline"],
            ["processes", "Processes", "git-network-outline"],
            ["connectors", "Connectors", "sync-outline"],
            ["history", "History", "time-outline"],
            ["sessions", "Sessions", "chatbubbles-outline"],
            ["recordings", "Recordings", "videocam-outline"],
            ["settings", "Settings", "settings-outline"],
          ] as const).map(([route, label, icon], i) => (
            <Pressable key={route} onPress={() => router.push(`/${route}` as never)}
              style={{ flexDirection: "row", alignItems: "center", gap: 12, padding: 14,
                borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder }}>
              <Ionicons name={icon} size={18} color={t.txtSecondary} />
              <Text style={{ color: t.txtPrimary, fontSize: 14, flex: 1 }}>{label}</Text>
              <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
            </Pressable>
          ))}
        </Panel>
        <VersionFooter />
      </ScrollView>
    </View>
  );
}
