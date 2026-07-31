import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useState } from "react";
import {
  ActivityIndicator, Alert, Platform, Pressable, ScrollView, StyleSheet,
  Text, TextInput, useWindowDimensions, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Chip, Dot, Empty, Panel, ScreenHeader } from "@/ui/kit";

const isWeb = Platform.OS === "web";

// Executor modes the daemon understands (daemon/processes.py MODES).
const MODES = ["do", "prepare", "cowork", "teach", "human"] as const;
const MODE_LABEL: Record<string, string> = {
  do: "do", prepare: "prepare", cowork: "cowork", teach: "teach", human: "human",
};

// Step lifecycle -> [colour token key, label]; mirrors procs.tsx STATE_STYLE.
function stateStyle(t: ThemeTokens, state?: string): [string, string] {
  switch (state) {
    case "done": return [t.ok, "done"];
    case "working": return [t.ai, "agent working"];
    case "ready": return [t.warn, "up next"];
    case "waiting": return [t.txtTertiary, "waiting"];
    default: return [t.txtTertiary, "proposed"];
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
          placeholder="step title"
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
          placeholder="due (YYYY-MM-DD)"
          placeholderTextColor={t.txtPlaceholder}
          style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, width: 140 }]}
        />
        {step.track ? (
          <Chip text="✓ card" dot={t.ok} />
        ) : (
          <>
            <Pressable onPress={() => act(idx, "accept")}
              style={[s.btn, { backgroundColor: t.accent + "29", borderColor: t.accent + "80" }]}>
              <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>Accept → card</Text>
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

function ProcCard({ p, invalidate }: { p: Process; invalidate: () => void }) {
  const t = useTheme();
  const router = useRouter();

  const stepMut = useMutation({
    mutationFn: (v: { idx: number; action: string; patch?: Record<string, unknown>; title?: string }) =>
      api.post<{ error?: string }>(`/processes/${p.id}/step`, { action: v.action, idx: v.idx, patch: v.patch, title: v.title }),
    onSuccess: (r, v) => {
      if (r?.error) { Alert.alert("Fehler", r.error); return; }
      if (v.action === "accept" || v.action === "accept_all")
        Alert.alert("Erledigt", `Card${v.action === "accept_all" ? "s" : ""} auf dem Board erstellt.`);
      invalidate();
    },
    onError: (e) => Alert.alert("Fehler", String((e as Error).message)),
  });
  const act = (idx: number, action: string, patch?: Record<string, unknown>, title?: string) =>
    stepMut.mutate({ idx, action, patch, title });

  function addStep() {
    if (isWeb) {
      const title = (globalThis as any).prompt?.("Step title:");
      if (title) act(0, "add", undefined, title);
      return;
    }
    // native: Alert.prompt is iOS-only; fall back to a generic step the user renames inline.
    if ((Alert as any).prompt) {
      (Alert as any).prompt("Neuer Schritt", "Titel:", (title: string) => title && act(0, "add", undefined, title));
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
        {p.client ? <Chip text={`client: ${p.client}`} /> : null}
        {p.due ? <Chip text={`due ${p.due}`} /> : null}
        {p.cost && p.cost > 0 ? <Chip text={`AI $${p.cost.toFixed(2)}`} /> : null}
      </View>
      {p.status === "proposing" ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Agent schlägt Schritte vor…</Text> : null}
      {p.status === "failed" ? <Text style={{ color: t.danger, fontSize: 12 }}>{p.error ?? "Vorschlag fehlgeschlagen"}</Text> : null}

      <View style={{ gap: 6, marginTop: 6 }}>
        {steps.map((st, i) => <StepRow key={i} pid={p.id} idx={i} step={st} act={act} />)}
      </View>

      {steps.length > 0 ? (
        <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
          <Pressable onPress={() => act(0, "accept_all")}
            style={[s.btn, { backgroundColor: t.accent + "29", borderColor: t.accent + "80" }]}>
            <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>Accept all → cards</Text>
          </Pressable>
          <Pressable onPress={addStep}
            style={[s.btn, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
            <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>+ add step</Text>
          </Pressable>
        </View>
      ) : null}
    </Panel>
  );
}

function NewProcess({ invalidate }: { invalidate: () => void }) {
  const t = useTheme();
  const [request, setRequest] = useState("");
  const [client, setClient] = useState("");
  const [due, setDue] = useState("");

  const mut = useMutation({
    mutationFn: () => api.post<{ error?: string }>("/processes/new", { request: request.trim(), client: client.trim(), due }),
    onSuccess: (r) => {
      if (r?.error) { Alert.alert("Fehler", r.error); return; }
      setRequest("");
      Alert.alert("Eingereicht", "Agent schlägt die Schritte vor.");
      setTimeout(invalidate, 1500);
    },
    onError: (e) => Alert.alert("Fehler", String((e as Error).message)),
  });

  return (
    <Panel style={glass(t)}>
      <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "600" }}>Neuer Prozess</Text>
      <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 4 }}>
        Beschreibe die Anfrage in Worten – ein Agent schlägt die Schritte vor, du passt sie an,
        jeder angenommene Schritt wird zu einer Card und die Kette läuft der Reihe nach.
      </Text>
      <TextInput
        value={request}
        onChangeText={setRequest}
        multiline
        placeholder="z. B. Kunde Meier braucht den Q3-Vertrag: aus Vorlage entwerfen, rechtlich prüfen, an Kunden zur Unterschrift, unterschriebene Kopie archivieren."
        placeholderTextColor={t.txtPlaceholder}
        style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, minHeight: 72, textAlignVertical: "top" }]}
      />
      <View style={{ flexDirection: "row", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        <TextInput value={client} onChangeText={setClient} placeholder="client (optional)" placeholderTextColor={t.txtPlaceholder}
          style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, width: 150 }]} />
        <TextInput value={due} onChangeText={setDue} placeholder="due (YYYY-MM-DD)" placeholderTextColor={t.txtPlaceholder}
          style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, width: 150 }]} />
        <Pressable onPress={() => (request.trim() ? mut.mutate() : Alert.alert("Hinweis", "Beschreibe die Anfrage."))} disabled={mut.isPending}
          style={[s.btn, { backgroundColor: t.accent, borderColor: t.accent }]}>
          <Text style={{ color: "#fff", fontSize: 12, fontWeight: "700" }}>{mut.isPending ? "…" : "Propose steps"}</Text>
        </Pressable>
      </View>
    </Panel>
  );
}

export default function Processes() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;
  const { data, isLoading, error } = useQuery({ queryKey: ["processes"], queryFn: api.processes, refetchInterval: 8000 });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["processes"] });

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title="Processes" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 60, width: "100%", maxWidth: wide ? 960 : undefined, alignSelf: "center" }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar.</Text> : null}
        <NewProcess invalidate={invalidate} />
        {data && data.length === 0 ? <Empty text="Keine Prozesse." /> : null}
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
