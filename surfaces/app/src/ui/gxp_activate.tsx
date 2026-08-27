import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { api, ApiError } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Inline, Section } from "./sign_off";

// GxP-mode activation (ops/docs/backlog/rbac-gxp card 6; ops/docs/
// gxp-mode-design.md §2.7's own text: "Einschalten: Owner-Aktion, selbst
// signiert, in der Ereignissenke"). Deliberately built as a sibling of
// sign_off.tsx, not a copy: same modal shell, same Section/Inline, same
// t.human "a person did this" token, same four house rules (select-never-
// sends is moot here - there's no meaning selector - but never Alert.alert,
// white-not-accentTxt on the filled button, and t.human as the one place a
// human action gets the app's primary color, all still apply).
//
// Deactivating is NOT a feature of this dialog, on purpose - it stays
// host-filesystem + daemon-restart only (spine/auth/gxp.py's own RESIDUAL
// RISK section explains why: this UI path is only as trustworthy as the
// daemon process serving it, and the whole point of gxp.lock living outside
// policy_live.json is that turning the mode OFF needs a stronger bar than a
// password over that same daemon).
export function GxpActivate({ onClose, onActivated }: {
  onClose: () => void;
  onActivated: (msg: string) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const { data: st, refetch } = useQuery({ queryKey: ["gxpState"], queryFn: api.gxpState });
  const [reposText, setReposText] = useState("");
  const [fourEyes, setFourEyes] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const repoLines = reposText.split("\n").map((s) => s.trim()).filter(Boolean);
  // Empty box = workspace-wide scope (undefined, not []) - gxp.py treats an
  // explicit empty list and "no list at all" differently (repos=None means
  // the whole workspace), so this must not send [] by accident.
  const repos = repoLines.length ? repoLines : undefined;
  const canSubmit = !!password && !busy;

  async function submit() {
    if (!canSubmit) return;
    setBusy(true); setErr(null);
    try {
      const rec = await api.activateGxp(repos, fourEyes, password);
      qc.invalidateQueries({ queryKey: ["gxpState"] });
      onActivated(rec.scope === "workspace"
        ? tr("gxp.activatedWorkspace", { who: rec.activated_by ?? "" })
        : tr("gxp.activatedRepos", { who: rec.activated_by ?? "", n: rec.repos?.length ?? 0 }));
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

          <View style={{ flexDirection: "row", alignItems: "center", gap: 8, padding: 16, paddingBottom: 10 }}>
            <Ionicons name="shield-checkmark" size={17} color={t.human} />
            <Text style={{ color: t.human, fontSize: 12, fontWeight: "700", letterSpacing: 0.8, flex: 1 }}>
              {tr("gxp.title").toUpperCase()}
            </Text>
            <Pressable onPress={onClose} hitSlop={10} accessibilityLabel={tr("ui.cancel")}>
              <Ionicons name="close" size={19} color={t.txtTertiary} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={{ padding: 16, paddingTop: 0, gap: 18 }}>
            <Text style={{ color: t.txtSecondary, fontSize: 12.5, lineHeight: 18 }}>
              {tr("gxp.explain")}
            </Text>

            <Section title={tr("gxp.currentState")}>
              {st?.active ? (
                <Text style={{ color: t.ok, fontSize: 12.5 }}>
                  {st.scope === "workspace"
                    ? tr("gxp.activeWorkspace", { who: st.activated_by ?? "?" })
                    : tr("gxp.activeRepos", { who: st.activated_by ?? "?", n: st.repos?.length ?? 0 })}
                </Text>
              ) : (
                <Text style={{ color: t.txtTertiary, fontSize: 12.5 }}>{tr("gxp.inactive")}</Text>
              )}
            </Section>

            <Section title={tr("gxp.scope")}>
              <Text style={{ color: t.txtTertiary, fontSize: 11.5, marginTop: -2 }}>
                {tr("gxp.scopeHint")}
              </Text>
              <TextInput
                value={reposText} onChangeText={setReposText}
                placeholder={tr("gxp.reposPh")} placeholderTextColor={t.txtPlaceholder}
                multiline autoCapitalize="none"
                style={{ color: t.txtPrimary, backgroundColor: t.surface2,
                  borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8,
                  padding: 10, fontSize: 13, minHeight: 60, maxHeight: 110, fontFamily: "monospace" }}
              />
              <Text style={{ color: t.txtTertiary, fontSize: 11 }}>
                {repos ? tr("gxp.scopeRepos", { n: repos.length }) : tr("gxp.scopeWorkspace")}
              </Text>
              {/* scope only ever grows (spine/auth/gxp.py) - said explicitly so
                  a returning owner isn't surprised a previously-listed repo is
                  still there even though this box shows only the NEW ones. */}
              {st?.active ? (
                <Text style={{ color: t.txtTertiary, fontSize: 11, fontStyle: "italic" }}>
                  {tr("gxp.scopeGrowsOnly")}
                </Text>
              ) : null}
            </Section>

            <Section title={tr("gxp.fourEyes")}>
              <Pressable onPress={() => setFourEyes((v) => !v)}
                style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                <Ionicons name={fourEyes ? "checkbox" : "square-outline"} size={19}
                  color={fourEyes ? t.human : t.txtTertiary} />
                <Text style={{ color: t.txtSecondary, fontSize: 12.5, flex: 1 }}>
                  {tr("gxp.fourEyesLabel")}
                </Text>
              </Pressable>
            </Section>

            <Section title={tr("sign.signature")}>
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
                {tr("gxp.legal")}
              </Text>
            </Section>

            {err ? <Inline t={t} text={err} onRetry={refetch} /> : null}
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
              {/* white, NOT t.accentTxt - see sign_off.tsx's note on this exact trap */}
              <Text style={{ color: "#fff", fontWeight: "700", fontSize: 13.5 }}>
                {busy ? tr("gxp.activating") : tr("gxp.activate")}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}
