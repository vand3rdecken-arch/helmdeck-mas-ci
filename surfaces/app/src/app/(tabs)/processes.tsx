import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Animated, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { HenryChat } from "@/ui/henry_chat";
import { t as i18nT, useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { useAiFlat } from "@/ui/billing";
import { Chip, Dot, Empty, Panel, ScreenHeader } from "@/ui/kit";
import { isWeb, useResponsive } from "@/ui/responsive";
import { webMotion } from "@/ui/web_motion";
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
function StepEditor({ idx, total, step, act, onClose, onOpenCard }: {
  idx: number; total: number; step: Step;
  act: (idx: number, action: string, patch?: Record<string, unknown>, title?: string, direction?: string) => void;
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
        {/* Reorder (owner report 2026-09-03: "cannot... switch steps") - a
            step's CARD is untouched by moving it, only the process's own
            step list order + the schedule laid out from it change. Works
            for any step regardless of whether it already has a card. */}
        <View style={{ gap: 1 }}>
          <Pressable onPress={() => idx > 0 && act(idx, "move", undefined, undefined, "up")}
            disabled={idx === 0} hitSlop={4}>
            <Ionicons name="chevron-up" size={14} color={idx === 0 ? t.borderSubtle : t.txtSecondary} />
          </Pressable>
          <Pressable onPress={() => idx < total - 1 && act(idx, "move", undefined, undefined, "down")}
            disabled={idx === total - 1} hitSlop={4}>
            <Ionicons name="chevron-down" size={14} color={idx === total - 1 ? t.borderSubtle : t.txtSecondary} />
          </Pressable>
        </View>
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
          <Pressable onPress={() => act(idx, "accept")}
            style={[s.btn, { backgroundColor: t.accent + "29", borderColor: t.accent + "80" }]}>
            <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>{tr("processes.acceptCard")}</Text>
          </Pressable>
        )}
        {/* Remove was refused for any step that already had a card - owner
            hit this on their own DONE process, where every step already
            had one, so "remove" was silently unreachable for the entire
            process. Removing only drops the step from this process's OWN
            list; a card a step already spawned lives independently and
            keeps existing on the board either way. */}
        <Pressable onPress={() => act(idx, "remove")}
          style={[s.btn, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
          <Text style={{ color: t.danger, fontSize: 11, fontWeight: "600" }}>✕</Text>
        </Pressable>
      </View>
      {step.desc ? <Text style={{ color: t.txtTertiary, fontSize: 11.5, paddingLeft: 26 }}>{step.desc}</Text> : null}
    </View>
  );
}

// ---- reading a plan: WHERE ARE WE, WHAT IS DONE, WHAT IS NEXT ---------------
// (owner 2026-10-21: the old horizontal pipeline of tiny circles hid the current
// step, the result of finished ones and the way to their cards.) One plan reads
// top-down: title + progress bar, a NOW block for the step it is on, then the
// finished steps (with what they delivered) and the ones still to come. The
// step's card facts come from GET /processes (`step.card`, derived at read time).

interface StepCard { id: string; lane?: string; status?: string; summary?: string; ask?: string; owner?: boolean; at?: string }
type StepV = Step & { card?: StepCard | null };

const isDone = (s: Step) => !!(s.done || s.state === "done");

/** "Title (Repo): rest of the sentence ..." -> ["Title (Repo)", "rest ..."]. */
function splitRequest(request: string): [string, string] {
  const first = (request || "").split("\n")[0].trim();
  const cut = first.indexOf(": ");
  if (cut >= 8 && cut <= 90) return [first.slice(0, cut), first.slice(cut + 2) + (request.includes("\n") ? "\n" + request.split("\n").slice(1).join("\n") : "")];
  return [first.length > 90 ? first.slice(0, 88) + "…" : first, first.length > 90 ? first : (request.includes("\n") ? request.split("\n").slice(1).join("\n") : "")];
}

function agoOf(at?: string): string {
  if (!at) return "";
  const ms = Date.now() - new Date(at.replace(" ", "T")).getTime();
  if (!isFinite(ms) || ms < 0) return "";
  const m = Math.floor(ms / 60000);
  if (m < 2) return "";
  if (m < 60) return `${m} min`;
  if (m < 1440) return `${Math.floor(m / 60)} h`;
  return `${Math.floor(m / 1440)} d`;
}

/** What a step is doing right now, in the owner's words: [label, colour]. */
function stepNow(t: ThemeTokens, st: StepV): [string, string] {
  const tr = i18nT;
  if (isDone(st)) return [tr("processes.stateDone"), t.ok];
  if (st.card?.owner || (st.state === "ready" && (st.mode === "human" || st.mode === "cowork" || st.mode === "teach")))
    return [tr("processes.waitsOnYou"), t.warn];
  if (st.state === "working") return [tr("processes.stateWorking"), t.ai];
  if (st.state === "ready") return [tr("processes.stateReady"), t.accent];
  if (!st.track) return [tr("processes.noCardYet"), t.txtTertiary];
  return [tr("processes.stateWaiting"), t.txtTertiary];
}

/** 1 when the plan's current step waits on the owner (a question, a review, a human step). */
function waitsOnOwner(p: Process): number {
  const steps = (p.steps ?? []) as StepV[];
  const cur = steps.find((x) => !isDone(x));
  return cur && (cur.card?.owner || (cur.state === "ready" && (cur.mode === "human" || cur.mode === "cowork" || cur.mode === "teach"))) ? 1 : 0;
}

function StepGlyph({ st, current }: { st: StepV; current: boolean }) {
  const t = useTheme();
  const [, colour] = stepNow(t, st);
  const done = isDone(st);
  return (
    <View style={{ width: 22, height: 22, borderRadius: 11, alignItems: "center", justifyContent: "center",
      backgroundColor: done ? t.ok + "26" : current ? colour + "26" : "transparent",
      borderWidth: done ? 0 : 1.5, borderColor: current ? colour : t.borderStrong }}>
      {done ? <Ionicons name="checkmark" size={14} color={t.ok} />
        : current ? <Ionicons name={(MODE_ICON[st.mode ?? "do"] ?? "ellipse") as never} size={12} color={colour} />
        : null}
    </View>
  );
}

/** One step: glyph, title, "state · result", a chevron to its card. */
function StepRow({ st, current, selected, onPress }: { st: StepV; current?: boolean; selected: boolean; onPress: () => void }) {
  const t = useTheme();
  const [label, colour] = stepNow(t, st);
  // opened: the detail below carries the whole text - not the same words twice
  const result = selected ? "" : (st.card?.ask || st.card?.summary || "");
  const age = !isDone(st) && st.card?.owner ? agoOf(st.card?.at) : "";
  // A step that is merely waiting its turn says nothing about itself: the same
  // "waiting" under every row was noise that hid the ones with something to say.
  const quiet = !current && !result && !isDone(st) && (st.state === "waiting" || st.state === "proposed");
  return (
    <Pressable onPress={onPress} accessibilityLabel={st.title}
      style={({ pressed }) => ({ flexDirection: "row", gap: 10, alignItems: "flex-start", paddingVertical: 8, paddingHorizontal: 4,
        borderRadius: 10, backgroundColor: selected || pressed ? t.surface2 : "transparent" })}>
      <View style={{ paddingTop: 1 }}><StepGlyph st={st} current={!!current} /></View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={{ color: isDone(st) ? t.txtSecondary : quiet ? t.txtSecondary : t.txtPrimary, fontSize: 14, lineHeight: 19, fontWeight: current ? "600" : "400" }}>{st.title}</Text>
        {quiet ? null : (
          <Text style={{ fontSize: 12, lineHeight: 16, color: t.txtTertiary }} numberOfLines={selected ? undefined : 2}>
            <Text style={{ color: colour, fontWeight: "600" }}>{label}{age ? ` · ${age}` : ""}</Text>
            {result ? `  ·  ${result}` : ""}
          </Text>
        )}
      </View>
      {st.track ? <Ionicons name="chevron-forward" size={14} color={t.txtTertiary} style={{ marginTop: 3 }} /> : null}
    </Pressable>
  );
}

/** Segmented progress: one bar piece per step, done = green, the current one = accent. */
function Progress({ steps, cur }: { steps: StepV[]; cur: number }) {
  const t = useTheme();
  const tr = useT();
  const n = steps.length;
  const done = steps.filter(isDone).length;
  return (
    <View style={{ gap: 6 }}>
      <View style={{ flexDirection: "row", gap: 3 }}>
        {steps.map((st, i) => (
          <View key={i} style={{ flex: 1, height: 5, borderRadius: 3,
            backgroundColor: isDone(st) ? t.ok : i === cur ? t.accent : t.surface2 }} />
        ))}
      </View>
      <Text style={{ color: t.txtTertiary, fontSize: 12 }}>
        {n === 0 ? tr("processes.noSteps") : done === n ? tr("processes.allDone") : tr("processes.progress", { done: String(done), n: String(n) })}
      </Text>
    </View>
  );
}

function StepDetail({ st, onOpenCard, onEdit }: { st: StepV; onOpenCard: () => void; onEdit: () => void }) {
  const t = useTheme();
  const tr = useT();
  return (
    <View style={{ marginLeft: 36, marginBottom: 8, gap: 8 }}>
      {st.card?.summary ? <Text selectable style={{ color: t.txtSecondary, fontSize: 12.5, lineHeight: 18 }}>{st.card.summary}</Text> : null}
      {st.desc ? <Text style={{ color: t.txtTertiary, fontSize: 12, lineHeight: 17 }}>{st.desc}</Text> : null}
      <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
        {st.track ? (
          <Pressable onPress={onOpenCard} style={[s.btn, { backgroundColor: t.accent + "29", borderColor: t.accent + "80" }]}>
            <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{tr("processes.openCardLink")}</Text>
          </Pressable>
        ) : null}
        <Pressable onPress={onEdit} style={[s.btn, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
          <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{tr("processes.editStep")}</Text>
        </Pressable>
      </View>
    </View>
  );
}

function ProcCard({ p, invalidate }: { p: Process; invalidate: () => void }) {
  const flat = useAiFlat();
  const t = useTheme();
  const tr = useT();
  const router = useRouter();

  const stepMut = useMutation({
    mutationFn: (v: { idx: number; action: string; patch?: Record<string, unknown>; title?: string; direction?: string }) =>
      api.post<{ error?: string; steps?: unknown[] }>(`/processes/${p.id}/step`,
        { action: v.action, idx: v.idx, patch: v.patch, title: v.title, direction: v.direction }),
    onSuccess: (r, v) => {
      if (r?.error) { Alert.alert(tr("ui.error"), r.error); return; }
      if (v.action === "accept" || v.action === "accept_all")
        Alert.alert(tr("processes.done"),
          v.action === "accept_all" ? tr("processes.cardsCreated") : tr("processes.cardCreated"));
      if (v.action === "accept" || v.action === "accept_all" || v.action === "remove") { setExpanded(null); setEditIdx(null); }
      // follow the SAME step to its new position, so repeated up/down taps
      // keep working on the step the owner is actually looking at.
      if (v.action === "move" && r && !r.error) {
        setExpanded(v.direction === "up" ? v.idx - 1 : v.idx + 1);
        setEditIdx(v.direction === "up" ? v.idx - 1 : v.idx + 1);
      }
      invalidate();
    },
    onError: (e) => Alert.alert(tr("ui.error"), String((e as Error).message)),
  });
  const act = (idx: number, action: string, patch?: Record<string, unknown>, title?: string, direction?: string) =>
    stepMut.mutate({ idx, action, patch, title, direction });
  const [expanded, setExpanded] = useState<number | null>(null);
  const [editIdx, setEditIdx] = useState<number | null>(null);   // the StepEditor (title/mode/due), apart from the read-only detail
  const [showDone, setShowDone] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [manage, setManage] = useState(false);

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
    mutationFn: (v: { action: "edit" | "cancel" | "delete"; patch?: Record<string, unknown> }) =>
      api.post<{ error?: string }>(`/processes/${p.id}/${v.action}`,
        v.action === "edit" ? { patch: v.patch } : {}),
    onSuccess: (r) => {
      if (r?.error) { Alert.alert(tr("ui.error"), r.error); return; }
      invalidate();   // a delete just means this card is absent from the next fetch
    },
    onError: (e) => Alert.alert(tr("ui.error"), String((e as Error).message)),
  });

  // Was a chain of two sequential OS prompts (one field at a time, native
  // "text window" dialogs) - clunky, and looked like an afterthought next
  // to the real inline editors this screen already has for steps. A real
  // inline form (same shape as StepEditor) instead, editing all three
  // fields at once with an explicit Save/Cancel.
  const [editingHeader, setEditingHeader] = useState(false);
  const [editTitle, setEditTitle] = useState(p.request ?? "");
  const [editClient, setEditClient] = useState(p.client ?? "");
  const [editDue, setEditDue] = useState(p.due ?? "");

  function saveHeaderEdit() {
    processMut.mutate({ action: "edit",
      patch: { request: editTitle, client: editClient, due: editDue } });
    setEditingHeader(false);
  }

  async function cancelProcess() {
    const yes = await confirmAsync(tr("processes.cancelConfirmTitle"), tr("processes.cancelConfirmBody"));
    if (yes) processMut.mutate({ action: "cancel" });
  }

  // Owner report 2026-09-03: "Or delete process" - cancel only soft-stops
  // the chain, the row stays in the list forever. Same "never touches a
  // card already spawned" guarantee as cancel, just removes the bookkeeping
  // entirely instead of marking it cancelled.
  async function deleteProcess() {
    const yes = await confirmAsync(tr("processes.deleteConfirmTitle"), tr("processes.deleteConfirmBody"));
    if (yes) processMut.mutate({ action: "delete" });
  }


  const steps = (p.steps ?? []) as StepV[];
  const [headerOpen, setHeaderOpen] = useState(false);
  const [title, rest] = splitRequest(p.request ?? p.id);
  const cur = steps.findIndex((x) => !isDone(x));                       // the step the plan is on (-1 = all done)
  const doneIdx = steps.map((x, i) => (isDone(x) ? i : -1)).filter((i) => i >= 0);
  const upIdx = steps.map((x, i) => (!isDone(x) && i !== cur ? i : -1)).filter((i) => i >= 0);
  const upShown = showAll ? upIdx : upIdx.slice(0, 3);
  const nowColour = cur >= 0 ? stepNow(t, steps[cur])[1] : t.ok;
  const row = (i: number, current = false) => (
    <View key={i}>
      <StepRow st={steps[i]} current={current} selected={expanded === i} onPress={() => setExpanded(expanded === i ? null : i)} />
      {expanded === i ? (
        <StepDetail st={steps[i]} onOpenCard={() => router.push(`/card/${steps[i].track}` as never)}
          onEdit={() => setEditIdx(editIdx === i ? null : i)} />
      ) : null}
      {editIdx === i ? (
        <View style={{ marginBottom: 8 }}>
          <StepEditor idx={i} total={steps.length} step={steps[i]} act={act} onClose={() => setEditIdx(null)}
            onOpenCard={(id) => router.push(`/card/${id}` as never)} />
        </View>
      ) : null}
    </View>
  );
  return (
    <Panel style={glass(t)}>
      {editingHeader ? (
        // A real inline form (same shape as StepEditor's own editor below) -
        // was a chain of two sequential OS "text window" prompts, one field
        // at a time, with no visible relation to Henry's identical chat
        // capability (owner: "Logik ist zu komisch"). One thing, one form.
        <View style={{ gap: 8 }}>
          <TextInput
            value={editTitle}
            onChangeText={setEditTitle}
            multiline
            placeholder={tr("processes.newProcessHint")}
            placeholderTextColor={t.txtPlaceholder}
            style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, minHeight: 60 }]}
          />
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            <TextInput
              value={editClient}
              onChangeText={setEditClient}
              placeholder={tr("processes.clientPrompt")}
              placeholderTextColor={t.txtPlaceholder}
              style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, flex: 1, minWidth: 120 }]}
            />
            <TextInput
              value={editDue}
              onChangeText={setEditDue}
              placeholder={tr("processes.duePrompt")}
              placeholderTextColor={t.txtPlaceholder}
              style={[s.input, { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle, width: 140 }]}
            />
          </View>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable onPress={saveHeaderEdit} disabled={processMut.isPending}
              style={[s.btn, { backgroundColor: t.accent + "29", borderColor: t.accent + "80" }]}>
              <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{tr("ui.save")}</Text>
            </Pressable>
            <Pressable onPress={() => setEditingHeader(false)}
              style={[s.btn, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
              <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{tr("ui.cancel")}</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <>
          {/* Was fixed at numberOfLines={2} with no way to read the rest -
              the owner's own report ("ich verstehe nur Bahnhof") named this:
              the request text IS the answer to "what is this process", and
              it was the one thing you could never fully read. Tap to
              expand/collapse; only shows the affordance when there is
              actually more to read. */}
          <Pressable onPress={() => rest && setHeaderOpen((v) => !v)} style={{ gap: 3 }}>
            <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600", lineHeight: 21 }}>{title}</Text>
            {rest ? <Text numberOfLines={headerOpen ? undefined : 2} style={{ color: t.txtTertiary, fontSize: 12.5, lineHeight: 17 }}>{rest}</Text> : null}
          </Pressable>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
            {p.status ? <Chip text={p.status} /> : null}
            {p.client ? <Chip text={tr("processes.clientChip", { name: p.client })} /> : null}
            {p.due ? <Chip text={tr("processes.dueChip", { due: p.due })} /> : null}
            {p.cost && p.cost > 0 ? <Chip text={flat ? tr("processes.aiFlat") : tr("processes.aiCost", { amount: p.cost.toFixed(2) })} /> : null}
          </View>
        </>
      )}
      {p.status === "proposing" ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("processes.proposing")}</Text> : null}
      {p.status === "failed" ? <Text style={{ color: t.danger, fontSize: 12 }}>{p.error ?? tr("processes.proposeFailed")}</Text> : null}

      {steps.length > 0 ? (
        <View style={{ marginTop: 12, gap: 12 }}>
          <Progress steps={steps} cur={cur} />
          {cur >= 0 ? (
            <View style={{ borderRadius: 12, borderWidth: 1, borderColor: nowColour + "66", backgroundColor: nowColour + "12", paddingHorizontal: 8, paddingTop: 8, paddingBottom: 2 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "600", letterSpacing: 0.6, paddingHorizontal: 4 }}>
                {tr("processes.now").toUpperCase()} · {tr("processes.stepOf", { i: String(cur + 1), n: String(steps.length) })}
              </Text>
              {row(cur, true)}
            </View>
          ) : null}
          <View>
            {doneIdx.length > 0 ? (
              <Pressable onPress={() => setShowDone((v) => !v)} style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 6, paddingHorizontal: 4 }}>
                <Ionicons name={showDone ? "chevron-down" : "chevron-forward"} size={14} color={t.txtTertiary} />
                <Text style={{ color: t.ok, fontSize: 12.5, fontWeight: "600" }}>{tr("processes.doneGroup", { n: String(doneIdx.length) })}</Text>
              </Pressable>
            ) : null}
            {showDone ? doneIdx.map((i) => row(i)) : null}
            {upShown.map((i) => row(i))}
            {upIdx.length > upShown.length ? (
              <Pressable onPress={() => setShowAll(true)} style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 6, paddingHorizontal: 4 }}>
                <Ionicons name="chevron-forward" size={14} color={t.txtTertiary} />
                <Text style={{ color: t.txtSecondary, fontSize: 12.5 }}>{tr("processes.moreSteps", { n: String(upIdx.length - upShown.length) })}</Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      ) : null}
      {/* Everything that CHANGES the plan sits behind one "Manage" row: the
          screen is for reading where the plan stands, not for a wall of
          Edit / Cancel / Delete buttons (owner 2026-10-21: "haesslich"). */}
      {!editingHeader ? (
        <View style={{ marginTop: 10 }}>
          <Pressable onPress={() => setManage((v) => !v)} style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 6, paddingHorizontal: 4 }}>
            <Ionicons name={manage ? "chevron-down" : "chevron-forward"} size={14} color={t.txtTertiary} />
            <Text style={{ color: t.txtTertiary, fontSize: 12.5 }}>{tr("processes.manage")}</Text>
          </Pressable>
          {manage ? (
            <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
              {steps.some((x) => !x.track) ? (
                <Pressable onPress={() => act(0, "accept_all")}
                  style={[s.btn, { backgroundColor: t.accent + "29", borderColor: t.accent + "80" }]}>
                  <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{tr("processes.acceptAll")}</Text>
                </Pressable>
              ) : null}
              <Pressable onPress={addStep} style={[s.btn, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
                <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{tr("processes.addStep")}</Text>
              </Pressable>
              <Pressable onPress={() => setEditingHeader(true)} disabled={processMut.isPending}
                style={[s.btn, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
                <Text style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{tr("processes.editProcess")}</Text>
              </Pressable>
              {p.status !== "cancelled" && p.status !== "done" ? (
                <Pressable onPress={cancelProcess} disabled={processMut.isPending}
                  style={[s.btn, { backgroundColor: t.danger + "1A", borderColor: t.danger + "80" }]}>
                  <Text style={{ color: t.danger, fontSize: 12, fontWeight: "600" }}>{tr("processes.cancelProcess")}</Text>
                </Pressable>
              ) : null}
              <Pressable onPress={deleteProcess} disabled={processMut.isPending}
                style={[s.btn, { backgroundColor: t.danger + "1A", borderColor: t.danger + "80" }]}>
                <Text style={{ color: t.danger, fontSize: 12, fontWeight: "600" }}>{tr("processes.deleteProcess")}</Text>
              </Pressable>
            </View>
          ) : null}
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
  const [open, setOpen] = useState(false);

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

  // Folded by default: the screen is for reading the plans that run; filing a
  // new one is the rare act, not the first thing in view.
  if (!open) {
    return (
      <Pressable onPress={() => setOpen(true)} accessibilityLabel={tr("processes.newProcess")}
        style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 10, paddingHorizontal: 12,
          borderRadius: 12, borderWidth: 1, borderColor: t.borderSubtle, backgroundColor: pressed ? t.surface2 : "transparent" })}>
        <Ionicons name="add" size={16} color={t.txtSecondary} />
        <Text style={{ color: t.txtSecondary, fontSize: 14 }}>{tr("processes.newProcess")}</Text>
      </Pressable>
    );
  }
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
  // No timer (2026-09-24): every writer of this data moves the daemon's `v`,
  // and a moved `v` reaches the phone as a pushed event (or the long-poll)
  // that invalidates every query - app/_layout.tsx useGlobalStream. A timer
  // here only re-asked what the daemon would have said anyway, and every
  // ask was a Cloudflare request (the 2026-09-23 rate limit).
  const { data, isLoading, error } = useQuery({ queryKey: ["processes"], queryFn: api.processes });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["processes"] });

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr("nav.processes")} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 60, width: "100%", maxWidth: wide ? 960 : undefined, alignSelf: "center" }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>{tr("health.unreachable")}</Text> : null}
        <NewProcess invalidate={invalidate} />
        {data && data.length === 0 ? <Empty text={tr("processes.empty")} /> : null}
        {[...(data ?? [])].sort((a: Process, b: Process) => waitsOnOwner(b) - waitsOnOwner(a))
          .map((p: Process) => <ProcCard key={p.id} p={p} invalidate={invalidate} />)}
      </ScrollView>
      {/* ONE floating chat entry, same as the board screen's FAB - not a
          "Henry fragen" button on every single process card (owner
          pushback 2026-09-03: "das soll ein Chat-Fenster wie auf dem Board
          sein, nicht ein Button überall"). Since it is the SHARED launcher,
          "identical to board.tsx" is now a property of the code rather than
          something two copies have to keep agreeing on. */}
      <HenryChat />
    </View>
  );
}

const s = StyleSheet.create({
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 7, fontSize: 12.5 },
  btn: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 7, alignItems: "center", justifyContent: "center" },
  step: { borderWidth: 1, borderRadius: 10, padding: 8, gap: 6 },
});
