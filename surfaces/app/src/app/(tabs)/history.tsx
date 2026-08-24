import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useState } from "react";
import {
  ActivityIndicator, Alert, Platform, Pressable, ScrollView, Text, useWindowDimensions, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import type { Me } from "@/data/types";
import { t as i18nT, useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Empty, ScreenHeader } from "@/ui/kit";
import { HistoryGraph, type Hist } from "@/ui/history_graph";

const isWeb = Platform.OS === "web";

interface Checkpoint { id: string; actor: string; reason: string; ts: string }
interface CpField { key: string; before: unknown; after: unknown }
interface CpDiff { id: string; settings: CpField[]; connectors: { added: string[]; removed: string[] } }
interface Debt {
  id: string; title: string; status: string; what: string; why_it_bites: string; trigger: string; fix: string;
}

function glass(t: ThemeTokens) {
  return isWeb
    ? ({ backgroundColor: t.glass, backdropFilter: "blur(16px) saturate(1.3)", WebkitBackdropFilter: "blur(16px) saturate(1.3)" } as any)
    : { backgroundColor: t.surface1 };
}

function val(v: unknown): string {
  if (v === null || v === undefined) return i18nT("history.unset");
  if (typeof v === "string") return v === "" ? '""' : v;
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function Panel({ t, title, sub, children }: { t: ThemeTokens; title: string; sub?: string; children: React.ReactNode }) {
  return (
    <View style={[glass(t), { borderWidth: 1, borderColor: t.glassBorder, borderRadius: 14, padding: 14, gap: 8 }]}>
      <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "700" }}>{title}</Text>
      {sub ? <Text style={{ color: t.txtTertiary, fontSize: 11.5, marginTop: -4 }}>{sub}</Text> : null}
      {children}
    </View>
  );
}

function CheckpointRow({ t, c, isOwner }: { t: ThemeTokens; c: Checkpoint; isOwner: boolean }) {
  const qc = useQueryClient();
  const tr = useT();
  const [open, setOpen] = useState(false);
  const { data: diff, isFetching } = useQuery({
    queryKey: ["cpdiff", c.id],
    queryFn: () => api.get<CpDiff>(`/checkpoints/${c.id}/diff`),
    enabled: open,
  });
  const restore = useMutation({
    mutationFn: () => api.post<{ error?: string; restored?: string }>(`/checkpoints/${c.id}/restore`, {}),
    onSuccess: (r) => {
      Alert.alert(r.error ? tr("ui.error") : tr("history.restored"), r.error ?? tr("history.restoredBody"));
      qc.invalidateQueries({ queryKey: ["checkpoints"] });
    },
    onError: (e) => Alert.alert(tr("ui.error"), String((e as Error).message)),
  });
  const noChange = diff && diff.settings.length === 0 && !diff.connectors.added.length && !diff.connectors.removed.length;
  return (
    <View style={{ borderBottomWidth: 1, borderBottomColor: t.glassBorder, paddingVertical: 8 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Pressable onPress={() => setOpen((v) => !v)} style={{ flex: 1, flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{open ? "▾" : "▸"}</Text>
          <View style={{ flex: 1 }}>
            <Text style={{ color: t.txtPrimary, fontSize: 12.5 }} numberOfLines={2}>{c.reason}</Text>
            <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{c.actor} · {c.ts}</Text>
          </View>
        </Pressable>
        {isOwner ? (
          <Pressable
            onPress={() => Alert.alert(tr("history.restoreTitle"), tr("history.restoreBody", { reason: c.reason }), [
              { text: tr("ui.cancel"), style: "cancel" },
              { text: tr("history.restore"), onPress: () => restore.mutate() },
            ])}
            style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 }}
          >
            <Text style={{ color: t.txtSecondary, fontSize: 11 }}>{tr("history.restoreShort")}</Text>
          </Pressable>
        ) : null}
      </View>
      {open ? (
        <View style={{ paddingLeft: 19, paddingTop: 6 }}>
          {isFetching && !diff ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("history.diffLoading")}</Text> : null}
          {diff && noChange ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("history.noFieldChange")}</Text> : null}
          {diff && !noChange ? (
            <View style={{ gap: 2 }}>
              {diff.settings.map((f) => (
                <Text key={f.key} style={{ fontSize: 12, fontFamily: isWeb ? "ui-monospace, monospace" : "monospace" }}>
                  <Text style={{ color: t.txtSecondary }}>{f.key}</Text>
                  <Text style={{ color: t.txtTertiary }}>: </Text>
                  <Text style={{ color: t.danger }}>{val(f.before)}</Text>
                  <Text style={{ color: t.txtTertiary }}> → </Text>
                  <Text style={{ color: t.ok }}>{val(f.after)}</Text>
                </Text>
              ))}
              {diff.connectors.added.map((n) => <Text key={"a" + n} style={{ color: t.ok, fontSize: 12 }}>{tr("history.connectorAdded", { name: n })}</Text>)}
              {diff.connectors.removed.map((n) => <Text key={"r" + n} style={{ color: t.danger, fontSize: 12 }}>{tr("history.connectorRemoved", { name: n })}</Text>)}
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

function DebtRow({ t, d, canFix }: { t: ThemeTokens; d: Debt; canFix: boolean }) {
  const qc = useQueryClient();
  const tr = useT();
  const fix = useMutation({
    mutationFn: () => api.post<{ error?: string; id?: string }>(`/debt/${d.id}/fix`, {}),
    onSuccess: (r) => {
      Alert.alert(r.error ? tr("ui.error") : tr("history.fixCardCreated"), r.error ?? tr("history.fixCardBody"));
      qc.invalidateQueries({ queryKey: ["tracks"] });
    },
    onError: (e) => Alert.alert(tr("ui.error"), String((e as Error).message)),
  });
  const stColor = d.status === "paid" ? t.ok : d.status === "in_progress" ? t.ai : t.warn;
  return (
    <View style={{ paddingVertical: 9, borderBottomWidth: 1, borderBottomColor: t.glassBorder, gap: 3 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <View style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 5, paddingHorizontal: 6, paddingVertical: 1 }}>
          <Text style={{ color: stColor, fontSize: 10.5, fontWeight: "600" }}>{d.status}</Text>
        </View>
        <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600", flexShrink: 1 }}>{d.title}</Text>
        {canFix && d.status === "open" ? (
          <Pressable
            onPress={() => fix.mutate()}
            style={{ marginLeft: "auto", borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 }}
          >
            <Text style={{ color: t.txtSecondary, fontSize: 11 }}>{tr("history.fileFixCard")}</Text>
          </Pressable>
        ) : null}
      </View>
      <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("history.bitesWhen", { trigger: d.trigger })}</Text>
      <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{d.why_it_bites}</Text>
      <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("history.fix", { fix: d.fix })}</Text>
    </View>
  );
}

export default function History() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;

  const qc = useQueryClient();
  const hist = useQuery({ queryKey: ["history"], queryFn: () => api.get<Hist>("/history") });
  const cps = useQuery({ queryKey: ["checkpoints"], queryFn: () => api.get<Checkpoint[]>("/checkpoints") });
  const debt = useQuery({ queryKey: ["debt"], queryFn: () => api.get<Debt[]>("/debt") });
  const me = useQuery<Me>({ queryKey: ["me"], queryFn: api.me });

  const isOwner = me.data?.role === "owner";
  const canFix = me.data ? me.data.role !== "client" : false;

  const forkMut = useMutation({
    mutationFn: (track: string) => api.fork(track) as Promise<{ id?: string; error?: string }>,
    onSuccess: (r) => {
      Alert.alert(r.error ? tr("ui.error") : tr("history.forked"), r.error ?? tr("history.forkedBody"));
      qc.invalidateQueries({ queryKey: ["history"] });
      qc.invalidateQueries({ queryKey: ["tracks"] });
    },
    onError: (e) => Alert.alert(tr("ui.error"), String((e as Error).message)),
  });

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr("nav.history")} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{
        padding: wide ? 20 : 12, gap: 14, paddingBottom: 60,
        width: "100%", maxWidth: wide ? 1200 : undefined, alignSelf: "center",
      }}>
        {hist.isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {hist.error ? <Text style={{ color: t.danger }}>{tr("health.unreachable")}</Text> : null}

        {hist.data ? (
          <Panel t={t} title={tr("history.commitGraph")}
            sub={tr("history.commitGraphSub")}>
            <HistoryGraph
              h={hist.data}
              onOpenCard={(id) => router.push(`/card/${id}`)}
              onFork={(track, branch) => Alert.alert(
                tr("history.forkTitle"),
                tr("history.forkBody", { branch }),
                [
                  { text: tr("ui.cancel"), style: "cancel" },
                  { text: tr("history.fork"), onPress: () => forkMut.mutate(track) },
                ],
              )}
            />
          </Panel>
        ) : null}

        {/* Owner only: the per-checkpoint diff returns settings VALUES (relay.sk,
            glance_token, invite_code), so the daemon route is owner-gated like
            restore. Showing the panel to an operator would leave an expander that
            can only 403. */}
        {isOwner ? (
          <Panel t={t} title={tr("history.checkpoints")}
            sub={tr("history.checkpointsSub")}>
            {cps.isLoading ? <ActivityIndicator color={t.accent} /> : null}
            {cps.data && cps.data.length === 0 ? <Empty text={tr("history.noCheckpoints")} /> : null}
            {(cps.data ?? []).slice(0, 20).map((c) => <CheckpointRow key={c.id} t={t} c={c} isOwner={isOwner} />)}
          </Panel>
        ) : null}

        <Panel t={t} title={tr("history.debt")}
          sub={tr("history.debtSub")}>
          {debt.isLoading ? <ActivityIndicator color={t.accent} /> : null}
          {debt.data && debt.data.length === 0 ? <Empty text={tr("history.noDebt")} /> : null}
          {(debt.data ?? []).map((d) => <DebtRow key={d.id} t={t} d={d} canFix={canFix} />)}
        </Panel>
      </ScrollView>
    </View>
  );
}
