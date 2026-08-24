import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Animated as RNAnimated, Easing, Platform, Pressable, ScrollView, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type LoopMap, type LoopNode } from "@/data/client";
import { useT } from "@/i18n";
import { laneColor, useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";

const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }) as string;

type Tr = (k: string, p?: Record<string, string | number>) => string;

// A glowing token that travels the lane pipeline, left to right, forever.
// RN core Animated (not reanimated worklets) so it stays React-Compiler safe.
function FlowToken({ width, color }: { width: number; color: string }) {
  const x = useRef(new RNAnimated.Value(0)).current;
  useEffect(() => {
    if (width <= 0) return;
    const anim = RNAnimated.loop(
      RNAnimated.timing(x, { toValue: 1, duration: 3200, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
    );
    anim.start();
    return () => anim.stop();
  }, [width, x]);
  const tx = x.interpolate({ inputRange: [0, 1], outputRange: [0, Math.max(0, width - 14)] });
  const op = x.interpolate({ inputRange: [0, 0.5, 1], outputRange: [0.15, 1, 0.15] });
  return (
    <RNAnimated.View pointerEvents="none" style={{ position: "absolute", top: -3, left: 0, transform: [{ translateX: tx }], opacity: op }}>
      <View style={{ width: 14, height: 14, borderRadius: 7, backgroundColor: color,
        shadowColor: color, shadowOpacity: 0.9, shadowRadius: 8, elevation: 6 }} />
    </RNAnimated.View>
  );
}

// The gate: a shield whose ring pulses, signalling "checked here".
function GatePulse({ color, active, onPress }: { color: string; active: boolean; onPress: () => void }) {
  const p = useRef(new RNAnimated.Value(0)).current;
  useEffect(() => {
    const anim = RNAnimated.loop(RNAnimated.timing(p, { toValue: 1, duration: 1600, easing: Easing.out(Easing.quad), useNativeDriver: true }));
    anim.start();
    return () => anim.stop();
  }, [p]);
  const scale = p.interpolate({ inputRange: [0, 1], outputRange: [0.7, 1.9] });
  const op = p.interpolate({ inputRange: [0, 1], outputRange: [0.55, 0] });
  return (
    <Pressable onPress={onPress} hitSlop={10} style={{ alignItems: "center", justifyContent: "center", width: 46 }}>
      <RNAnimated.View style={{ position: "absolute", width: 34, height: 34, borderRadius: 17,
        borderWidth: 2, borderColor: color, transform: [{ scale }], opacity: op }} />
      <View style={{ width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center",
        backgroundColor: active ? color : "transparent", borderWidth: 1.5, borderColor: color }}>
        <Ionicons name="shield-checkmark" size={18} color={active ? "#fff" : color} />
      </View>
    </Pressable>
  );
}

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

export default function LoopMapScreen() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { data, isLoading, error } = useQuery<LoopMap>({ queryKey: ["loopmap"], queryFn: api.loopMap, staleTime: 60000 });
  // The lane pipeline's selection. The build loop no longer shares it: tapping a
  // stage at the BOTTOM of the page used to mutate one detail card wedged under
  // the pipeline at the TOP, i.e. far off screen — so the explanation existed
  // and the owner never saw it fire. Loop stages now expand in place.
  const [lane, setLane] = useState<string>("");
  const [openState, setOpenState] = useState<string>("");
  const [trackW, setTrackW] = useState(0);
  const [showCharter, setShowCharter] = useState(false);
  // On a desktop window this page is almost all prose, and prose at 1280px is a
  // 200-character measure nobody reads. Same cap the automation hub uses.
  const { width } = useWindowDimensions();
  const wide = Platform.OS === "web" && width >= 900;

  const openHub = () => router.push("/automation" as never);
  const editable = data?.editable ?? [];
  const lanes = data?.runtime.lanes ?? [];
  // gate sits after "working"
  const gateAfter = data?.runtime.gate.between?.[0] ?? "working";
  // default selection = the gate: the one node on the pipeline that is neither
  // a lane nor optional, so the card below the track is never empty.
  const selected = useMemo<LoopNode | null>(() => {
    if (!data) return null;
    if (lane && lane !== "gate") return lanes.find((l) => l.key === lane) ?? null;
    return data.runtime.gate;
  }, [data, lane, lanes]);

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
        <Text style={{ color: t.txtPrimary, fontSize: 17, fontWeight: "700", flex: 1 }}>{tr("loopmap.title")}</Text>
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
            <View onLayout={(e) => setTrackW(e.nativeEvent.layout.width)} style={{ position: "relative" }}>
              <FlowToken width={trackW} color={t.accent} />
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                {lanes.map((l, i) => {
                  const on = selected?.key === l.key;
                  return (
                    <View key={l.key} style={{ flexDirection: "row", alignItems: "center", flex: 1 }}>
                      <Pressable testID={"lane-" + l.key} onPress={() => setLane(l.key)}
                        style={{ alignItems: "center", gap: 6, flex: 1 }}>
                        {/* the SELECTED lane is filled, so the card below is
                            visibly the answer to the last tap rather than a
                            standalone paragraph that silently swapped content */}
                        <View style={{ width: 30, height: 30, borderRadius: 15, alignItems: "center", justifyContent: "center",
                          backgroundColor: on ? laneColor(t, l.key) : t.surface2, borderWidth: 2, borderColor: laneColor(t, l.key) }}>
                          <View style={{ width: 11, height: 11, borderRadius: 6,
                            backgroundColor: on ? t.canvas : laneColor(t, l.key) }} />
                        </View>
                        <Text numberOfLines={1} style={{ color: on ? t.txtPrimary : t.txtSecondary,
                          fontSize: 11, fontWeight: on ? "800" : "600" }}>{l.label}</Text>
                      </Pressable>
                      {i < lanes.length - 1 ? (
                        l.key === gateAfter ? (
                          <GatePulse color={t.accent2} active={selected?.key === "gate"}
                            onPress={() => setLane("gate")} />
                        ) : (
                          <View style={{ width: 26, height: 2, backgroundColor: t.borderStrong }} />
                        )
                      ) : null}
                    </View>
                  );
                })}
              </View>
            </View>
            <Text style={{ color: t.txtTertiary, fontSize: 11, marginTop: 14, textAlign: "center", lineHeight: 16 }}>
              {tr("loopmap.hint")}
            </Text>
          </View>

          {/* the selected lane/gate, directly under the track it belongs to */}
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

          {/* Lane RENAMES are data on every lane whatever its kind, and nothing
              on this screen said so — the owner could stare at four lanes he is
              free to rename and see only padlocks and dots. */}
          {data.lane_labels_path && editable.includes(data.lane_labels_path) ? (
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

          {/* ---- 3. the agent briefs: what an AGENT is started with ----
              Exported by harness.describe(). Without this a broken agent file is
              INVISIBLE: harness.py falls back to its built-in default rather than
              breaking a spawn, so nothing else would say an edit is being ignored. */}
          {data.harness ? (
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
        </ScrollView>
      )}
    </View>
  );
}
