import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, ScrollView, Text, TextInput, View, Pressable } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Empty, ScreenHeader } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

// The audit-trail review screen (ops/docs/backlog/rbac-gxp card 5). Read-only
// by construction - there is no write affordance anywhere on this screen,
// matching GET /audit's own owner/auditor-only, read-only contract
// (routes_audit.py). Nav visibility is capability-gated (cap: "audit.read",
// more.tsx) so a role without it never sees the entry point at all - the 403
// this screen would otherwise hit on load is prevented one layer up.
interface AuditEvent {
  id: string; at_utc: string; kind: string; track: string; actor?: string;
  [k: string]: unknown;
}
interface AuditResponse { total: number; returned: number; events: AuditEvent[] }

function fieldStyle(t: ThemeTokens) {
  return { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle,
    borderWidth: 1, borderRadius: 8, padding: 9, fontSize: 12.5 } as const;
}

function EventRow({ t, e }: { t: ThemeTokens; e: AuditEvent }) {
  const [open, setOpen] = useState(false);
  const extra = Object.fromEntries(
    Object.entries(e).filter(([k]) => !["id", "at_utc", "ts", "kind", "track"].includes(k)),
  );
  return (
    <Pressable onPress={() => setOpen((v) => !v)}
      style={{ paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: t.glassBorder, gap: 3 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        {/* t.human is reserved for the one place a human signed something
            (sign_off.tsx) - an audit row is a record OF an action, not the
            act itself, so this uses the neutral accent instead. */}
        <View style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 5, paddingHorizontal: 6, paddingVertical: 1 }}>
          <Text style={{ color: t.accent, fontSize: 10.5, fontWeight: "600" }}>{e.kind}</Text>
        </View>
        <Text style={{ color: t.txtSecondary, fontSize: 12, flex: 1 }} numberOfLines={1}>
          {(e.actor as string) ?? "-"}{e.track && e.track !== "-" ? "  ·  " + e.track : ""}
        </Text>
        <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{e.at_utc}</Text>
      </View>
      {open ? (
        <Text selectable style={{ color: t.txtTertiary, fontSize: 11, fontFamily: "monospace" }}>
          {JSON.stringify(extra, null, 2)}
        </Text>
      ) : null}
    </Pressable>
  );
}

export default function AuditScreen() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();

  const [kind, setKind] = useState("");
  const [actor, setActor] = useState("");
  const [q, setQ] = useState("");
  // Applied filters only change on submit (house doctrine: typing never
  // silently reruns a query mid-edit) - a manual Suchen tap, not per-keystroke.
  const [applied, setApplied] = useState({ kind: "", actor: "", q: "" });

  const query = useQuery({
    queryKey: ["audit", applied],
    queryFn: () => {
      const params = new URLSearchParams();
      if (applied.kind) params.set("kind", applied.kind);
      if (applied.actor) params.set("actor", applied.actor);
      if (applied.q) params.set("q", applied.q);
      params.set("limit", "200");
      return api.get<AuditResponse>(`/audit?${params.toString()}`);
    },
  });

  const rows = query.data?.events ?? [];

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr("audit.title")} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{
        padding: wide ? 20 : 12, gap: 10, paddingBottom: insets.bottom + 40,
        width: "100%", maxWidth: wide ? 900 : undefined, alignSelf: "center",
      }}>
        <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("audit.sub")}</Text>
        <View style={{ flexDirection: wide ? "row" : "column", gap: 8 }}>
          <TextInput value={kind} onChangeText={setKind} autoCapitalize="none"
            placeholder={tr("audit.kindPh")} placeholderTextColor={t.txtPlaceholder}
            style={[fieldStyle(t), { flex: 1 }]} />
          <TextInput value={actor} onChangeText={setActor} autoCapitalize="none"
            placeholder={tr("audit.actorPh")} placeholderTextColor={t.txtPlaceholder}
            style={[fieldStyle(t), { flex: 1 }]} />
          <TextInput value={q} onChangeText={setQ} autoCapitalize="none"
            placeholder={tr("audit.qPh")} placeholderTextColor={t.txtPlaceholder}
            style={[fieldStyle(t), { flex: 1 }]} />
          <Pressable onPress={() => setApplied({ kind, actor, q })}
            style={{ backgroundColor: t.accent, borderRadius: 8, paddingHorizontal: 16,
              alignItems: "center", justifyContent: "center" }}>
            <Text style={{ color: "#fff", fontWeight: "600", fontSize: 12.5 }}>{tr("audit.search")}</Text>
          </Pressable>
        </View>

        {query.isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {query.error ? <Text style={{ color: t.danger, fontSize: 12.5 }}>{tr("health.unreachable")}</Text> : null}
        {query.data ? (
          <Text style={{ color: t.txtTertiary, fontSize: 11 }}>
            {tr("audit.count", { returned: rows.length, total: query.data.total })}
          </Text>
        ) : null}
        {query.data && rows.length === 0 ? <Empty text={tr("audit.empty")} /> : null}
        <View>
          {rows.map((e) => <EventRow key={e.id} t={t} e={e} />)}
        </View>
      </ScrollView>
    </View>
  );
}
