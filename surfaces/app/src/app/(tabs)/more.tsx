import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAnalytics } from "@/data/analytics";
import { useBlockerVoice } from "@/data/blocker_voice";
import { api, AuthRequired } from "@/data/client";
import { useConfig } from "@/data/config";
import { FEEDBACK_BOARD_URL, openFeedbackBoard } from "@/data/feedback";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { ApkUpdateBanner } from "@/ui/apk_update";
import { Panel, SectionLabel } from "@/ui/kit";
import { Hint, Toggle } from "@/ui/settings_sections";
import { VersionFooter } from "@/ui/updates_info";

// The phone's "everything else" list, grouped so 9 flat rows become 3 scannable
// blocks. Every row carries a one-line subtitle (more.sub.*) - the labels alone
// ("Automatik", "Prozesse") proved opaque even to the owner - and every icon is
// UNIQUE within the list (three near-identical git glyphs before).
const GROUPS: readonly [string, readonly (readonly [string, string, keyof typeof Ionicons.glyphMap, string])[]][] = [
  ["more.grp.control", [
    ["automation", "nav.automation", "options-outline", "more.sub.automation"],
    ["processes", "nav.processes", "git-network-outline", "more.sub.processes"],
    ["connectors", "nav.connectors", "extension-puzzle-outline", "more.sub.connectors"],
  ]],
  ["more.grp.logs", [
    ["history", "nav.history", "time-outline", "more.sub.history"],
    ["escalations", "nav.escalations", "alert-circle-outline", "more.sub.escalations"],
    ["sessions", "nav.sessions", "chatbubbles-outline", "more.sub.sessions"],
    ["recordings", "nav.recordings", "videocam-outline", "more.sub.recordings"],
  ]],
  ["more.grp.system", [
    ["settings", "nav.settings", "settings-outline", "more.sub.settings"],
    ["loopmap", "nav.loopmap", "map-outline", "more.sub.loopmap"],
  ]],
] as const;

export default function MoreTab() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { baseUrl, token, set, applyPairing, relayMode } = useConfig();
  const qc = useQueryClient();
  const [url, setUrl] = useState(baseUrl);
  const [tok, setTok] = useState(token);
  const [pair, setPair] = useState("");
  const [pairMsg, setPairMsg] = useState("");
  // The colour of the status line is driven by this kind, never by sniffing the
  // message text - the message is translated, its meaning must not be.
  const [pairKind, setPairKind] = useState<"info" | "ok" | "err">("info");
  const [pairBusy, setPairBusy] = useState(false);
  const paired = relayMode();
  // Once paired, the two big connection panels collapse to one status line -
  // they were the top half of the screen on a phone that is long since paired.
  const [connOpen, setConnOpen] = useState(false);
  const showConn = !paired || connOpen;
  const analyticsOn = useAnalytics((s) => s.enabled);
  const setAnalytics = useAnalytics((s) => s.setEnabled);
  const blockerVoiceOn = useBlockerVoice((s) => s.enabled);
  const setBlockerVoice = useBlockerVoice((s) => s.setEnabled);

  // Apply the code, then PROVE the connection with a real round-trip before
  // claiming success — a parsed-but-dead code (expired window, relay down,
  // wrong keys) must say what's wrong, not "Gekoppelt" (no silent fallback).
  async function doPair() {
    const applied = applyPairing(pair);
    if (!applied.ok) { setPairKind("err"); setPairMsg(applied.reason); return; }
    setPairBusy(true); setPairKind("info"); setPairMsg(tr("settings.more.verifying"));
    try {
      await api.me();
      qc.invalidateQueries();   // board/dashboard ran pre-pairing (empty) - reload against the new config
      setPairKind("ok");
      setPairMsg(applied.mode === "relay"
        ? tr("settings.more.pairedRelayOk")
        : tr("settings.more.pairedLanOk"));
      setPair("");
    } catch (e) {
      setPairKind("err");
      setPairMsg(e instanceof AuthRequired
        ? tr("settings.more.tokenRejected")
        : tr("settings.more.noAnswer", { err: String((e as Error).message) }));
    } finally { setPairBusy(false); }
  }

  const field = { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle,
    borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 13 } as const;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", paddingTop: insets.top + 10, paddingHorizontal: 16, paddingBottom: 6 }}>
        {tr("nav.more")}
      </Text>
      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 120, gap: 10 }}>
        {paired ? (
          <Panel>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: t.ok }} />
              <Text style={{ color: t.txtPrimary, fontSize: 13, flex: 1 }}>{tr("more.conn.connectedRelay")}</Text>
              <Pressable onPress={() => setConnOpen((o) => !o)}>
                <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>
                  {connOpen ? tr("more.conn.hide") : tr("more.conn.edit")}
                </Text>
              </Pressable>
            </View>
          </Panel>
        ) : null}
        {showConn ? (
        <Panel>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <SectionLabel text={tr("settings.more.pairSection")} />
            <Text style={{ color: paired ? t.ok : t.txtTertiary, fontSize: 11 }}>
              {paired ? tr("settings.more.pairedRelay") : tr("settings.more.notPaired")}
            </Text>
          </View>
          <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 6 }}>
            {tr("settings.more.pairHelp")}
          </Text>
          <Pressable onPress={() => router.push("/scan" as never)}
            style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
              backgroundColor: t.accent, borderRadius: 8, padding: 12, marginBottom: 10 }}>
            <Ionicons name="qr-code-outline" size={18} color="#fff" />
            <Text style={{ color: "#fff", fontWeight: "700" }}>{tr("settings.more.scanQr")}</Text>
          </Pressable>
          <Text style={{ color: t.txtTertiary, fontSize: 11, marginBottom: 6 }}>{tr("settings.more.orPaste")}</Text>
          <TextInput value={pair} onChangeText={setPair} autoCapitalize="none" multiline
            placeholder={tr("settings.more.pairPh")} placeholderTextColor={t.txtPlaceholder} style={[field, { minHeight: 60 }]} />
          <View style={{ height: 8 }} />
          <Pressable onPress={doPair} disabled={pairBusy}
            style={{ backgroundColor: t.accent, borderRadius: 8, padding: 11, alignItems: "center", opacity: pairBusy ? 0.6 : 1 }}>
            <Text style={{ color: "#fff", fontWeight: "600" }}>{pairBusy ? tr("settings.more.checking") : tr("settings.more.pairBtn")}</Text>
          </Pressable>
          {pairMsg ? <Text style={{ color: pairKind === "ok" ? t.ok : pairKind === "info" ? t.txtSecondary : t.danger, fontSize: 12, marginTop: 6 }}>{pairMsg}</Text> : null}
        </Panel>
        ) : null}
        {showConn ? (
        <Panel>
          <SectionLabel text={tr("settings.more.lanSection")} />
          <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 6 }}>{tr("settings.more.lanHelp")}</Text>
          <TextInput value={url} onChangeText={setUrl} autoCapitalize="none" placeholder="http://10.0.2.2:8140"
            placeholderTextColor={t.txtPlaceholder} style={field} />
          <View style={{ height: 8 }} />
          <TextInput value={tok} onChangeText={setTok} autoCapitalize="none" placeholder={tr("settings.more.tokenPh")}
            placeholderTextColor={t.txtPlaceholder} style={field} />
          <View style={{ height: 10 }} />
          <Pressable onPress={() => set({ baseUrl: url.replace(/\/+$/, ""), token: tok.trim() })}
            style={{ backgroundColor: t.accent, borderRadius: 8, padding: 11, alignItems: "center" }}>
            <Text style={{ color: "#fff", fontWeight: "600" }}>{tr("ui.save")}</Text>
          </Pressable>
        </Panel>
        ) : null}
        {/* device-local switches, one panel instead of two */}
        <Panel>
          <SectionLabel text={tr("more.device.section")} />
          <Toggle label={tr("settings.voice.speakBlockers")} value={blockerVoiceOn} onChange={setBlockerVoice} />
          <Hint text={tr("settings.voice.hint")} />
          <View style={{ height: 10 }} />
          <Toggle label={tr("settings.privacy.analyticsToggle")} value={analyticsOn} onChange={setAnalytics} />
          <Hint text={tr("settings.privacy.hint")} />
        </Panel>
        {GROUPS.map(([grpKey, links]) => (
          <View key={grpKey} style={{ gap: 6 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 11.5, fontWeight: "700", letterSpacing: 0.6,
              textTransform: "uppercase", paddingHorizontal: 4, paddingTop: 6 }}>{tr(grpKey)}</Text>
            <Panel style={{ padding: 0 }}>
              {links.map(([route, labelKey, icon, subKey], i) => (
                <Pressable key={route} onPress={() => router.push(`/${route}` as never)}
                  style={{ flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 14, paddingVertical: 11,
                    borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder }}>
                  <Ionicons name={icon} size={18} color={t.txtSecondary} />
                  <View style={{ flex: 1, gap: 1 }}>
                    <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{tr(labelKey)}</Text>
                    <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr(subKey)}</Text>
                  </View>
                  <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
                </Pressable>
              ))}
              {grpKey === "more.grp.system" && FEEDBACK_BOARD_URL ? (
                <Pressable onPress={openFeedbackBoard}
                  style={{ flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 14, paddingVertical: 11,
                    borderTopWidth: 1, borderTopColor: t.glassBorder }}>
                  <Ionicons name="megaphone-outline" size={18} color={t.txtSecondary} />
                  <View style={{ flex: 1, gap: 1 }}>
                    <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{tr("nav.feedback")}</Text>
                    <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("more.sub.feedback")}</Text>
                  </View>
                  <Ionicons name="open-outline" size={16} color={t.txtTertiary} />
                </Pressable>
              ) : null}
            </Panel>
          </View>
        ))}
        <ApkUpdateBanner />
        <VersionFooter />
      </ScrollView>
    </View>
  );
}
