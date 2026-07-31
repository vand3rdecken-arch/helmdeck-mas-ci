import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { Chip, KVRow, Panel, SectionLabel } from "@/ui/kit";

export default function Automation() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { data, isLoading, error } = useQuery({ queryKey: ["automation"], queryFn: api.automation });

  const cur = (data?.loop_current as { state: string; action: string }[]) ?? [];
  const states = (data?.loop_states as { state: string; desc: string }[]) ?? [];
  const curState = cur[0]?.state ?? "";
  const ns = (data?.nightshift as any) ?? {};
  const nsCfg = ns.config ?? {};
  const pol = (data?.policy as any) ?? {};
  const repos = (data?.repos as string[]) ?? [];

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", padding: 10, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>Automation & loop</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 40 }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>Nur für Owner / Desktop nicht erreichbar.</Text> : null}
        {data ? (
          <>
            <Panel>
              <SectionLabel text="build-loop" />
              <Text style={{ color: t.accent, fontWeight: "500", marginBottom: 2 }}>{curState ? `jetzt: ${curState}` : "?"}</Text>
              {cur[0]?.action ? <Text style={{ color: t.txtSecondary, fontSize: 12, marginBottom: 6 }}>{cur[0].action}</Text> : null}
              {states.map((st) => {
                const here = st.state === curState;
                return (
                  <View key={st.state} style={{ flexDirection: "row", paddingVertical: 2 }}>
                    <Text style={{ width: 84, color: here ? t.accent : t.txtSecondary, fontWeight: here ? "700" : "500", fontSize: 12 }}>
                      {here ? "▸ " : ""}{st.state}
                    </Text>
                    <Text style={{ flex: 1, color: t.txtTertiary, fontSize: 11.5 }}>{st.desc}</Text>
                  </View>
                );
              })}
            </Panel>
            <Panel>
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                <SectionLabel text="night-shift" />
                <Chip text={nsCfg.enabled ? "an" : "aus"} dot={nsCfg.enabled ? t.ok : t.txtTertiary} />
              </View>
              <KVRow k="Fenster" v={nsCfg.window || "always"} />
              <KVRow k="Idle-Gate" v={`${nsCfg.idle_minutes ?? 20} min`} />
              <KVRow k="Max/Nacht" v={`${nsCfg.max_cards ?? 3}`} />
              <KVRow k="Heute gestartet" v={`${(ns.tonight?.started ?? []).length}`} />
            </Panel>
            <Panel>
              <SectionLabel text="policy" />
              <KVRow k="Auto-accept grün" v={pol.auto_accept_green ? "ja" : "nein"} />
              <KVRow k="Auto-dispatch" v={(pol.auto_dispatch_modes ?? []).join(", ") || "-"} />
              <KVRow k="Chat-Admin" v={(pol.chat_configure_roles ?? ["owner"]).join(", ")} />
            </Panel>
            <Panel>
              <SectionLabel text={`repos (${repos.length})`} />
              {repos.length === 0 ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>keine</Text> :
                repos.map((r) => <Text key={r} style={{ color: t.txtSecondary, fontSize: 11.5 }}>{r}</Text>)}
            </Panel>
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}
