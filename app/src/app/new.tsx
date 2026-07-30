import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";

export default function NewCard() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const [task, setTask] = useState("");
  const [repo, setRepo] = useState(metrics?.settings?.default_repo ?? "");
  const [busy, setBusy] = useState(false);

  const field = { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle,
    borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 14 } as const;

  async function file() {
    if (!task.trim()) return;
    setBusy(true);
    try {
      await api.newTrack({ task: task.trim(), repo: repo.trim(), lane: "backlog", priority: "medium" });
      await qc.invalidateQueries({ queryKey: ["tracks"] });
      router.back();
    } catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
    finally { setBusy(false); }
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <Text style={{ color: t.txtPrimary, fontSize: 20, fontWeight: "700", padding: 16 }}>Neue Karte</Text>
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10 }}>
        <Panel>
          <SectionLabel text="was soll getan werden?" />
          <TextInput value={task} onChangeText={setTask} multiline placeholder="Beschreibe die Aufgabe…"
            placeholderTextColor={t.txtPlaceholder} style={[field, { minHeight: 90 }]} />
          <View style={{ height: 10 }} />
          <SectionLabel text="repo" />
          <TextInput value={repo} onChangeText={setRepo} autoCapitalize="none" placeholder="Pfad / default"
            placeholderTextColor={t.txtPlaceholder} style={field} />
        </Panel>
        <View style={{ flexDirection: "row", gap: 10 }}>
          <Pressable onPress={() => router.back()} style={{ flex: 1, borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, padding: 12, alignItems: "center" }}>
            <Text style={{ color: t.txtSecondary }}>Abbrechen</Text>
          </Pressable>
          <Pressable onPress={file} disabled={busy || !task.trim()} style={{ flex: 1, backgroundColor: t.accent, borderRadius: 8, padding: 12, alignItems: "center", opacity: busy || !task.trim() ? 0.5 : 1 }}>
            <Text style={{ color: "#fff", fontWeight: "600" }}>Anlegen</Text>
          </Pressable>
        </View>
      </ScrollView>
    </View>
  );
}
