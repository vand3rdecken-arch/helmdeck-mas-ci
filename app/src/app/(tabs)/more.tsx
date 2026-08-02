import { Ionicons } from "@expo/vector-icons";
import Constants from "expo-constants";
import { useRouter } from "expo-router";
import * as Updates from "expo-updates";
import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useConfig } from "@/data/config";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";

/** Version + the running JS bundle, so silent OTA updates are visible: the OTA
 *  id/date changes each time an update is applied - if it moved, you updated. */
function VersionFooter({ t }: { t: ReturnType<typeof useTheme> }) {
  // expoConfig is null in release/OTA builds - fall back to the updates
  // runtimeVersion (policy: appVersion), which equals the app version there.
  const ver = Constants.expoConfig?.version ?? Updates.runtimeVersion ?? "?";
  const code = (Constants.expoConfig as { android?: { versionCode?: number } })?.android?.versionCode;
  const ota = Updates.isEmbeddedLaunch
    ? "Basis-Build (eingebettet, kein OTA)"
    : Updates.updateId
    ? `OTA ${Updates.updateId.slice(0, 8)} · ${Updates.createdAt ? new Date(Updates.createdAt).toLocaleString() : "?"}`
    : "Dev";
  return (
    <View style={{ alignItems: "center", paddingVertical: 16, gap: 3 }}>
      <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>HelmDeck v{ver}{code ? ` · Build ${code}` : ""}</Text>
      <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{ota}</Text>
    </View>
  );
}

export default function MoreTab() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { baseUrl, token, set, applyPairing, relayMode } = useConfig();
  const [url, setUrl] = useState(baseUrl);
  const [tok, setTok] = useState(token);
  const [pair, setPair] = useState("");
  const [pairMsg, setPairMsg] = useState("");
  const paired = relayMode();

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
          <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 6 }}>
            Desktop: Settings → Mobile app → Pair phone. Code hier einfügen.
          </Text>
          <TextInput value={pair} onChangeText={setPair} autoCapitalize="none" multiline
            placeholder="Pairing-Code / Link" placeholderTextColor={t.txtPlaceholder} style={[field, { minHeight: 60 }]} />
          <View style={{ height: 8 }} />
          <Pressable onPress={() => { const ok = applyPairing(pair); setPairMsg(ok ? "Gekoppelt – verschlüsselt über Relay." : "Kein gültiger Code."); if (ok) setPair(""); }}
            style={{ backgroundColor: t.accent, borderRadius: 8, padding: 11, alignItems: "center" }}>
            <Text style={{ color: "#fff", fontWeight: "600" }}>Pair</Text>
          </Pressable>
          {pairMsg ? <Text style={{ color: pairMsg.startsWith("Gekoppelt") ? t.ok : t.danger, fontSize: 12, marginTop: 6 }}>{pairMsg}</Text> : null}
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
            ["automation", "Automation & loop", "git-branch-outline"],
            ["processes", "Processes", "git-network-outline"],
            ["connectors", "Connectors", "sync-outline"],
            ["history", "History", "time-outline"],
            ["sessions", "Sessions", "chatbubbles-outline"],
            ["recordings", "Recordings", "videocam-outline"],
            ["settings", "Settings", "settings-outline"],
          ] as const).map(([route, label, icon], i) => (
            <Pressable key={route} onPress={() => router.push(`/${route}`)}
              style={{ flexDirection: "row", alignItems: "center", gap: 12, padding: 14,
                borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder }}>
              <Ionicons name={icon} size={18} color={t.txtSecondary} />
              <Text style={{ color: t.txtPrimary, fontSize: 14, flex: 1 }}>{label}</Text>
              <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
            </Pressable>
          ))}
        </Panel>
        <VersionFooter t={t} />
      </ScrollView>
    </View>
  );
}
