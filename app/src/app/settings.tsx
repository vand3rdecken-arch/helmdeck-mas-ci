import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { Chip, KVRow, Panel, ScreenHeader, SectionLabel } from "@/ui/kit";

export default function Settings() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: s, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const { data: users } = useQuery({ queryKey: ["users"], queryFn: api.users });

  const [repo, setRepo] = useState("");
  const [wip, setWip] = useState("");
  const [value, setValue] = useState("");
  useEffect(() => {
    if (!s) return;
    setRepo(s.default_repo ?? "");
    setWip(String(s.capacity?.wip_limit ?? ""));
    setValue(String(s.value_per_card ?? ""));
  }, [s]);

  const field = { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle,
    borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 14 } as const;

  async function saveBusiness() {
    try {
      await api.saveSettings({ default_repo: repo, value_per_card: Number(value) || 0,
        capacity: { ...(s?.capacity ?? {}), wip_limit: Number(wip) || 0 } });
      await qc.invalidateQueries({ queryKey: ["settings"] });
      Alert.alert("Gespeichert");
    } catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
  }

  const policy = s?.policy ?? {};

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title="Settings" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 40 }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>Nur für Owner / Desktop nicht erreichbar.</Text> : null}
        {s ? (
          <>
            <Panel>
              <SectionLabel text="business" />
              <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Standard-Repo</Text>
              <TextInput value={repo} onChangeText={setRepo} autoCapitalize="none" style={field} />
              <View style={{ height: 8 }} />
              <View style={{ flexDirection: "row", gap: 8 }}>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: t.txtTertiary, fontSize: 12 }}>WIP-Limit</Text>
                  <TextInput value={wip} onChangeText={setWip} keyboardType="numeric" style={field} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Wert/Karte</Text>
                  <TextInput value={value} onChangeText={setValue} keyboardType="numeric" style={field} />
                </View>
              </View>
              <View style={{ height: 10 }} />
              <Pressable onPress={saveBusiness} style={{ backgroundColor: t.accent, borderRadius: 8, padding: 11, alignItems: "center" }}>
                <Text style={{ color: "#fff", fontWeight: "600" }}>Speichern</Text>
              </Pressable>
            </Panel>

            <Panel>
              <SectionLabel text="automation policy" />
              <KVRow k="Auto-accept grün" v={policy.auto_accept_green ? "ja" : "nein"} />
              <KVRow k="Auto-dispatch" v={(policy.auto_dispatch_modes ?? []).join(", ") || "-"} />
              <KVRow k="Lane-Labels" v={Object.values(policy.lane_labels ?? {}).join(" · ") || "-"} />
            </Panel>

            <Panel>
              <SectionLabel text={`users (${users?.length ?? 0})`} />
              {(users ?? []).map((u) => (
                <View key={u.name} style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6, borderTopWidth: 1, borderTopColor: t.glassBorder }}>
                  <Text style={{ color: t.txtPrimary, fontSize: 13.5, flex: 1 }}>{u.name}</Text>
                  <Chip text={u.role} dot={u.role === "owner" ? t.accent : u.role === "operator" ? t.human : t.txtTertiary} />
                  <Pressable onPress={async () => {
                    try { const r = await api.issueToken(u.name, "mobile"); await Clipboard.setStringAsync(r.token); Alert.alert("Token kopiert", "Device-Token in die Zwischenablage."); }
                    catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
                  }}>
                    <Text style={{ color: t.accent, fontSize: 12 }}>+ Token</Text>
                  </Pressable>
                </View>
              ))}
            </Panel>
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}
