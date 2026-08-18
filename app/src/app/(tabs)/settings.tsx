import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { useRouter } from "expo-router";
import util from "tweetnacl-util";
import { useConfig } from "@/data/config";
import { qrDataUrl } from "@/data/qrgen";
import { useEffect, useState } from "react";
import { ActivityIndicator, Alert, Image, Platform, Pressable, ScrollView, Text, TextInput, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useAuthGate } from "@/data/authgate";
import { useCellEnabled } from "@/data/cells";
import type { UserRow } from "@/data/types";
import { LANGS, useT, type Lang } from "@/i18n";
import { useTheme } from "@/theme";
import { Chip, KVRow, Panel, ScreenHeader, SectionLabel } from "@/ui/kit";
import { UsagePanel } from "@/ui/dash_panels";
import { PMControls } from "@/ui/pm_panel";
import { Btn, Caption, ChipPick, confirmAsync, fieldStyle, FormGrid, Hint, isWeb, promptText, Toggle } from "@/ui/settings_sections";
import { UpdatesPanel } from "@/ui/updates_info";

const BACKDROPS = ["mesh", "aurora", "ember", "forest", "mono"] as const;
// auto-modes / chat-roles / prios / lane-labels moved to the Automatik hub
// (schema-driven) - settings only points there now.
// The language chips show the language's own name (Deutsch / English - never
// translated); the id behind the label is what lands in policy.lang.
const LANG_LABELS = LANGS.map((l) => l.label);
const langId = (label: string): Lang => (LANGS.find((l) => l.label === label)?.id ?? "de");

type PlanRepo = { items?: { title: string; priority?: string }[]; error?: string | null };
type NightPlan = { made?: string; actor?: string; repos?: Record<string, PlanRepo> };

export default function Settings() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;
  const { data: s, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const { data: users, refetch: refetchUsers } = useQuery({ queryKey: ["users"], queryFn: api.users });
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 8000 });
  const actors = metrics?.capacity?.actors ?? {};   // touch units per person today
  const pmEnabled = useCellEnabled("pm");

  const field = fieldStyle(t);

  // ---- business ----
  const [repo, setRepo] = useState("");
  const [wip, setWip] = useState("");
  const [value, setValue] = useState("");
  const [budget, setBudget] = useState("");
  const [tSteer, setTSteer] = useState(""); const [tReview, setTReview] = useState(""); const [tBounce, setTBounce] = useState("");

  // ---- language ----
  const [lang, setLangSel] = useState<Lang>("de");

  // ---- appearance (policy knobs live in the Automatik hub now) ----
  const [backdrop, setBackdrop] = useState("mesh");

  // ---- jira / imports ----
  const [jBase, setJBase] = useState(""); const [jEmail, setJEmail] = useState("");
  const [jToken, setJToken] = useState(""); const [jJql, setJJql] = useState("");
  const [impUrl, setImpUrl] = useState(""); const [busyImp, setBusyImp] = useState(false);

  // ---- night shift ----
  const [nsOn, setNsOn] = useState(false);
  const [nsWindow, setNsWindow] = useState("01:00-07:00");
  const [nsMax, setNsMax] = useState("3");
  const [nsIdle, setNsIdle] = useState("20");
  const [nsRepos, setNsRepos] = useState("");
  const [nsBusy, setNsBusy] = useState(false);
  const [nsPlan, setNsPlan] = useState<NightPlan | null>(null);
  const [nsReport, setNsReport] = useState<string | null>(null);
  const [nsReportOpen, setNsReportOpen] = useState(false);

  // ---- pairing ----
  const [pairCode, setPairCode] = useState("");
  const [pairLink, setPairLink] = useState("");
  const [qr, setQr] = useState("");
  const [pairBusy, setPairBusy] = useState(false);
  const [pairTtlMin, setPairTtlMin] = useState(15);
  const [relayUrl, setRelayUrl] = useState("");

  // ---- add user ----
  const [uName, setUName] = useState(""); const [uPw, setUPw] = useState(""); const [uRole, setURole] = useState("operator");

  // ---- registration ----
  const [regOpen, setRegOpen] = useState(false);
  const [regCode, setRegCode] = useState("");
  const [regRole, setRegRole] = useState("client");

  useEffect(() => {
    if (!s) return;
    setRepo(s.default_repo ?? "");
    setWip(String(s.capacity?.wip_limit ?? ""));
    setValue(String(s.value_per_card ?? ""));
    setBudget(String(s.capacity?.touch_budget_day ?? ""));
    setTSteer(String(s.capacity?.tariff?.steer ?? ""));
    setTReview(String(s.capacity?.tariff?.review ?? ""));
    setTBounce(String(s.capacity?.tariff?.bounce ?? ""));
    const pol = s.policy ?? {};
    setLangSel(pol.lang === "en" ? "en" : "de");
    setBackdrop(s.appearance?.backdrop ?? "mesh");
    setJBase(s.jira?.base ?? ""); setJEmail(s.jira?.email ?? "");
    setJToken(s.jira?.api_token ?? ""); setJJql(s.jira?.default_jql ?? "");
    setRelayUrl(s.relay?.url ?? "");
    const ns = s.nightshift ?? {};
    setNsOn(!!ns.enabled); setNsWindow(ns.window ?? "01:00-07:00");
    setNsMax(String(ns.max_cards ?? 3)); setNsIdle(String(ns.idle_minutes ?? 20));
    setNsRepos((ns.repos ?? []).join("\n"));
    setRegOpen(!!s.registration?.open); setRegCode(s.registration?.invite_code ?? "");
    setRegRole(s.registration?.default_role ?? "client");
  }, [s]);

  const ok = (msg: string) => Alert.alert(tr("settings.savedTitle"), msg);
  const fail = (e: unknown) => Alert.alert(tr("ui.error"), String((e as Error).message));
  async function invalidate() { await qc.invalidateQueries({ queryKey: ["settings"] }); }

  // The language is policy data like any other field; the daemon merges the
  // policy patch, so writing lang alone leaves the rest of the policy intact.
  // No success alert: the whole UI flipping language IS the confirmation.
  // ["me"] is the query that must refetch - useLang() reads /me, because that
  // is the only endpoint every role can call (/dashboard/data strips settings
  // for operators and 403s clients).
  async function saveLang(l: Lang) {
    if (l === lang) return;
    setLangSel(l);
    try {
      await api.saveSettings({ policy: { lang: l } });
      await invalidate();
      await qc.invalidateQueries({ queryKey: ["me"] });
      await qc.invalidateQueries({ queryKey: ["metrics"] });
    } catch (e) { fail(e); }
  }

  async function saveBusiness() {
    try {
      await api.saveSettings({ default_repo: repo.trim(), value_per_card: Number(value) || 0,
        capacity: { ...(s?.capacity ?? {}), wip_limit: Number(wip) || 0,
          touch_budget_day: Number(budget) || 0,
          tariff: { ...(s?.capacity?.tariff ?? {}),
            steer: Number(tSteer) || 1, review: Number(tReview) || 1, bounce: Number(tBounce) || 3 } } });
      await invalidate(); ok(tr("settings.saved.business"));
    } catch (e) { fail(e); }
  }

  async function saveJira() {
    try {
      await api.saveSettings({ jira: { base: jBase.trim(), email: jEmail.trim(), api_token: jToken.trim(), default_jql: jJql.trim() } });
      ok(tr("settings.saved.jira"));
    } catch (e) { fail(e); }
  }
  async function importJira() {
    setBusyImp(true);
    try {
      const r = await api.post<{ imported?: number; error?: string }>("/import/jira", { jql: jJql.trim() });
      Alert.alert(r.error ? tr("ui.error") : tr("settings.import.title"),
        r.error ?? tr("settings.import.jiraDone", { n: r.imported ?? 0 }));
    } catch (e) { fail(e); } finally { setBusyImp(false); }
  }
  async function importUrl() {
    if (!impUrl.trim()) return;
    setBusyImp(true);
    try {
      const r = await api.post<{ id?: string; error?: string }>("/import/url", { url: impUrl.trim() });
      Alert.alert(r.error ? tr("ui.error") : tr("settings.import.title"), r.error ?? tr("settings.import.urlDone"));
      if (!r.error) setImpUrl("");
    } catch (e) { fail(e); } finally { setBusyImp(false); }
  }

  async function saveNight() {
    try {
      await api.saveSettings({ nightshift: { enabled: nsOn, window: nsWindow.trim(),
        repos: nsRepos.split("\n").map((r) => r.trim()).filter(Boolean),
        max_cards: Number(nsMax) || 3, idle_minutes: Number(nsIdle) || 20 } });
      await invalidate(); ok(tr("settings.saved.night"));
    } catch (e) { fail(e); }
  }
  async function planNow() {
    setNsBusy(true);
    try {
      await api.post("/nightshift/plan", {});
      Alert.alert(tr("settings.night.planStartedTitle"), tr("settings.night.planStartedMsg"));
    } catch (e) { fail(e); } finally { setNsBusy(false); }
  }
  async function showPlan() {
    try {
      const r = await api.get<{ plan?: NightPlan; report?: string | null }>("/nightshift");
      setNsPlan(r.plan ?? null);
      setNsReport(r.report ?? null);
      if (!r.plan) Alert.alert(tr("settings.night.noPlanTitle"), tr("settings.night.noPlanMsg"));
    } catch (e) { fail(e); }
  }

  async function pairPhone() {
    if (!relayUrl.trim()) { Alert.alert(tr("settings.pair.noRelayTitle"), tr("settings.pair.noRelayMsg")); return; }
    setPairBusy(true);
    try {
      const r = await api.post<{ url?: string; room?: string; daemon_pub?: string; device_token?: string; expires_in?: number; error?: string }>("/relay/pair", {});
      if (r.error) { Alert.alert(tr("ui.error"), r.error); return; }
      setPairTtlMin(Math.round((r.expires_in ?? 900) / 60));
      // Byte-compatible with applyPairing / the web pairing code: base64(JSON{u,r,k,t}).
      const code = util.encodeBase64(util.decodeUTF8(JSON.stringify({ u: r.url, r: r.room, k: r.daemon_pub, t: r.device_token })));
      setPairCode(code);
      // QR = the relay's own /pair App Link (phone cameras open https, not a
      // custom scheme). Carry the relay url in the payload too: /pair redirects
      // the phone to helmdeck://pair?c=… (custom scheme), so the https origin is
      // gone by the time pair.tsx runs and can't be recovered from the link.
      const link = `${(r.url ?? "").replace(/\/$/, "")}/pair?c=${code}`;
      setPairLink(link);              // tap-to-pair link — send to the phone, no QR scan
      setQr(await qrDataUrl(link));   // real on web/desktop, "" on native (phone scans)
    } catch (e) { fail(e); } finally { setPairBusy(false); }
  }
  async function saveRelay() {
    try { await api.saveSettings({ relay: { url: relayUrl.trim() } }); await invalidate(); ok(tr("settings.saved.relay")); }
    catch (e) { fail(e); }
  }

  // ---- users ----
  async function addUser() {
    if (!uName.trim() || !uPw) { Alert.alert(tr("settings.users.missingTitle"), tr("settings.users.missingMsg")); return; }
    try {
      const r = await api.post<{ error?: string }>("/users", { name: uName.trim(), password: uPw, role: uRole });
      if (r.error) { Alert.alert(tr("ui.error"), r.error); return; }
      setUName(""); setUPw(""); await refetchUsers();
    } catch (e) { fail(e); }
  }
  function changeRole(u: UserRow) {
    Alert.alert(u.name, tr("settings.users.setRole"), [
      ...["owner", "operator", "client"].filter((r) => r !== u.role).map((r) => ({
        text: r, onPress: async () => { try { await api.setRole(u.name, r); await refetchUsers(); } catch (e) { fail(e); } },
      })),
      { text: tr("ui.cancel"), style: "cancel" as const },
    ]);
  }
  async function resetPw(u: UserRow) {
    const pw = await promptText(tr("settings.users.newPwPrompt", { name: u.name }));
    if (pw == null) { if (!isWeb && Platform.OS !== "ios") Alert.alert(tr("settings.users.unsupportedTitle"), tr("settings.users.unsupportedMsg")); return; }
    if (pw.length < 8) { Alert.alert(tr("settings.users.tooShortTitle"), tr("settings.users.tooShortMsg")); return; }
    try { await api.post(`/users/${u.name}/password`, { password: pw }); Alert.alert(tr("settings.users.pwSetTitle"), tr("settings.users.pwSetMsg")); }
    catch (e) { fail(e); }
  }
  async function delUser(u: UserRow) {
    if (!(await confirmAsync(tr("settings.users.delConfirm", { name: u.name }), tr("settings.users.delMsg")))) return;
    try { await api.post(`/users/${u.name}/delete`, {}); await refetchUsers(); } catch (e) { fail(e); }
  }
  async function addToken(u: UserRow) {
    const label = (await promptText(tr("settings.users.tokenLabelPrompt", { name: u.name }), "device")) ?? "device";
    try { const r = await api.issueToken(u.name, label); await Clipboard.setStringAsync(r.token); Alert.alert(tr("settings.users.tokenCopiedTitle"), tr("settings.users.tokenCopiedMsg")); await refetchUsers(); }
    catch (e) { fail(e); }
  }
  // Owner invites a teammate: issue THEIR personal token and package it with the
  // daemon connection into one importable code (direct {b,t} on LAN/desktop, or
  // relay {u,r,k,t} when a relay is configured). They paste it in More → Pairing
  // and join the same board AS themselves (their touches are attributed to them).
  async function invite(u: UserRow) {
    try {
      const r = await api.issueToken(u.name, "invite-" + u.name);
      let payload: Record<string, string>;
      if (relayUrl.trim()) {
        // invite:true = the teammate authenticates with THEIR token issued
        // above; without the flag the daemon would also mint (and orphan) an
        // owner device token per invite. Opens the same single-use window.
        const p = await api.post<{ url?: string; room?: string; daemon_pub?: string; error?: string }>("/relay/pair", { invite: true });
        if (p.error || !p.url) { Alert.alert(tr("ui.error"), p.error ?? tr("settings.pair.relayFailed")); return; }
        payload = { u: p.url, r: p.room ?? "", k: p.daemon_pub ?? "", t: r.token };
      } else {
        payload = { b: useConfig.getState().baseUrl, t: r.token };
      }
      const code = util.encodeBase64(util.decodeUTF8(JSON.stringify(payload)));
      await Clipboard.setStringAsync(code);
      Alert.alert(tr("settings.users.inviteCopiedTitle"), tr("settings.users.inviteCopiedMsg", { name: u.name, role: u.role }));
      await refetchUsers();
    } catch (e) { fail(e); }
  }
  async function revokeToken(u: UserRow, token: string) {
    if (!(await confirmAsync(tr("settings.users.revokeTitle"), tr("settings.users.revokeMsg")))) return;
    try { await api.post(`/users/${u.name}/revoke`, { token }); await refetchUsers(); } catch (e) { fail(e); }
  }
  async function saveReg() {
    try { await api.saveSettings({ registration: { open: regOpen, invite_code: regCode.trim(), default_role: regRole } }); ok(tr("settings.saved.registration")); }
    catch (e) { fail(e); }
  }

  // Restores the "Abmelden" control the old Next.js web app had (lost at the
  // Expo cutover along with its login screen - see login_screen.tsx). Always
  // reachable, not gated behind the owner-only settings block below: if
  // you're stuck with a bad token, you need this REGARDLESS of whether
  // /settings itself loads. Best-effort server-side logout (clears the
  // cookie session too, for any other consumer that reads it), then clear
  // the local token and re-show the login screen via the same gate a 401
  // already drives.
  const logout = () => {
    api.post("/auth/logout", {}).catch(() => { /* best-effort - proceed regardless */ });
    useConfig.getState().set({ token: "" });
    useAuthGate.getState().reportAuthRequired();
  };

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr("nav.settings")} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 60,
        width: "100%", maxWidth: wide ? 1100 : undefined, alignSelf: "center" }}>
        <Pressable onPress={logout} style={{ alignSelf: "flex-start" }}>
          <Text style={{ color: t.danger, fontSize: 13, fontWeight: "600" }}>Abmelden</Text>
        </Pressable>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>{tr("settings.ownerOnly")}</Text> : null}
        {s ? (
          <>
            {/* Language first: it changes every label below it. */}
            <Panel>
              <SectionLabel text={tr("ui.language")} />
              <Hint text={tr("settings.lang.hint")} />
              <ChipPick options={LANG_LABELS} selected={[LANGS.find((l) => l.id === lang)?.label ?? LANG_LABELS[0]]}
                single onToggle={(label) => saveLang(langId(label))} />
              <View style={{ height: 10 }} />
              <Caption text={tr("settings.policy.backdrop")} />
              <ChipPick options={BACKDROPS} selected={[backdrop]} single
                onToggle={(b) => { setBackdrop(b); api.saveSettings({ appearance: { backdrop: b } }).then(invalidate).catch(fail); }} />
            </Panel>

            {/* Claude subscription usage (5h + weekly windows) with weekly pacing -
                the same data the PM flags proactively when the pace runs ahead. */}
            <UsagePanel />

            {/* The planning loop's CONTROLS - goal, proactive on/off + the
                notify/ask/act ladder, replan, consolidate. Moved off the
                dashboard so the overview stays clean; the board shows what the
                loop is DOING, the steering of it lives here. PM has no
                nav.tabs entry to hide, so it gates off the cell flag directly. */}
            {pmEnabled ? (
              <Panel>
                <SectionLabel text={tr("pm.title")} />
                <PMControls />
              </Panel>
            ) : null}

            <Panel>
              <SectionLabel text={tr("settings.sec.business")} />
              <FormGrid wide={wide}>
                <View>
                  <Caption text={tr("settings.business.repo")} />
                  <TextInput value={repo} onChangeText={setRepo} autoCapitalize="none" style={field} />
                </View>
                <View>
                  <Caption text={tr("settings.business.wip")} />
                  <TextInput value={wip} onChangeText={setWip} keyboardType="numeric" style={field} />
                </View>
                <View>
                  <Caption text={tr("settings.business.value")} />
                  <TextInput value={value} onChangeText={setValue} keyboardType="numeric" style={field} />
                </View>
                <View>
                  <Caption text={tr("settings.business.budget")} />
                  <TextInput value={budget} onChangeText={setBudget} keyboardType="numeric" style={field} />
                </View>
              </FormGrid>
              <View style={{ height: 10 }} />
              <Caption text={tr("settings.business.tariff")} />
              <View style={{ flexDirection: "row", gap: 8 }}>
                <View style={{ flex: 1 }}>
                  <TextInput value={tSteer} onChangeText={setTSteer} keyboardType="numeric" style={field} />
                </View>
                <View style={{ flex: 1 }}>
                  <TextInput value={tReview} onChangeText={setTReview} keyboardType="numeric" style={field} />
                </View>
                <View style={{ flex: 1 }}>
                  <TextInput value={tBounce} onChangeText={setTBounce} keyboardType="numeric" style={field} />
                </View>
              </View>
              <View style={{ height: 12 }} />
              <Btn label={tr("ui.save")} onPress={saveBusiness} />
            </Panel>

            {/* Loop, harness & automation policy now live in ONE place - the
                Automatik hub (schema-driven, editable there). This is just the
                pointer, so there is no second edit surface for the same data. */}
            <Panel>
              <SectionLabel text={tr("settings.sec.automation")} />
              <Hint text={tr("automation.movedHint")} />
              <View style={{ height: 6 }} />
              <Btn label={tr("automation.title")} kind="ghost" onPress={() => router.push("/(tabs)/automation")} />
            </Panel>

            <Panel>
              <SectionLabel text={tr("settings.sec.dataflows")} />
              <Caption text={tr("settings.jira.caption")} />
              <FormGrid wide={wide}>
                <TextInput value={jBase} onChangeText={setJBase} autoCapitalize="none" placeholder="https://your.atlassian.net" placeholderTextColor={t.txtPlaceholder} style={field} />
                <TextInput value={jEmail} onChangeText={setJEmail} autoCapitalize="none" placeholder={tr("settings.jira.emailPh")} placeholderTextColor={t.txtPlaceholder} style={field} />
                <TextInput value={jToken} onChangeText={setJToken} autoCapitalize="none" secureTextEntry placeholder={tr("settings.jira.tokenPh")} placeholderTextColor={t.txtPlaceholder} style={field} />
                <TextInput value={jJql} onChangeText={setJJql} autoCapitalize="none" placeholder={tr("settings.jira.jqlPh")} placeholderTextColor={t.txtPlaceholder} style={field} />
              </FormGrid>
              <View style={{ height: 10 }} />
              <View style={{ flexDirection: "row", gap: 8 }}>
                <View style={{ flex: 1 }}><Btn label={tr("settings.jira.saveConn")} kind="ghost" onPress={saveJira} /></View>
                <View style={{ flex: 1 }}><Btn label={busyImp ? "…" : tr("settings.jira.importNow")} onPress={importJira} disabled={busyImp} /></View>
              </View>
              <View style={{ height: 14 }} />
              <Caption text={tr("settings.import.urlCaption")} />
              <TextInput value={impUrl} onChangeText={setImpUrl} autoCapitalize="none" placeholder="https://..." placeholderTextColor={t.txtPlaceholder} style={field} />
              <View style={{ height: 8 }} />
              <Btn label={busyImp ? "…" : tr("settings.import.page")} onPress={importUrl} disabled={busyImp} />
            </Panel>

            <Panel>
              <SectionLabel text={tr("settings.sec.night")} />
              <Hint text={tr("settings.night.hint")} />
              <Toggle label={tr("settings.night.enabled")} value={nsOn} onChange={setNsOn} />
              <View style={{ height: 8 }} />
              <FormGrid wide={wide}>
                <View>
                  <Caption text={tr("settings.night.window")} />
                  <TextInput value={nsWindow} onChangeText={setNsWindow} autoCapitalize="none" placeholder="always" placeholderTextColor={t.txtPlaceholder} style={field} />
                </View>
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <View style={{ flex: 1 }}>
                    <Caption text={tr("settings.night.max")} />
                    <TextInput value={nsMax} onChangeText={setNsMax} keyboardType="numeric" style={field} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Caption text={tr("settings.night.idle")} />
                    <TextInput value={nsIdle} onChangeText={setNsIdle} keyboardType="numeric" style={field} />
                  </View>
                </View>
              </FormGrid>
              <View style={{ height: 10 }} />
              <Caption text={tr("settings.night.repos")} />
              <TextInput value={nsRepos} onChangeText={setNsRepos} autoCapitalize="none" multiline
                placeholder={"C:\\Users\\you\\Downloads\\myrepo"} placeholderTextColor={t.txtPlaceholder}
                style={[field, { minHeight: 84, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", fontSize: 12 }]} />
              <View style={{ height: 10 }} />
              <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                <View style={{ flex: 1, minWidth: 120 }}><Btn label={tr("ui.save")} onPress={saveNight} /></View>
                <View style={{ flex: 1, minWidth: 120 }}><Btn label={nsBusy ? tr("settings.night.planning") : tr("settings.night.planNow")} kind="ghost" onPress={planNow} disabled={nsBusy} /></View>
                <View style={{ flex: 1, minWidth: 120 }}><Btn label={tr("settings.night.showPlan")} kind="ghost" onPress={showPlan} /></View>
              </View>
              {nsPlan?.repos ? (
                <View style={{ marginTop: 12, gap: 4 }}>
                  {nsPlan.made ? <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("settings.night.planFrom", { when: nsPlan.made })}</Text> : null}
                  {Object.entries(nsPlan.repos).map(([r, block]) => (
                    <View key={r} style={{ marginTop: 6 }}>
                      <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "600" }}>{r.split(/[\\/]/).pop()}</Text>
                      {block.error ? <Text style={{ color: t.danger, fontSize: 11.5 }}>— {block.error}</Text> : null}
                      {(block.items ?? []).map((it, i) => (
                        <Text key={i} style={{ color: t.txtSecondary, fontSize: 11.5, paddingLeft: 8 }}>· [{it.priority}] {it.title}</Text>
                      ))}
                    </View>
                  ))}
                </View>
              ) : null}
              {nsReport ? (
                <View style={{ marginTop: 12 }}>
                  <Pressable onPress={() => setNsReportOpen((o) => !o)}>
                    <Text style={{ color: t.txtSecondary, fontSize: 12.5 }}>
                      {nsReportOpen ? "▾" : "▸"} {tr("settings.night.lastReport")}
                    </Text>
                  </Pressable>
                  {nsReportOpen ? (
                    <View style={{ marginTop: 8, backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8, padding: 10 }}>
                      <Text selectable style={{ color: t.txtSecondary, fontSize: 11.5,
                        fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" }}>{nsReport}</Text>
                    </View>
                  ) : null}
                </View>
              ) : null}
            </Panel>

            <Panel>
              <SectionLabel text={tr("settings.sec.mobile")} />
              <Hint text={tr("settings.pair.hint")} />
              <Caption text={tr("settings.pair.relayUrl")} />
              <View style={{ flexDirection: "row", gap: 8 }}>
                <TextInput value={relayUrl} onChangeText={setRelayUrl} autoCapitalize="none" placeholder="https://relay.example.com"
                  placeholderTextColor={t.txtPlaceholder} style={[field, { flex: 1 }]} />
                <Btn label={tr("ui.save")} kind="ghost" onPress={saveRelay} />
              </View>
              <View style={{ height: 10 }} />
              <Btn label={pairBusy ? "…" : tr("settings.pair.pairPhone")} onPress={pairPhone} disabled={pairBusy} />
              {pairCode ? (
                <View style={{ marginTop: 10, gap: 8 }}>
                  <Hint text={tr("settings.pair.ttl", { min: pairTtlMin })} />
                  {pairLink ? (
                    <View style={{ gap: 6 }}>
                      <Hint text={tr("settings.pair.linkHint")} />
                      <View style={{ backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8, padding: 10 }}>
                        <Text selectable numberOfLines={2} style={{ color: t.accent, fontSize: 11.5 }}>{pairLink}</Text>
                      </View>
                      <View style={{ flexDirection: "row", gap: 8 }}>
                        <View style={{ flex: 1 }}><Btn label={tr("settings.pair.copyLink")} onPress={async () => { await Clipboard.setStringAsync(pairLink); Alert.alert(tr("settings.pair.copiedTitle"), tr("settings.pair.linkCopied")); }} /></View>
                        {isWeb && typeof navigator !== "undefined" && (navigator as unknown as { share?: unknown }).share ? (
                          <View style={{ flex: 1 }}><Btn label={tr("settings.pair.share")} kind="ghost" onPress={() => { (navigator as unknown as { share: (d: { url: string }) => Promise<void> }).share({ url: pairLink }).catch(() => {}); }} /></View>
                        ) : null}
                      </View>
                    </View>
                  ) : null}
                  {qr ? (
                    <View style={{ alignItems: "center", gap: 6 }}>
                      <Hint text={tr("settings.pair.qrHint")} />
                      <Image source={{ uri: qr }} style={{ width: 220, height: 220, borderRadius: 10, backgroundColor: "#fff" }} />
                    </View>
                  ) : null}
                  <Hint text={tr("settings.pair.codeHint")} />
                  <View style={{ backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8, padding: 10 }}>
                    <Text selectable numberOfLines={2} style={{ color: t.txtSecondary, fontSize: 11, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" }}>{pairCode}</Text>
                  </View>
                  <Btn label={tr("settings.pair.copyCode")} kind="ghost" onPress={async () => { await Clipboard.setStringAsync(pairCode); Alert.alert(tr("settings.pair.copiedTitle"), tr("settings.pair.codeCopied")); }} />
                </View>
              ) : null}
            </Panel>

            <Panel>
              <SectionLabel text={tr("settings.sec.users", { n: users?.length ?? 0 })} />
              {(users ?? []).map((u) => (
                <View key={u.name} style={{ paddingVertical: 8, borderTopWidth: 1, borderTopColor: t.glassBorder, gap: 6 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                    <Text style={{ color: t.txtPrimary, fontSize: 13.5, flex: 1 }}>{u.name}</Text>
                    {actors[u.name] ? <Text style={{ color: t.human, fontSize: 11 }}>{tr("settings.users.touchesToday", { n: actors[u.name] })}</Text> : null}
                    <Pressable onPress={() => changeRole(u)}>
                      <Chip text={u.role} dot={u.role === "owner" ? t.accent : u.role === "operator" ? t.human : t.txtTertiary} />
                    </Pressable>
                  </View>
                  {u.tokens?.length ? (
                    <View style={{ gap: 3 }}>
                      {u.tokens.map((tk) => (
                        <View key={tk.token} style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                          <Text style={{ color: t.txtTertiary, fontSize: 11, flex: 1 }} numberOfLines={1}>{tk.label} · …{tk.token.slice(-6)}</Text>
                          <Pressable onPress={() => revokeToken(u, tk.token)}><Text style={{ color: t.danger, fontSize: 11 }}>{tr("settings.users.revoke")}</Text></Pressable>
                        </View>
                      ))}
                    </View>
                  ) : null}
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 14 }}>
                    <Pressable onPress={() => invite(u)}
                      style={{ flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: t.accent + "1F",
                        borderColor: t.accent + "66", borderWidth: 1, borderRadius: 6, paddingHorizontal: 9, paddingVertical: 3 }}>
                      <Ionicons name="person-add-outline" size={12} color={t.accent} />
                      <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{tr("settings.users.invite")}</Text>
                    </Pressable>
                    <Pressable onPress={() => addToken(u)}><Text style={{ color: t.txtSecondary, fontSize: 12 }}>{tr("settings.users.addToken")}</Text></Pressable>
                    <Pressable onPress={() => resetPw(u)}><Text style={{ color: t.txtSecondary, fontSize: 12 }}>{tr("settings.users.password")}</Text></Pressable>
                    <Pressable onPress={() => delUser(u)}><Text style={{ color: t.danger, fontSize: 12 }}>{tr("settings.users.delete")}</Text></Pressable>
                  </View>
                </View>
              ))}
              <View style={{ height: 12, borderTopWidth: 1, borderTopColor: t.glassBorder, marginTop: 4 }} />
              <Caption text={tr("settings.users.newUser")} />
              <FormGrid wide={wide}>
                <TextInput value={uName} onChangeText={setUName} autoCapitalize="none" placeholder={tr("settings.users.namePh")} placeholderTextColor={t.txtPlaceholder} style={field} />
                <TextInput value={uPw} onChangeText={setUPw} autoCapitalize="none" secureTextEntry placeholder={tr("settings.users.pwPh")} placeholderTextColor={t.txtPlaceholder} style={field} />
              </FormGrid>
              <View style={{ height: 8 }} />
              <ChipPick options={["operator", "client", "owner"]} selected={[uRole]} single onToggle={setURole} />
              <View style={{ height: 10 }} />
              <Btn label={tr("settings.users.create")} onPress={addUser} />
            </Panel>

            <Panel>
              <SectionLabel text={tr("settings.sec.registration")} />
              <Hint text={tr("settings.reg.hint")} />
              <Toggle label={tr("settings.reg.open")} value={regOpen} onChange={setRegOpen} />
              <View style={{ height: 8 }} />
              <Caption text={tr("settings.reg.code")} />
              <TextInput value={regCode} onChangeText={setRegCode} autoCapitalize="none" style={field} />
              <View style={{ height: 10 }} />
              <Caption text={tr("settings.reg.role")} />
              <ChipPick options={["client", "operator"]} selected={[regRole]} single onToggle={setRegRole} />
              <View style={{ height: 12 }} />
              <Btn label={tr("settings.reg.save")} onPress={saveReg} />
            </Panel>
          </>
        ) : null}
        {/* Outside the owner-only block: build/OTA identity must be checkable
            even when the daemon is unreachable or the user isn't owner. */}
        <UpdatesPanel />
      </ScrollView>
    </View>
  );
}
