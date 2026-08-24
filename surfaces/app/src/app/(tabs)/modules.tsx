// Modules & Rules — the user-facing config surface for the plugin system.
// Shows what DeepSeek-style composability means here: the loaded modules
// (engines, surfaces), the SEEDED rules (policies + charter) with live toggles,
// and the append-only reconfiguration journal (every change, who made it).
// Adjusting a policy posts a TRACKED swap to /policy/swap.

import { useEffect, useState, type ReactNode } from "react";
import { ActivityIndicator, Pressable, ScrollView, Switch, Text, View } from "react-native";

import { api, type CellInfo } from "@/data/client";
// `t` is the THEME on this screen (see below), so the translator is `tr` here -
// the same aliasing every other tab does. Shadowing one with the other is what
// left this screen hardcoded German in the first place.
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { KEYS, type Engine, type PolicySet, type CharterDoc } from "@/kernel";
import { useKernelOptional, useSurfaces, useJournal } from "@/kernel/react";
import { CellDiagram } from "@/ui/cell_diagram";

type PolicyDoc = { version?: number; policies?: PolicySet; charter?: CharterDoc };

export default function ModulesTab() {
  const t = useTheme();
  const tr = useT();
  const kernel = useKernelOptional();
  const surfaces = useSurfaces();
  const journal = useJournal();
  const [doc, setDoc] = useState<PolicyDoc | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Cell registry (cells.py GET /cells) - falls back to an empty list
  // on any error (403 for a client role, daemon unreachable, etc.) so this
  // screen still renders the rest of Modules & Rules without crashing.
  const [cells, setCells] = useState<CellInfo[]>([]);
  // Which cell's architecture diagram is showing (Section "Cells" below) -
  // SELECT, not expand-in-place, so at most one diagram renders at a time
  // (5 stacked diagrams would blow past the reference style's density
  // target). Tapping the same cell again collapses it.
  const [selectedCell, setSelectedCell] = useState<string | null>(null);

  const load = () =>
    api
      .get<PolicyDoc>("/policy")
      .then((d) => { setDoc(d); setErr(null); })
      .catch((e) => setErr(String(e?.message ?? e)));
  const loadCells = () =>
    api.cells()
      .then((d) => setCells(d.cells ?? []))
      .catch(() => setCells([]));
  useEffect(() => { void load(); void loadCells(); }, []);

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
      <Text style={{ color: t.txtPrimary, fontSize: 24, fontWeight: "700" }}>{tr("modules.title")}</Text>
      <Text style={{ color: t.txtSecondary, fontSize: 13, marginTop: 4, marginBottom: 20 }}>
        {tr("modules.sub")}
      </Text>

      {err ? <Text style={{ color: t.danger, fontSize: 12, marginBottom: 14 }}>{err}</Text> : null}

      <Section title={tr("modules.engines")} hint={tr("modules.enginesHint")}>
        {engines.length ? engines.map((e) => (
          <Row key={e.id} label={e.label} sub={e.id}
            right={<View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: e.available() ? t.ok : t.txtTertiary }} />
              <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr(e.available() ? "modules.engineOn" : "modules.engineOff")}</Text>
            </View>} />
        )) : <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("modules.noKernel")}</Text>}
      </Section>

      <Section title={tr("modules.surfaces")} hint={tr("modules.surfacesHint", { n: surfaces.length })}>
        {/* labelKey is a DICT KEY ("nav.board"), so it has to go through the
            translator - rendered raw, this section listed fourteen dotted keys
            where the nav labels belong. An unknown key still renders as itself
            (i18n/core render()), so a surface with no entry degrades to what it
            printed before instead of blanking. */}
        {/* `||`, not `??`: every nav surface carries title: "" (the label lives
            in nav.labelKey), and `??` keeps an empty string - which is why the
            one surface without a labelKey, tab.more, rendered a blank row. */}
        {surfaces.map((s) => <Row key={s.id} label={s.nav?.labelKey ? tr(s.nav.labelKey) : (s.title || s.id)} sub={s.id} />)}
      </Section>

      <Section title={tr("modules.rules")} hint={tr("modules.rulesHint")}>
        {policies ? (
          <>
            <Bool k="gateBeforeReview" label={tr("modules.gateBeforeReview")} sub={tr("modules.gateBeforeReviewSub")} />
            <Bool k="auditAppendOnly" label={tr("modules.auditAppendOnly")} />
            <Bool k="worktreeIsolation" label={tr("modules.worktreeIsolation")} />
            <Bool k="authRequired" label={tr("modules.authRequired")} />
            <Bool k="measuredEconomics" label={tr("modules.measuredEconomics")} />
            <Bool k="agentMaySwap" label={tr("modules.agentMaySwap")} sub={tr("modules.agentMaySwapSub")} />
            <Row label={tr("modules.wipLimit")} sub={tr("modules.wipLimitSub")} right={<Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "600" }}>{policies.wipLimit}</Text>} />
          </>
        ) : <ActivityIndicator color={t.accent} />}
      </Section>

      <Section title={tr("modules.cells")} hint={tr("modules.cellsHint")}>
        {cells.length ? cells.map((c) => (
          <Pressable key={c.id} onPress={() => setSelectedCell(selectedCell === c.id ? null : c.id)}>
            <Row label={c.id} sub={`${c.role}${c.surface ? ` — ${c.surface}` : ""}${c.modes.length ? ` — modes: ${c.modes.join(", ")}` : ""}`}
              right={
                <Switch value={c.enabled} disabled={busy}
                  onValueChange={(v) => setPolicy(c.enabledKey as keyof PolicySet, v).then(loadCells)}
                  trackColor={{ true: t.accent, false: t.glassBorder }} />
              } />
          </Pressable>
        )) : <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("modules.noCells")}</Text>}
        {selectedCell ? (() => {
          const c = cells.find((x) => x.id === selectedCell);
          return c ? (
            <View style={{ marginTop: 10, borderWidth: 1, borderColor: t.glassBorder, borderRadius: 10, padding: 8 }}>
              <CellDiagram cell={c} />
            </View>
          ) : null;
        })() : null}
      </Section>

      {charter ? (
        <Section title={tr("modules.charter")} hint={tr("modules.charterHint", { source: charter.source })}>
          {charter.laws?.map((law, i) => (
            <Text key={i} style={{ color: t.txtSecondary, fontSize: 12.5, marginBottom: 6, lineHeight: 17 }}>• {law}</Text>
          ))}
        </Section>
      ) : null}

      <Section title={tr("modules.journal")} hint={tr("modules.journalHint")}>
        {journal.length ? journal.slice(-12).reverse().map((e) => (
          <Row key={e.seq} label={`#${e.seq} ${e.op} ${e.pluginId}`}
            sub={tr("modules.journalBy", { actor: e.actor })
              + (e.replaced ? tr("modules.journalReplaced", { id: e.replaced }) : "")
              + (e.note ? ` — ${e.note}` : "")} />
        )) : <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("modules.noJournal")}</Text>}
      </Section>
    </ScrollView>
  );
}
