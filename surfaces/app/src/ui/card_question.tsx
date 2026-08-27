// The worker's open question, as real BUTTONS (Paseo adoption, Phase 2.4).
//
// HelmDeck runs its workers headless, where a question can only ever come back
// as prose - so a blocked card used to end its turn with "A oder B?" and park,
// and the owner had to retype the answer as a fresh steer. This panel is the
// other half of daemon/ask.py: the worker's question arrives typed, the owner
// taps a choice, and the SAME session continues with it.
//
// It is deliberately NOT a feed item. It is pinned above the composer because
// (a) it must stay reachable when the reader has scrolled up into the history,
// and (b) the feed is replaced wholesale on every long-poll tick, which would
// throw away half-made selections.
import { useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, Text, TextInput, useWindowDimensions, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/data/client";
import type { AskQuestion, PendingQuestion } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";

function Option({ label, description, on, multi, onPress, t }: {
  label: string; description?: string; on: boolean; multi: boolean;
  onPress: () => void; t: ThemeTokens;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole={multi ? "checkbox" : "radio"}
      // aria-checked in addition to accessibilityState: the legacy state prop
      // does not reach the DOM as aria-checked on web, so a screen reader could
      // not tell which option was selected (caught by the browser a11y check in
      // ops/tests/uifix_question_interact.py).
      aria-checked={on}
      accessibilityState={{ checked: on }}
      accessibilityLabel={label}
      style={{
        flexDirection: "row", alignItems: "flex-start", gap: 9,
        backgroundColor: on ? t.accent + "22" : t.surface2,
        borderColor: on ? t.accent : t.borderSubtle, borderWidth: 1,
        borderRadius: 9, paddingHorizontal: 11, paddingVertical: 9,
      }}>
      <Ionicons
        name={multi ? (on ? "checkbox" : "square-outline") : (on ? "radio-button-on" : "radio-button-off")}
        size={16} color={on ? t.accent : t.txtTertiary} style={{ marginTop: 1 }} />
      <View style={{ flex: 1 }}>
        <Text style={{ color: on ? t.accent : t.txtPrimary, fontSize: 13.5, fontWeight: on ? "700" : "600" }}>
          {label}
        </Text>
        {description ? (
          <Text style={{ color: t.txtSecondary, fontSize: 11.5, lineHeight: 16, marginTop: 2 }}>
            {description}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

export function QuestionPanel({ cardId, question, onAnswered }: {
  cardId: string; question: PendingQuestion; onAnswered: () => void;
}) {
  const t = useTheme();
  const tr = useT();
  const [idx, setIdx] = useState(0);
  // header -> chosen labels. A Set per question so multiSelect is natural and
  // single-select is just "replace the set".
  const [picked, setPicked] = useState<Record<string, string[]>>({});
  // header -> the owner's own typed answer (the Paseo "Other" escape hatch),
  // kept beside `picked` so a preset choice and free text never clobber each
  // other in the same state slot.
  const [custom, setCustom] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  // The panel is PINNED above the composer (it must survive the feed being
  // replaced on every long-poll tick, which would drop a half-made choice). But
  // pinned + full-height hid the whole conversation behind it ("kann nicht sehen
  // was vorher kam"). So it is now COLLAPSIBLE and height-capped: even expanded
  // it never eats more than ~half the screen (the question+options scroll inside
  // that cap), and one tap on the header collapses it to a single line so the
  // transcript is fully readable - Paseo-style, the question never blocks history.
  const [open, setOpen] = useState(true);
  const { height: winH } = useWindowDimensions();

  const qs = question.questions ?? [];
  const q = qs[Math.min(idx, qs.length - 1)];
  if (!q) return null;
  const chosen = picked[q.header] ?? [];
  const freeText = (custom[q.header] ?? "").trim();
  const answered = (x: AskQuestion) => (picked[x.header] ?? []).length > 0 || (custom[x.header] ?? "").trim().length > 0;
  const last = idx >= qs.length - 1;
  const answeredAll = qs.every(answered);

  async function submit(next: Record<string, string[]>) {
    setBusy(true);
    try {
      // single-select travels as a plain string (what the daemon renders back
      // to the worker); multiSelect keeps the array. Free text rides the same
      // channel: appended for multiSelect, or standing alone for single-select.
      const answers: Record<string, string | string[]> = {};
      for (const x of qs) {
        const v = next[x.header] ?? [];
        const c = (custom[x.header] ?? "").trim();
        answers[x.header] = x.multiSelect
          ? (c ? [...v, c] : v)
          : (c || v[0]);
      }
      await api.answer(cardId, answers, question.id);
      onAnswered();
    } catch (e) {
      Alert.alert(tr("card.q.failedTitle"), String((e as Error).message));
      setBusy(false);
    }
  }

  // Tapping SELECTS; it never sends. Auto-submitting on tap made a mis-tap
  // irreversible (the answer goes straight into the worker's next turn) and
  // left the confirm button rendered but permanently dead. Select-then-confirm
  // is one extra tap and always predictable.
  function choose(label: string) {
    const cur = picked[q.header] ?? [];
    const next = q.multiSelect
      ? (cur.includes(label) ? cur.filter((l) => l !== label) : [...cur, label])
      : [label];
    setPicked({ ...picked, [q.header]: next });
    // single-select is one answer: tapping an option retracts a typed one so
    // the two never both count. multiSelect keeps free text as an extra answer.
    if (!q.multiSelect && freeText) setCustom({ ...custom, [q.header]: "" });
  }

  function typeOwn(text: string) {
    setCustom({ ...custom, [q.header]: text });
    // mirror choose(): on single-select, typing retracts any tapped option.
    if (!q.multiSelect && text.trim() && chosen.length) setPicked({ ...picked, [q.header]: [] });
  }

  return (
    <View style={{ paddingHorizontal: 12, paddingTop: 8 }}>
      <View style={{
        backgroundColor: t.accent + "14", borderColor: t.accent + "66", borderWidth: 1,
        borderRadius: 12, padding: 11, gap: 9,
        // Never taller than ~half the viewport: the transcript above always
        // keeps room, and the question's own body scrolls within this cap.
        maxHeight: open ? Math.round(winH * 0.5) : undefined,
      }}>
        <Pressable onPress={() => setOpen(!open)} accessibilityRole="button"
          accessibilityLabel={open ? tr("card.q.collapse") : tr("card.q.expand")}
          style={{ flexDirection: "row", alignItems: "center", gap: 7 }}>
          <Ionicons name="help-circle" size={16} color={t.accent} />
          <Text style={{ color: t.accent, fontSize: 11, fontWeight: "700", letterSpacing: 0.4 }}>
            {tr("card.q.title")}
          </Text>
          <View style={{ flex: 1 }} />
          <Text style={{ color: t.txtTertiary, fontSize: 11 }}>
            {qs.length > 1
              ? tr("card.q.progress", { n: idx + 1, total: qs.length })
              : tr("card.q.count", { n: q.options.length })}
          </Text>
          {/* the toggle: chevron-up = "collapse", chevron-down = "expand" */}
          <Ionicons name={open ? "chevron-up" : "chevron-down"} size={16} color={t.txtSecondary} />
        </Pressable>

        {!open ? (
          // Collapsed: one tappable preview line so the transcript is fully
          // visible; tap anywhere on the card to expand and answer.
          <Pressable onPress={() => setOpen(true)}>
            <Text numberOfLines={2} style={{ color: t.txtSecondary, fontSize: 12.5, lineHeight: 17 }}>
              {q.question}
            </Text>
            <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600", marginTop: 4 }}>
              {answeredAll ? tr("card.q.tapAnswer") : tr("card.q.tapExpand")}
            </Text>
          </Pressable>
        ) : (
        <>
        {/* Question text + options scroll TOGETHER inside the height cap, so a
            long question or a long option list never pushes the free-text box
            and the answer button off screen (the whole panel is bounded above). */}
        <ScrollView style={{ flexShrink: 1 }} contentContainerStyle={{ gap: 9 }}
          showsVerticalScrollIndicator persistentScrollbar keyboardShouldPersistTaps="handled">
          <Text style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "600", lineHeight: 19 }}>
            {q.question}
          </Text>
          <View style={{ gap: 6 }}>
            {q.options.map((o) => (
              <Option key={o.label} label={o.label} description={o.description}
                on={chosen.includes(o.label)} multi={q.multiSelect}
                onPress={() => choose(o.label)} t={t} />
            ))}
          </View>
        </ScrollView>

        {/* The Paseo "Other" escape hatch: none of the offered options ever has
            to be the answer - the owner can always type his own, exactly as he
            can in a fresh steer. On single-select this and the options are the
            same answer slot (choose()/typeOwn() keep them mutually exclusive);
            on multiSelect it is one more selected answer. */}
        <View style={{ gap: 5 }}>
          <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "600", letterSpacing: 0.3 }}>
            {tr("card.q.otherLabel")}
          </Text>
          <TextInput
            value={custom[q.header] ?? ""}
            onChangeText={typeOwn}
            placeholder={tr("card.q.otherPh")}
            placeholderTextColor={t.txtTertiary}
            multiline
            scrollEnabled
            accessibilityLabel={tr("card.q.otherLabel")}
            style={{
              color: t.txtPrimary, fontSize: 13, minHeight: 38,
              // Capped, NOT open-ended: a multiline TextInput with no maxHeight
              // grows with its content, and pasting a long answer pushed the
              // hint + Antworten-button out of the panel's own height cap
              // (visually clipped/unreachable - "can't paste long answer").
              // Past this height it scrolls INTERNALLY instead of growing, so
              // the button stays put and any length of pasted text still works.
              maxHeight: 120,
              backgroundColor: t.surface2,
              borderColor: freeText ? t.accent : t.borderSubtle, borderWidth: 1,
              borderRadius: 9, paddingHorizontal: 11, paddingVertical: 9,
            }} />
        </View>

        <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 15 }}>
          {tr("card.q.hint")}
        </Text>

        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          {idx > 0 ? (
            <Pressable onPress={() => setIdx(idx - 1)} hitSlop={8}
              accessibilityRole="button" accessibilityLabel={tr("card.q.back")}
              style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 6, paddingHorizontal: 4 }}>
              <Ionicons name="chevron-back" size={14} color={t.txtSecondary} />
              <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{tr("card.q.back")}</Text>
            </Pressable>
          ) : null}
          <View style={{ flex: 1 }} />
          {busy ? <ActivityIndicator size="small" color={t.accent} /> : null}
          {/* Always present, so the panel never depends on a tap that silently
              sends: selecting is one step, answering is another. */}
          <Pressable
            disabled={busy || !answered(q) || (last && !answeredAll)}
            onPress={() => (last ? void submit(picked) : setIdx(idx + 1))}
            accessibilityRole="button"
            accessibilityState={{ disabled: !answered(q) }}
            style={{
              flexDirection: "row", alignItems: "center", gap: 5,
              backgroundColor: answered(q) ? t.accent : t.surface2,
              borderColor: answered(q) ? t.accent : t.borderSubtle, borderWidth: 1,
              opacity: busy ? 0.6 : 1,
              borderRadius: 9, paddingHorizontal: 14, paddingVertical: 9,
            }}>
            {/* NOT t.accentTxt: that token is accent-COLOURED text (same value
                as t.accent), so on an accent fill the label vanished entirely.
                White on accent is the house idiom - see the composer's send
                button. */}
            <Text style={{ color: answered(q) ? "#fff" : t.txtTertiary, fontSize: 13, fontWeight: "700" }}>
              {tr(last ? "card.q.send" : "card.q.next")}
            </Text>
            <Ionicons name={last ? "arrow-up" : "chevron-forward"} size={14}
              color={answered(q) ? "#fff" : t.txtTertiary} />
          </Pressable>
        </View>
        </>
        )}
      </View>
    </View>
  );
}
