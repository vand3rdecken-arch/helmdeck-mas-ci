import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useState } from "react";
import { ActivityIndicator, Modal, Platform, Pressable, ScrollView, Text, View } from "react-native";

import { api } from "@/data/client";
import { useConfig } from "@/data/config";
import type { InviteRow } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Inline, Section } from "./sign_off";

// "Mitglied einladen" - the ONE way a person joins the workspace (owner
// decree 2026-09-09, 22:15: creating a user and inviting them are the same
// act, and the role is chosen HERE, at invitation time, like Jira).
//
// What this replaced: a "create user" form where the owner typed someone
// else's password (and then had to transmit it), PLUS a separate registration
// panel holding one global, never-expiring, infinitely reusable code whose
// role came from a workspace-wide default. Three surfaces, one of which
// silently decided the role of everyone who used the other.
//
// Built as a sibling of gxp_activate.tsx, not a copy: same modal shell, same
// Section from sign_off.tsx, same house rules (never Alert.alert from inside
// the dialog - errors render inline; white, not accentTxt, on the filled
// button). The role picker is a LIST with one sentence per role rather than a
// ChipPick, because "operator" means nothing to the person choosing it and
// picking wrong is a permission mistake, not a preference.
const ROLES = ["client", "operator"] as const;
type InviteRole = (typeof ROLES)[number];
const TTLS = [1, 7, 30];

/** Where the invited person should open the app. On web that is wherever the
 *  owner is looking at it right now (works for the packaged desktop shell and
 *  a LAN browser alike); on a phone the daemon's own URL is the only base the
 *  app knows, and it is right whenever the teammate is on the same network.
 *  Returns "" when there is nothing honest to build a link from - the code
 *  alone still works, so the button simply does not appear. */
function inviteBase(): string {
  if (Platform.OS === "web") {
    const o = globalThis.location?.origin ?? "";
    if (o && !o.startsWith("file:")) return o.replace(/\/+$/, "");
  }
  const base = useConfig.getState().baseUrl ?? "";
  return base.includes("10.0.2.2") || base.includes("localhost") ? "" : base.replace(/\/+$/, "");
}

export function TeamInvite({ onClose, onCreated }: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const t = useTheme();
  const tr = useT();
  const [role, setRole] = useState<InviteRole>("client");
  const [ttl, setTtl] = useState(7);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [made, setMade] = useState<InviteRow | null>(null);
  const [copied, setCopied] = useState("");

  const link = made ? `${inviteBase()}/?invite=${made.code}` : "";

  async function create() {
    setBusy(true); setErr(null);
    try {
      const inv = await api.createInvite(role, ttl);
      setMade(inv);
      onCreated();               // the open-invitations list below refreshes now,
    } catch (e) {                // not when the dialog eventually closes
      setErr(String((e as Error).message));
    } finally { setBusy(false); }
  }

  async function copy(what: "code" | "link") {
    await Clipboard.setStringAsync(what === "code" ? made!.code : link);
    setCopied(what);             // inline confirmation, not an Alert stacked on a modal
  }

  return (
    <Modal transparent animationType="fade" visible statusBarTranslucent onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: t.backdrop, justifyContent: "center", padding: 16 }}>
        <View style={{ backgroundColor: t.surface1, borderColor: t.accent + "66", borderWidth: 1,
          borderRadius: 16, maxHeight: "92%", overflow: "hidden", width: "100%", maxWidth: 460, alignSelf: "center" }}>

          <View style={{ flexDirection: "row", alignItems: "center", gap: 8, padding: 16, paddingBottom: 10 }}>
            <Ionicons name="person-add" size={17} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 12, fontWeight: "700", letterSpacing: 0.8, flex: 1 }}>
              {tr("team.inviteMember").toUpperCase()}
            </Text>
            <Pressable onPress={onClose} hitSlop={10} accessibilityLabel={tr("ui.cancel")}>
              <Ionicons name="close" size={19} color={t.txtTertiary} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={{ padding: 16, paddingTop: 0, gap: 18 }}>
            {!made ? (
              <>
                <Section title={tr("team.inviteRole")}>
                  <View style={{ borderColor: t.glassBorder, borderWidth: 1, borderRadius: 10, overflow: "hidden" }}>
                    {ROLES.map((r, i) => (
                      <Pressable key={r} onPress={() => setRole(r)}
                        style={{ flexDirection: "row", alignItems: "center", gap: 10, padding: 12,
                          borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder,
                          backgroundColor: role === r ? t.accent + "14" : "transparent" }}>
                        <Ionicons name={role === r ? "radio-button-on" : "radio-button-off"}
                          size={17} color={role === r ? t.accent : t.txtTertiary} />
                        <View style={{ flex: 1, gap: 2 }}>
                          <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{tr(`team.role.${r}`)}</Text>
                          <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr(`team.role.${r}.sub`)}</Text>
                        </View>
                      </Pressable>
                    ))}
                  </View>
                </Section>

                <Section title={tr("team.inviteTtl")}>
                  <View style={{ flexDirection: "row", gap: 8 }}>
                    {TTLS.map((d) => (
                      <Pressable key={d} onPress={() => setTtl(d)}
                        style={{ flex: 1, alignItems: "center", paddingVertical: 9, borderRadius: 9, borderWidth: 1,
                          borderColor: ttl === d ? t.accent : t.glassBorder,
                          backgroundColor: ttl === d ? t.accent + "14" : "transparent" }}>
                        <Text style={{ color: ttl === d ? t.accent : t.txtSecondary, fontSize: 12.5,
                          fontWeight: ttl === d ? "700" : "500" }}>
                          {d === 1 ? tr("team.ttlOneDay") : tr("team.ttlDays", { n: d })}
                        </Text>
                      </Pressable>
                    ))}
                  </View>
                </Section>

                {err ? <Inline t={t} text={err} /> : null}

                <Pressable onPress={create} disabled={busy}
                  style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
                    backgroundColor: busy ? t.surface2 : t.accent, borderRadius: 12, paddingVertical: 13 }}>
                  {busy ? <ActivityIndicator color={t.txtSecondary} /> : null}
                  <Text style={{ color: busy ? t.txtSecondary : "#fff", fontSize: 14.5, fontWeight: "600" }}>
                    {tr("team.createInvite")}
                  </Text>
                </Pressable>
              </>
            ) : (
              <>
                <View style={{ gap: 4 }}>
                  <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "600" }}>
                    {tr("team.inviteReady", { role: tr(`team.role.${made.role}`) })}
                  </Text>
                  <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("team.inviteReadyHint")}</Text>
                </View>

                <View style={{ backgroundColor: t.surface2, borderColor: t.accent + "55", borderWidth: 1,
                  borderRadius: 12, paddingVertical: 18, alignItems: "center" }}>
                  <Text selectable style={{ color: t.accent, fontSize: 26, letterSpacing: 5, fontWeight: "700",
                    fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" }}>{made.code}</Text>
                </View>

                <View style={{ flexDirection: "row", gap: 8 }}>
                  <Pressable onPress={() => copy("code")}
                    style={{ flex: 1, alignItems: "center", paddingVertical: 11, borderRadius: 10,
                      borderWidth: 1, borderColor: t.glassBorder }}>
                    <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600" }}>{tr("team.copyCode")}</Text>
                  </Pressable>
                  {inviteBase() ? (
                    <Pressable onPress={() => copy("link")}
                      style={{ flex: 1, alignItems: "center", paddingVertical: 11, borderRadius: 10,
                        borderWidth: 1, borderColor: t.glassBorder }}>
                      <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600" }}>{tr("team.copyLink")}</Text>
                    </Pressable>
                  ) : null}
                </View>
                {copied ? (
                  <Text style={{ color: t.ok, fontSize: 12 }}>{tr("team.copied")}</Text>
                ) : null}
                {link ? (
                  <Text selectable numberOfLines={2} style={{ color: t.txtTertiary, fontSize: 11 }}>{link}</Text>
                ) : null}

                <Pressable onPress={onClose}
                  style={{ alignItems: "center", justifyContent: "center", backgroundColor: t.accent,
                    borderRadius: 12, paddingVertical: 13 }}>
                  <Text style={{ color: "#fff", fontSize: 14.5, fontWeight: "600" }}>{tr("ui.close")}</Text>
                </Pressable>
              </>
            )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}
