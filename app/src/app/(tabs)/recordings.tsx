import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Linking, Platform, Pressable, ScrollView, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useConfig } from "@/data/config";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Chip, Empty, Panel, ScreenHeader } from "@/ui/kit";

const isWeb = Platform.OS === "web";

function glassStyle(t: ThemeTokens) {
  return isWeb
    ? ({ backgroundColor: t.glass, backdropFilter: "blur(16px) saturate(1.3)", WebkitBackdropFilter: "blur(16px) saturate(1.3)" } as any)
    : { backgroundColor: t.surface1 };
}

// One timeline step: {i,t,ts,kind,detail} appended by actionlog.py. "flag" steps
// are review call-outs — tinted like the web's <li class="flag">.
interface TimelineStep { i?: number; t?: number; ts?: string; kind?: string; detail?: string }

function stepColor(t: ThemeTokens, kind?: string): string {
  return ({ flag: t.warn, click: t.ai, type: t.ai, navigate: t.human, shell: t.accent2, note: t.txtTertiary } as Record<string, string>)[kind ?? ""] ?? t.txtSecondary;
}

function RunRow({ run }: { run: any }) {
  const t = useTheme();
  const [open, setOpen] = useState(false);
  const { baseUrl, token, relayMode } = useConfig();

  // Only fetch the timeline once the row is expanded.
  const timeline = useQuery({
    queryKey: ["run-timeline", run.id],
    queryFn: () => api.get<TimelineStep[]>(`/runs/${run.id}/timeline`),
    enabled: open,
  });

  // GET /runs/<id>/video — daemon accepts ?token= for auth (server.py _user()).
  // Direct mode only; the relay tunnel can't stream a plain media URL.
  const videoUrl = `${baseUrl}/runs/${run.id}/video?token=${encodeURIComponent(token)}`;
  const relayed = relayMode();

  return (
    <Panel style={glassStyle(t)}>
      <Pressable onPress={() => setOpen((v) => !v)} style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Text style={{ color: t.txtTertiary, fontSize: 13, width: 14 }}>{open ? "▾" : "▸"}</Text>
        <Text style={{ color: t.txtPrimary, fontSize: 14, flex: 1 }} numberOfLines={1}>{run.title ?? run.id}</Text>
        {run.status ? <Chip text={run.status} /> : null}
      </Pressable>
      <Text style={{ color: t.txtTertiary, fontSize: 12, marginLeft: 22 }}>
        {run.kind ?? ""}{run.id ? ` · ${run.id}` : ""}{run.steps != null ? ` · ${run.steps} Schritte` : ""}
      </Text>

      {open ? (
        <View style={{ marginTop: 10, marginLeft: 22, gap: 8 }}>
          {timeline.isLoading ? <ActivityIndicator color={t.accent} /> : null}
          {timeline.error ? <Text style={{ color: t.danger, fontSize: 12 }}>Timeline nicht ladbar.</Text> : null}
          {timeline.data && timeline.data.length === 0 ? <Empty text="Keine Schritte aufgezeichnet." /> : null}

          {(timeline.data ?? []).map((s, i) => (
            <View key={s.i ?? i} style={{ flexDirection: "row", gap: 8, alignItems: "flex-start" }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11, width: 46, textAlign: "right", fontVariant: ["tabular-nums"] }}>
                {(s.t ?? 0).toFixed(1)}s
              </Text>
              <Text style={{ color: stepColor(t, s.kind), fontSize: 11, fontWeight: "600", width: 64 }}>{s.kind}</Text>
              <Text style={{ color: t.txtSecondary, fontSize: 12, flex: 1 }}>{s.detail}</Text>
            </View>
          ))}

          {/* Video: expo-video is NOT installed, so we surface a link/notice instead
              of an embedded player. Add expo-video to embed inline playback. */}
          <View style={{ marginTop: 6, paddingTop: 8, borderTopWidth: 1, borderTopColor: t.glassBorder, gap: 4 }}>
            {relayed ? (
              <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>
                Video verfügbar auf dem Desktop (im Relay-Modus nicht direkt streambar).
              </Text>
            ) : (
              <>
                <Pressable onPress={() => Linking.openURL(videoUrl)}
                  style={{ alignSelf: "flex-start", borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 6 }}>
                  <Text style={{ color: t.accent, fontSize: 12.5 }}>▶ Video öffnen</Text>
                </Pressable>
                <Text style={{ color: t.txtTertiary, fontSize: 11 }}>
                  Für eingebettete Wiedergabe expo-video installieren.
                </Text>
              </>
            )}
          </View>
        </View>
      ) : null}
    </Panel>
  );
}

export default function Recordings() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;
  const { data, isLoading, error } = useQuery({ queryKey: ["runs"], queryFn: api.runs });

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title="Recordings" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: wide ? 20 : 12, gap: 8, paddingBottom: 40,
        width: "100%", maxWidth: wide ? 760 : undefined, alignSelf: "center" }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar.</Text> : null}
        {data && data.length === 0 ? <Empty text="Keine Aufnahmen." /> : null}
        {(data ?? []).map((r: any) => <RunRow key={r.id} run={r} />)}
      </ScrollView>
    </View>
  );
}
