import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Animated as RNAnimated, Easing, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type LoopMap, type LoopNode } from "@/data/client";
import { laneColor, useTheme } from "@/theme";

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
  if (!kind) return null;
  const fixed = kind === "fixed";
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: t.surface2,
      borderColor: fixed ? t.danger : t.ok, borderWidth: 1, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 }}>
      <Ionicons name={fixed ? "lock-closed" : "options-outline"} size={11} color={fixed ? t.danger : t.ok} />
      <Text style={{ color: fixed ? t.danger : t.ok, fontSize: 10.5, fontWeight: "700" }}>{fixed ? "FIX (Harness)" : "POLICY (justierbar)"}</Text>
    </View>
  );
}

export default function LoopMapScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { data, isLoading, error } = useQuery<LoopMap>({ queryKey: ["loopmap"], queryFn: api.loopMap, staleTime: 60000 });
  const [sel, setSel] = useState<{ title: string; kind?: string; body: string } | null>(null);
  const [trackW, setTrackW] = useState(0);
  const [showCharter, setShowCharter] = useState(false);

  const pick = (label: string, node: { kind?: string; instruction: string }) =>
    setSel({ title: label, kind: node.kind, body: node.instruction });

  const lanes = data?.runtime.lanes ?? [];
  // gate sits after "working"
  const gateAfter = data?.runtime.gate.between?.[0] ?? "working";
  const detail = useMemo(() => sel ?? (data ? { title: data.runtime.gate.label, kind: data.runtime.gate.kind, body: data.runtime.gate.instruction } : null), [sel, data]);

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 8, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
        <Text style={{ color: t.txtPrimary, fontSize: 17, fontWeight: "700", flex: 1 }}>Loop &amp; Harness</Text>
      </View>

      {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 40 }} /> :
       error || !data ? <Text style={{ color: t.danger, padding: 16 }}>Desktop nicht erreichbar.</Text> : (
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
              Tippe einen Schritt oder das Schild, um die Regel dahinter zu sehen.
            </Text>
          </View>

          {/* ---- detail card (what's behind the selected node) ---- */}
          {detail ? (
            <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 14, padding: 14, gap: 8 }}>
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                <Text style={{ color: t.txtPrimary, fontSize: 14.5, fontWeight: "700" }}>{detail.title}</Text>
                <KindBadge kind={detail.kind} t={t} />
              </View>
              <Text style={{ color: t.txtSecondary, fontSize: 13, lineHeight: 19 }}>{detail.body}</Text>
            </View>
          ) : null}

          {/* ---- build loop states ---- */}
          <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700", marginTop: 4 }}>{data.build.title}</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {data.build.states.map((s, i) => (
              <Pressable key={s.key} onPress={() => pick(s.key, { instruction: s.instruction })}
                style={{ flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: t.surface1,
                  borderColor: t.glassBorder, borderWidth: 1, borderRadius: 999, paddingHorizontal: 11, paddingVertical: 7 }}>
                <Text style={{ color: t.accent, fontSize: 11, fontWeight: "800" }}>{i + 1}</Text>
                <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{s.key}</Text>
                {i < data.build.states.length - 1 ? <Ionicons name="chevron-forward" size={12} color={t.txtTertiary} /> : null}
              </Pressable>
            ))}
          </View>

          {/* ---- harness laws ---- */}
          <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700", marginTop: 4 }}>Harness-Gesetze (fix)</Text>
          <View style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 14, overflow: "hidden" }}>
            {data.laws.map((law, i) => (
              <View key={law.key} style={{ flexDirection: "row", alignItems: "center", gap: 10, padding: 12,
                borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder }}>
                <Ionicons name="lock-closed" size={15} color={t.danger} />
                <Text style={{ color: t.txtSecondary, fontSize: 12.5, flex: 1 }}>{law.text}</Text>
              </View>
            ))}
          </View>

          {/* ---- charter (the code-level rulebook) ---- */}
          <Pressable onPress={() => setShowCharter((v) => !v)}
            style={{ flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: t.surface1,
              borderColor: t.glassBorder, borderWidth: 1, borderRadius: 14, padding: 13 }}>
            <Ionicons name="document-text-outline" size={16} color={t.txtSecondary} />
            <Text style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "600", flex: 1 }}>Capability-Charter (Code, read-only)</Text>
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
