import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useState } from "react";
import {
  ActivityIndicator, Alert, Platform, Pressable, ScrollView, StyleSheet,
  Text, useWindowDimensions, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import type { Track } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Empty, Panel, ScreenHeader } from "@/ui/kit";

const isWeb = Platform.OS === "web";

interface ClaudeSession {
  id: string; cwd: string; project: string; first: string; last_active?: string;
}

function glass(t: ThemeTokens) {
  return isWeb
    ? ({ backgroundColor: t.glass, backdropFilter: "blur(16px) saturate(1.3)", WebkitBackdropFilter: "blur(16px) saturate(1.3)" } as any)
    : { backgroundColor: t.surface1 };
}

function SessionRow({ sv, onAdopt, busy }: {
  sv: ClaudeSession;
  onAdopt: (sv: ClaudeSession, mode: "continue" | "fork") => void;
  busy: string;
}) {
  const t = useTheme();
  const tr = useT();
  return (
    <Panel style={glass(t)}>
      <View style={{ flexDirection: "row", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <Text style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "600" }}>{sv.project || tr("sessions.session")}</Text>
        {sv.last_active ? <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{sv.last_active}</Text> : null}
        <Text style={{ color: t.txtTertiary, fontSize: 11, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" }}>{sv.id.slice(0, 8)}</Text>
      </View>
      <Text style={{ color: t.txtSecondary, fontSize: 12 }} numberOfLines={2}>{sv.first || tr("sessions.noText")}</Text>
      <Text style={{ color: t.txtTertiary, fontSize: 10.5 }} numberOfLines={1}>{sv.cwd}</Text>
      <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
        <Pressable onPress={() => onAdopt(sv, "continue")} disabled={!!busy}
          style={[s.btn, { backgroundColor: t.accent, borderColor: t.accent, opacity: busy ? 0.6 : 1 }]}>
          <Text style={{ color: "#fff", fontSize: 11.5, fontWeight: "700" }}>{busy === sv.id + "continue" ? "…" : tr("sessions.continue")}</Text>
        </Pressable>
        <Pressable onPress={() => onAdopt(sv, "fork")} disabled={!!busy}
          style={[s.btn, { backgroundColor: t.surface2, borderColor: t.borderSubtle, opacity: busy ? 0.6 : 1 }]}>
          <Text style={{ color: t.txtSecondary, fontSize: 11.5, fontWeight: "600" }}>{busy === sv.id + "fork" ? "…" : tr("sessions.branch")}</Text>
        </Pressable>
      </View>
    </Panel>
  );
}

export default function Sessions() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;
  const { data, isLoading, error } = useQuery({ queryKey: ["sessions"], queryFn: api.claudeSessions });
  const [busy, setBusy] = useState("");

  async function adopt(sv: ClaudeSession, mode: "continue" | "fork") {
    setBusy(sv.id + mode);
    try {
      // POST /sessions/claude/adopt — mode "continue" resumes in place (--resume),
      // "fork" branches a fresh session/worktree seeded with the original request.
      const r = await api.post<Track & { error?: string }>("/sessions/claude/adopt", {
        session_id: sv.id, cwd: sv.cwd, first: sv.first, mode,
      });
      if (r?.error) { Alert.alert(tr("ui.error"), r.error); return; }
      await qc.invalidateQueries({ queryKey: ["tracks"] });
      Alert.alert(
        mode === "continue" ? tr("sessions.asCard") : tr("sessions.branched"),
        mode === "continue" ? tr("sessions.asCardBody") : tr("sessions.branchedBody"),
      );
      if (mode === "continue" && r?.id) router.push(`/card/${r.id}`);
    } catch (e) {
      Alert.alert(tr("ui.error"), String((e as Error).message));
    } finally {
      setBusy("");
    }
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr("nav.sessions")} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 60, width: "100%", maxWidth: wide ? 900 : undefined, alignSelf: "center" }}>
        <Text style={{ color: t.txtSecondary, fontSize: 12, lineHeight: 18 }}>
          {tr("sessions.intro")}
        </Text>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>{tr("health.unreachable")}</Text> : null}
        {data && data.length === 0 ? <Empty text={tr("sessions.empty")} /> : null}
        {(data ?? []).map((sv: ClaudeSession, i: number) => (
          <SessionRow key={sv.id ?? i} sv={sv} onAdopt={adopt} busy={busy} />
        ))}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  btn: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8, alignItems: "center", justifyContent: "center" },
});
