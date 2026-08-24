import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { api, ApiError } from "@/data/client";
import type { SignMeaning, Track } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Inline, MEANINGS, Section, meaningTone } from "./sign_off";

// Batch sign-off: ONE password, N independent signatures.
//
// 21 CFR 11.200 speaks of a SERIES of signings, and batch approval with a
// single credential entry is established practice in regulated document and
// LIMS systems - provided every record gets its own full manifestation (name,
// UTC time, meaning) and the signer sees each item at signing time. Both hold
// here: the daemon writes N separate records, each bound to its OWN commit
// pair, and every card is listed with its own meaning selector.
//
// This is the real UX lever the design identified. The signing-session
// concession in 11.200(a)(1)(i)(A) only saves typing a username; approving
// three cards in one ceremony rather than three ceremonies is what actually
// changes someone's day.
//
// Caveat carried over from the design (gxp-mode-design.md 2.5): this is the one
// point with genuine interpretive room. A conservative auditor may want a
// separate password entry per record. The single dialog still exists, so that
// stance is a policy decision, not a rebuild.

export function SignOffBatch({ cards, onClose, onSigned }: {
  cards: Track[];
  onClose: () => void;
  /** landed = the ids that got an APPROVED signature and can now be moved. */
  onSigned: (msg: string, landed: string[]) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const [meanings, setMeanings] = useState<Record<string, SignMeaning>>(
    () => Object.fromEntries(cards.map((c) => [c.id, "approved" as SignMeaning])));
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [perCard, setPerCard] = useState<Record<string, string>>({});

  // A rejection still has to say why - same rule as the single dialog, enforced
  // for every card here so the request is not sent to be refused server-side.
  const missingReason = cards.some(
    (c) => meanings[c.id] === "rejected" && !(reasons[c.id] || "").trim());
  const canSubmit = !!password && !busy && !missingReason && cards.length > 0;

  async function submit() {
    if (!canSubmit) return;
    setBusy(true); setErr(null); setPerCard({});
    try {
      const r = await api.signBatch(
        cards.map((c) => ({ card: c.id, meaning: meanings[c.id],
                            reason: reasons[c.id] || "" })), password);
      const landed = r.results.filter((x) => x.ok && meanings[x.card] === "approved")
                              .map((x) => x.card);
      const nOk = r.results.filter((x) => x.ok).length;
      const failed = r.results.filter((x) => !x.ok);
      onSigned(tr("sign.batchSome", { ok: String(nOk), n: String(cards.length) }), landed);
      if (failed.length) {
        // NOT all-or-nothing: a card that drifted since the list was drawn
        // fails alone. Stay open and show which one and why - closing here
        // would leave the batch silently half-applied.
        setPerCard(Object.fromEntries(failed.map((x) => [x.card, x.error || "?"])));
        setErr(nOk ? tr("sign.batchSome", { ok: String(nOk), n: String(cards.length) })
                   : tr("sign.batchNone"));
        setPassword("");
        return;
      }
      onClose();
    } catch (e) {
      const ae = e as ApiError;
      setErr(ae?.status === 401 ? tr("sign.errBadPassword") : String((e as Error).message));
      setPassword("");
    } finally { setBusy(false); }
  }

  return (
    <Modal transparent animationType="fade" visible statusBarTranslucent onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: t.backdrop, justifyContent: "center", padding: 16 }}>
        <View style={{ backgroundColor: t.surface1, borderColor: t.human + "66", borderWidth: 1,
          borderRadius: 16, maxHeight: "92%", overflow: "hidden" }}>

          <View style={{ flexDirection: "row", alignItems: "center", gap: 8, padding: 16, paddingBottom: 4 }}>
            <Ionicons name="shield-checkmark" size={17} color={t.human} />
            <Text style={{ color: t.human, fontSize: 12, fontWeight: "700", letterSpacing: 0.8, flex: 1 }}>
              {tr("sign.batchTitle").toUpperCase()}
            </Text>
            <Pressable onPress={onClose} hitSlop={10} accessibilityLabel={tr("ui.cancel")}>
              <Ionicons name="close" size={19} color={t.txtTertiary} />
            </Pressable>
          </View>
          <Text style={{ color: t.txtTertiary, fontSize: 11.5, paddingHorizontal: 16, paddingBottom: 8 }}>
            {tr("sign.batchHint")}
          </Text>

          <ScrollView contentContainerStyle={{ padding: 16, paddingTop: 0, gap: 12 }}>
            {cards.map((c) => (
              <BatchRow
                key={c.id} card={c}
                meaning={meanings[c.id]}
                reason={reasons[c.id] || ""}
                error={perCard[c.id]}
                onMeaning={(m) => { setMeanings((p) => ({ ...p, [c.id]: m })); setErr(null); }}
                onReason={(v) => setReasons((p) => ({ ...p, [c.id]: v }))}
              />
            ))}

            <Section title={tr("sign.signature")}>
              <TextInput
                value={password} onChangeText={(v) => { setPassword(v); setErr(null); }}
                placeholder={tr("sign.passwordPh")} placeholderTextColor={t.txtPlaceholder}
                secureTextEntry autoCapitalize="none" onSubmitEditing={submit}
                style={{ color: t.txtPrimary, backgroundColor: t.surface2,
                  borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8,
                  padding: 10, fontSize: 14 }}
              />
              <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 15 }}>
                {tr("sign.legal")}
              </Text>
            </Section>

            {err ? <Inline t={t} text={err} /> : null}
          </ScrollView>

          <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8,
            padding: 14, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
            <Pressable onPress={onClose} style={{ paddingVertical: 10, paddingHorizontal: 16 }}>
              <Text style={{ color: t.txtSecondary, fontWeight: "500", fontSize: 13.5 }}>
                {tr("ui.cancel")}
              </Text>
            </Pressable>
            <Pressable onPress={submit} disabled={!canSubmit}
              accessibilityState={{ disabled: !canSubmit }}
              style={{ flexDirection: "row", alignItems: "center", gap: 8,
                paddingVertical: 10, paddingHorizontal: 18, borderRadius: 10,
                backgroundColor: t.human, opacity: canSubmit ? 1 : 0.45 }}>
              {busy ? <ActivityIndicator size="small" color="#fff" /> : null}
              <Text style={{ color: "#fff", fontWeight: "700", fontSize: 13.5 }}>
                {busy ? tr("sign.submitting") : tr("sign.ctaN", { n: String(cards.length) })}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/** One card in the batch: title, its own meaning, its own reason, and - only
 *  when it failed - its own error. The per-card bench stays collapsed; with
 *  three expanded nobody scrolls as far as the password field. */
function BatchRow({ card, meaning, reason, error, onMeaning, onReason }: {
  card: Track; meaning: SignMeaning; reason: string; error?: string;
  onMeaning: (m: SignMeaning) => void; onReason: (v: string) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const needsReason = meaning === "rejected" && !reason.trim();
  return (
    <View style={{ borderWidth: 1, borderColor: error ? t.danger + "66" : t.borderSubtle,
      borderRadius: 10, padding: 10, gap: 8 }}>
      <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600" }} numberOfLines={2}>
        {card.id}  ·  {card.task}
      </Text>
      <View style={{ flexDirection: "row", gap: 6 }}>
        {MEANINGS.map((m) => {
          const on = meaning === m.id;
          const tone = meaningTone(t, m.id);
          return (
            <Pressable key={m.id} onPress={() => onMeaning(m.id)}
              accessibilityRole="radio" accessibilityState={{ selected: on }}
              style={{ flex: 1, alignItems: "center", paddingVertical: 7, borderRadius: 8,
                borderWidth: 1, borderColor: on ? tone : t.borderSubtle,
                backgroundColor: on ? tone + "1A" : "transparent" }}>
              <Text style={{ color: on ? tone : t.txtSecondary, fontSize: 12,
                fontWeight: on ? "700" : "500" }}>{tr(m.label)}</Text>
            </Pressable>
          );
        })}
      </View>
      {meaning === "rejected" ? (
        <TextInput
          value={reason} onChangeText={onReason}
          placeholder={tr("sign.reasonPh")} placeholderTextColor={t.txtPlaceholder}
          style={{ color: t.txtPrimary, backgroundColor: t.surface2,
            borderColor: needsReason ? t.danger : t.borderSubtle,
            borderWidth: 1, borderRadius: 8, padding: 9, fontSize: 13 }}
        />
      ) : null}
      {error ? <Text style={{ color: t.danger, fontSize: 11.5 }}>{error}</Text> : null}
    </View>
  );
}
