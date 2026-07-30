import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useConfig } from "@/data/config";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";

export default function MoreTab() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { baseUrl, token, set } = useConfig();
  const [url, setUrl] = useState(baseUrl);
  const [tok, setTok] = useState(token);

  const field = { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle,
    borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 13 } as const;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", paddingTop: insets.top + 10, paddingHorizontal: 16, paddingBottom: 6 }}>
        More
      </Text>
      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 120, gap: 10 }}>
        <Panel>
          <SectionLabel text="connection" />
          <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 6 }}>Daemon URL (LAN/Relay) + Device-Token.</Text>
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
            ["history", "History", "time-outline"],
            ["sessions", "Sessions", "chatbubbles-outline"],
            ["recordings", "Recordings", "videocam-outline"],
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
      </ScrollView>
    </View>
  );
}
