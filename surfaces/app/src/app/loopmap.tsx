import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type HarnessConfig, type LoopMap, type LoopNode, type RepoTemplates } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { RuleBlock } from "@/ui/harness_rules";
import { RepoPipeline } from "@/ui/repo_pipeline";
import { useResponsive } from "@/ui/responsive";
import { SchemaStation, useSchema } from "@/ui/settings_schema_page";

const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }) as string;

type Tr = (k: string, p?: Record<string, string | number>) => string;

// The gate's pulsing shield moved into ui/repo_pipeline.tsx with the rest of the
// station row - it belongs to the pipeline, not to this screen, now that repo
// onboarding draws the same row.
//
// FlowToken (a glowing dot travelling the pipeline) lived here and was already
// unrendered: the stations grew a label AND a note line, and the token's
// absolutely-positioned band then landed on top of the last station and read as
// a stray artifact. It was cut from the render and left defined; this card
// removes the definition too, so the file does not carry a decoration nothing
// can reach.

/**
 * FIXED vs ADJUSTABLE, in words.
 *
 * This used to be a bare padlock glyph on every row, and red (t.danger) at that
 * — so a deliberate design guarantee rendered as an unexplained alarm and the
 * whole screen read as "everything is locked, nothing here is for you". The
 * badge now SAYS which of the two it is, and the two states are colour-coded by
 * what they mean rather than by severity:
 *   fixed  — neutral/quiet. It is structure, not a problem.
 *   policy — accent. It is a live affordance; something is tappable behind it.
 */
function KindBadge({ kind, t, tr, small }: { kind?: string; t: ThemeTokens; tr: Tr; small?: boolean }) {
  if (kind !== "fixed" && kind !== "policy") return null;
  const fixed = kind === "fixed";
  const fg = fixed ? t.txtTertiary : t.accent;
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: t.surface2,
      borderColor: fixed ? t.borderStrong : t.accent, borderWidth: 1, borderRadius: 999,
      paddingHorizontal: small ? 7 : 9, paddingVertical: small ? 2 : 3 }}>
      <Ionicons name={fixed ? "lock-closed" : "options-outline"} size={small ? 10 : 11.5} color={fg} />
      <Text style={{ color: fg, fontSize: small ? 10 : 10.5, fontWeight: "700" }}>
        {tr(fixed ? "loopmap.kindFixed" : "loopmap.kindPolicy")}
      </Text>
    </View>
  );
}

/** A section heading + what the section IS + whether it is fixed or yours.
 *  The old screen gave lanes, loop stages, briefs and laws the same bare bold
 *  line, so four unrelated concepts read as one list. */
function SectionHead({ title, hint, kind, right, t, tr }: {
  title: string; hint?: string; kind?: string; right?: React.ReactNode; t: ThemeTokens; tr: Tr;
}) {
  return (
    <View style={{ gap: 5, marginTop: 6 }}>
      {/* deliberately NOT flexWrap: the German titles are long, so a wrapping
          row would drop the badge onto a line of its own and break the
          "heading, then what kind of thing it is" reading order. The title
          wraps INSIDE its own Text instead and the badge stays anchored right. */}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700", flex: 1 }}>{title}</Text>
        <KindBadge kind={kind} t={t} tr={tr} />
        {right}
      </View>
      {hint ? (
        <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16.5 }}>{hint}</Text>
      ) : null}
    </View>
  );
}

/**
 * One settings path a node names.
 *
 * `editable` is the daemon's list of paths /automation really renders a control
 * for. Before this, EVERY path became a tappable chip pointing at the hub —
 * including capacity.wip_limit (settings.json only) and env.SWARM_WIP_MINUTES
 * (an environment variable), so two of the four chips on this screen navigated
 * to a form that does not contain them. A knob the app cannot edit is still
 * worth naming; it just gets told where it actually lives instead of a link.
 */
function KnobChip({ path, editable, onOpen, t, tr }: {
  path: string; editable: boolean; onOpen: () => void; t: ThemeTokens; tr: Tr;
}) {
  const where = path.startsWith("env.") ? tr("loopmap.knobEnv") : tr("loopmap.knobFile");
  if (!editable) {
    return (
      <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 7, backgroundColor: t.surface2,
        borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8 }}>
        <Ionicons name="document-text-outline" size={13} color={t.txtTertiary} style={{ marginTop: 1 }} />
        <View style={{ flex: 1, gap: 2 }}>
          <Text selectable style={{ color: t.txtSecondary, fontSize: 11.5, fontFamily: MONO }}>{path}</Text>
          <Text style={{ color: t.txtTertiary, fontSize: 10.5, lineHeight: 15 }}>{where}</Text>
        </View>
      </View>
    );
  }
  return (
    <Pressable onPress={onOpen}
      style={{ flexDirection: "row", alignItems: "center", gap: 7, backgroundColor: t.surface2,
        borderColor: t.accent, borderWidth: 1, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8 }}>
      <Ionicons name="options-outline" size={13} color={t.accent} />
      <View style={{ flex: 1, gap: 2 }}>
        <Text selectable style={{ color: t.txtPrimary, fontSize: 11.5, fontFamily: MONO }}>{path}</Text>
        <Text style={{ color: t.accent, fontSize: 10.5, fontWeight: "600" }}>{tr("loopmap.openAutomation")}</Text>
      </View>
      <Ionicons name="chevron-forward" size={13} color={t.txtTertiary} />
    </Pressable>
  );
}

/**
 * What is behind one node: the rule, WHY it is the way it is, and the proof —
 * a source line for a fixed node, the real knobs for a policy one.
 *
 * `why` comes from the daemon (loop_state.LOOP_STATES / sessions.LANE_FLOW),
 * declared next to `kind` by the module that decides a node is fixed. The
 * fallbacks below are for an older daemon only; they say the generic truth
 * rather than inventing a specific reason the app cannot verify.
 */
function NodeBody({ node, editable, onOpen, t, tr }: {
  node: LoopNode; editable: string[]; onOpen: () => void; t: ThemeTokens; tr: Tr;
}) {
  const fixed = node.kind === "fixed";
  const why = node.why || tr(fixed ? "loopmap.whyFixedFallback" : "loopmap.whyPolicyFallback");
  return (
    <View style={{ gap: 9 }}>
      <Text style={{ color: t.txtSecondary, fontSize: 12.5, lineHeight: 18.5 }}>{node.instruction}</Text>

      {/* the reason, set apart by a rule so it does not read as more of the
          same paragraph — this line is the whole answer to "why the padlock?" */}
      <View style={{ flexDirection: "row", gap: 9, borderLeftWidth: 2,
        borderLeftColor: fixed ? t.borderStrong : t.accent, paddingLeft: 9 }}>
        <Text style={{ color: t.txtSecondary, fontSize: 12, lineHeight: 17.5, flex: 1 }}>{why}</Text>
      </View>

      {fixed && node.source ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Ionicons name="code-slash-outline" size={12} color={t.txtTertiary} />
          <Text selectable style={{ color: t.txtTertiary, fontSize: 11, fontFamily: MONO, flex: 1 }}>
            {node.source}
          </Text>
        </View>
      ) : null}

      {!fixed && (node.settings?.length ?? 0) > 0 ? (
        <View style={{ gap: 6 }}>
          <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("loopmap.governedBy")}</Text>
          {node.settings!.map((s) => (
            <KnobChip key={s} path={s} editable={editable.includes(s)} onOpen={onOpen} t={t} tr={tr} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

/**
 * THE LEFT NAVIGATION (design doc section 5.2), and why it is three primitives
 * rather than one list component: the groups hold DIFFERENT kinds of thing
 * (stations, Henry's blocks, the machine) and the only thing they share is the
 * row shape. A single component taking a discriminated union would have to know
 * what a station is, which is exactly the knowledge this screen does not keep -
 * every label and every order below comes off the payload.
 */
function NavGroup({ label, children, t }: {
  label: string; children: React.ReactNode; t: ThemeTokens;
}) {
  return (
    <View style={{ marginBottom: 14 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 10, fontWeight: "700", letterSpacing: 0.7,
        marginBottom: 5, paddingHorizontal: 2 }}>
        {label.toUpperCase()}
      </Text>
      <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
        borderRadius: 12, overflow: "hidden" }}>
        {children}
      </View>
    </View>
  );
}

function NavItem({ label, active, onPress, right, testID, t }: {
  label: string; active: boolean; onPress: () => void;
  right?: React.ReactNode; testID?: string; t: ThemeTokens;
}) {
  return (
    <Pressable testID={testID} onPress={onPress}
      style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 11,
        paddingVertical: 10, backgroundColor: active ? t.surface2 : "transparent" }}>
      {/* A left rail rather than a filled row: the active entry has to read as
          selected next to a detail pane, without turning the whole column into
          a block of colour on a phone where the column is full width. */}
      <View style={{ width: 2.5, height: 15, borderRadius: 2,
        backgroundColor: active ? t.accent : "transparent" }} />
      <Text numberOfLines={1} style={{ color: active ? t.txtPrimary : t.txtSecondary,
        fontSize: 12.5, fontWeight: active ? "700" : "500", flex: 1 }}>
        {label}
      </Text>
      {right}
    </Pressable>
  );
}

/** How many knobs sit behind an entry. DERIVED (from the schema / the rule
 *  list), never a number anybody maintains - the same discipline the pipeline's
 *  own knob badge already lives under. */
function NavCount({ n, t }: { n: number; t: ThemeTokens }) {
  if (!n) return null;
  return (
    <View style={{ minWidth: 17, alignItems: "center", borderRadius: 999, paddingHorizontal: 5,
      paddingVertical: 1, backgroundColor: t.surface2, borderWidth: 1, borderColor: t.borderSubtle }}>
      <Text style={{ color: t.txtTertiary, fontSize: 10, fontWeight: "700" }}>{n}</Text>
    </View>
  );
}

export default function LoopMapScreen() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  // Which repo the pipeline is drawn for. "" = the general machine, which is
  // what this screen has always shown - so the default is unchanged.
  const [repo, setRepo] = useState("");
  const { data, isLoading, error } = useQuery<LoopMap>({
    queryKey: ["loopmap", repo], queryFn: () => api.loopMap(repo), staleTime: 60000,
  });
  // The repo chips need the registry, not the map. Failing to load them must
  // not take the map down with it - the map is useful without them.
  const { data: reg } = useQuery<RepoTemplates>({
    queryKey: ["repoTemplates"], queryFn: api.repoTemplates, staleTime: 60000, retry: false,
  });
  const repos = reg?.repos ?? [];
  // The lane pipeline's selection. The build loop no longer shares it: tapping a
  // stage at the BOTTOM of the page used to mutate one detail card wedged under
  // the pipeline at the TOP, i.e. far off screen — so the explanation existed
  // and the owner never saw it fire. Loop stages now expand in place.
  const [lane, setLane] = useState<string>("");
  const [openState, setOpenState] = useState<string>("");
  const [showCharter, setShowCharter] = useState(false);
  // On a desktop window this page is almost all prose, and prose at 1280px is a
  // 200-character measure nobody reads. Same cap the automation hub uses.
  const { wide } = useResponsive();
  const qc = useQueryClient();

  // HENRY'S RULES, resolved for the repo the page is showing (harness-config-ui
  // phase 3). A second query rather than a fatter /loop/map: the stations and
  // their knobs already arrive there, and one route answering both would be one
  // route describing the machine twice. Failing to load must not take the map
  // down - the pipeline is useful without the rules, and `retry: false` keeps a
  // role without settings.read from re-asking on every mount.
  const { data: cfg } = useQuery<HarnessConfig>({
    queryKey: ["harnessConfig", repo], queryFn: () => api.harnessConfig(repo),
    staleTime: 30000, retry: false,
  });
  // The knobs a STATION owns, from the same schema the settings hub renders -
  // so a knob keeps its control, its save path and its badge when it changes
  // owner (design doc section 6: "landet bei" means MOVE, never duplicate).
  const schema = useSchema();

  const openHub = () => router.push("/automation" as never);
  const editable = data?.editable ?? [];
  const lanes = data?.runtime.lanes ?? [];
  // THE LEFT NAVIGATION (design doc section 5.2): stations in flow order, then
  // Henry's blocks, then the ground rules. The ORDER COMES FROM THE SERVER -
  // `runtime.stations` for the first half, `cfg.blocks` for the second - so the
  // client keeps no list of either. A sixth Henry block or a renamed station
  // costs a daemon edit and nothing here.
  const stations = data?.runtime.stations ?? [];
  const nodeFor = useMemo(() => (k: string): LoopNode | null => {
    if (!data) return null;
    if (k === "gate") return data.runtime.gate;
    if (k === "deploy") return data.runtime.deploy ?? null;
    return lanes.find((l) => l.key === k) ?? null;
  }, [data, lanes]);
  // How many knobs a station owns. DERIVED from the schema, never counted by
  // hand - the same derivation the pipeline's own badge already trusts.
  const knobsAt = useMemo(() => {
    const by: Record<string, number> = {};
    for (const it of schema) if (it.station) by[it.station] = (by[it.station] ?? 0) + 1;
    return by;
  }, [schema]);
  const blocks = cfg?.blocks ?? [];
  const nav = lane || (stations[0] ? "st:" + stations[0] : "laws");
  const setNav = (k: string) => setLane(k);
  // Tapping a station on the PIPELINE selects it in the navigation - the graph
  // IS the table of contents (section 5.2), which is why nothing else was
  // needed to wire it: `onSelect` has existed since the component shipped.
  const selectStation = (k: string) => setLane("st:" + k);
  const selectedStation = nav.startsWith("st:") ? nav.slice(3) : "";
  const selectedBlock = nav.startsWith("blk:") ? nav.slice(4) : "";
  // Deploy and the gate are steps-on-an-edge rather than lanes, so they resolve
  // through nodeFor like everything else - otherwise tapping the one station
  // the owner most wants explained (the only switchable one) selects nothing.
  const selected = selectedStation ? nodeFor(selectedStation) : null;
  const surfaceLabels = useMemo(() => {
    const by: Record<string, string> = {};
    for (const s of cfg?.surfaces ?? []) by[s.key] = s.label;
    return by;
  }, [cfg]);

  /** THE ONE WRITE PATH for a rule. A null value CLEARS it (restores
   *  inheritance); the daemon picks the layer from the rule's own scope, so
   *  this cannot ask for the wrong one. On failure the row is NOT optimistically
   *  moved - the refusal text is the daemon's own why-sentence, and showing a
   *  flipped switch next to it would be the screen lying about what happened. */
  async function setRule(path: string, value: unknown) {
    try {
      const res = await api.saveHarnessConfig(repo, { [path]: value });
      if (res?.error) throw new Error(res.error);
      await qc.invalidateQueries({ queryKey: ["harnessConfig"] });
      // The rules render INTO the briefs, so the harness section's char counts
      // and any open settings view move with them.
      await qc.invalidateQueries({ queryKey: ["loopmap"] });
    } catch (e) {
      Alert.alert(tr("harness.saveFailed"), String((e as Error).message));
    }
  }

  const build = data?.build;
  const states = build?.states ?? [];
  // which stages are actually adjustable — read off `kind`, so the section note
  // above the list states the real split instead of a remembered one
  const policyStates = states.filter((s) => s.kind === "policy");
  // OUTGOING edges per state — NOT states[i] -> states[i+1].
  // The list order is declaration order, which is not the transition order: in
  // card mode the real edges are EXECUTE->CLEAN, WIP->COMMIT, COMMIT->DONE,
  // so pairing neighbours drew three arrows the machine does not have (and, with
  // no matching edge, drew them with an empty condition). Rendering the edge
  // list itself is both honest and self-maintaining.
  const outFrom = (key: string) => (build?.edges ?? []).filter((e) => e.from === key);

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 8, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
        <View style={{ flex: 1 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 17, fontWeight: "700" }}>{tr("harness.page")}</Text>
          <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("harness.pageSub")}</Text>
        </View>
      </View>

      {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 40 }} /> :
       error || !data ? <Text style={{ color: t.danger, padding: 16 }}>{tr("health.unreachable")}</Text> : (
        <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 60, gap: 16,
          width: "100%", maxWidth: wide ? 860 : undefined, alignSelf: "center" }}>
          {/* ---- orientation + legend ----
              The screen shows three unrelated machines and two kinds of row.
              Saying so once, up front, is cheaper than the owner deducing it
              from a padlock glyph that never explained itself. */}
          <Text style={{ color: t.txtSecondary, fontSize: 12.5, lineHeight: 18 }}>{tr("loopmap.intro")}</Text>
          <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
            borderRadius: 14, padding: 12, gap: 10 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700", letterSpacing: 0.6 }}>
              {tr("loopmap.legend").toUpperCase()}
            </Text>
            {(["fixed", "policy"] as const).map((k) => (
              <View key={k} style={{ flexDirection: "row", alignItems: "flex-start", gap: 9 }}>
                <View style={{ paddingTop: 1 }}><KindBadge kind={k} t={t} tr={tr} small /></View>
                <Text style={{ color: t.txtSecondary, fontSize: 11.5, lineHeight: 16.5, flex: 1 }}>
                  {tr(k === "fixed" ? "loopmap.legendFixedHint" : "loopmap.legendPolicyHint")}
                </Text>
              </View>
            ))}
          </View>

          {/* ---- 1. lanes: where a CARD sits ---- */}
          <SectionHead title={tr("loopmap.secLanes")} hint={tr("loopmap.secLanesHint")} t={t} tr={tr} />
          <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 16, padding: 14, paddingTop: 20 }}>
            {/* WHICH REPO is this pipeline for? With no repo the map answers for
                the general machine; with one it answers for that repo's
                template - which stations run, and where the owner has since
                deviated. The chips are a FILTER, never an editor: the type is
                chosen on /repo, so this screen stays read-only. */}
            {repos.length ? (
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 14 }}>
                <Pressable testID="maprepo-all" onPress={() => setRepo("")}
                  style={{ backgroundColor: !repo ? t.accent : t.surface2, borderColor: t.glassBorder,
                    borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 }}>
                  <Text style={{ color: !repo ? t.canvas : t.txtSecondary, fontSize: 11, fontWeight: "700" }}>
                    {tr("loopmap.allRepos")}
                  </Text>
                </Pressable>
                {repos.map((r) => (
                  // testID by NAME: a Windows path's backslashes are CSS escape
                  // sequences in `[data-testid="..."]`, so a path-based id
                  // matched nothing and the shot driver silently photographed
                  // an unclicked screen.
                  <Pressable key={r.repo} testID={"maprepo-" + (r.project?.name || r.repo)}
                    onPress={() => setRepo(r.repo)}
                    style={{ backgroundColor: repo === r.repo ? t.accent : t.surface2,
                      borderColor: t.glassBorder, borderWidth: 1, borderRadius: 999,
                      paddingHorizontal: 10, paddingVertical: 5 }}>
                    <Text numberOfLines={1} style={{ color: repo === r.repo ? t.canvas : t.txtSecondary,
                      fontSize: 11, fontWeight: "700", maxWidth: 200 }}>
                      {r.project?.name || r.repo}
                    </Text>
                  </Pressable>
                ))}
              </View>
            ) : null}
            {/* The travelling FlowToken was dropped here, not forgotten: the
                stations now carry a label AND a note line, so the token's
                absolutely-positioned band no longer sits above a row of bare
                dots - it landed on top of the last station and read as a stray
                artifact. Judged from the screenshot; a decoration that collides
                with content loses. */}
            {/* ONE pipeline component, shared with repo onboarding (see
                ui/repo_pipeline.tsx). Station list, order and on/off all come
                from the daemon - the route is not described twice in this app. */}
            {/* showKnobs: this screen IS the harness view, so it gets the knob
                badges and the Henry track. Repo onboarding leaves them off -
                it shows the route to someone who has no repo set up yet and
                therefore no knobs to count. */}
            {/* The graph IS the table of contents (section 5.2): tapping a
                station selects it in the navigation below. `onSelect` has
                existed since the component shipped - this card only uses it. */}
            <RepoPipeline map={data} onSelect={selectStation} selected={selectedStation} hideHint showKnobs />
            <Text style={{ color: t.txtTertiary, fontSize: 11, marginTop: 14, textAlign: "center", lineHeight: 16 }}>
              {repo ? tr("loopmap.repoHint") : tr("loopmap.hint")}
            </Text>
          </View>

          {/* ================= NAVIGATION + DETAIL =================
              Stations in flow order, then Henry's blocks, then the ground
              rules - the GitHub-repo-settings / Stripe shape. Side by side on a
              wide window, stacked on a phone: the SAME entries and the same
              detail pane, not a second layout concept. */}
          <View style={{ flexDirection: wide ? "row" : "column", gap: 14, alignItems: "flex-start" }}>
            <View style={wide ? { width: 208 } : { width: "100%" }}>
              <NavGroup label={tr("harness.navStations")} t={t}>
                {stations.map((k) => {
                  const n = nodeFor(k);
                  const cnt = knobsAt[k] ?? 0;
                  return (
                    <NavItem key={k} testID={"nav-st-" + k} active={nav === "st:" + k}
                      label={n?.label ?? k} onPress={() => setNav("st:" + k)} t={t}
                      right={n?.kind === "fixed"
                        ? <Ionicons name="lock-closed" size={11} color={t.txtTertiary} />
                        : cnt ? <NavCount n={cnt} t={t} /> : null} />
                  );
                })}
              </NavGroup>
              {blocks.length ? (
                <NavGroup label={tr("harness.navHenry")} t={t}>
                  {blocks.map((b) => (
                    <NavItem key={b.key} testID={"nav-blk-" + b.key} active={nav === "blk:" + b.key}
                      label={tr(b.labelKey)} onPress={() => setNav("blk:" + b.key)} t={t}
                      right={<NavCount n={(cfg?.rules ?? []).filter((r) => r.block === b.key).length} t={t} />} />
                  ))}
                </NavGroup>
              ) : null}
              <NavGroup label={tr("harness.navMachine")} t={t}>
                <NavItem testID="nav-build" active={nav === "build"} label={tr("harness.navBuild")}
                  onPress={() => setNav("build")} t={t} />
                <NavItem testID="nav-briefs" active={nav === "briefs"} label={tr("harness.navBriefs")}
                  onPress={() => setNav("briefs")} t={t} />
                <NavItem testID="nav-laws" active={nav === "laws"} label={tr("harness.navLaws")}
                  onPress={() => setNav("laws")} t={t}
                  right={<Ionicons name="lock-closed" size={11} color={t.txtTertiary} />} />
              </NavGroup>
            </View>

            <View style={{ flex: wide ? 1 : undefined, width: wide ? undefined : "100%", gap: 14 }}>
              {/* ---- a STATION: what it is, why it is fixed, and its knobs ---- */}
              {selected ? (
                <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 14, padding: 14, gap: 10 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <Text style={{ color: t.txtPrimary, fontSize: 14.5, fontWeight: "700", flexShrink: 1 }}>
                      {selected.label ?? selected.key}
                    </Text>
                    <KindBadge kind={selected.kind} t={t} tr={tr} />
                  </View>
                  <NodeBody node={selected} editable={editable} onOpen={openHub} t={t} tr={tr} />
                </View>
              ) : null}
              {/* The knobs that MOVED here (section 6). Rendered by the hub's own
                  SchemaStation, so a knob keeps its control, its save path and
                  its badge when it changes owner - which is what makes "kein
                  Knopf verliert seine Editierbarkeit" a property of the data
                  rather than something this screen has to re-earn. */}
              {selectedStation ? (
                (knobsAt[selectedStation] ?? 0) > 0
                  ? <SchemaStation station={selectedStation} schema={schema} />
                  : (
                    <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16.5 }}>
                      {tr("harness.noKnobs")}
                    </Text>
                  )
              ) : null}

              {/* ---- one of HENRY's blocks ---- */}
              {selectedBlock && cfg ? (
                <>
                  {repo ? (
                    <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 16 }}>
                      {tr("harness.projectScope")}
                    </Text>
                  ) : null}
                  {blocks.filter((b) => b.key === selectedBlock).map((b) => (
                    <RuleBlock key={b.key} block={b} rules={cfg.rules} surfaces={surfaceLabels}
                      project={cfg.project} onSet={setRule} />
                  ))}
                </>
              ) : null}

          {/* Lane RENAMES are data on every lane whatever its kind, and nothing
              on this screen said so — the owner could stare at four lanes he is
              free to rename and see only padlocks and dots. Shown with the
              stations, since that is what it renames. */}
          {selectedStation && data.lane_labels_path && editable.includes(data.lane_labels_path) ? (
            <Pressable onPress={openHub}
              style={{ flexDirection: "row", alignItems: "center", gap: 9, backgroundColor: t.surface1,
                borderColor: t.accent, borderWidth: 1, borderRadius: 14, padding: 12 }}>
              <Ionicons name="create-outline" size={16} color={t.accent} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600" }}>{tr("loopmap.renameLanes")}</Text>
                <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontFamily: MONO, marginTop: 1 }}>
                  {data.lane_labels_path}
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
            </Pressable>
          ) : null}

          {/* ---- 2. build loop: how a CHANGE gets built ----
              Rendered from loop_state.machine(): the state list, which one is
              ACTIVE in this checkout, and the guard on each transition. Nothing
              here is described a second time in the app — a new state or a
              changed condition shows up by itself. */}
          {nav === "build" ? (<>
          <SectionHead title={tr("loopmap.secBuild")} hint={tr("loopmap.secBuildHint")} t={t} tr={tr}
            right={build?.mode ? (
              <View style={{ backgroundColor: t.surface2, borderColor: t.glassBorder, borderWidth: 1,
                borderRadius: 999, paddingHorizontal: 9, paddingVertical: 3 }}>
                <Text style={{ color: t.txtSecondary, fontSize: 10.5, fontWeight: "700" }}>
                  {tr(build.mode === "card" ? "loopmap.modeCard" : "loopmap.modeRepo")}
                </Text>
              </View>
            ) : undefined} />
          {build?.mode_note ? (
            <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16.5, marginTop: -10 }}>
              {build.mode_note}
            </Text>
          ) : null}

          {/* WHY IS NEARLY EVERY ROW BELOW LOCKED?
              Per-row reasons were not enough: the owner reads the SECTION, sees
              a column of padlocks, and concludes the screen is read-only before
              he taps anything. So the section answers it once, up front, and
              points at the screen that does hold the knobs.

              The counts are DERIVED from the payload, never written down. A
              hand-typed "all stages are fixed" would already be wrong today
              (COMMIT and WIP are policy nodes governed by SWARM_WIP_MINUTES)
              and would go wrong again the next time a state changes kind - and
              a screen whose job is to say what is fixed cannot afford to state
              that falsely. */}
          {states.length ? (
            <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
              borderRadius: 14, padding: 12, gap: 9 }}>
              <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 9 }}>
                <Ionicons name="information-circle-outline" size={16} color={t.txtTertiary}
                  style={{ marginTop: 1 }} />
                <Text style={{ color: t.txtSecondary, fontSize: 12, lineHeight: 17.5, flex: 1 }}>
                  {policyStates.length
                    ? tr("loopmap.buildFixedNote", {
                        fixed: states.length - policyStates.length, total: states.length,
                        policy: policyStates.map((s) => s.key).join(", "),
                      })
                    : tr("loopmap.buildAllFixedNote", { total: states.length })}
                </Text>
              </View>
              {/* the pointer the screen was missing: the knobs are real, they
                  are just not on this page */}
              <Pressable onPress={openHub}
                style={{ flexDirection: "row", alignItems: "center", gap: 9, backgroundColor: t.surface2,
                  borderColor: t.accent, borderWidth: 1, borderRadius: 10, paddingHorizontal: 10,
                  paddingVertical: 9 }}>
                <Ionicons name="options-outline" size={15} color={t.accent} />
                <View style={{ flex: 1 }}>
                  <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "600" }}>
                    {tr("loopmap.editElsewhere")}
                  </Text>
                  <Text style={{ color: t.txtTertiary, fontSize: 10.5, marginTop: 1 }}>
                    {tr("loopmap.editElsewhereWhere")}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={15} color={t.txtTertiary} />
              </Pressable>
            </View>
          ) : null}

          <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
            borderRadius: 14, overflow: "hidden" }}>
            {states.map((s, i) => {
              const active = !!s.active;
              const open = openState === s.key;
              const outs = outFrom(s.key);
              return (
                <View key={s.key} style={{ borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder }}>
                  {/* testID: the shot driver has to open these rows to judge
                      them, and matching on the visible text hits the EDGE label
                      of the state above first (an "-> COMMIT ..." line is text
                      too) - which clicks a non-pressable Text, expands nothing,
                      and reports no error. A screenshot of a row that silently
                      failed to open is worse than no screenshot. */}
                  <Pressable testID={"loopstate-" + s.key} onPress={() => setOpenState(open ? "" : s.key)}
                    style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12,
                      paddingVertical: 11, backgroundColor: active ? t.surface2 : "transparent" }}>
                    {/* a DOT, not an index. The list order is declaration order
                        and WIP is an overlay, so numbering it "4 of 5" asserted
                        a sequence the edge list flatly contradicts. */}
                    <View style={{ width: 9, height: 9, borderRadius: 5,
                      backgroundColor: active ? t.accent : "transparent",
                      borderWidth: active ? 0 : 1.5, borderColor: t.borderStrong }} />
                    <Text style={{ color: active ? t.txtPrimary : t.txtSecondary, fontSize: 12.5,
                      fontWeight: active ? "800" : "600", flex: 1 }}>
                      {s.key}
                    </Text>
                    {active ? (
                      <Text style={{ color: t.accent, fontSize: 10.5, fontWeight: "800" }}>{tr("loopmap.here")}</Text>
                    ) : null}
                    <KindBadge kind={s.kind} t={t} tr={tr} small />
                    <Ionicons name={open ? "chevron-up" : "chevron-down"} size={14} color={t.txtTertiary} />
                  </Pressable>

                  {/* the rule + the reason, IN PLACE under the row that was tapped */}
                  {open ? (
                    <View style={{ paddingHorizontal: 12, paddingBottom: 12, paddingTop: 2 }}>
                      <NodeBody node={s} editable={editable} onOpen={openHub} t={t} tr={tr} />
                    </View>
                  ) : null}

                  {/* every real transition OUT of this state, each naming its
                      target and the guard the code actually tests */}
                  {outs.map((e) => (
                    <View key={e.to} style={{ flexDirection: "row", alignItems: "flex-start", gap: 6,
                      paddingLeft: 20, paddingRight: 12, paddingBottom: 8 }}>
                      <Ionicons name="arrow-forward" size={11} color={t.txtTertiary} style={{ marginTop: 2 }} />
                      <Text style={{ color: t.txtSecondary, fontSize: 10.5, fontWeight: "700", lineHeight: 15 }}>
                        {e.to}
                      </Text>
                      {e.when ? (
                        <Text style={{ color: t.txtTertiary, fontSize: 10.5, lineHeight: 15, flex: 1 }}>
                          {e.when}
                        </Text>
                      ) : null}
                    </View>
                  ))}
                </View>
              );
            })}
          </View>
          </>) : null}

          {/* ---- 3. the agent briefs: what an AGENT is started with ----
              Exported by harness.describe(). Without this a broken agent file is
              INVISIBLE: harness.py falls back to its built-in default rather than
              breaking a spawn, so nothing else would say an edit is being ignored. */}
          {nav === "briefs" && data.harness ? (
            <>
              <SectionHead title={tr("loopmap.harness")} hint={tr("loopmap.secHarnessHint")}
                kind="policy" t={t} tr={tr} />
              <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
                borderRadius: 14, overflow: "hidden" }}>
                {data.harness.agents.map((a, i) => (
                  <View key={a.name} style={{ paddingHorizontal: 12, paddingVertical: 10,
                    borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder, gap: 2 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "700", flex: 1 }}>{a.name}</Text>
                      <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>
                        {tr("loopmap.chars", { n: a.chars })}
                      </Text>
                    </View>
                    <Text selectable style={{ color: t.txtSecondary, fontSize: 11, fontFamily: MONO }}>{a.source}</Text>
                    <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontFamily: MONO }}>
                      --setting-sources {a.setting_sources === "" ? '""' : (a.setting_sources ?? tr("harness.sourcesOff"))}
                      {a.settings ? "  --settings " + a.settings : ""}
                    </Text>
                  </View>
                ))}
                {Object.entries(data.harness.errors ?? {}).map(([p, m]) => (
                  <View key={p} style={{ paddingHorizontal: 12, paddingVertical: 9, borderTopWidth: 1,
                    borderTopColor: t.glassBorder, flexDirection: "row", gap: 7 }}>
                    <Ionicons name="alert-circle" size={14} color={t.danger} style={{ marginTop: 1 }} />
                    <Text style={{ color: t.danger, fontSize: 11, flex: 1 }}>{p}: {m}</Text>
                  </View>
                ))}
              </View>
              <Pressable onPress={openHub}
                style={{ flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: t.surface1,
                  borderColor: t.accent, borderWidth: 1, borderRadius: 14, padding: 13 }}>
                <Ionicons name="construct-outline" size={16} color={t.accent} />
                <Text style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "600", flex: 1 }}>
                  {tr("loopmap.editHarness")}
                </Text>
                <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
              </Pressable>
            </>
          ) : null}

          {/* ---- 4. harness laws ---- */}
          {nav === "laws" ? (<>
          <SectionHead title={tr("loopmap.laws")} hint={tr("loopmap.lawsHint")} kind="fixed" t={t} tr={tr} />
          <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 14, overflow: "hidden" }}>
            {data.laws.map((law, i) => (
              <View key={law.key} style={{ flexDirection: "row", alignItems: "flex-start", gap: 10, padding: 12,
                borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder }}>
                {/* neutral, not danger-red: a law being in force is the healthy
                    state, not an error condition */}
                <Ionicons name="lock-closed" size={14} color={t.txtTertiary} style={{ marginTop: 2 }} />
                <View style={{ flex: 1 }}>
                  <Text style={{ color: t.txtSecondary, fontSize: 12.5, lineHeight: 18 }}>{law.text}</Text>
                  {/* the module that ENFORCES it — a law you cannot trace to code
                      is only a promise on a screen */}
                  {law.source ? (
                    <Text selectable style={{ color: t.txtTertiary, fontSize: 10.5, fontFamily: MONO, marginTop: 2 }}>
                      {law.source}
                    </Text>
                  ) : null}
                </View>
              </View>
            ))}
          </View>

          {/* ---- charter (the code-level rulebook) ---- */}
          <Pressable onPress={() => setShowCharter((v) => !v)}
            style={{ flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: t.surface1,
              borderColor: t.glassBorder, borderWidth: 1, borderRadius: 14, padding: 13 }}>
            <Ionicons name="document-text-outline" size={16} color={t.txtSecondary} />
            <Text style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "600", flex: 1 }}>{tr("loopmap.charter")}</Text>
            <Ionicons name={showCharter ? "chevron-up" : "chevron-down"} size={16} color={t.txtTertiary} />
          </Pressable>
          {showCharter ? (
            <View style={{ backgroundColor: t.canvas, borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 12, padding: 12 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 17 }}>{data.charter}</Text>
            </View>
          ) : null}
          </>) : null}
            </View>
          </View>
        </ScrollView>
      )}
    </View>
  );
}
