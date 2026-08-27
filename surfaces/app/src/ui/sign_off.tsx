import { Ionicons } from "@expo/vector-icons";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { api, ApiError } from "@/data/client";
import type { SignMeaning, SignSubject, Track } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";

// The GxP sign-off dialog. ops/docs/gxp-mode-design.md 3.
//
// Four house rules this obeys, each of them a lesson someone already paid for:
//
//  1. SELECTING NEVER SENDS. Doctrine from card_question.tsx:116-119 -
//     auto-submitting on tap made a mis-tap irreversible. That matters more
//     here than anywhere else in the app: this tap merges and deploys.
//  2. NEVER Alert.alert. It is a no-op on react-native-web (new.tsx:52-55), so
//     every failure renders inline where the user is standing.
//  3. White on a t.human fill, NOT t.accentTxt - that token is accent-COLOURED
//     text, so on a filled button the label vanishes (card_question.tsx:254-257).
//  4. t.human is the colour. It is the app's "a person did this" token and is
//     the primary colour nowhere else; the one human act in the whole system
//     should not look like every machine action.
//
// It also says out loud what is about to happen (merge + deploy). Today a
// single 13px ghost pill does both with no confirmation at all, so "what
// happens" is genuinely new information, not ceremony.

export const MEANINGS: { id: SignMeaning; label: string; sub: string }[] = [
  { id: "approved", label: "sign.approved", sub: "sign.approvedSub" },
  { id: "reviewed", label: "sign.reviewed", sub: "sign.reviewedSub" },
  { id: "rejected", label: "sign.rejected", sub: "sign.rejectedSub" },
];

/** Colour per meaning. A lookup rather than a keyof index, so adding a
 *  meaning is a compile error here instead of a silent undefined colour. */
export function meaningTone(t: ThemeTokens, m: SignMeaning): string {
  return m === "approved" ? t.ok : m === "reviewed" ? t.human : t.danger;
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const t = useTheme();
  return (
    <View style={{ gap: 6 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", letterSpacing: 0.6 }}>
        {title}
      </Text>
      {children}
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: "row", gap: 10 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 12.5, width: 74 }}>{label}</Text>
      <Text style={{ color: t.txtSecondary, fontSize: 12.5, flex: 1 }}>{value}</Text>
    </View>
  );
}

export function SignOff({ card, onClose, onSigned }: {
  card: Track;
  onClose: () => void;
  onSigned: (msg: string) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const [subj, setSubj] = useState<SignSubject | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [meaning, setMeaning] = useState<SignMeaning | null>(null);
  const [reason, setReason] = useState("");
  const [password, setPassword] = useState("");
  const [showFiles, setShowFiles] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadErr(null); setSubj(null);
    try { setSubj(await api.signSubject(card.id)); }
    catch (e) { setLoadErr(String((e as Error).message)); }
  }, [card.id]);

  useEffect(() => { load(); }, [load]);

  // Four-eyes is decided by the daemon, but showing it BEFORE the password is
  // typed saves the user from filling the whole form for a refusal we can
  // already see coming.
  const fourEyesBlocked = !!subj?.four_eyes
    && !!subj.dispatched_by && subj.dispatched_by === subj.signer.name;

  const needsReason = meaning === "rejected";
  const canSubmit = !!meaning && !!password && !busy && !!subj?.subject
    && (!needsReason || !!reason.trim())
    && !(meaning === "approved" && fourEyesBlocked);

  async function submit() {
    if (!canSubmit || !meaning) return;
    setBusy(true); setErr(null);
    try {
      await api.sign(card.id, meaning, reason, password);
      onSigned(
        meaning === "approved" ? tr("sign.doneApproved", { who: subj!.signer.name, at: "" })
        : meaning === "reviewed" ? tr("sign.doneReviewed")
        : tr("sign.doneRejected"));
      onClose();
    } catch (e) {
      const ae = e as ApiError;
      // 401 is the wrong password; 409 means the card stopped being signable
      // between opening the dialog and pressing the button (a new commit, or
      // main moved). The second one needs a reload, not a retry, so it says so.
      setErr(ae?.status === 401 ? tr("sign.errBadPassword")
        : ae?.status === 409 ? String(ae.message)
        : String((e as Error).message));
      setPassword("");
    } finally { setBusy(false); }
  }

  const s = subj?.subject;
  return (
    <Modal transparent animationType="fade" visible statusBarTranslucent onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: t.backdrop, justifyContent: "center", padding: 16 }}>
        <View style={{ backgroundColor: t.surface1, borderColor: t.human + "66", borderWidth: 1,
          borderRadius: 16, maxHeight: "92%", overflow: "hidden" }}>

          <View style={{ flexDirection: "row", alignItems: "center", gap: 8, padding: 16, paddingBottom: 10 }}>
            <Ionicons name="shield-checkmark" size={17} color={t.human} />
            <Text style={{ color: t.human, fontSize: 12, fontWeight: "700", letterSpacing: 0.8, flex: 1 }}>
              {tr("sign.title").toUpperCase()}
            </Text>
            <Pressable onPress={onClose} hitSlop={10} accessibilityLabel={tr("ui.cancel")}>
              <Ionicons name="close" size={19} color={t.txtTertiary} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={{ padding: 16, paddingTop: 0, gap: 18 }}>
            <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "600" }}>
              {card.id}  ·  {card.task}
            </Text>

            {!subj && !loadErr ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <ActivityIndicator color={t.human} />
                <Text style={{ color: t.txtTertiary, fontSize: 12.5 }}>{tr("sign.loading")}</Text>
              </View>
            ) : null}

            {loadErr ? <Inline t={t} text={loadErr} onRetry={load} retryLabel={tr("sign.reload")} /> : null}

            {/* The card is not signable at all - almost always uncommitted work.
                No point rendering a form that cannot be submitted. */}
            {subj && subj.blocked ? (
              <Inline t={t} text={subj.blocked} onRetry={load} retryLabel={tr("sign.reload")} />
            ) : null}

            {s ? (
              <>
                <Section title={tr("sign.whatHappens")}>
                  <Text style={{ color: t.txtSecondary, fontSize: 12.5 }}>
                    →  {tr("sign.willMerge", { branch: s.branch, base: "main" })}
                  </Text>
                  <Text style={{ color: t.txtSecondary, fontSize: 12.5 }}>
                    →  {tr("sign.willDeploy")}
                  </Text>
                </Section>

                <Section title={tr("sign.bench")}>
                  <Row label={tr("sign.commits", { n: String(s.commits) })}
                       value={s.shortstat || "—"} />
                  <Row label="Range" value={tr("sign.range", {
                    base: s.base.slice(0, 8), head: s.head.slice(0, 8) })} />
                  {subj?.dispatched_by ? (
                    <Row label="" value={tr("sign.dispatchedBy", { who: subj.dispatched_by })} />
                  ) : null}
                  {s.files.length ? (
                    <Pressable onPress={() => setShowFiles((v) => !v)} hitSlop={6}>
                      <Text style={{ color: t.accent, fontSize: 12.5 }}>
                        {showFiles ? tr("sign.filesHide") : tr("sign.files")}
                      </Text>
                    </Pressable>
                  ) : null}
                  {showFiles ? (
                    <View style={{ backgroundColor: t.surface2, borderRadius: 8, padding: 10, gap: 2,
                      maxHeight: 160 }}>
                      <ScrollView>
                        {s.files.map((f) => (
                          <Text key={f} style={{ color: t.txtTertiary, fontSize: 11.5 }}
                                numberOfLines={1}>{f}</Text>
                        ))}
                      </ScrollView>
                    </View>
                  ) : null}
                </Section>

                <Section title={tr("sign.meaning")}>
                  <Text style={{ color: t.txtTertiary, fontSize: 11.5, marginTop: -2 }}>
                    {tr("sign.meaningHint")}
                  </Text>
                  {MEANINGS.map((m) => {
                    const on = meaning === m.id;
                    const blocked = m.id === "approved" && fourEyesBlocked;
                    const tone = meaningTone(t, m.id);
                    return (
                      <Pressable
                        key={m.id}
                        disabled={blocked}
                        onPress={() => { setMeaning(m.id); setErr(null); }}
                        accessibilityRole="radio"
                        accessibilityState={{ selected: on, disabled: blocked }}
                        style={{ flexDirection: "row", alignItems: "center", gap: 10, padding: 10,
                          borderRadius: 10, borderWidth: 1, opacity: blocked ? 0.45 : 1,
                          borderColor: on ? tone : t.borderSubtle,
                          backgroundColor: on ? tone + "1A" : "transparent" }}>
                        <Ionicons name={on ? "radio-button-on" : "radio-button-off"}
                                  size={17} color={on ? tone : t.txtPlaceholder} />
                        <View style={{ flex: 1 }}>
                          <Text style={{ color: on ? tone : t.txtPrimary, fontSize: 13.5, fontWeight: "600" }}>
                            {tr(m.label)}
                          </Text>
                          <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>
                            {blocked ? tr("sign.errFourEyes") : tr(m.sub)}
                          </Text>
                        </View>
                      </Pressable>
                    );
                  })}
                </Section>

                <Section title={tr("sign.reason")}>
                  <TextInput
                    value={reason} onChangeText={setReason}
                    placeholder={tr("sign.reasonPh")} placeholderTextColor={t.txtPlaceholder}
                    multiline
                    style={{ color: t.txtPrimary, backgroundColor: t.surface2,
                      borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8,
                      padding: 10, fontSize: 14, minHeight: 44, maxHeight: 110 }}
                  />
                  {needsReason && !reason.trim() ? (
                    <Text style={{ color: t.danger, fontSize: 11.5 }}>{tr("sign.reasonRequired")}</Text>
                  ) : null}
                </Section>

                <Section title={tr("sign.signature")}>
                  <Row label={tr("sign.signer")}
                       value={`${subj!.signer.name} (${subj!.signer.role})`} />
                  <TextInput
                    value={password} onChangeText={(v) => { setPassword(v); setErr(null); }}
                    placeholder={tr("sign.passwordPh")} placeholderTextColor={t.txtPlaceholder}
                    secureTextEntry autoCapitalize="none"
                    onSubmitEditing={submit}
                    style={{ color: t.txtPrimary, backgroundColor: t.surface2,
                      borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8,
                      padding: 10, fontSize: 14 }}
                  />
                  <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 15 }}>
                    {tr("sign.legal")}
                  </Text>
                </Section>

                {err ? <Inline t={t} text={err} /> : null}
              </>
            ) : null}
          </ScrollView>

          <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8,
            padding: 14, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
            <Pressable onPress={onClose} style={{ paddingVertical: 10, paddingHorizontal: 16 }}>
              <Text style={{ color: t.txtSecondary, fontWeight: "500", fontSize: 13.5 }}>
                {tr("ui.cancel")}
              </Text>
            </Pressable>
            <Pressable
              onPress={submit}
              disabled={!canSubmit}
              accessibilityState={{ disabled: !canSubmit }}
              style={{ flexDirection: "row", alignItems: "center", gap: 8,
                paddingVertical: 10, paddingHorizontal: 18, borderRadius: 10,
                backgroundColor: t.human, opacity: canSubmit ? 1 : 0.45 }}>
              {busy ? <ActivityIndicator size="small" color="#fff" /> : null}
              {/* white, NOT t.accentTxt - see the note at the top of this file */}
              <Text style={{ color: "#fff", fontWeight: "700", fontSize: 13.5 }}>
                {busy ? tr("sign.submitting") : tr("sign.submit")}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/** Inline failure box. Never an Alert - see rule 2 at the top. */
export function Inline({ t, text, onRetry, retryLabel }: {
  t: ThemeTokens; text: string; onRetry?: () => void; retryLabel?: string;
}) {
  return (
    <View style={{ backgroundColor: t.danger + "1A", borderColor: t.danger + "66", borderWidth: 1,
      borderRadius: 8, padding: 10, gap: 6 }}>
      <Text style={{ color: t.danger, fontSize: 12.5, lineHeight: 17 }}>{text}</Text>
      {onRetry ? (
        <Pressable onPress={onRetry} hitSlop={6}>
          <Text style={{ color: t.accent, fontSize: 12.5, fontWeight: "600" }}>{retryLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
