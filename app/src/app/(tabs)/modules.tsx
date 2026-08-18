// Modules & Rules — the user-facing config surface for the plugin system.
// Shows what DeepSeek-style composability means here: the loaded modules
// (engines, surfaces), the SEEDED rules (policies + charter) with live toggles,
// and the append-only reconfiguration journal (every change, who made it).
// Adjusting a policy posts a TRACKED swap to /policy/swap.

import { useEffect, useState, type ReactNode } from "react";
import { ActivityIndicator, ScrollView, Switch, Text, View } from "react-native";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { KEYS, type Engine, type PolicySet, type CharterDoc } from "@/kernel";
import { useKernelOptional, useSurfaces, useJournal } from "@/kernel/react";

type PolicyDoc = { version?: number; policies?: PolicySet; charter?: CharterDoc };

export default function ModulesTab() {
  const t = useTheme();
  const kernel = useKernelOptional();
  const surfaces = useSurfaces();
  const journal = useJournal();
  const [doc, setDoc] = useState<PolicyDoc | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = () =>
    api
      .get<PolicyDoc>("/policy")
      .then((d) => { setDoc(d); setErr(null); })
      .catch((e) => setErr(String(e?.message ?? e)));
  useEffect(() => { void load(); }, []);

  const engines: Engine[] = kernel?.get(KEYS.ENGINES)?.list().map((e) => e.value) ?? [];
  const policies = doc?.policies;
  const charter = doc?.charter;

  const setPolicy = async (key: keyof PolicySet, value: unknown) => {
    setBusy(true);
    try {
      await api.post("/policy/swap", { section: "policies", patch: { [key]: value }, actor: "user", note: `UI: ${String(key)}` });
      await load();
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const Section = ({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) => (
    <View style={{ marginBottom: 22 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", letterSpacing: 0.6, textTransform: "uppercase" }}>{title}</Text>
      {hint ? <Text style={{ color: t.txtTertiary, fontSize: 12, marginTop: 2, marginBottom: 8 }}>{hint}</Text> : <View style={{ height: 8 }} />}
      {children}
    </View>
  );

  const Row = ({ label, sub, right }: { label: string; sub?: string; right?: ReactNode }) => (
    <View style={{ flexDirection: "row", alignItems: "center", paddingVertical: 9, borderBottomWidth: 1, borderBottomColor: t.glassBorder }}>
      <View style={{ flex: 1 }}>
        <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{label}</Text>
        {sub ? <Text style={{ color: t.txtTertiary, fontSize: 11.5, marginTop: 1 }}>{sub}</Text> : null}
      </View>
      {right}
    </View>
  );

  const Bool = ({ k, label, sub }: { k: keyof PolicySet; label: string; sub?: string }) => (
    <Row label={label} sub={sub} right={
      <Switch value={!!policies?.[k]} disabled={busy || !policies} onValueChange={(v) => setPolicy(k, v)}
        trackColor={{ true: t.accent, false: t.glassBorder }} />
    } />
  );

  return (
    <ScrollView style={{ flex: 1, backgroundColor: t.canvas }} contentContainerStyle={{ padding: 18, paddingBottom: 60 }}>
      <Text style={{ color: t.txtPrimary, fontSize: 24, fontWeight: "700" }}>Module &amp; Regeln</Text>
      <Text style={{ color: t.txtSecondary, fontSize: 13, marginTop: 4, marginBottom: 20 }}>
        Alles ist ein Modul. Regeln sind aus dem Charter geseedet — anpassbar, jede Änderung wird protokolliert.
      </Text>

      {err ? <Text style={{ color: t.danger, fontSize: 12, marginBottom: 14 }}>{err}</Text> : null}

      <Section title="Engines" hint="Agent-Backends hinter einem Kontrakt (Claude / Copilot / DeepSeek).">
        {engines.length ? engines.map((e) => (
          <Row key={e.id} label={e.label} sub={e.id}
            right={<View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: e.available() ? t.ok : t.txtTertiary }} />
              <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{e.available() ? "verfügbar" : "aus"}</Text>
            </View>} />
        )) : <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Kein Kernel — Fallback aktiv.</Text>}
      </Section>

      <Section title="Surfaces" hint={`${surfaces.length} registrierte Oberflächen (Nav aus der Registry).`}>
        {surfaces.map((s) => <Row key={s.id} label={s.nav?.labelKey ?? s.title ?? s.id} sub={s.id} />)}
      </Section>

      <Section title="Regeln (geseedet)" hint="Standard = heutiger Charter. Umschalten schreibt einen getrackten Swap.">
        {policies ? (
          <>
            <Bool k="gateBeforeReview" label="Gate vor Review" sub="Suite muss grün sein, bevor reviewt wird" />
            <Bool k="auditAppendOnly" label="Append-only Audit" />
            <Bool k="worktreeIsolation" label="Worktree-Isolation" />
            <Bool k="authRequired" label="Auth erforderlich" />
            <Bool k="measuredEconomics" label="Gemessene Ökonomie" />
            <Bool k="agentMaySwap" label="Agent darf Module tauschen" sub="Aus = Human-Bestätigung nötig" />
            <Row label="WIP-Limit" sub="laufende Karten" right={<Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "600" }}>{policies.wipLimit}</Text>} />
          </>
        ) : <ActivityIndicator color={t.accent} />}
      </Section>

      {charter ? (
        <Section title="Charter (geseedet)" hint={`Quelle: ${charter.source} — selbst ein tauschbares Modul.`}>
          {charter.laws?.map((law, i) => (
            <Text key={i} style={{ color: t.txtSecondary, fontSize: 12.5, marginBottom: 6, lineHeight: 17 }}>• {law}</Text>
          ))}
        </Section>
      ) : null}

      <Section title="Reconfig-Journal" hint="Jede Modul-/Regeländerung, mit Urheber (die einzige Invariante: nichts ungetrackt).">
        {journal.length ? journal.slice(-12).reverse().map((e) => (
          <Row key={e.seq} label={`#${e.seq} ${e.op} ${e.pluginId}`} sub={`von ${e.actor}${e.replaced ? ` (ersetzt ${e.replaced})` : ""}${e.note ? ` — ${e.note}` : ""}`} />
        )) : <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Noch keine Einträge.</Text>}
      </Section>
    </ScrollView>
  );
}
