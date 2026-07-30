import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import {
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable,
  ScrollView, Text, TextInput, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type Step } from "@/data/client";
import type { Track } from "@/data/types";
import { executorLabel, laneColor, statusColor, useTheme } from "@/theme";
import { Chip, Empty, KVRow, Panel, SectionLabel } from "@/ui/kit";

type Tab = "overview" | "chat";

function ts(x?: string) {
  if (!x || !x.includes("T")) return x ?? "";
  try { return new Date(x).toLocaleTimeString(); } catch { return x.split("T")[1]?.slice(0, 8) ?? ""; }
}

export default function CardScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [tab, setTab] = useState<Tab>("overview");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks });
  const k: Track | undefined = tracks?.find((x) => x.id === id);
  const running = k?.status === "running";
  const { data: transcript } = useQuery({ queryKey: ["transcript", id], queryFn: () => api.transcript(id!),
    enabled: !!id, refetchInterval: running ? 3000 : false });
  const { data: hist } = useQuery({ queryKey: ["history", id], queryFn: () => api.history(id!), enabled: !!id });

  const feed = useMemo(() => {
    const rows: Step[] = [...(transcript ?? []), ...(hist ?? [])];
    return rows.filter((r) => (r.text || r.result || r.tool)).sort((a, b) => (a.ts ?? "").localeCompare(b.ts ?? ""));
  }, [transcript, hist]);

  async function send() {
    if (!text.trim() || !id) return;
    setSending(true);
    try {
      await api.steer(id, text.trim());
      setText("");
      await qc.invalidateQueries({ queryKey: ["transcript", id] });
      await qc.invalidateQueries({ queryKey: ["tracks"] });
    } catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
    finally { setSending(false); }
  }

  function menu() {
    if (!k) return;
    Alert.alert(k.task, undefined, [
      { text: "Fork", onPress: () => api.fork(k.id) },
      { text: "Archivieren", onPress: () => api.archive(k.id).then(() => router.back()) },
      { text: "Löschen", style: "destructive", onPress: () => api.del(k.id).then(() => router.back()) },
      { text: "Abbrechen", style: "cancel" },
    ]);
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <Stack.Screen options={{ headerShown: false }} />
      {/* header */}
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 8, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600", flex: 1 }} numberOfLines={1}>{k?.task ?? "Karte"}</Text>
        <Pressable onPress={menu} hitSlop={10}><Ionicons name="ellipsis-horizontal" size={22} color={t.txtSecondary} /></Pressable>
      </View>
      {/* tab switch */}
      <View style={{ flexDirection: "row", borderBottomWidth: 1, borderBottomColor: t.glassBorder }}>
        {(["overview", "chat"] as Tab[]).map((x) => (
          <Pressable key={x} onPress={() => setTab(x)} style={{ flex: 1, paddingVertical: 10, alignItems: "center",
            borderBottomWidth: 2, borderBottomColor: tab === x ? t.accent : "transparent" }}>
            <Text style={{ color: tab === x ? t.accent : t.txtTertiary, fontWeight: "600" }}>
              {x === "overview" ? "Overview" : `Chat${k?.turns ? ` (${k.turns}t)` : ""}`}
            </Text>
          </Pressable>
        ))}
      </View>

      {!k ? <ActivityIndicator color={t.accent} style={{ marginTop: 30 }} /> :
        tab === "overview" ? (
          <ScrollView contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 40 }}>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {k.status ? <Chip text={k.status.replace(/_/g, " ")} dot={statusColor(t, k.status)} /> : null}
              <Chip text={k.lane} dot={laneColor(t, k.lane)} />
              {k.mode ? <Chip text={executorLabel(k.mode)} dot={t.ai} /> : null}
              {k.ai_cost > 0 ? <Chip text={`AI $${k.ai_cost.toFixed(2)}`} /> : null}
            </View>
            <Panel>
              <SectionLabel text="description" />
              <Text selectable style={{ color: t.txtPrimary, fontSize: 14 }}>{k.description || k.task}</Text>
            </Panel>
            <Panel>
              <SectionLabel text="technical" />
              <KVRow k="Branch" v={k.branch || "—"} />
              <KVRow k="Repo" v={k.repo || "—"} />
              <KVRow k="Turns" v={`${k.turns}`} />
              <KVRow k="Tokens" v={`${k.tokens_in}/${k.tokens_out}`} />
              {k.value ? <KVRow k="Value" v={`€${k.value}`} /> : null}
              {k.due ? <KVRow k="Due" v={k.due} /> : null}
            </Panel>
          </ScrollView>
        ) : (
          <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
            <ScrollView contentContainerStyle={{ padding: 12, gap: 8, paddingBottom: 20 }}>
              {feed.length === 0 ? <Empty text="Noch keine Nachrichten." /> :
                feed.map((r, i) => {
                  const mine = r.cls === "user" || r.role === "user";
                  const sys = r.kind === "system" || r.cls === "note";
                  return (
                    <View key={i} style={{ alignSelf: mine ? "flex-end" : "stretch", maxWidth: mine ? "85%" : "100%" }}>
                      {r.tool ? (
                        <Text style={{ color: t.txtTertiary, fontSize: 12 }}>⚙ {r.tool}{r.result ? `: ${r.result.slice(0, 120)}` : ""}</Text>
                      ) : (
                        <View style={{ backgroundColor: mine ? t.accent + "22" : sys ? "transparent" : t.surface1,
                          borderRadius: 10, padding: sys ? 2 : 10 }}>
                          <Text selectable style={{ color: sys ? t.txtTertiary : t.txtPrimary, fontSize: sys ? 12 : 14 }}>
                            {r.text || r.result}
                          </Text>
                          {r.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10, marginTop: 2 }}>{ts(r.ts)}</Text> : null}
                        </View>
                      )}
                    </View>
                  );
                })}
            </ScrollView>
            <View style={{ flexDirection: "row", padding: 8, gap: 8, borderTopWidth: 1, borderTopColor: t.glassBorder,
              paddingBottom: insets.bottom + 8, alignItems: "flex-end" }}>
              <TextInput value={text} onChangeText={setText} multiline placeholder="Nachricht an den Agenten…"
                placeholderTextColor={t.txtPlaceholder}
                style={{ flex: 1, color: t.txtPrimary, backgroundColor: t.surface2, borderRadius: 10, padding: 10, maxHeight: 120 }} />
              <Pressable onPress={send} disabled={sending || !text.trim()}
                style={{ backgroundColor: t.accent, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center", opacity: sending || !text.trim() ? 0.5 : 1 }}>
                {sending ? <ActivityIndicator color="#fff" /> : <Ionicons name="arrow-up" size={22} color="#fff" />}
              </Pressable>
            </View>
          </KeyboardAvoidingView>
        )}
    </View>
  );
}
