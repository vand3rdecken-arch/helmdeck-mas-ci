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
  /** set by the daemon (claude_sessions.list_sessions, derived from the track
   *  store - the one owner) when this session is already bound to a card.
   *  Continuing it would just bounce with "session already on the board". */
  card?: string;
}

function glass(t: ThemeTokens) {
  return isWeb
    ? ({ backgroundColor: t.glass, backdropFilter: "blur(16px) saturate(1.3)", WebkitBackdropFilter: "blur(16px) saturate(1.3)" } as any)
    : { backgroundColor: t.surface1 };
}

function SessionRow({ sv, onAdopt, onOpenCard, busy }: {
  sv: ClaudeSession;
  onAdopt: (sv: ClaudeSession, mode: "continue" | "fork") => void;
  onOpenCard: (id: string) => void;
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
      {sv.card ? (
        // Already bound to a card - "continue" would only bounce with "session
        // already on the board" (one session, one owning card). Link to it
        // instead of offering a dead-end button.
        <Pressable onPress={() => onOpenCard(sv.card as string)}
          style={[s.btn, { alignSelf: "flex-start", marginTop: 8, backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
          <Text style={{ color: t.accent, fontSize: 11.5, fontWeight: "600" }}>{tr("sessions.onBoard")}</Text>
        </Pressable>
      ) : (
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
      )}
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
  // Alert.alert is a NO-OP on react-native-web (desktop): a rejected adopt used
  // to fail completely silently there - same class fixed in app/new.tsx. Show
  // it inline instead so the desktop owner isn't left staring at nothing.
  const [err, setErr] = useState("");

  async function adopt(sv: ClaudeSession, mode: "continue" | "fork") {
    setBusy(sv.id + mode);
    setErr("");
    try {
      // POST /sessions/claude/adopt — mode "continue" resumes in place (--resume),
      // "fork" branches a fresh session/worktree seeded with the original request.
      const r = await api.post<Track & { error?: string }>("/sessions/claude/adopt", {
        session_id: sv.id, cwd: sv.cwd, first: sv.first, mode,
      });
      if (r?.error) { setErr(r.error); return; }
      await qc.invalidateQueries({ queryKey: ["tracks"] });
      if (mode === "continue" && r?.id) router.push(`/card/${r.id}`);
      else Alert.alert(tr("sessions.branched"), tr("sessions.branchedBody"));
    } catch (e) {
      setErr(String((e as Error).message));
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
        {err ? (
          <View style={{ backgroundColor: t.danger + "1A", borderColor: t.danger + "66", borderWidth: 1,
            borderRadius: 8, padding: 10 }}>
            <Text style={{ color: t.danger, fontSize: 12.5 }}>{err}</Text>
          </View>
        ) : null}
        {data && data.length === 0 ? <Empty text={tr("sessions.empty")} /> : null}
        {(data ?? []).map((sv: ClaudeSession, i: number) => (
          <SessionRow key={sv.id ?? i} sv={sv} onAdopt={adopt}
            onOpenCard={(id) => router.push(`/card/${id}` as never)} busy={busy} />
        ))}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  btn: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8, alignItems: "center", justifyContent: "center" },
});
