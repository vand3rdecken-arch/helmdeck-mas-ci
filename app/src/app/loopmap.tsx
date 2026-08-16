import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Animated as RNAnimated, Easing, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type LoopMap } from "@/data/client";
import { useT } from "@/i18n";
import { laneColor, useTheme } from "@/theme";

const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }) as string;

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

function KindBadge({ kind, t }: { kind?: string; t: ReturnType<typeof useTheme> }) {
  const tr = useT();
  if (!kind) return null;
  const fixed = kind === "fixed";
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: t.surface2,
      borderColor: fixed ? t.danger : t.ok, borderWidth: 1, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 }}>
      <Ionicons name={fixed ? "lock-closed" : "options-outline"} size={11} color={fixed ? t.danger : t.ok} />
      <Text style={{ color: fixed ? t.danger : t.ok, fontSize: 10.5, fontWeight: "700" }}>{fixed ? tr("loopmap.kindFixed") : tr("loopmap.kindPolicy")}</Text>
    </View>
  );
}

type Detail = {
  title: string; kind?: string; body: string;
  /** "tools/loop_state.py:472" for a fixed node — the code it IS. */
  source?: string;
  /** dotted settings paths for a policy node — the knobs that govern it. */
  settings?: string[];
};

export default function LoopMapScreen() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { data, isLoading, error } = useQuery<LoopMap>({ queryKey: ["loopmap"], queryFn: api.loopMap, staleTime: 60000 });
  const [sel, setSel] = useState<Detail | null>(null);
  const [trackW, setTrackW] = useState(0);
  const [showCharter, setShowCharter] = useState(false);

  const pick = (label: string, node: { kind?: string; instruction: string; source?: string; settings?: string[] }) =>
    setSel({ title: label, kind: node.kind, body: node.instruction, source: node.source, settings: node.settings });

  const lanes = data?.runtime.lanes ?? [];
  // gate sits after "working"
  const gateAfter = data?.runtime.gate.between?.[0] ?? "working";
  const detail = useMemo<Detail | null>(() => sel ?? (data ? {
    title: data.runtime.gate.label ?? "Gate", kind: data.runtime.gate.kind,
    body: data.runtime.gate.instruction, source: data.runtime.gate.source,
    settings: data.runtime.gate.settings,
  } : null), [sel, data]);

  // The build loop, straight off the export. `active` says where THIS checkout
  // sits; `edges` carry the condition the code actually tests, so the arrow
  // between two states can state its own guard instead of being decorative.
  const build = data?.build;
  const states = build?.states ?? [];
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
        <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 60, gap: 18 }}>
          {/* ---- runtime lane flow ---- */}
          <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700" }}>{data.runtime.title}</Text>
          <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 16, padding: 14, paddingTop: 20 }}>
            <View onLayout={(e) => setTrackW(e.nativeEvent.layout.width)} style={{ position: "relative" }}>
              <FlowToken width={trackW} color={t.accent} />
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                {lanes.map((l, i) => (
                  <View key={l.key} style={{ flexDirection: "row", alignItems: "center", flex: 1 }}>
                    <Pressable onPress={() => pick(l.label ?? l.key, l)} style={{ alignItems: "center", gap: 6, flex: 1 }}>
                      <View style={{ width: 30, height: 30, borderRadius: 15, alignItems: "center", justifyContent: "center",
                        backgroundColor: t.surface2, borderWidth: 2, borderColor: laneColor(t, l.key) }}>
                        <View style={{ width: 11, height: 11, borderRadius: 6, backgroundColor: laneColor(t, l.key) }} />
                      </View>
                      <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 11, fontWeight: "600" }}>{l.label}</Text>
                    </Pressable>
                    {i < lanes.length - 1 ? (
                      l.key === gateAfter ? (
                        <GatePulse color={t.accent2} active={detail?.title === data.runtime.gate.label}
                          onPress={() => pick(data.runtime.gate.label ?? "Gate", data.runtime.gate)} />
                      ) : (
                        <View style={{ width: 26, height: 2, backgroundColor: t.borderStrong }} />
                      )
                    ) : null}
                  </View>
                ))}
              </View>
            </View>
            <Text style={{ color: t.txtTertiary, fontSize: 11, marginTop: 14, textAlign: "center" }}>
              {tr("loopmap.hint")}
            </Text>
          </View>

          {/* ---- detail card (what's behind the selected node) ---- */}
          {detail ? (
            <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 14, padding: 14, gap: 8 }}>
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <Text style={{ color: t.txtPrimary, fontSize: 14.5, fontWeight: "700", flexShrink: 1 }}>{detail.title}</Text>
                <KindBadge kind={detail.kind} t={t} />
              </View>
              <Text style={{ color: t.txtSecondary, fontSize: 13, lineHeight: 19 }}>{detail.body}</Text>

              {/* STRUCTURE IS CODE, PARAMETERS ARE DATA — shown, not asserted.
                  A fixed node cites the source line it IS; a policy node offers
                  the knob that governs it. The boundary itself is enforced by
                  the daemon (kind comes from the export, and /harness validates
                  every write) — this is the readable face of it, not the rule. */}
              {detail.kind === "fixed" && detail.source ? (
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Ionicons name="lock-closed" size={12} color={t.txtTertiary} />
                  <Text selectable style={{ color: t.txtTertiary, fontSize: 11.5, fontFamily: MONO }}>
                    {detail.source}
                  </Text>
                </View>
              ) : null}
              {detail.kind === "policy" && (detail.settings?.length ?? 0) > 0 ? (
                <View style={{ gap: 6 }}>
                  <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("loopmap.governedBy")}</Text>
                  {detail.settings!.map((s) => (
                    <Pressable key={s} onPress={() => router.push("/automation" as never)}
                      style={{ flexDirection: "row", alignItems: "center", gap: 7, backgroundColor: t.surface2,
                        borderColor: t.ok, borderWidth: 1, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8 }}>
                      <Ionicons name="options-outline" size={13} color={t.ok} />
                      <Text style={{ color: t.txtPrimary, fontSize: 11.5, fontFamily: MONO, flex: 1 }}>{s}</Text>
                      <Ionicons name="chevron-forward" size={13} color={t.txtTertiary} />
                    </Pressable>
                  ))}
                </View>
              ) : null}
            </View>
          ) : null}

          {/* ---- build loop states ----
              Rendered from loop_state.machine(): the state list, which one is
              ACTIVE in this checkout, and the guard on each transition. Nothing
              here is described a second time in the app — a new state or a
              changed condition shows up by itself. */}
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 }}>
            <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700", flex: 1 }}>{data.build.title}</Text>
            {build?.mode ? (
              <View style={{ backgroundColor: t.surface2, borderColor: t.glassBorder, borderWidth: 1,
                borderRadius: 999, paddingHorizontal: 9, paddingVertical: 3 }}>
                <Text style={{ color: t.txtSecondary, fontSize: 10.5, fontWeight: "700" }}>
                  {tr(build.mode === "card" ? "loopmap.modeCard" : "loopmap.modeRepo")}
                </Text>
              </View>
            ) : null}
          </View>
          {build?.mode_note ? (
            <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16, marginTop: -10 }}>
              {build.mode_note}
            </Text>
          ) : null}
          <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
            borderRadius: 14, overflow: "hidden" }}>
            {states.map((s, i) => {
              const active = !!s.active;
              const outs = outFrom(s.key);
              return (
                <View key={s.key}>
                  <Pressable onPress={() => pick(s.key, s)}
                    style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12,
                      paddingVertical: 11, backgroundColor: active ? t.surface2 : "transparent" }}>
                    <View style={{ width: 22, height: 22, borderRadius: 11, alignItems: "center",
                      justifyContent: "center", backgroundColor: active ? t.accent : "transparent",
                      borderWidth: active ? 0 : 1.5, borderColor: t.borderStrong }}>
                      <Text style={{ color: active ? "#fff" : t.txtTertiary, fontSize: 10.5, fontWeight: "800" }}>
                        {i + 1}
                      </Text>
                    </View>
                    <Text style={{ color: active ? t.txtPrimary : t.txtSecondary, fontSize: 12.5,
                      fontWeight: active ? "800" : "600", flex: 1 }}>
                      {s.key}
                    </Text>
                    {active ? (
                      <Text style={{ color: t.accent, fontSize: 10.5, fontWeight: "800" }}>{tr("loopmap.here")}</Text>
                    ) : null}
                    <Ionicons name={s.kind === "policy" ? "options-outline" : "lock-closed"} size={12}
                      color={s.kind === "policy" ? t.ok : t.txtTertiary} />
                  </Pressable>
                  {/* every real transition OUT of this state, each naming its
                      target and the guard the code actually tests */}
                  {outs.map((e) => (
                    <View key={e.to} style={{ flexDirection: "row", alignItems: "flex-start", gap: 6,
                      paddingLeft: 22, paddingRight: 12, paddingBottom: 6 }}>
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

          {/* ---- the harness surfaces: which brief each agent actually got ----
              Exported by harness.describe(). Without this a broken agent file is
              INVISIBLE: harness.py falls back to its built-in default rather than
              breaking a spawn, so nothing else would say an edit is being ignored. */}
          {data.harness ? (
            <>
              <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700", marginTop: 4 }}>
                {tr("loopmap.harness")}
              </Text>
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
              <Pressable onPress={() => router.push("/automation" as never)}
                style={{ flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: t.surface1,
                  borderColor: t.glassBorder, borderWidth: 1, borderRadius: 14, padding: 13 }}>
                <Ionicons name="construct-outline" size={16} color={t.accent} />
                <Text style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "600", flex: 1 }}>
                  {tr("loopmap.editHarness")}
                </Text>
                <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
              </Pressable>
            </>
          ) : null}

          {/* ---- harness laws ---- */}
          <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700", marginTop: 4 }}>{tr("loopmap.laws")}</Text>
          <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 14, overflow: "hidden" }}>
            {data.laws.map((law, i) => (
              <View key={law.key} style={{ flexDirection: "row", alignItems: "flex-start", gap: 10, padding: 12,
                borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder }}>
                <Ionicons name="lock-closed" size={15} color={t.danger} style={{ marginTop: 1 }} />
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
              <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 17, fontFamily: undefined }}>{data.charter}</Text>
            </View>
          ) : null}
        </ScrollView>
      )}
    </View>
  );
}
