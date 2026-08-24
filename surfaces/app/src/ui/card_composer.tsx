import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Alert, Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useTheme } from "@/theme";
import type { SteerOpts } from "@/data/client";
import {
  type Attach, filesToAttachments, isWeb, MAX_FILES, MAX_MB, mergeAttachments, pickFiles,
  pickImages, recoverPendingImages, takePhoto,
} from "@/data/attachments";
import { loadDraft, loadOpts, saveDraft, saveOpts } from "@/data/drafts";
import { useT } from "@/i18n";

export interface SlashCommand { name: string; hint: string; insert: string }
export interface ModeOption { id: string; label: string }

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
  onVoice,
}: {
  onSend: (text: string, opts: SteerOpts) => void | Promise<void>;
  busy?: boolean;
  onStop?: () => void;
  models: (string | { id: string; label?: string; desc?: string })[];
  modeOptions?: ModeOption[];
  slashCommands?: SlashCommand[];
  placeholder?: string;
  seed?: { text: string; key: number };
  bottomInset?: number;
  draftKey?: string;   // persist in-progress text per surface (board / each card)
  /** Open voice mode. Passed in rather than mounted here so the composer stays
   *  a pure input surface: only the chat screen knows how to run a turn, and
   *  voice must go through that same path (one chat, spoken or typed). Omitted
   *  on surfaces that have no voice — the button then does not exist at all,
   *  rather than existing and refusing. */
  onVoice?: () => void;
}) {
  const t = useTheme();
  const tr = useT();
  const [text, setTextRaw] = useState("");
  const [model, setModel] = useState("auto");
  const [thinking, setThinking] = useState("");
  const [mode, setMode] = useState(modeOptions?.[0]?.id ?? "");
  const [picker, setPicker] = useState(false);
  const [attachMenu, setAttachMenu] = useState(false);
  const [atts, setAtts] = useState<Attach[]>([]);
  const [seedKey, setSeedKey] = useState(0);
  const picking = useRef(false);   // Android: a double-tap otherwise opens two pickers
  // queue-while-busy: hold a message typed during a running turn, auto-send on free
  const [queued, setQueued] = useState<{ text: string; opts: SteerOpts } | null>(null);
  const flushing = useRef(false);

  // draft persistence — write-through on every edit, restore on mount
  function setText(v: string) {
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

  function buildOpts(): SteerOpts {
    return { model, thinking, ...(modeOptions ? { mode } : {}), ...(atts.length ? { attachments: atts } : {}) };
  }

  // clear input + its persisted draft after a message leaves the composer
  function clearInput() { setTextRaw(""); setAtts([]); if (draftKey) saveDraft(draftKey, ""); }

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

  // when the agent frees up, deliver the held message
  useEffect(() => {
    if (!busy && queued && !flushing.current) {
      flushing.current = true;
      const q = queued; setQueued(null);
      Promise.resolve(onSend(q.text, q.opts)).finally(() => { flushing.current = false; });
    }
  }, [busy, queued]);   // eslint-disable-line react-hooks/exhaustive-deps

  const matches = useMemo(() => {
    if (!slashCommands) return [];
    const m = text.match(/^\/(\S*)$/);
    return m ? slashCommands.filter((c) => c.name.startsWith(m[1].toLowerCase())) : [];
  }, [text, slashCommands]);

  const thinkShort = tr(THINK.find((x) => x.id === thinking)?.key ?? "composer.thinkOff");
  const modeLabel = modeOptions?.find((m) => m.id === mode)?.label;
  const modelLabel = model === "auto" ? tr("composer.modelAutoShort")
    : model.replace("claude-", "").replace(/-\d{8}$/, "");

  function fire() {
    // an attachment alone is a valid message ("look at this") - give the agent
    // a sentence so the turn is never empty prose with a dangling file list
    const v = text.trim() || (atts.length ? tr("composer.seeAttachment") : "");
    if (!v) return;
    const opts = buildOpts();
    if (busy) setQueued({ text: v, opts });   // hold until the agent is free
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
          <Pressable onPress={() => { const i = modeOptions.findIndex((m) => m.id === mode); pickMode(modeOptions[(i + 1) % modeOptions.length].id); }}
            style={toolBtn(true)}>
            <Ionicons name="options-outline" size={13} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 12 }}>{modeLabel}</Text>
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
      {queued ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: 8, marginTop: 8,
          backgroundColor: t.accent + "1A", borderColor: t.accent + "66", borderWidth: 1, borderRadius: 9, paddingHorizontal: 10, paddingVertical: 7 }}>
          <ActivityIndicator size="small" color={t.accent} />
          <Pressable style={{ flex: 1 }} onPress={() => { setText(queued.text); setQueued(null); }}>
            <Text style={{ color: t.accent, fontSize: 11, fontWeight: "700" }}>{tr("composer.queued")}</Text>
            <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 12 }}>{queued.text}</Text>
          </Pressable>
          <Pressable onPress={() => { const q = queued; setQueued(null); onSend(q.text, q.opts); }}
            style={{ backgroundColor: t.accent, borderRadius: 7, paddingHorizontal: 9, paddingVertical: 5 }}>
            <Text style={{ color: "#fff", fontSize: 12, fontWeight: "700" }}>{tr("composer.sendNow")}</Text>
          </Pressable>
          <Pressable onPress={() => setQueued(null)} hitSlop={8}>
            <Ionicons name="close" size={18} color={t.txtTertiary} />
          </Pressable>
        </View>
      ) : null}

      {/* input row */}
      <View style={{ flexDirection: "row", padding: 8, gap: 8, alignItems: "flex-end" }}>
        <TextInput value={text} onChangeText={setText} multiline
          placeholder={placeholder ?? tr("composer.placeholder")} placeholderTextColor={t.txtPlaceholder}
          style={{ flex: 1, color: t.txtPrimary, backgroundColor: t.surface2, borderRadius: 10, padding: 10, maxHeight: 120,
            borderWidth: 1, borderColor: t.borderSubtle }} />
        {busy && onStop ? (
          <Pressable onPress={onStop}
            style={{ backgroundColor: t.danger, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
            <Ionicons name="stop" size={20} color="#fff" />
          </Pressable>
        ) : null}
        {/* Empty composer -> voice; anything typed -> send. The same swap
            ChatGPT makes, and for the same reason: the two are never both the
            obvious next action, so one slot can carry both without a choice. */}
        {onVoice && !text.trim() && !atts.length ? (
          <Pressable onPress={onVoice} accessibilityLabel={tr("voice.open")}
            style={{ backgroundColor: t.accent2, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
            <Ionicons name="mic" size={21} color="#fff" />
          </Pressable>
        ) : (
          /* send stays enabled while busy — the message is queued instead of dropped */
          <Pressable onPress={fire} disabled={!text.trim() && !atts.length}
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
              {["auto", ...models].map((raw) => {
                // /models returns objects {id,label,desc}; older/custom setups may
                // return plain id strings. Normalise both so we never render an
                // object as a React child (that crashed the whole app -> black).
                const id = typeof raw === "string" ? raw : raw.id;
                const label = id === "auto" ? tr("composer.modelAuto")
                  : typeof raw === "string" ? raw : (raw.label || raw.id);
                const desc = typeof raw === "string" ? "" : (raw.desc || "");
                return (
                  <Pressable key={id} onPress={() => { pickModel(id); setPicker(false); }}
                    style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 14, paddingVertical: 11, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
                    <Ionicons name={id === model ? "radio-button-on" : "radio-button-off"} size={16} color={id === model ? t.accent : t.txtTertiary} />
                    <View style={{ flex: 1 }}>
                      <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{label}</Text>
                      {desc ? <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{desc}</Text> : null}
                    </View>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}
