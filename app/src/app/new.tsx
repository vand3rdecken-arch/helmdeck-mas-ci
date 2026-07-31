import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";
import { Caption, ChipPick, fieldStyle } from "@/ui/settings_sections";

// Ported from archive/web/components/modal.tsx (EXAMPLES). Tapping a chip seeds
// the task text and, where the web example set one, the driver.
const EXAMPLES = [
  { label: "bug fix", task: "Fix: the dashboard capacity gauge shows 0% when touch budget is 0 - guard the division and show a hint instead.", driver: "claude" },
  { label: "feature", task: "Add a CSV export button to the dashboard work table (all columns, current filters applied).", driver: "claude" },
  { label: "desktop task", task: "Open the invoice tool, export June as PDF into Downloads, and verify the file exists.", driver: "claude-desktop" },
  { label: "browser task", task: "Go to the supplier portal, download the latest price list, and summarize what changed vs the file in data/prices.csv.", driver: "claude-desktop" },
  { label: "research", task: "Read the three competitor changelogs linked in docs/watchlist.md and write a one-page summary of what shipped this month.", driver: "claude" },
] as const;

const PRIORITIES = ["low", "medium", "high"] as const;

export default function NewCard() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const [task, setTask] = useState("");
  const [repo, setRepo] = useState(metrics?.settings?.default_repo ?? "");
  const [priority, setPriority] = useState<string>("medium");
  const [due, setDue] = useState("");
  const [value, setValue] = useState("");
  const [client, setClient] = useState("");
  const [driver, setDriver] = useState("");
  const [busy, setBusy] = useState(false);

  const field = fieldStyle(t);
  // The app already knows the configured drivers via metrics.settings.drivers
  // (same source the web modal uses). Selector when present, text input otherwise.
  const drivers = Object.keys(metrics?.settings?.drivers ?? {});

  async function file() {
    if (!task.trim()) return;
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        task: task.trim(), repo: repo.trim(), lane: "backlog", priority,
      };
      if (due.trim()) body.due = due.trim();
      if (value.trim()) body.value = parseFloat(value);
      if (client.trim()) body.client = client.trim();
      if (driver.trim()) body.driver = driver.trim();
      // The daemon can reject with a 200-body {error} (bad repo, WIP limit…),
      // so inspect it rather than assuming success.
      const res = await api.newTrack(body) as { error?: string };
      if (res?.error) { Alert.alert("Abgelehnt", res.error); return; }
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
          <Caption text="beispiel-aufgaben" />
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
            {EXAMPLES.map((ex) => (
              <Pressable key={ex.label} onPress={() => { setTask(ex.task); setDriver(ex.driver); }}
                style={{ backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1,
                  borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 }}>
                <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "500" }}>{ex.label}</Text>
              </Pressable>
            ))}
          </View>
          <SectionLabel text="was soll getan werden?" />
          <TextInput value={task} onChangeText={setTask} multiline placeholder="Beschreibe die Aufgabe…"
            placeholderTextColor={t.txtPlaceholder} style={[field, { minHeight: 90 }]} />
          <View style={{ height: 10 }} />
          <SectionLabel text="repo" />
          <TextInput value={repo} onChangeText={setRepo} autoCapitalize="none" placeholder="Pfad / default"
            placeholderTextColor={t.txtPlaceholder} style={field} />
        </Panel>
        <Panel>
          <Caption text="priorität" />
          <View style={{ marginBottom: 10 }}>
            <ChipPick options={PRIORITIES} selected={[priority]} onToggle={setPriority} single />
          </View>
          <Caption text="fällig (YYYY-MM-DD)" />
          <TextInput value={due} onChangeText={setDue} autoCapitalize="none" placeholder="2026-07-31"
            placeholderTextColor={t.txtPlaceholder} style={field} />
          <View style={{ height: 10 }} />
          <View style={{ flexDirection: "row", gap: 10 }}>
            <View style={{ flex: 1 }}>
              <Caption text="wert (€)" />
              <TextInput value={value} onChangeText={setValue} keyboardType="numeric" placeholder="50"
                placeholderTextColor={t.txtPlaceholder} style={field} />
            </View>
            <View style={{ flex: 1 }}>
              <Caption text="kunde" />
              <TextInput value={client} onChangeText={setClient} placeholder="Kunde"
                placeholderTextColor={t.txtPlaceholder} style={field} />
            </View>
          </View>
          <View style={{ height: 10 }} />
          <Caption text="driver" />
          {drivers.length > 0 ? (
            <ChipPick options={drivers} selected={[driver]} onToggle={setDriver} single />
          ) : (
            <TextInput value={driver} onChangeText={setDriver} autoCapitalize="none" placeholder="claude"
              placeholderTextColor={t.txtPlaceholder} style={field} />
          )}
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
