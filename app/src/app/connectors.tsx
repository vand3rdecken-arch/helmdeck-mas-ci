import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, Text, TextInput, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import type { Track } from "@/data/types";
import { statusColor, useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Chip, Empty, Panel, ScreenHeader } from "@/ui/kit";

const isWeb = Platform.OS === "web";

// Real frosted glass on the web; a crisp translucent surface on native (mirrors board.tsx).
function glassStyle(t: ThemeTokens) {
  return isWeb
    ? ({ backgroundColor: t.glass, backdropFilter: "blur(16px) saturate(1.3)", WebkitBackdropFilter: "blur(16px) saturate(1.3)" } as any)
    : { backgroundColor: t.surface1 };
}

interface ConnectorInfo { name: string; description?: string; last_run?: string | null; versions?: number; schedule?: number }

// One produced-card tile in the connector grid — tapping opens the card detail.
function CardTile({ k, wide }: { k: Track; wide: boolean }) {
  const t = useTheme();
  const router = useRouter();
  return (
    <Pressable
      onPress={() => router.push(`/card/${k.id}`)}
      style={[glassStyle(t), {
        borderColor: t.glassBorder, borderWidth: 1, borderRadius: 12, padding: 10, gap: 6,
        width: wide ? 300 : undefined, flexGrow: wide ? 0 : 1,
      }]}
    >
      <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "500" }} numberOfLines={2}>{k.task}</Text>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        {k.status ? <Chip text={k.status.replace(/_/g, " ")} dot={statusColor(t, k.status)} /> : null}
        {k.client ? <Chip text={k.client} /> : null}
        {k.priority && k.priority !== "medium" ? <Chip text={k.priority} /> : null}
      </View>
    </Pressable>
  );
}

function ConnectorPanel({ conn, tracks, savedMins, onRefresh }:
  { conn: ConnectorInfo; tracks: Track[]; savedMins: number; onRefresh: () => Promise<void> }) {
  const t = useTheme();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;
  const [busy, setBusy] = useState(false);
  const [mins, setMins] = useState(savedMins > 0 ? String(savedMins) : "");

  // The web derives produced cards by branch prefix: "conn-" + name[:14].
  const produced = tracks.filter((k) => (k.branch ?? "").startsWith("conn-" + conn.name.slice(0, 14)));

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try { await fn(); await onRefresh(); Alert.alert(ok); }
    catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
    finally { setBusy(false); }
  }

  async function saveSchedule() {
    const m = parseInt(mins, 10) || 0;
    setBusy(true);
    try {
      const cur = (await api.settings()).connectors ?? {};
      const next = { ...cur } as Record<string, { every_minutes: number }>;
      if (m > 0) next[conn.name] = { every_minutes: m }; else delete next[conn.name];
      await api.saveSettings({ connectors: next });
      await onRefresh();
      Alert.alert(m > 0 ? `Alle ${m} Min geplant` : "Zeitplan entfernt");
    } catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
    finally { setBusy(false); }
  }

  return (
    <Panel style={glassStyle(t)}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "600", flex: 1 }}>{conn.name}</Text>
        {savedMins > 0 ? <Chip text={`alle ${savedMins}m`} /> : null}
      </View>
      {conn.description ? (
        <Text style={{ color: t.txtSecondary, fontSize: 12.5, marginTop: 2 }}>{conn.description}</Text>
      ) : null}
      <Text style={{ color: t.txtTertiary, fontSize: 11.5, marginTop: 4 }}>
        Letzter Lauf: {conn.last_run ?? "nie"}
      </Text>

      {/* Actions */}
      <View style={{ flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
        <Pressable disabled={busy} onPress={() => act(() => api.runConnector(conn.name), "Gestartet")}
          style={{ backgroundColor: t.accent, borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8, opacity: busy ? 0.6 : 1 }}>
          <Text style={{ color: "#fff", fontSize: 13 }}>{busy ? "…" : "Jetzt laufen"}</Text>
        </Pressable>
        {(conn.versions ?? 0) > 0 ? (
          <Pressable disabled={busy} onPress={() => act(() => api.rollbackConnector(conn.name), "Zurückgerollt")}
            style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8 }}>
            <Text style={{ color: t.txtSecondary, fontSize: 13 }}>Rollback ({conn.versions})</Text>
          </Pressable>
        ) : null}
      </View>

      {/* Editable schedule — POST /settings {connectors:{...}} is the save route. */}
      <View style={{ flexDirection: "row", gap: 8, marginTop: 10, alignItems: "center", flexWrap: "wrap" }}>
        <Text style={{ color: t.txtTertiary, fontSize: 12 }}>alle</Text>
        <TextInput
          value={mins}
          onChangeText={setMins}
          keyboardType="number-pad"
          placeholder="-"
          placeholderTextColor={t.txtPlaceholder}
          style={{ width: 64, color: t.txtPrimary, fontSize: 13, borderWidth: 1, borderColor: t.borderSubtle,
            borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: t.surface2 }}
        />
        <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Minuten</Text>
        <Pressable disabled={busy} onPress={saveSchedule}
          style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, paddingHorizontal: 14, paddingVertical: 6 }}>
          <Text style={{ color: t.txtSecondary, fontSize: 13 }}>Zeitplan speichern</Text>
        </Pressable>
      </View>

      {/* Produced cards */}
      <View style={{ marginTop: 12, gap: 6 }}>
        <Text style={{ color: t.txtTertiary, fontSize: 11, letterSpacing: 0.8 }}>
          {`ERZEUGTE KARTEN (${produced.length})`}
        </Text>
        {produced.length === 0 ? <Empty text="Noch keine – lass ihn laufen." /> : (
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {produced.slice(0, 12).map((k) => <CardTile key={k.id} k={k} wide={wide} />)}
          </View>
        )}
      </View>
    </Panel>
  );
}

export default function Connectors() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;
  const qc = useQueryClient();

  const connectors = useQuery({ queryKey: ["connectors"], queryFn: api.connectors });
  const tracks = useQuery({ queryKey: ["tracks"], queryFn: api.tracks });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });

  async function refresh() {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["connectors"] }),
      qc.invalidateQueries({ queryKey: ["tracks"] }),
      qc.invalidateQueries({ queryKey: ["settings"] }),
    ]);
  }

  const sched: Record<string, { every_minutes?: number }> = settings.data?.connectors ?? {};
  const data = (connectors.data ?? []) as ConnectorInfo[];

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title="Connectors" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: wide ? 20 : 12, gap: 10, paddingBottom: 40,
        width: "100%", maxWidth: wide ? 900 : undefined, alignSelf: "center" }}>
        {connectors.isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {connectors.error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar.</Text> : null}
        {data.length === 0 && !connectors.isLoading ? <Empty text="Keine Connectors." /> : null}
        {data.map((c) => (
          <ConnectorPanel
            key={c.name}
            conn={c}
            tracks={(tracks.data ?? []) as Track[]}
            savedMins={sched[c.name]?.every_minutes ?? 0}
            onRefresh={refresh}
          />
        ))}
      </ScrollView>
    </View>
  );
}
