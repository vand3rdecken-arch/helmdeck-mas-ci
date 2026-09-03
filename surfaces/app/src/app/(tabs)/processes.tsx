import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Animated, Pressable, ScrollView, StyleSheet,
  Text, TextInput, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { saveDraft } from "@/data/drafts";
import { t as i18nT, useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { useAiFlat } from "@/ui/billing";
import { Chip, Dot, Empty, Panel, ScreenHeader } from "@/ui/kit";
import { isWeb, useResponsive } from "@/ui/responsive";
import { confirmAsync, promptText } from "@/ui/settings_sections";

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

// Expanded editor for exactly one step at a time (the one tapped open in the
// Pipeline above): title, mode, due, and accept/remove (or a "card" chip once
// accepted). Every mutation hits POST /processes/{id}/step. Rendered inline
// below the timeline instead of as a permanent per-step row, so only the step
// the user opened shows editable controls.
function StepEditor({ idx, step, act, onClose, onOpenCard }: {
  idx: number; step: Step;
  act: (idx: number, action: string, patch?: Record<string, unknown>, title?: string) => void;
  onClose: () => void;
  onOpenCard: (trackId: string) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const [title, setTitle] = useState(step.title);
  const [due, setDue] = useState(step.due ?? "");
  const [colour, label] = stateStyle(t, step.state);

  return (
    <View style={[s.step, { borderColor: t.accent + "80", backgroundColor: t.accent + "0F" }]}>
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
        <Pressable onPress={onClose} hitSlop={8}>
          <Text style={{ color: t.txtTertiary, fontSize: 16, paddingHorizontal: 2 }}>✕</Text>
        </Pressable>
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
          // Was a plain status Chip - the ONLY visibility this screen gave
          // into a running step was the pipeline dot's colour, nothing about
          // what the card is actually doing (owner report 2026-09-03). The
          // card's own detail view already has the full transcript/progress;
          // this is the missing bridge to it, not a duplicate of it.
          <Pressable onPress={() => onOpenCard(step.track!)}>
            <Chip text={tr("processes.cardChipOpen")} dot={t.ok} />
          </Pressable>
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
// EVERY node is tappable (fixed 2026-09-03 - a step already turned into a
// card used to render with `if (!interactive) return node` skipping the
// Pressable wrapper entirely, so a step WITH a card - the case that most
// needs a tap-through to its card's transcript - was the one case you could
// never reach; the "Card oeffnen" link built for exactly that lived inside
// an editor nothing could open). `interactive` now drives styling ONLY -
// the raised ring + pencil badge for a still-editable (no card yet) step -
// never whether the node responds to a tap.
function PipeNode({ step, interactive, selected, onPress }: {
  step: Step; interactive: boolean; selected: boolean; onPress?: () => void;
}) {
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

  const node = (
    <View style={{ width: 96, alignItems: "center" }}>
      <View style={{
        width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center",
        borderWidth: selected ? 2.5 : 0,
        borderColor: t.accent,
        backgroundColor: selected ? t.accent + "22" : "transparent",
      }}>
        <Animated.View style={{
          width: 42, height: 42, borderRadius: 21, alignItems: "center", justifyContent: "center",
          borderWidth: interactive ? 2.5 : 1.5, borderStyle: proposed && interactive ? "dashed" : "solid",
          borderColor: interactive ? (proposed ? t.borderStrong : colour) : t.borderSubtle,
          backgroundColor: interactive ? colour + "2E" : colour + "14",
          opacity: state === "ready" ? opacity : (interactive ? 1 : 0.62),
          ...(isWeb && interactive ? ({ boxShadow: `0 1px 4px ${colour}55` } as any) : null),
        }}>
          <Ionicons name={done ? "checkmark" : (MODE_ICON[step.mode ?? "do"] ?? "ellipse")}
            size={18} color={interactive ? (proposed ? t.borderStrong : colour) : t.txtTertiary} />
        </Animated.View>
        {interactive ? (
          <View style={{
            position: "absolute", right: -2, bottom: -2, width: 16, height: 16, borderRadius: 8,
            alignItems: "center", justifyContent: "center", backgroundColor: t.accent, borderWidth: 1.5, borderColor: t.canvas,
          }}>
            <Ionicons name="create" size={9} color="#fff" />
          </View>
        ) : null}
      </View>
      <Text numberOfLines={2} style={{
        fontSize: 10.5, lineHeight: 13, marginTop: 4, textAlign: "center",
        color: interactive ? t.txtSecondary : t.txtTertiary,
      }}>
        {step.title}
      </Text>
      <Text style={{ fontSize: 9.5, fontWeight: "600", color: interactive ? (proposed ? t.txtTertiary : colour) : t.txtTertiary }}>
        {label}
      </Text>
    </View>
  );

  return (
    <Pressable onPress={onPress} hitSlop={4}
      style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}>
      {node}
    </Pressable>
  );
}

// Horizontal n8n-style read of the chain: one node per step joined by connector
// arrows. Scrolls sideways when it overflows. Tapping ANY node expands its
// editor below - a step without a card yet gets the full editor, a step with
// one gets a read-only summary + a link to that card's own transcript.
function Pipeline({ p, expanded, onToggle }: { p: Process; expanded: number | null; onToggle: (i: number) => void }) {
  const t = useTheme();
  const steps = p.steps ?? [];
  if (steps.length === 0) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={{ alignItems: "flex-start", paddingVertical: 8, paddingHorizontal: 2 }}>
      {steps.map((st, i) => (
        <View key={i} style={{ flexDirection: "row", alignItems: "flex-start" }}>
          <PipeNode step={st} interactive={!st.track} selected={expanded === i} onPress={() => onToggle(i)} />
          {i < steps.length - 1 ? (
            <View style={{ width: 22, height: 48, alignItems: "center", justifyContent: "center" }}>
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
      api.post<{ error?: string; steps?: unknown[] }>(`/processes/${p.id}/step`,
        { action: v.action, idx: v.idx, patch: v.patch, title: v.title }),
    onSuccess: (r, v) => {
      if (r?.error) { Alert.alert(tr("ui.error"), r.error); return; }
      if (v.action === "accept" || v.action === "accept_all")
        Alert.alert(tr("processes.done"),
          v.action === "accept_all" ? tr("processes.cardsCreated") : tr("processes.cardCreated"));
      if (v.action === "accept" || v.action === "accept_all" || v.action === "remove") setExpanded(null);
      invalidate();
    },
    onError: (e) => Alert.alert(tr("ui.error"), String((e as Error).message)),
  });
  const act = (idx: number, action: string, patch?: Record<string, unknown>, title?: string) =>
    stepMut.mutate({ idx, action, patch, title });
  const [expanded, setExpanded] = useState<number | null>(null);

  async function addStep() {
    // Was: isWeb ? window.prompt : (Alert as any).prompt(...) - Alert.prompt's
    // entire body is `if (Platform.OS === 'ios')` (react-native's own
    // Alert.js), so on Android the function reference is truthy but its
    // body never runs and the callback never fires - "+ Schritt" did
    // NOTHING on Android: no dialog, no step, no error (owner report
    // 2026-09-03, screenshot circling the button). promptText() is the
    // app's own cross-platform helper (settings_sections.tsx) - web uses
    // window.prompt, iOS Alert.prompt, and ANDROID GETS A REAL MODAL
    // (<PromptHost/>, mounted once at the app root in _layout.tsx) instead
    // of silently no-oping.
    const title = await promptText(tr("processes.stepTitlePrompt"));
    if (title) act(0, "add", undefined, title);
  }

  // Process-LEVEL actions (owner report 2026-09-03: "+Schritt war die
  // einzige Aktion ausser Steps annehmen - man kann nicht mal den Client/
  // die Faelligkeit aendern oder abbrechen"). Separate mutation from
  // stepMut - these hit /processes/<id>/edit|cancel, not /step, and are
  // admin-gated server-side (cards.admin), unlike the per-step editor.
  const processMut = useMutation({
    mutationFn: (v: { action: "edit" | "cancel"; patch?: Record<string, unknown> }) =>
      api.post<{ error?: string }>(`/processes/${p.id}/${v.action}`,
        v.action === "edit" ? { patch: v.patch } : {}),
    onSuccess: (r) => {
      if (r?.error) { Alert.alert(tr("ui.error"), r.error); return; }
      invalidate();
    },
    onError: (e) => Alert.alert(tr("ui.error"), String((e as Error).message)),
  });

  async function editProcess() {
    const client = await promptText(tr("processes.clientPrompt"), p.client ?? "");
    if (client === null) return;   // cancelled
    const due = await promptText(tr("processes.duePrompt"), p.due ?? "");
    if (due === null) return;
    processMut.mutate({ action: "edit", patch: { client, due } });
  }

  async function cancelProcess() {
    const yes = await confirmAsync(tr("processes.cancelConfirmTitle"), tr("processes.cancelConfirmBody"));
    if (yes) processMut.mutate({ action: "cancel" });
  }

  async function askHenry() {
    await saveDraft("board-copilot", tr("processes.askHenryDraft", { title: (p.request ?? p.id).slice(0, 60) }));
    router.push("/chat" as never);
  }

  const steps = p.steps ?? [];
  const [headerOpen, setHeaderOpen] = useState(false);
  const truncated = (p.request?.length ?? 0) > 120;
  return (
    <Panel style={glass(t)}>
      {/* Was fixed at numberOfLines={2} with no way to read the rest - the
          owner's own report ("ich verstehe nur Bahnhof") named this: the
          request text IS the answer to "what is this process", and it was
          the one thing you could never fully read. Tap to expand/collapse;
          only shows the affordance when there is actually more to read. */}
      <Pressable onPress={() => truncated && setHeaderOpen((v) => !v)}
        style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600", flex: 1 }}
          numberOfLines={headerOpen ? undefined : 2}>
          {p.request ?? p.id}
        </Text>
        {truncated ? <Ionicons name={headerOpen ? "chevron-up" : "chevron-down"} size={16} color={t.txtTertiary} /> : null}
      </Pressable>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
        {p.status ? <Chip text={p.status} /> : null}
        {p.client ? <Chip text={tr("processes.clientChip", { name: p.client })} /> : null}
        {p.due ? <Chip text={tr("processes.dueChip", { due: p.due })} /> : null}
        {p.cost && p.cost > 0 ? <Chip text={flat ? tr("processes.aiFlat") : tr("processes.aiCost", { amount: p.cost.toFixed(2) })} /> : null}
      </View>
      {p.status === "proposing" ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("processes.proposing")}</Text> : null}
      {p.status === "failed" ? <Text style={{ color: t.danger, fontSize: 12 }}>{p.error ?? tr("processes.proposeFailed")}</Text> : null}

      <Pipeline p={p} expanded={expanded} onToggle={(i) => setExpanded(expanded === i ? null : i)} />

      {expanded !== null && steps[expanded] ? (
        <View style={{ marginTop: 6 }}>
          <StepEditor idx={expanded} step={steps[expanded]} act={act} onClose={() => setExpanded(null)}
            onOpenCard={(id) => router.push(`/card/${id}` as never)} />
        </View>
      ) : null}

      {steps.length > 0 ? (
        <View style={{ flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
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
      {/* process-level actions - separate row so they read as a different
          class of action from the step-level ones above. Was HIDDEN
          entirely once done/cancelled - which is exactly the state the
          owner's own "Accounts & Boards PRD" process was in when reporting
          this, so the fix rendered as if nothing had changed at all.
          Bearbeiten (rename/re-client, still legitimate after done) stays;
          only Abbrechen (nothing left to stop) hides. */}
      <View style={{ flexDirection: "row", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        <Pressable onPress={editProcess} disabled={processMut.isPending}
          style={[s.btn, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
          <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{tr("processes.editProcess")}</Text>
        </Pressable>
        {p.status !== "cancelled" && p.status !== "done" ? (
          <Pressable onPress={cancelProcess} disabled={processMut.isPending}
            style={[s.btn, { backgroundColor: t.danger + "1A", borderColor: t.danger + "80" }]}>
            <Text style={{ color: t.danger, fontSize: 12, fontWeight: "600" }}>{tr("processes.cancelProcess")}</Text>
          </Pressable>
        ) : null}
        {/* Henry entry point - the chat actions (process_status/edit_process/
            cancel_process/add_step/update_step/remove_step) existed with no
            way to discover them from this screen (owner: "wo ist der
            chat"). Pre-fills the composer so the owner doesn't have to
            remember the process's id/fragment by hand. */}
        <Pressable onPress={askHenry}
          style={[s.btn, { backgroundColor: t.accent + "14", borderColor: t.accent + "60" }]}>
          <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{tr("processes.askHenry")}</Text>
        </Pressable>
      </View>
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
  const { wide } = useResponsive();
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
