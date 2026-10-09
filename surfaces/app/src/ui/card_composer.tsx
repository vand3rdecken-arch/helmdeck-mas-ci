import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Alert, Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "@/theme";
import { api, type ReplyRef, type SteerOpts } from "@/data/client";
import { applyCleanup, undoCleanup } from "@/data/dictation_clean";
import {
  type Attach, filesToAttachments, isWeb, MAX_FILES, MAX_MB, mergeAttachments, pickFiles,
  pickImages, recoverPendingImages, takePhoto,
} from "@/data/attachments";
import { loadDraft, loadOpts, saveDraft, saveOpts } from "@/data/drafts";
import { useDictation } from "@/data/use_dictation";
import { DictationBar } from "@/ui/dictation_bar";
import { useT } from "@/i18n";
import type { ModelAvail } from "@/data/types";

export interface SlashCommand { name: string; hint: string; insert: string }
export interface ModeOption { id: string; label: string; desc?: string }

// One line per permission mode on WHAT IT ALLOWS - the picker's second line.
// Keyed by the harness's own mode ids so a surface only has to pass id+label.
const MODE_DESC: Record<string, string> = {
  auto: "composer.mode.desc.auto",
  bypassPermissions: "composer.mode.desc.full",
  acceptEdits: "composer.mode.desc.edit",
  plan: "composer.mode.desc.plan",
};
const MODE_ICON: Record<string, React.ComponentProps<typeof Ionicons>["name"]> = {
  auto: "shield-half-outline",
  bypassPermissions: "shield-outline",
  acceptEdits: "create-outline",
  plan: "reader-outline",
};
export interface Recipient {
  id: string; label: string; color: string; hint?: string;
  icon: React.ComponentProps<typeof Ionicons>["name"];
}

// thinking levels — each `id` maps to a real Claude Code budget keyword
// server-side (never translated); `key` is only the button label.
const THINK: { id: string; key: string }[] = [
  { id: "", key: "composer.thinkOff" }, { id: "think", key: "composer.thinkOn" },
  { id: "think-hard", key: "composer.thinkHard" }, { id: "ultrathink", key: "composer.thinkUltra" },
];

// Card steer composer — ported from the archived web Composer, rebuilt for RN.
// Model picker (from api.models()), thinking-level cycle, agent/permission mode
// cycle, slash-command affordance. Wires into api.steer(id, text, {model,thinking,mode}).
export function Composer({
  onSend, busy, onStop, models, modeOptions, slashCommands, placeholder, seed, bottomInset = 0, draftKey,
  recipients, defaultTo, contextChip, onClearContext, onSteerLive, quote, onClearQuote,
}: {
  onSend: (text: string, opts: SteerOpts) => void | Promise<void>;
  /** Typed while busy: try to fold the message into the RUNNING turn first
   *  (board chat -> copilot.try_inject). Resolves false when the turn cannot
   *  take it right now; the message is then queued like before. */
  onSteerLive?: (text: string, opts: SteerOpts) => Promise<boolean>;
  busy?: boolean;
  onStop?: () => void;
  models: (string | { id: string; label?: string; desc?: string; avail?: ModelAvail })[];
  modeOptions?: ModeOption[];
  slashCommands?: SlashCommand[];
  placeholder?: string;
  seed?: { text: string; key: number };
  bottomInset?: number;
  draftKey?: string;   // persist in-progress text per surface (board / each card)
  /** The team-chat roster (Henry / the card's Worker) — omitted on surfaces
   *  with only one possible recipient (the global board chat), which then
   *  gets no @mention popover and no recipient chip. */
  recipients?: Recipient[];
  /** Who an unaddressed message goes to. Re-applied whenever it changes
   *  UNLESS the user has manually @mentioned someone this composer session
   *  (a card going from idle to running must not silently steal a message
   *  the owner just addressed to Henry). */
  defaultTo?: string;
  /** ATTACH CONTEXT (harness-config-ui design doc 5.5): what this message is
   *  ABOUT, shown above the input before a word is typed.
   *
   *  It lives here, in the shared composer, rather than beside it on the one
   *  screen that needed it first - the card chat renders this same component,
   *  so the improvement lands on both surfaces and there is still exactly ONE
   *  chat UI. The gesture is VS Code Copilot's "Attach Context": the owner sees
   *  what he is asking about, and can drop it. */
  contextChip?: string;
  onClearContext?: () => void;
  /** The message this one will answer (messenger-style reply, owner
   *  2026-09-25): shown as WhatsApp's quote bar above the input, dropped
   *  with its x. The SENDER attaches it to the send - this only shows it. */
  quote?: ReplyRef | null;
  onClearQuote?: () => void;
}) {
  const t = useTheme();
  const tr = useT();
  const [text, setTextRaw] = useState("");
  // Mirrors `text`, but written SYNCHRONOUSLY (refs aren't batched through
  // React's commit cycle the way state is). fire() reads this, not `text`:
  // typing fast and tapping Send in the same instant can deliver the final
  // onChangeText and the send tap's onPress before React has committed the
  // render from that last keystroke, so `fire`'s closure over `text` would
  // still be the PREVIOUS render's value - the message goes out missing
  // exactly the tail the user just typed. The ref has no such lag: its
  // write always happens inside onChangeText, which always runs before a
  // later tap's onPress (native events are FIFO).
  const textRef = useRef("");
  // picking "Antworten" puts the cursor in the input, like every messenger
  const inputRef = useRef<TextInput>(null);
  useEffect(() => { if (quote) inputRef.current?.focus(); }, [quote]);
  const [model, setModel] = useState("auto");
  const [thinking, setThinking] = useState("");
  const [mode, setMode] = useState(modeOptions?.[0]?.id ?? "");
  const [picker, setPicker] = useState(false);
  // Engine and model are ONE choice: the picker is grouped by engine, each with
  // its own models, and an engine that cannot run here stays visible - greyed,
  // with the reason - instead of vanishing or failing the turn later.
  // One group per engine TYPE (claude-desktop is a card capability grant, not a
  // second chat engine). A daemon without `models` on /engines (or no engine
  // with a catalog) falls back to the flat list the surface passed in.
  const { data: engineData } = useQuery({ queryKey: ["engines"], queryFn: () => api.engines(), staleTime: 60_000 });
  // Which OpenCode models REALLY run (a real request per model, spine/agent/
  // opencode_models.py): the `avail` on each model. The probe runs on the
  // daemon in the background; its progress and every result arrive through the
  // event stream's invalidation - no polling here.
  const qc = useQueryClient();
  const { data: probe } = useQuery({ queryKey: ["modelsProbe"], queryFn: () => api.modelsProbe(), staleTime: 30_000, enabled: picker });
  const [showDead, setShowDead] = useState(false);
  function probeModels(id?: string) {
    void api.probeModels(id).then((v) => { qc.setQueryData(["modelsProbe"], v); void qc.invalidateQueries({ queryKey: ["engines"] }); }).catch(() => {});
  }
  const modelGroups = useMemo(() => {
    const seen = new Set<string>();
    const out: { id: string; label: string; ready: boolean; models: { id: string; label?: string; desc?: string; avail?: ModelAvail }[] }[] = [];
    for (const e of engineData?.engines ?? []) {
      if (!e.enabled || !e.models?.length || seen.has(e.type)) continue;
      seen.add(e.type);
      out.push({ id: e.id, label: e.label, ready: e.status === "ready", models: e.models });
    }
    return out;
  }, [engineData]);
  const [modePicker, setModePicker] = useState(false);   // permission-mode sheet
  const [to, setTo] = useState(defaultTo);
  const manualTo = useRef(false);
  useEffect(() => { if (!manualTo.current) setTo(defaultTo); }, [defaultTo]);
  const [attachMenu, setAttachMenu] = useState(false);
  const [atts, setAtts] = useState<Attach[]>([]);
  const [seedKey, setSeedKey] = useState(0);
  const picking = useRef(false);   // Android: a double-tap otherwise opens two pickers
  // queue-while-busy: hold messages typed during a running turn, auto-send in
  // order on free. A LIST: the single slot silently overwrote the first held
  // message with the second (Paseo keeps queuedMessages per agent).
  const [queued, setQueued] = useState<{ id: number; text: string; opts: SteerOpts }[]>([]);
  const qid = useRef(0);
  const enqueue = (text: string, opts: SteerOpts) =>
    setQueued((q) => [...q, { id: ++qid.current, text, opts }]);
  const unqueue = (id: number) => setQueued((q) => q.filter((x) => x.id !== id));
  const flushing = useRef(false);

  // draft persistence — write-through on every edit, restore on mount
  function setText(v: string) {
    textRef.current = v;
    setTextRaw(v);
    if (draftKey) saveDraft(draftKey, v);
  }
  useEffect(() => {
    if (!draftKey) return;
    let live = true;
    loadDraft(draftKey).then((d) => { if (live && d) setTextRaw(d); });
    return () => { live = false; };
  }, [draftKey]);

  // picker persistence (model / thinking / mode) — same write-through-on-pick,
  // restore-on-mount shape as the text draft above. Explicit setters only (not
  // a blanket effect on [model, thinking, mode]): a save-on-every-change effect
  // would fire with the useState DEFAULTS on the very first render, racing the
  // async load below and permanently clobbering a real saved choice before it
  // is ever read back.
  function pickModel(id: string) { setModel(id); if (draftKey) saveOpts(draftKey, { model: id, thinking, mode }); }
  function pickThinking(id: string) { setThinking(id); if (draftKey) saveOpts(draftKey, { model, thinking: id, mode }); }
  function pickMode(id: string) { setMode(id); if (draftKey) saveOpts(draftKey, { model, thinking, mode: id }); }
  useEffect(() => {
    if (!draftKey) return;
    let live = true;
    loadOpts(draftKey).then((o) => {
      if (!live) return;
      if (o.model) setModel(o.model);
      if (o.thinking !== undefined) setThinking(o.thinking);
      // Restored unvalidated, like model above: modeOptions is itself async
      // (an API-loaded prop) and may not have arrived yet when this runs. An
      // id that turns out stale just fails the `.find()` in modeLabel and
      // renders nothing — never a crash — so there is nothing to guard here.
      if (o.mode) setMode(o.mode);
    });
    return () => { live = false; };
  }, [draftKey]);   // eslint-disable-line react-hooks/exhaustive-deps

  // external injection (rewind from transcript)
  if (seed && seed.key !== seedKey) { setSeedKey(seed.key); setText(seed.text); }

  // DICTATION (Paseo's composer dictation, data/use_dictation.ts): hold or tap
  // the mic and talk; the text is APPENDED to what is already typed (never
  // replaces it), either left for review or sent through the same fire() a
  // typed message uses - one send path, so queueing/steering/attachments all
  // behave exactly as they do for typing.
  const [note, setNote] = useState("");
  // CLEANUP (data/dictation_clean.ts): the raw transcript goes in at once; a few
  // seconds later the daemon's cleaned version swaps in IF the raw text still sits
  // verbatim in the field, with a one-tap undo. "Insert and send" skips it - the
  // owner chose speed there.
  const [clean, setClean] = useState<"idle" | "working" | "done">("idle");
  const lastClean = useRef<{ raw: string; cleaned: string } | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function cleanDictation(raw: string) {
    setClean("working");
    try {
      const r = await api.dictationClean(raw);
      const next = r.changed ? applyCleanup(textRef.current, raw, r.text) : null;
      if (!alive.current) return;
      if (next !== null) {
        setText(next);
        lastClean.current = { raw, cleaned: r.text };
        setClean("done");
      } else setClean("idle");
    } catch { if (alive.current) setClean("idle"); }    // an old daemon or a dead link: the raw text stands
  }
  function undoClean() {
    const lc = lastClean.current;
    lastClean.current = null;
    if (lc) { const next = undoCleanup(textRef.current, lc.cleaned, lc.raw); if (next !== null) setText(next); }
    setClean("idle");
  }
  const dict = useDictation({
    onText: (txt, send) => {
      const cur = textRef.current;
      setText(cur && !/\s$/.test(cur) ? `${cur} ${txt}` : cur + txt);
      lastClean.current = null;
      if (send) fire(); else void cleanDictation(txt);
    },
    onEmpty: () => { setNote(tr("dictation.empty")); setTimeout(() => setNote(""), 2500); },
  });
  const micDownAt = useRef(0);
  const stopOnRelease = useRef(false);
  const dictating = dict.state !== "idle";

  function buildOpts(): SteerOpts {
    return { model, thinking, ...(modeOptions ? { mode } : {}),
      ...(atts.length ? { attachments: atts } : {}), ...(to ? { to } : {}) };
  }

  // clear input + its persisted draft after a message leaves the composer
  function clearInput() { textRef.current = ""; setTextRaw(""); setAtts([]); if (draftKey) saveDraft(draftKey, ""); }

  // -- attachments ----------------------------------------------------------
  // The daemon SILENTLY skips oversized/extra files (turnopts.save_attachments),
  // so every refusal is surfaced here instead of the file just vanishing.
  function addAttachments(add: Attach[]) {
    if (!add.length) return;
    setAtts((cur) => {
      const { next, problem } = mergeAttachments(cur, add);
      if (problem) Alert.alert(tr("composer.notAttached"), problem);
      return next;
    });
  }

  async function runPick(fn: () => Promise<Attach[]>) {
    if (picking.current) return;
    picking.current = true;
    setAttachMenu(false);
    try { addAttachments(await fn()); }
    catch (e) { Alert.alert(tr("composer.attach"), String((e as Error).message)); }
    finally { picking.current = false; }
  }

  // Android can kill the activity behind the system picker; without this the
  // user's selection is silently lost when the app comes back.
  useEffect(() => { recoverPendingImages().then(addAttachments); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // Web: paste an image straight into the composer (the archived web composer
  // had this; RN has no paste event, so it is a DOM listener and web-only).
  useEffect(() => {
    if (!isWeb) return;
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.items ?? [])
        .filter((i) => i.kind === "file")
        .map((i) => i.getAsFile())
        .filter((f): f is File => !!f);
      if (!files.length) return;
      e.preventDefault();
      filesToAttachments(files).then(addAttachments);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // Web: drag & drop onto the window. Ignored while a turn is being submitted -
  // a drop landing mid-submit would be cleared by clearInput().
  useEffect(() => {
    if (!isWeb) return;
    const stop = (e: DragEvent) => { e.preventDefault(); };
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length) filesToAttachments(files).then(addAttachments);
    };
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", onDrop);
    return () => { window.removeEventListener("dragover", stop); window.removeEventListener("drop", onDrop); };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // when the agent frees up, deliver the OLDEST held message; the next one
  // follows when that turn frees up again (one turn per message, in order)
  useEffect(() => {
    if (!busy && queued.length && !flushing.current) {
      flushing.current = true;
      const q = queued[0]; unqueue(q.id);
      Promise.resolve(onSend(q.text, q.opts)).finally(() => { flushing.current = false; });
    }
  }, [busy, queued]);   // eslint-disable-line react-hooks/exhaustive-deps

  const matches = useMemo(() => {
    if (!slashCommands) return [];
    const m = text.match(/^\/(\S*)$/);
    return m ? slashCommands.filter((c) => c.name.startsWith(m[1].toLowerCase())) : [];
  }, [text, slashCommands]);

  // @mention: a token at the END of what's been typed so far (mid-message
  // addressing, not just at the start like slash commands). Only active
  // when a roster was actually handed in.
  const atMatches = useMemo(() => {
    if (!recipients?.length) return [];
    const m = text.match(/(?:^|\s)@(\S*)$/);
    if (!m) return [];
    const q = m[1].toLowerCase();
    return recipients.filter((r) => r.label.toLowerCase().startsWith(q));
  }, [text, recipients]);

  function pickRecipient(r: Recipient) {
    manualTo.current = true;
    setTo(r.id);
    setText(text.replace(/(?:^|\s)@\S*$/, (whole) => (whole.startsWith(" ") ? " " : "")));
  }

  const current = recipients?.find((r) => r.id === to);

  const thinkShort = tr(THINK.find((x) => x.id === thinking)?.key ?? "composer.thinkOff");
  const modeLabel = modeOptions?.find((m) => m.id === mode)?.label;
  const modelLabel = model === "auto" ? tr("composer.modelAutoShort")
    : model.replace("claude-", "").replace(/-\d{8}$/, "");

  function fire() {
    // Read textRef, not `text` state - see the comment on textRef's
    // declaration: a fast type-then-immediately-tap-send can otherwise send
    // a render behind, silently dropping the tail of the sentence.
    // an attachment alone is a valid message ("look at this") - give the agent
    // a sentence so the turn is never empty prose with a dangling file list
    const v = textRef.current.trim() || (atts.length ? tr("composer.seeAttachment") : "");
    if (!v) return;
    const opts = buildOpts();
    if (busy && onSteerLive) {
      // into the running turn if it can take it, else hold it
      onSteerLive(v, opts).then((ok) => { if (!ok) enqueue(v, opts); }, () => enqueue(v, opts));
    } else if (busy) enqueue(v, opts);   // hold until the agent is free
    else onSend(v, opts);
    clearInput();
  }

  const toolBtn = (active: boolean) => ({
    flexDirection: "row" as const, alignItems: "center" as const, gap: 4,
    backgroundColor: active ? t.accent + "26" : t.surface2,
    borderColor: active ? t.accent + "80" : t.borderSubtle, borderWidth: 1,
    borderRadius: 7, paddingHorizontal: 8, paddingVertical: 5,
  });

  return (
    <View style={{ borderTopWidth: 1, borderTopColor: t.glassBorder, paddingBottom: bottomInset }}>
      {/* THE CONTEXT CHIP, above everything: what this message is about. Placed
          over the input rather than inside it so it survives the draft being
          cleared and cannot be accidentally deleted with a backspace. */}
      {quote ? (
        <View testID="composer-quote" style={{ flexDirection: "row", alignItems: "center", gap: 8,
          marginHorizontal: 12, marginTop: 8, paddingLeft: 9, paddingRight: 6, paddingVertical: 6,
          borderLeftWidth: 3, borderLeftColor: t.accent2, backgroundColor: t.surface2, borderRadius: 7 }}>
          <Ionicons name="return-up-back-outline" size={14} color={t.accent2} />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text numberOfLines={1} style={{ color: t.accent2, fontSize: 11, fontWeight: "700" }}>
              {quote.by ? tr("composer.replyTo", { who: quote.by }) : tr("composer.replyToMsg")}
            </Text>
            <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 12 }}>{quote.text}</Text>
          </View>
          {onClearQuote ? (
            <Pressable testID="composer-quote-clear" onPress={onClearQuote} hitSlop={8}
              accessibilityLabel={tr("composer.replyCancel")}>
              <Ionicons name="close" size={15} color={t.txtTertiary} />
            </Pressable>
          ) : null}
        </View>
      ) : null}
      {contextChip ? (
        <View testID="composer-context"
          style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12,
            paddingTop: 8 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
            borderColor: t.accent, backgroundColor: t.surface2, borderRadius: 999,
            paddingLeft: 9, paddingRight: onClearContext ? 5 : 9, paddingVertical: 3, maxWidth: "100%" }}>
            <Ionicons name="at-outline" size={12} color={t.accent} />
            <Text numberOfLines={1} style={{ color: t.accent, fontSize: 11, fontWeight: "600", flexShrink: 1 }}>
              {contextChip}
            </Text>
            {onClearContext ? (
              <Pressable testID="composer-context-clear" onPress={onClearContext} hitSlop={8}>
                <Ionicons name="close" size={12} color={t.txtTertiary} />
              </Pressable>
            ) : null}
          </View>
        </View>
      ) : null}
      {/* @mention popover: pick who this message goes to */}
      {atMatches.length > 0 ? (
        <View style={{ backgroundColor: t.surface1, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
          {atMatches.map((r) => (
            <Pressable key={r.id} onPress={() => pickRecipient(r)}
              style={{ flexDirection: "row", gap: 8, paddingHorizontal: 12, paddingVertical: 8, alignItems: "baseline" }}>
              <Ionicons name={r.icon} size={14} color={r.color} style={{ alignSelf: "center" }} />
              <Text style={{ color: r.color, fontWeight: "700", fontSize: 13 }}>@{r.label}</Text>
              {r.hint ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{r.hint}</Text> : null}
            </Pressable>
          ))}
        </View>
      ) : null}

      {/* slash-command popover */}
      {matches.length > 0 ? (
        <View style={{ backgroundColor: t.surface1, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
          {matches.map((c) => (
            <Pressable key={c.name} onPress={() => setText(c.insert)}
              style={{ flexDirection: "row", gap: 8, paddingHorizontal: 12, paddingVertical: 8, alignItems: "baseline" }}>
              <Text style={{ color: t.accent, fontWeight: "700", fontSize: 13 }}>/{c.name}</Text>
              <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{c.hint}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      {/* control bar */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0 }}
        contentContainerStyle={{ gap: 6, paddingHorizontal: 8, paddingTop: 8, alignItems: "center" }}>
        <Pressable onPress={() => setPicker(true)} style={toolBtn(model !== "auto")}>
          <Ionicons name="sparkles-outline" size={13} color={model !== "auto" ? t.accent : t.txtSecondary} />
          <Text style={{ color: model !== "auto" ? t.accent : t.txtSecondary, fontSize: 12 }}>{modelLabel}</Text>
        </Pressable>
        <Pressable onPress={() => { const i = THINK.findIndex((x) => x.id === thinking); pickThinking(THINK[(i + 1) % THINK.length].id); }}
          style={toolBtn(thinking !== "")}>
          <Ionicons name="bulb-outline" size={13} color={thinking !== "" ? t.accent : t.txtSecondary} />
          <Text style={{ color: thinking !== "" ? t.accent : t.txtSecondary, fontSize: 12 }}>{thinkShort}</Text>
        </Pressable>
        {modeOptions && modeOptions.length > 1 ? (
          // PERMISSION MODE. A sheet, not a cycle (owner, 2026-09-12: the
          // cycling chip that only showed "Auto" read as model routing, and
          // nothing said four states sat behind it). The chip names what it
          // is; the sheet says what each mode allows.
          <Pressable onPress={() => setModePicker(true)} style={toolBtn(mode !== "auto")}
            accessibilityLabel={tr("composer.mode")}>
            <Ionicons name={MODE_ICON[mode] ?? "shield-half-outline"} size={13}
              color={mode !== "auto" ? t.accent : t.txtSecondary} />
            <Text style={{ color: mode !== "auto" ? t.accent : t.txtSecondary, fontSize: 12 }}>
              {tr("composer.modeChip", { mode: modeLabel ?? mode })}
            </Text>
          </Pressable>
        ) : null}
        <Pressable onPress={() => setAttachMenu(true)} style={toolBtn(atts.length > 0)}
          accessibilityLabel={tr("composer.addAttachment")}>
          <Ionicons name="attach" size={14} color={atts.length ? t.accent : t.txtSecondary} />
          <Text style={{ color: atts.length ? t.accent : t.txtSecondary, fontSize: 12 }}>
            {atts.length ? `${atts.length}/${MAX_FILES}` : tr("composer.attach")}
          </Text>
        </Pressable>
      </ScrollView>

      {/* attachment chips */}
      {atts.length ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0 }}
          contentContainerStyle={{ gap: 6, paddingHorizontal: 8, paddingTop: 8, alignItems: "center" }}>
          {atts.map((a, i) => (
            <View key={`${a.name}-${i}`} style={{ flexDirection: "row", alignItems: "center", gap: 6,
              backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1,
              borderRadius: 999, paddingLeft: 9, paddingRight: 5, paddingVertical: 4, maxWidth: 220 }}>
              <Ionicons name={(a.mime || "").startsWith("image/") ? "image-outline" : "document-outline"}
                size={12} color={t.txtTertiary} />
              <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 11.5, flexShrink: 1 }}>{a.name}</Text>
              <Pressable onPress={() => setAtts((c) => c.filter((_, j) => j !== i))} hitSlop={8}
                accessibilityLabel={tr("composer.removeAttachment", { name: a.name })}>
                <Ionicons name="close-circle" size={15} color={t.txtTertiary} />
              </Pressable>
            </View>
          ))}
        </ScrollView>
      ) : null}

      {/* queued-while-busy chip: held until the running turn frees up */}
      {queued.map((q) => (
        <View key={q.id} testID="composer-queued"
          style={{ flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: 8, marginTop: 8,
          backgroundColor: t.accent + "1A", borderColor: t.accent + "66", borderWidth: 1, borderRadius: 9, paddingHorizontal: 10, paddingVertical: 7 }}>
          <ActivityIndicator size="small" color={t.accent} />
          <Pressable style={{ flex: 1 }} onPress={() => { setText(q.text); unqueue(q.id); }}>
            <Text style={{ color: t.accent, fontSize: 11, fontWeight: "700" }}>{tr("composer.queued")}</Text>
            <Text numberOfLines={2} style={{ color: t.txtSecondary, fontSize: 12 }}>{q.text}</Text>
          </Pressable>
          <Pressable onPress={() => { unqueue(q.id); onSend(q.text, q.opts); }}
            style={{ backgroundColor: t.accent, borderRadius: 7, paddingHorizontal: 9, paddingVertical: 5 }}>
            <Text style={{ color: "#fff", fontSize: 12, fontWeight: "700" }}>{tr("composer.sendNow")}</Text>
          </Pressable>
          <Pressable onPress={() => unqueue(q.id)} hitSlop={8}>
            <Ionicons name="close" size={18} color={t.txtTertiary} />
          </Pressable>
        </View>
      ))}

      {/* recipient chip: who an unaddressed message goes to right now — never
          invisible, unlike the old Worker/Agent tab state it replaces. */}
      {current ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 8, paddingTop: 8 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 5,
            backgroundColor: current.color + "22", borderColor: current.color + "66", borderWidth: 1,
            borderRadius: 999, paddingLeft: 9, paddingRight: 6, paddingVertical: 4 }}>
            <Ionicons name={current.icon} size={12} color={current.color} />
            <Text style={{ color: current.color, fontSize: 11.5, fontWeight: "700" }}>{current.label}</Text>
            {manualTo.current ? (
              <Pressable onPress={() => { manualTo.current = false; setTo(defaultTo); }} hitSlop={8}>
                <Ionicons name="close-circle" size={13} color={current.color} />
              </Pressable>
            ) : null}
          </View>
        </View>
      ) : null}

      {note ? (
        <Text testID="dictation-note" style={{ color: t.txtTertiary, fontSize: 12, paddingHorizontal: 12, paddingTop: 6 }}>{note}</Text>
      ) : null}
      {!dictating && clean === "working" ? (
        <View testID="dictation-cleaning" style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingTop: 6 }}>
          <ActivityIndicator size="small" color={t.txtTertiary} />
          <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("dictation.cleaning")}</Text>
        </View>
      ) : null}
      {!dictating && clean === "done" ? (
        <View testID="dictation-cleaned" style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, paddingTop: 6 }}>
          <Ionicons name="sparkles" size={13} color={t.accent} />
          <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{tr("dictation.cleaned")}</Text>
          <Pressable testID="dictation-undo" onPress={undoClean} hitSlop={8}>
            <Text style={{ color: t.accent, fontSize: 12, fontWeight: "700" }}>{tr("dictation.undo")}</Text>
          </Pressable>
        </View>
      ) : null}

      {/* input row. While a dictation runs the TEXT FIELD gives way to the
          dictation bar - but the mic button itself stays mounted in the same
          spot: it is the target of a hold-to-talk, and a pressed element that
          unmounts under the finger never receives its release (measured in the
          browser e2e: the first version swapped the whole row and a held mic
          could not end the recording). */}
      <View style={{ flexDirection: "row", padding: 8, gap: 8, alignItems: "flex-end" }}>
        {dictating ? <DictationBar d={dict} inline /> : (
        <TextInput ref={inputRef} value={text} onChangeText={setText} multiline
          // Web/desktop: Enter sends, Shift+Enter is a newline (IME composing excluded).
          onKeyPress={isWeb ? (e: any) => {
            const ne = e.nativeEvent;
            if (ne.key === "Enter" && !ne.shiftKey && !ne.isComposing) { e.preventDefault?.(); fire(); }
          } : undefined}
          placeholder={placeholder ?? tr("composer.placeholder")} placeholderTextColor={t.txtPlaceholder}
          style={{ flex: 1, color: t.txtPrimary, backgroundColor: t.surface2, borderRadius: 10, padding: 10, maxHeight: 120,
            borderWidth: 1, borderColor: t.borderSubtle }} />
        )}
        {!dictating && busy && onStop ? (
          <Pressable onPress={onStop}
            style={{ backgroundColor: t.danger, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
            <Ionicons name="stop" size={20} color="#fff" />
          </Pressable>
        ) : null}
        {/* DICTATE: hold = push-to-talk (release inserts the text for review),
            tap = start and keep talking (the bar's pencil / arrow end it, and so
            does tapping this button again). Start is on press-in; a release
            ends the recording only after a HOLD of 600 ms+ or when this press
            began on an already-running recording - a short first tap must never
            end the recording it just began. */}
        {dict.usable ? (
          <Pressable testID="composer-dictate" accessibilityLabel={tr("dictation.start")}
            onPressIn={() => {
              micDownAt.current = Date.now();
              stopOnRelease.current = dict.state === "recording";
              dict.start();
            }}
            onPressOut={() => {
              if (stopOnRelease.current || Date.now() - micDownAt.current >= 600) dict.confirm(false);
              stopOnRelease.current = false;
            }}
            style={{ backgroundColor: dictating ? t.danger : t.surface2, borderColor: dictating ? t.danger : t.borderSubtle,
              borderWidth: 1, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
            <Ionicons name="mic" size={21} color={dictating ? "#fff" : t.accent} />
          </Pressable>
        ) : null}
        {dictating ? null : (
          /* send stays enabled while busy — the message is queued instead of dropped */
          <Pressable testID="composer-send" onPress={fire} disabled={!text.trim() && !atts.length}
            style={{ backgroundColor: t.accent, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center", opacity: (!text.trim() && !atts.length) ? 0.5 : 1 }}>
            <Ionicons name={busy ? "add" : "arrow-up"} size={22} color="#fff" />
          </Pressable>
        )}
      </View>

      {/* attachment source sheet. On web the photo picker IS a file dialog, so
          only offer "Datei"; camera is native-only. */}
      <Modal visible={attachMenu} transparent animationType="fade" onRequestClose={() => setAttachMenu(false)}>
        <Pressable onPress={() => setAttachMenu(false)}
          style={{ flex: 1, backgroundColor: t.backdrop, justifyContent: "flex-end", padding: 16 }}>
          <View style={{ backgroundColor: t.surface1, borderRadius: 14, borderWidth: 1, borderColor: t.glassBorder, overflow: "hidden" }}>
            {[
              ...(isWeb ? [] : [{ icon: "camera-outline" as const, label: tr("composer.takePhoto"), fn: takePhoto }]),
              { icon: "image-outline" as const, label: tr(isWeb ? "composer.pickImageWeb" : "composer.pickImage"), fn: pickImages },
              { icon: "document-outline" as const, label: tr("composer.pickFile"), fn: pickFiles },
            ].map((o, i) => (
              <Pressable key={o.label} onPress={() => runPick(o.fn)}
                style={{ flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 14,
                  borderTopWidth: i ? 1 : 0, borderTopColor: t.borderSubtle }}>
                <Ionicons name={o.icon} size={19} color={t.accent} />
                <Text style={{ color: t.txtPrimary, fontSize: 15 }}>{o.label}</Text>
              </Pressable>
            ))}
          </View>
          <Text style={{ color: t.txtTertiary, fontSize: 11, textAlign: "center", paddingTop: 10 }}>
            {tr("composer.attachLimits", { n: MAX_FILES, mb: MAX_MB })}
            {isWeb ? tr("composer.attachPasteDrop") : ""}
          </Text>
        </Pressable>
      </Modal>

      {/* model picker modal */}
      <Modal visible={picker} transparent animationType="fade" onRequestClose={() => setPicker(false)}>
        <Pressable onPress={() => setPicker(false)} style={{ flex: 1, backgroundColor: t.backdrop, justifyContent: "center", padding: 24 }}>
          <View style={{ backgroundColor: t.surface1, borderRadius: 14, borderWidth: 1, borderColor: t.glassBorder, maxHeight: "70%", overflow: "hidden" }}>
            <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", padding: 12 }}>{tr("composer.model")}</Text>
            <ScrollView>
              {(() => {
                const retest = (id: string) => (
                  <Pressable onPress={() => probeModels(id)} hitSlop={8} accessibilityLabel={tr("models.retest")}>
                    <Ionicons name="refresh-outline" size={16} color={t.txtTertiary} />
                  </Pressable>
                );
                const reasonOf = (a: ModelAvail) => tr("models.reason." + (["country", "auth", "missing", "timeout"].includes(a.status ?? "") ? a.status : "error"));
                const row = (id: string, label: string, desc: string, off = false, avail?: ModelAvail) => (
                  <Pressable key={id} disabled={off} onPress={() => { pickModel(id); setPicker(false); }}
                    style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 14, paddingVertical: 11,
                      borderTopWidth: 1, borderTopColor: t.borderSubtle, opacity: off ? 0.45 : 1 }}>
                    <Ionicons name={id === model ? "radio-button-on" : "radio-button-off"} size={16} color={id === model ? t.accent : t.txtTertiary} />
                    <View style={{ flex: 1 }}>
                      <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{label}</Text>
                      {desc ? <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{desc}</Text> : null}
                    </View>
                    {avail?.state === "untested" ? (
                      <>
                        <Text style={{ color: t.txtTertiary, fontSize: 11, fontStyle: "italic" }}>{tr("models.untested")}</Text>
                        {retest(id)}
                      </>
                    ) : null}
                    {avail?.state === "testing" ? (
                      <>
                        <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("models.testing")}</Text>
                        <ActivityIndicator size="small" color={t.accent} />
                      </>
                    ) : null}
                  </Pressable>
                );
                // a model a real request proved dead is NOT a row of the list: it
                // sits in a collapsed group with the reason, never selectable
                const deadGroup = (g: { id: string; models: { id: string; label?: string; avail?: ModelAvail }[] }) => {
                  if (g.models.length === 0) return [];
                  return [
                    <Pressable key={"dead-" + g.id} onPress={() => setShowDead((v) => !v)}
                      style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 14, paddingVertical: 10, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
                      <Ionicons name={showDead ? "chevron-down" : "chevron-forward"} size={14} color={t.txtTertiary} />
                      <Text style={{ color: t.txtTertiary, fontSize: 12, fontWeight: "600" }}>{tr("models.unavailable", { n: g.models.length })}</Text>
                    </Pressable>,
                    ...(showDead ? g.models.map((m) => (
                      <View key={m.id} style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 14, paddingVertical: 9, paddingLeft: 32, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
                        <View style={{ flex: 1 }}>
                          <Text style={{ color: t.txtTertiary, fontSize: 13 }}>{m.label || m.id}</Text>
                          <Text style={{ color: t.danger, fontSize: 11.5 }}>{m.avail ? reasonOf(m.avail) : ""}</Text>
                        </View>
                        {retest(m.id)}
                      </View>
                    )) : []),
                  ];
                };
                const auto = row("auto", tr("composer.modelAuto"), "");
                if (modelGroups.length === 0) {
                  // /models returns objects {id,label,desc}; older/custom setups may
                  // return plain id strings. Normalise both so we never render an
                  // object as a React child (that crashed the whole app -> black).
                  return [auto, ...models.filter((raw) => typeof raw === "string" || raw.avail?.state !== "failed").map((raw) => {
                    const id = typeof raw === "string" ? raw : raw.id;
                    return row(id, typeof raw === "string" ? raw : (raw.label || raw.id), typeof raw === "string" ? "" : (raw.desc || ""), false,
                      typeof raw === "string" ? undefined : raw.avail);
                  })];
                }
                return [auto, ...modelGroups.flatMap((g) => {
                  const probed = g.models.some((m) => !!m.avail);
                  const dead = g.models.filter((m) => m.avail?.state === "failed");
                  return [
                    <View key={"h-" + g.id} style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 14, paddingTop: 12, paddingBottom: 4, gap: 8 }}>
                      <Text style={{ flex: 1, color: t.txtTertiary, fontSize: 11, fontWeight: "700" }}>
                        {g.label}{g.ready ? "" : " · " + tr("new.engineMissing")}
                      </Text>
                      {probed && g.ready ? (
                        <Pressable disabled={!!probe?.running} onPress={() => probeModels()} hitSlop={6}
                          style={{ flexDirection: "row", alignItems: "center", gap: 5, opacity: probe?.running ? 0.7 : 1 }}>
                          {probe?.running ? <ActivityIndicator size="small" color={t.accent} /> : <Ionicons name="pulse-outline" size={14} color={t.accent} />}
                          <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>
                            {probe?.running ? tr("models.checking", { done: probe.done, total: probe.total }) : tr("models.check")}
                          </Text>
                        </Pressable>
                      ) : null}
                    </View>,
                    ...g.models.filter((m) => m.avail?.state !== "failed").map((m) => row(m.id, m.label || m.id, m.desc || "", !g.ready, m.avail)),
                    ...deadGroup({ id: g.id, models: dead }),
                  ];
                })];
              })()}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>

      {/* permission-mode sheet - same shape as the model picker so the two
          read as one system: caption, one row per option, radio, a line on
          what the option allows. Current mode is the checked row, whatever
          order the surface passed. */}
      {modeOptions ? (
        <Modal visible={modePicker} transparent animationType="fade" onRequestClose={() => setModePicker(false)}>
          <Pressable onPress={() => setModePicker(false)} style={{ flex: 1, backgroundColor: t.backdrop, justifyContent: "center", padding: 24 }}>
            <View style={{ backgroundColor: t.surface1, borderRadius: 14, borderWidth: 1, borderColor: t.glassBorder, maxHeight: "70%", overflow: "hidden" }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", paddingHorizontal: 12, paddingTop: 12 }}>{tr("composer.mode")}</Text>
              <Text style={{ color: t.txtTertiary, fontSize: 11.5, paddingHorizontal: 12, paddingTop: 4, paddingBottom: 10 }}>{tr("composer.mode.hint")}</Text>
              <ScrollView>
                {modeOptions.map((m) => {
                  const desc = m.desc ?? (MODE_DESC[m.id] ? tr(MODE_DESC[m.id]) : "");
                  const on = m.id === mode;
                  return (
                    <Pressable key={m.id} onPress={() => { pickMode(m.id); setModePicker(false); }}
                      accessibilityRole="radio" accessibilityState={{ checked: on }}
                      style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 14, paddingVertical: 11, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
                      <Ionicons name={on ? "radio-button-on" : "radio-button-off"} size={16} color={on ? t.accent : t.txtTertiary} />
                      <Ionicons name={MODE_ICON[m.id] ?? "shield-half-outline"} size={15} color={on ? t.accent : t.txtSecondary} />
                      <View style={{ flex: 1 }}>
                        <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{m.label}</Text>
                        {desc ? <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{desc}</Text> : null}
                      </View>
                    </Pressable>
                  );
                })}
              </ScrollView>
            </View>
          </Pressable>
        </Modal>
      ) : null}
    </View>
  );
}
