import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Animated, Platform, Pressable, ScrollView, StyleSheet,
  Text, TextInput, useWindowDimensions, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { t as i18nT, useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { useAiFlat } from "@/ui/billing";
import { Chip, Dot, Empty, Panel, ScreenHeader } from "@/ui/kit";

const isWeb = Platform.OS === "web";

// Executor modes the daemon understands (daemon/processes.py MODES).
const MODES = ["do", "prepare", "cowork", "teach", "human"] as const;
const MODE_LABEL: Record<string, string> = {
  do: "do", prepare: "prepare", cowork: "cowork", teach: "teach", human: "human",
};
// Mode -> Ionicon shown inside the pipeline node (mirrors procs.tsx MODE_ICONS).
const MODE_ICON: Record<string, keyof typeof Ionicons.glyphMap> = {
  do: "flash", prepare: "construct", cowork: "people", teach: "school", human: "person",
};

// Step lifecycle -> [colour token key, label]; mirrors procs.tsx STATE_STYLE.
function stateStyle(t: ThemeTokens, state?: string): [string, string] {
  switch (state) {
    case "done": return [t.ok, i18nT("processes.stateDone")];
    case "working": return [t.ai, i18nT("processes.stateWorking")];
    case "ready": return [t.warn, i18nT("processes.stateReady")];
    case "waiting": return [t.txtTertiary, i18nT("processes.stateWaiting")];
    default: return [t.txtTertiary, i18nT("processes.stateProposed")];
  }
}

interface Step {
  title: string; desc?: string; mode?: string; due?: string;
  state?: string; track?: string; lane?: string; done?: boolean;
}
interface Process {
  id: string; request: string; status: string; client?: string;
  due?: string; cost?: number; error?: string; steps?: Step[];
}

function glass(t: ThemeTokens) {
  return isWeb
    ? ({ backgroundColor: t.glass, backdropFilter: "blur(16px) saturate(1.3)", WebkitBackdropFilter: "blur(16px) saturate(1.3)" } as any)
    : { backgroundColor: t.surface1 };
}

function ModeSelect({ value, onChange }: { value?: string; onChange: (m: string) => void }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
      {MODES.map((m) => {
        const on = (value ?? "do") === m;
        return (
          <Pressable key={m} onPress={() => onChange(m)}
            style={{ borderWidth: 1, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3,
              backgroundColor: on ? t.accent + "29" : t.surface2,
              borderColor: on ? t.accent + "80" : t.borderSubtle }}>
            <Text style={{ color: on ? t.accent : t.txtSecondary, fontSize: 11, fontWeight: "500" }}>{MODE_LABEL[m]}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// One editable step row: title, mode, due, and accept/remove (or a "card" chip
// once accepted). Every mutation hits POST /processes/{id}/step.
function StepRow({ pid, idx, step, act }: {
  pid: string; idx: number; step: Step;
  act: (idx: number, action: string, patch?: Record<string, unknown>, title?: string) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const [title, setTitle] = useState(step.title);
  const [due, setDue] = useState(step.due ?? "");
  const [colour, label] = stateStyle(t, step.state);

  return (
    <View style={[s.step, { borderColor: t.borderSubtle }]}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Text style={{ color: t.txtTertiary, width: 18, textAlign: "right", fontSize: 12 }}>{idx + 1}.</Text>
        <TextInput
          value={title}
          onChangeText={setTitle}
          onBlur={() => title !== step.title && act(idx, "update", { title })}
          onSubmitEditing={() => title !== step.title && act(idx, "update", { title })}
          placeholder={tr("processes.stepTitlePlaceholder")}
          placeholderTextColor={t.txtPlaceholder}
          style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, flex: 1 }]}
        />
        <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Dot color={colour} />
          <Text style={{ color: colour, fontSize: 10, fontWeight: "600" }}>{label}</Text>
        </View>
      </View>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingLeft: 26, flexWrap: "wrap" }}>
        <ModeSelect value={step.mode} onChange={(m) => act(idx, "update", { mode: m })} />
        <TextInput
          value={due}
          onChangeText={setDue}
          onBlur={() => due !== (step.due ?? "") && act(idx, "update", { due })}
          onSubmitEditing={() => due !== (step.due ?? "") && act(idx, "update", { due })}
          placeholder={tr("processes.duePlaceholder")}
          placeholderTextColor={t.txtPlaceholder}
          style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, width: 140 }]}
        />
        {step.track ? (
          <Chip text={tr("processes.cardChip")} dot={t.ok} />
        ) : (
          <>
            <Pressable onPress={() => act(idx, "accept")}
              style={[s.btn, { backgroundColor: t.accent + "29", borderColor: t.accent + "80" }]}>
              <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>{tr("processes.acceptCard")}</Text>
            </Pressable>
            <Pressable onPress={() => act(idx, "remove")}
              style={[s.btn, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
              <Text style={{ color: t.danger, fontSize: 11, fontWeight: "600" }}>✕</Text>
            </Pressable>
          </>
        )}
      </View>
      {step.desc ? <Text style={{ color: t.txtTertiary, fontSize: 11.5, paddingLeft: 26 }}>{step.desc}</Text> : null}
    </View>
  );
}

// One pipeline node: a coloured circle (checkmark when done, else a mode icon),
// the step title, and its state label. "ready" pulses amber; "proposed" is dashed.
function PipeNode({ step }: { step: Step }) {
  const t = useTheme();
  const tr = useT();
  const state = step.state ?? "proposed";
  const [colour] = stateStyle(t, state);
  const label = state === "proposed" ? tr("processes.stateProposed")
    : step.lane === "review" ? tr("processes.inReview") : stateStyle(t, state)[1];
  const done = step.done || state === "done";
  const proposed = state === "proposed";

  // Subtle pulse on the step the chain is waiting on (up next / waiting-for-human).
  const pulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (state !== "ready") return;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 800, useNativeDriver: !isWeb }),
        Animated.timing(pulse, { toValue: 0, duration: 800, useNativeDriver: !isWeb }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [state, pulse]);
  const opacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 0.45] });

  return (
    <View style={{ width: 96, alignItems: "center" }}>
      <Animated.View style={{
        width: 42, height: 42, borderRadius: 21, alignItems: "center", justifyContent: "center",
        borderWidth: 2.5, borderStyle: proposed ? "dashed" : "solid",
        borderColor: proposed ? t.borderStrong : colour,
        backgroundColor: colour + "2E",
        opacity: state === "ready" ? opacity : 1,
      }}>
        <Ionicons name={done ? "checkmark" : (MODE_ICON[step.mode ?? "do"] ?? "ellipse")}
          size={18} color={proposed ? t.borderStrong : colour} />
      </Animated.View>
      <Text numberOfLines={2} style={{ fontSize: 10.5, lineHeight: 13, marginTop: 4, textAlign: "center", color: t.txtSecondary }}>
        {step.title}
      </Text>
      <Text style={{ fontSize: 9.5, fontWeight: "600", color: proposed ? t.txtTertiary : colour }}>{label}</Text>
    </View>
  );
}

// Horizontal n8n-style read of the chain: one node per step joined by connector
// arrows. Scrolls sideways when it overflows.
function Pipeline({ p }: { p: Process }) {
  const t = useTheme();
  const steps = p.steps ?? [];
  if (steps.length === 0) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={{ alignItems: "flex-start", paddingVertical: 8, paddingHorizontal: 2 }}>
      {steps.map((st, i) => (
        <View key={i} style={{ flexDirection: "row", alignItems: "flex-start" }}>
          <PipeNode step={st} />
          {i < steps.length - 1 ? (
            <View style={{ width: 22, height: 42, alignItems: "center", justifyContent: "center" }}>
              <Ionicons name="chevron-forward" size={14}
                color={(st.done || st.state === "done") ? t.ok : t.borderStrong} />
            </View>
          ) : null}
        </View>
      ))}
    </ScrollView>
  );
}

function ProcCard({ p, invalidate }: { p: Process; invalidate: () => void }) {
  const flat = useAiFlat();
  const t = useTheme();
  const tr = useT();
  const router = useRouter();

  const stepMut = useMutation({
    mutationFn: (v: { idx: number; action: string; patch?: Record<string, unknown>; title?: string }) =>
      api.post<{ error?: string }>(`/processes/${p.id}/step`, { action: v.action, idx: v.idx, patch: v.patch, title: v.title }),
    onSuccess: (r, v) => {
      if (r?.error) { Alert.alert(tr("ui.error"), r.error); return; }
      if (v.action === "accept" || v.action === "accept_all")
        Alert.alert(tr("processes.done"),
          v.action === "accept_all" ? tr("processes.cardsCreated") : tr("processes.cardCreated"));
      invalidate();
    },
    onError: (e) => Alert.alert(tr("ui.error"), String((e as Error).message)),
  });
  const act = (idx: number, action: string, patch?: Record<string, unknown>, title?: string) =>
    stepMut.mutate({ idx, action, patch, title });

  function addStep() {
    if (isWeb) {
      const title = (globalThis as any).prompt?.(tr("processes.stepTitlePrompt"));
      if (title) act(0, "add", undefined, title);
      return;
    }
    // native: Alert.prompt is iOS-only; fall back to a generic step the user renames inline.
    if ((Alert as any).prompt) {
      (Alert as any).prompt(tr("processes.newStep"), tr("processes.titleLabel"),
        (title: string) => title && act(0, "add", undefined, title));
    } else {
      act(0, "add", undefined, "new step");
    }
  }

  const steps = p.steps ?? [];
  return (
    <Panel style={glass(t)}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600", flex: 1 }} numberOfLines={2}>
          {p.request?.slice(0, 120) ?? p.id}
        </Text>
        {p.status ? <Chip text={p.status} /> : null}
        {p.client ? <Chip text={tr("processes.clientChip", { name: p.client })} /> : null}
        {p.due ? <Chip text={tr("processes.dueChip", { due: p.due })} /> : null}
        {p.cost && p.cost > 0 ? <Chip text={flat ? tr("processes.aiFlat") : tr("processes.aiCost", { amount: p.cost.toFixed(2) })} /> : null}
      </View>
      {p.status === "proposing" ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("processes.proposing")}</Text> : null}
      {p.status === "failed" ? <Text style={{ color: t.danger, fontSize: 12 }}>{p.error ?? tr("processes.proposeFailed")}</Text> : null}

      <Pipeline p={p} />

      <View style={{ gap: 6, marginTop: 6 }}>
        {steps.map((st, i) => <StepRow key={i} pid={p.id} idx={i} step={st} act={act} />)}
      </View>

      {steps.length > 0 ? (
        <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
          <Pressable onPress={() => act(0, "accept_all")}
            style={[s.btn, { backgroundColor: t.accent + "29", borderColor: t.accent + "80" }]}>
            <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{tr("processes.acceptAll")}</Text>
          </Pressable>
          <Pressable onPress={addStep}
            style={[s.btn, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
            <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{tr("processes.addStep")}</Text>
          </Pressable>
        </View>
      ) : null}
    </Panel>
  );
}

function NewProcess({ invalidate }: { invalidate: () => void }) {
  const t = useTheme();
  const tr = useT();
  const [request, setRequest] = useState("");
  const [client, setClient] = useState("");
  const [due, setDue] = useState("");

  const mut = useMutation({
    mutationFn: () => api.post<{ error?: string }>("/processes/new", { request: request.trim(), client: client.trim(), due }),
    onSuccess: (r) => {
      if (r?.error) { Alert.alert(tr("ui.error"), r.error); return; }
      setRequest("");
      Alert.alert(tr("processes.submitted"), tr("processes.submittedBody"));
      setTimeout(invalidate, 1500);
    },
    onError: (e) => Alert.alert(tr("ui.error"), String((e as Error).message)),
  });

  return (
    <Panel style={glass(t)}>
      <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "600" }}>{tr("processes.newProcess")}</Text>
      <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 4 }}>
        {tr("processes.newProcessHint")}
      </Text>
      <TextInput
        value={request}
        onChangeText={setRequest}
        multiline
        placeholder={tr("processes.requestPlaceholder")}
        placeholderTextColor={t.txtPlaceholder}
        style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, minHeight: 72, textAlignVertical: "top" }]}
      />
      <View style={{ flexDirection: "row", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        <TextInput value={client} onChangeText={setClient} placeholder={tr("processes.clientPlaceholder")} placeholderTextColor={t.txtPlaceholder}
          style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, width: 150 }]} />
        <TextInput value={due} onChangeText={setDue} placeholder={tr("processes.duePlaceholder")} placeholderTextColor={t.txtPlaceholder}
          style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, width: 150 }]} />
        <Pressable onPress={() => (request.trim() ? mut.mutate() : Alert.alert(tr("processes.hint"), tr("processes.describeRequest")))} disabled={mut.isPending}
          style={[s.btn, { backgroundColor: t.accent, borderColor: t.accent }]}>
          <Text style={{ color: "#fff", fontSize: 12, fontWeight: "700" }}>{mut.isPending ? "…" : tr("processes.proposeSteps")}</Text>
        </Pressable>
      </View>
    </Panel>
  );
}

export default function Processes() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;
  const { data, isLoading, error } = useQuery({ queryKey: ["processes"], queryFn: api.processes, refetchInterval: 8000 });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["processes"] });

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr("nav.processes")} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 60, width: "100%", maxWidth: wide ? 960 : undefined, alignSelf: "center" }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>{tr("health.unreachable")}</Text> : null}
        <NewProcess invalidate={invalidate} />
        {data && data.length === 0 ? <Empty text={tr("processes.empty")} /> : null}
        {(data ?? []).map((p: Process) => <ProcCard key={p.id} p={p} invalidate={invalidate} />)}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 7, fontSize: 12.5 },
  btn: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 7, alignItems: "center", justifyContent: "center" },
  step: { borderWidth: 1, borderRadius: 10, padding: 8, gap: 6 },
});
