import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { useLocalSearchParams, useRouter } from "expo-router";
import util from "tweetnacl-util";
import { useConfig } from "@/data/config";
import { qrDataUrl } from "@/data/qrgen";
import { useEffect, useState } from "react";
import { ActivityIndicator, Alert, Image, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAnalytics } from "@/data/analytics";
import { useBlockerVoice } from "@/data/blocker_voice";
import { useBoards } from "@/data/boards";
import { useLaneLabels } from "@/ui/board";
import { api } from "@/data/client";
import { useAuthGate } from "@/data/authgate";
import { useCellEnabled } from "@/data/cells";
import { clearProfileCache } from "@/data/profile";
import { DOOR_IDS, type DoorId } from "@/data/settings_schema";
import type { Me, UserRow } from "@/data/types";
import { LANGS, useT, type Lang } from "@/i18n";
import { can } from "@/kernel";
import { useTheme } from "@/theme";
import { Chip, Panel, ScreenHeader, SectionLabel } from "@/ui/kit";
import { CellsCatalog } from "@/ui/cells_catalog";
import { UsagePanel } from "@/ui/dash_panels";
import { HarnessSection } from "@/ui/harness_section";
import { GxpActivate } from "@/ui/gxp_activate";
import { PMControls } from "@/ui/pm_panel";
import { SchemaDoor, ScopeBadge, useSchema } from "@/ui/settings_schema_page";
import { Btn, Caption, ChipPick, confirmAsync, fieldStyle, FormGrid, Hint, isWeb, promptText, Toggle } from "@/ui/settings_sections";
import { DesktopUpdateBanner } from "@/ui/desktop_update";
import { UpdatesPanel } from "@/ui/updates_info";
import { useResponsive } from "@/ui/responsive";

// ---------------------------------------------------------------------------
// THE SETTINGS HUB (settings-ia-redesign, completed as accounts-boards-prd
// phase 4 "settings-hub").
//
// ONE route ("settings"), an internal door list + door detail, addressable via
// ?door=<id> - so /automation and /modules are redirects into it rather than
// screens of their own. Doors group by USER GOAL (Home-Assistant pattern), not
// by which daemon key backs a field.
//
// WHAT PHASE 4 CHANGED, and why the file got SHORTER rather than longer:
//
//  - Rows are no longer hand-placed. Every knob the daemon can describe is
//    rendered by <SchemaDoor>, which reads the knob's own `door`/`group`/
//    `level`/`scope` metadata (spine/http/apimeta.py). Adding a knob - or a
//    section, or the first knob in a door that had none - is now a daemon-side
//    edit with NO change here. That is this card's acceptance criterion.
//  - Every row wears a SCOPE BADGE saying who a change affects (Konto / Board
//    / Workspace / Gerät / System), and the scope also decides where the write
//    goes: profile rows PUT /me/config, the rest POST /settings. G4's "one
//    owner, one storage location, one edit surface" is data, not convention.
//  - Door 1 is "Mein Profil" and is ACCOUNT-backed (PRD section 5). Its rows
//    ride on /me, so a `client` - who 403s on /automation - can still set
//    their own language. Genuinely device-bound switches sit alongside them
//    with a "Gerät" badge, moved out of the Mehr tab (the plan's point B).
//  - New door "Boards" between 1 and 2 (PRD section 5): my boards + the shared
//    one, each opening the board editor.
//  - Door 3 "Zellen" is a real door now, not a link: @/ui/cells_catalog.tsx
//    renders inside the hub and (tabs)/modules.tsx is a redirect.
//  - The hand-built business panel dissolved into schema knobs in door 6.
//
// Hand-built by design (the plan's explicit "handgebaut bleiben nur ..."):
// wizards (Jira, pairing, invite), the users/devices lists, the harness brief
// editor, PMControls, and the board list. Those are flows and tables, not
// knobs; forcing them through a control union would be the second monolith
// this redesign exists to avoid.
type Door = { id: DoorId; labelKey: string; subKey: string; icon: keyof typeof Ionicons.glyphMap; cap?: string };
// Order comes from DOOR_IDS (the daemon's own order, mirrored in
// data/settings_schema.ts) - this table only decorates it. `cap` hides a door
// from a role that would 403 behind it: the plan's "Nicht-Owner sehen nur
// Tür 1 - Rest unsichtbar statt 403". Boards is capless on purpose; every
// role has boards.
const DOOR_META: Record<DoorId, Omit<Door, "id">> = {
  general: { labelKey: "hub.door.general", subKey: "hub.door.general.sub", icon: "person-circle-outline" },
  boards: { labelKey: "hub.door.boards", subKey: "hub.door.boards.sub", icon: "grid-outline" },
  automation: { labelKey: "hub.door.automation", subKey: "hub.door.automation.sub", icon: "flash-outline", cap: "settings.read" },
  cells: { labelKey: "hub.door.cells", subKey: "hub.door.cells.sub", icon: "cube-outline", cap: "settings.read" },
  connections: { labelKey: "hub.door.connections", subKey: "hub.door.connections.sub", icon: "extension-puzzle-outline", cap: "settings.read" },
  team: { labelKey: "hub.door.team", subKey: "hub.door.team.sub", icon: "people-outline", cap: "settings.read" },
  system: { labelKey: "hub.door.system", subKey: "hub.door.system.sub", icon: "hardware-chip-outline", cap: "settings.read" },
};
const DOORS: readonly Door[] = DOOR_IDS.map((id) => ({ id, ...DOOR_META[id] }));

const LANG_LABELS = LANGS.map((l) => l.label);
const langId = (label: string): Lang => (LANGS.find((l) => l.label === label)?.id ?? "de");

export default function Settings() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { wide } = useResponsive();
  const params = useLocalSearchParams<{ door?: string }>();
  const doorParam = (Array.isArray(params.door) ? params.door[0] : params.door) as DoorId | undefined;
  const [door, setDoor] = useState<DoorId | null>(doorParam && DOORS.some((d) => d.id === doorParam) ? doorParam : null);
  useEffect(() => {
    if (doorParam && DOORS.some((d) => d.id === doorParam)) setDoor(doorParam);
  }, [doorParam]);

  const { data: me } = useQuery<Me>({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  // EVERY query below this line reads an owner-only route, so every one of
  // them is gated on the live capability rather than fired and left to 403.
  // Before phase 4 this screen WAS owner-only, so firing them unconditionally
  // cost nothing; now a client legitimately opens door 1 here, and an
  // ungated fetch would mean four failed requests and four red console lines
  // on the one door that is meant to be theirs.
  const owner = can(me, "settings.read");
  const { data: s, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: api.settings, enabled: owner });
  const { data: auto } = useQuery({ queryKey: ["automation"], queryFn: api.automation, staleTime: 30000, retry: false, enabled: owner });
  const { data: users, refetch: refetchUsers } = useQuery({ queryKey: ["users"], queryFn: api.users, enabled: owner });
  const { data: devices, refetch: refetchDevices } = useQuery({ queryKey: ["devices"], queryFn: api.devices, enabled: owner });
  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks, enabled: owner });
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 8000, enabled: owner });
  const actors = metrics?.capacity?.actors ?? {};
  // The pm cell merged into copilot (owner directive 2026-09-03) - PMControls
  // now gates on the same switch as Henry's chat. useCellEnabled fails OPEN
  // for an unknown id, so leaving this reading "pm" would have made the
  // panel unhideable the moment the pm cell id left the manifest.
  const pmEnabled = useCellEnabled("copilot");
  // BOTH halves of the config schema (/me's account rows + /automation's
  // workspace rows), concatenated. Every door then just filters it.
  const schema = useSchema();
  const { boards } = useBoards();
  // A station's own name - what an unlabelled column renders as. The SAME
  // resolver the board and its editor use, not a second one: this door shows
  // the labels those screens draw, so it has to agree with them by
  // construction rather than by care.
  const stationName = useLaneLabels();

  const field = fieldStyle(t);

  // ---- GxP mode (door: system, rbac-gxp card 6) ----
  const [showGxp, setShowGxp] = useState(false);
  const [gxpMsg, setGxpMsg] = useState<string | null>(null);
  const { data: gxpState } = useQuery({ queryKey: ["gxpState"], queryFn: api.gxpState,
    enabled: can(me, "gxp.activate") });

  // ---- device-local switches (door: general, badge "Gerät") ----
  // Moved here out of the Mehr tab (the plan's point B: "Gerätelokale Toggles
  // ziehen in Tür 1 mit 'Dieses Gerät'-Badge"). They are NOT schema knobs and
  // must not be: they live in a zustand store on this device and never travel
  // to the daemon at all, which is exactly what the "Gerät" badge says.
  const analyticsOn = useAnalytics((x) => x.enabled);
  const setAnalytics = useAnalytics((x) => x.setEnabled);
  const blockerVoiceOn = useBlockerVoice((x) => x.enabled);
  const setBlockerVoice = useBlockerVoice((x) => x.setEnabled);

  // ---- workspace-default language/appearance (door: general, owner-only) ----
  // The WORKSPACE DEFAULT that accounts inherit until they choose. A genuinely
  // different knob from the account's own (which is a schema row above it),
  // not a second surface for the same one: changing this moves everyone who
  // never picked one, and nobody who did.
  const [wsLang, setWsLang] = useState<Lang>("de");
  const [wsBackdrop, setWsBackdrop] = useState("mesh");

  // ---- jira / imports (door: connections) ----
  const [jBase, setJBase] = useState(""); const [jEmail, setJEmail] = useState("");
  const [jToken, setJToken] = useState(""); const [jJql, setJJql] = useState("");
  const [impUrl, setImpUrl] = useState(""); const [busyImp, setBusyImp] = useState(false);

  // nightshift.repos is NOT a schema knob (a newline list, which no control in
  // the union renders) - kept as its own field so the key still has exactly
  // ONE edit surface, next to the schema-rendered night rows in the same door.
  const [nsRepos, setNsRepos] = useState("");
  const [nsBusy, setNsBusy] = useState(false);
  useEffect(() => { if (s) setNsRepos((s.nightshift?.repos ?? []).join("\n")); }, [s]);
  async function saveNsRepos() {
    setNsBusy(true);
    try {
      await api.saveSettings({ nightshift: { repos: nsRepos.split("\n").map((r) => r.trim()).filter(Boolean) } });
      await qc.invalidateQueries({ queryKey: ["settings"] });
      await qc.invalidateQueries({ queryKey: ["automation"] });
    } catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); } finally { setNsBusy(false); }
  }
  const cur = (auto?.loop_current as { state: string; action: string }[]) ?? [];
  const curState = cur[0]?.state ?? "";
  const autoRepos = (auto?.repos as string[]) ?? [];

  // ---- pairing (door: team) ----
  const [pairCode, setPairCode] = useState("");
  const [pairLink, setPairLink] = useState("");
  const [qr, setQr] = useState("");
  const [pairBusy, setPairBusy] = useState(false);
  const [pairTtlMin, setPairTtlMin] = useState(15);
  const [relayUrl, setRelayUrl] = useState("");
  // ---- watch pairing (spoken device-code, POST /relay/pair/code) ----
  const [wearLabel, setWearLabel] = useState("");
  const [wearCode, setWearCode] = useState("");
  const [wearTtlMin, setWearTtlMin] = useState(15);
  const [wearBusy, setWearBusy] = useState(false);

  // ---- add user (door: team) ----
  const [uName, setUName] = useState(""); const [uPw, setUPw] = useState(""); const [uRole, setURole] = useState("operator");

  // ---- registration (door: team) ----
  const [regOpen, setRegOpen] = useState(false);
  const [regCode, setRegCode] = useState("");
  const [regRole, setRegRole] = useState("client");

  useEffect(() => {
    if (!s) return;
    const pol = s.policy ?? {};
    setWsLang(pol.lang === "en" ? "en" : "de");
    setWsBackdrop(s.appearance?.backdrop ?? "mesh");
    setJBase(s.jira?.base ?? ""); setJEmail(s.jira?.email ?? "");
    setJToken(s.jira?.api_token ?? ""); setJJql(s.jira?.default_jql ?? "");
    setRelayUrl(s.relay?.url ?? "");
    setRegOpen(!!s.registration?.open); setRegCode(s.registration?.invite_code ?? "");
    setRegRole(s.registration?.default_role ?? "client");
  }, [s]);

  const ok = (msg: string) => Alert.alert(tr("settings.savedTitle"), msg);
  const fail = (e: unknown) => Alert.alert(tr("ui.error"), String((e as Error).message));
  async function invalidate() { await qc.invalidateQueries({ queryKey: ["settings"] }); }

  async function saveWsLang(l: Lang) {
    if (l === wsLang) return;
    const prev = wsLang;
    setWsLang(l);
    try {
      await api.saveSettings({ policy: { lang: l } });
      await invalidate();
      await qc.invalidateQueries({ queryKey: ["me"] });
      await qc.invalidateQueries({ queryKey: ["metrics"] });
    } catch (e) { setWsLang(prev); fail(e); }
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

  async function pairPhone() {
    if (!relayUrl.trim()) { Alert.alert(tr("settings.pair.noRelayTitle"), tr("settings.pair.noRelayMsg")); return; }
    setPairBusy(true);
    try {
      const r = await api.post<{ url?: string; room?: string; daemon_pub?: string; device_token?: string; expires_in?: number; error?: string }>("/relay/pair", {});
      if (r.error) { Alert.alert(tr("ui.error"), r.error); return; }
      setPairTtlMin(Math.round((r.expires_in ?? 900) / 60));
      const code = util.encodeBase64(util.decodeUTF8(JSON.stringify({ u: r.url, r: r.room, k: r.daemon_pub, t: r.device_token })));
      setPairCode(code);
      const link = `${(r.url ?? "").replace(/\/$/, "")}/pair?c=${code}`;
      setPairLink(link);
      setQr(await qrDataUrl(link));
    } catch (e) { fail(e); } finally { setPairBusy(false); }
  }
  async function pairWatch() {
    // Same guard as pairPhone() - checked, not assumed: relay_client.py's
    // insecure_url() only rejects PLAIN-http; an EMPTY relay URL parses to
    // scheme "" (not "http"), so pairing_payload() would happily mint a
    // payload with url:"" server-side. pairPhone() already compensates for
    // this client-side rather than relying on the daemon to catch it -
    // pairWatch() mirrors that instead of reintroducing the gap.
    if (!relayUrl.trim()) { Alert.alert(tr("settings.pair.noRelayTitle"), tr("settings.pair.noRelayMsg")); return; }
    setWearBusy(true);
    try {
      const r = await api.post<{ code?: string; expires_in?: number; error?: string }>(
        "/relay/pair/code", { label: wearLabel.trim() || "Watch" });
      if (r.error) { Alert.alert(tr("ui.error"), r.error); return; }
      setWearCode(r.code ?? "");
      setWearTtlMin(Math.round((r.expires_in ?? 900) / 60));
    } catch (e) { fail(e); } finally { setWearBusy(false); }
  }
  async function saveRelay() {
    try { await api.saveSettings({ relay: { url: relayUrl.trim() } }); await invalidate(); ok(tr("settings.saved.relay")); }
    catch (e) { fail(e); }
  }

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
  async function invite(u: UserRow) {
    try {
      const r = await api.issueToken(u.name, "invite-" + u.name);
      let payload: Record<string, string>;
      if (relayUrl.trim()) {
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
  async function revokeToken(u: UserRow, tokenId: string) {
    if (!(await confirmAsync(tr("settings.users.revokeTitle"), tr("settings.users.revokeMsg")))) return;
    try { await api.post(`/users/${u.name}/revoke`, { token: tokenId }); await refetchUsers(); } catch (e) { fail(e); }
  }
  async function saveReg() {
    try { await api.saveSettings({ registration: { open: regOpen, invite_code: regCode.trim(), default_role: regRole } }); ok(tr("settings.saved.registration")); }
    catch (e) { fail(e); }
  }
  async function addDevice() {
    const label = (await promptText(tr("settings.devices.labelPrompt"), "my-pc")) ?? "my-pc";
    try {
      const r = await api.registerDevice(label);
      await Clipboard.setStringAsync(r.token);
      Alert.alert(tr("settings.devices.tokenCopiedTitle"), tr("settings.devices.tokenCopiedMsg"));
      await refetchDevices();
    } catch (e) { fail(e); }
  }
  async function revokeDeviceH(d: import("@/data/types").DeviceRow) {
    if (!(await confirmAsync(tr("settings.devices.revokeTitle"), tr("settings.devices.revokeMsg", { label: d.label })))) return;
    try { await api.revokeDevice(d.id); await refetchDevices(); } catch (e) { fail(e); }
  }
  function reassignCard(card: import("@/data/types").Track) {
    const others = (devices ?? []).filter((d) => ("local:" + d.id) !== card.exec_site);
    Alert.alert(card.task.slice(0, 60), tr("settings.devices.reassignPrompt"), [
      ...others.map((d) => ({
        text: d.label,
        onPress: async () => { try { await api.reassignCard(card.id, d.id); await qc.invalidateQueries({ queryKey: ["tracks"] }); } catch (e) { fail(e); } },
      })),
      { text: tr("settings.devices.reassignClear"), onPress: async () => { try { await api.reassignCard(card.id, ""); await qc.invalidateQueries({ queryKey: ["tracks"] }); } catch (e) { fail(e); } } },
      { text: tr("ui.cancel"), style: "cancel" as const },
    ]);
  }

  const logout = () => {
    api.post("/auth/logout", {}).catch(() => { /* best-effort - proceed regardless */ });
    useConfig.getState().set({ token: "" });
    // The profile cache is the LAST account's view. Left behind, the next
    // person to sign in on this device renders in their predecessor's language
    // for the frame before /me answers - the same class of leak clearCache()
    // already closes for the board.
    void clearProfileCache();
    useAuthGate.getState().reportAuthRequired();
  };

  const goDoor = (d: DoorId) => { setDoor(d); router.setParams({ door: d }); };
  const goList = () => { setDoor(null); router.setParams({ door: undefined }); };

  const content = { padding: 12, gap: 10, paddingBottom: 60, width: "100%" as const,
    maxWidth: wide ? 1100 : undefined, alignSelf: "center" as const };

  // -------------------------------------------------------------- door list
  if (!door) {
    const visible = DOORS.filter((d) => can(me, d.cap));
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
        <ScreenHeader title={tr("nav.settings")} onBack={() => router.back()} />
        <ScrollView contentContainerStyle={content}>
          {isLoading && owner ? <ActivityIndicator color={t.accent} /> : null}
          {error && owner ? <Text style={{ color: t.danger }}>{tr("settings.ownerOnly")}</Text> : null}
          <Panel style={{ padding: 0 }}>
            {visible.map((d, i) => (
              <Pressable key={d.id} onPress={() => goDoor(d.id)}
                style={{ flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 14, paddingVertical: 13,
                  borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder }}>
                <Ionicons name={d.icon} size={19} color={t.txtSecondary} />
                <View style={{ flex: 1, gap: 1 }}>
                  <Text style={{ color: t.txtPrimary, fontSize: 15 }}>{tr(d.labelKey)}</Text>
                  <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr(d.subKey)}</Text>
                </View>
                <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
              </Pressable>
            ))}
          </Panel>
          {/* Destructive LAST (NN/g, and the plan's door-6 "Abmelden +
              Gefahrenzone"). It stays on the door LIST rather than moving into
              door 6, because door 6 is owner-only and a client must be able to
              sign out of their own account - the hub root is the one page
              every role reaches. */}
          <Pressable onPress={logout}
            style={{ alignSelf: "flex-start", paddingVertical: 10, paddingHorizontal: 4 }}>
            <Text style={{ color: t.danger, fontSize: 13, fontWeight: "600" }}>{tr("settings.logout")}</Text>
          </Pressable>
          <DesktopUpdateBanner />
          <UpdatesPanel />
        </ScrollView>
      </View>
    );
  }

  const doorMeta = DOORS.find((d) => d.id === door)!;
  const Frame = ({ children }: { children: React.ReactNode }) => (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr(doorMeta.labelKey)} onBack={goList} />
      <ScrollView contentContainerStyle={content}>{children}</ScrollView>
    </View>
  );

  // ------------------------------------------------------ door 1: Mein Profil
  if (door === "general") {
    return (
      <Frame>
        {/* The account's own rows, straight from the schema on /me - so a
            client role, who cannot read /settings at all, still lands on a
            door with something in it. */}
        <Hint text={tr("profile.section.hint")} />
        <SchemaDoor door="general" schema={schema} />
        {/* Device-local, badged as such: these never leave this device. */}
        <Panel>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <SectionLabel text={tr("more.device.section")} />
            <ScopeBadge scope="device" />
          </View>
          <Toggle label={tr("settings.voice.speakBlockers")} value={blockerVoiceOn} onChange={setBlockerVoice} />
          <Hint text={tr("settings.voice.hint")} />
          <View style={{ height: 10 }} />
          <Toggle label={tr("settings.privacy.analyticsToggle")} value={analyticsOn} onChange={setAnalytics} />
          <Hint text={tr("settings.privacy.hint")} />
        </Panel>
        {can(me, "settings.write") ? (
          <Panel>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <SectionLabel text={tr("profile.wsSection")} />
              <ScopeBadge scope="workspace" />
            </View>
            <Hint text={tr("profile.wsSection.hint")} />
            <Caption text={tr("ui.language")} />
            <ChipPick options={LANG_LABELS} selected={[LANGS.find((l) => l.id === wsLang)?.label ?? LANG_LABELS[0]]}
              single onToggle={(label) => saveWsLang(langId(label))} />
            <View style={{ height: 10 }} />
            <Caption text={tr("settings.policy.backdrop")} />
            <ChipPick options={["mesh", "aurora", "ember", "forest", "mono"]} selected={[wsBackdrop]} single
              onToggle={(b) => { setWsBackdrop(b); api.saveSettings({ appearance: { backdrop: b } }).then(invalidate).catch(fail); }} />
          </Panel>
        ) : null}
      </Frame>
    );
  }

  // ---------------------------------------------------------- door 2: Boards
  if (door === "boards") {
    return (
      <Frame>
        <Panel>
          <SectionLabel text={tr("hub.boards.mine")} />
          <Hint text={tr("hub.boards.hint")} />
          {boards.length === 0 ? (
            <Text style={{ color: t.txtTertiary, fontSize: 12.5 }}>{tr("hub.boards.none")}</Text>
          ) : boards.map((b, i) => (
            <Pressable key={b.id || "fallback-" + i}
              onPress={() => router.push(`/boards?board=${encodeURIComponent(b.id)}` as never)}
              style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10,
                borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.glassBorder }}>
              <Ionicons name={b.owner === "" ? "people-outline" : "person-outline"} size={16} color={t.txtSecondary} />
              <View style={{ flex: 1, gap: 1 }}>
                <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{b.name}</Text>
                {/* THE BOARD-SCOPED VALUE, shown rather than counted.
                    This row used to say "4 Spalten", which is the one fact
                    about a board that needed no screen. The column LABELS are
                    the only genuinely board-owned values there are - the thing
                    the hub's "Board" badge points at - and they lived in the
                    boards table with no surface outside the editor. A label
                    left empty is shown as the station's own name in the same
                    dimmed style the editor uses for its placeholder, because
                    empty means exactly that (boards.py invariant 1) and
                    printing nothing would read as a broken row. */}
                <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 11.5 }}>
                  {(b.columns ?? []).length
                    ? (b.columns ?? []).map((c) => c.label || stationName(c.station)).join(" · ")
                    : tr("hub.boards.columns", { n: 0 })}
                </Text>
              </View>
              {b.owner === "" ? <Chip text={tr("boards.shared")} dot={t.accent} /> : null}
              <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
            </Pressable>
          ))}
          <View style={{ height: 12 }} />
          <Btn label={tr("hub.boards.open")} kind="ghost" onPress={() => router.push("/boards" as never)} />
        </Panel>
        {/* The STATION-NAME registry - workspace-scoped, and the badge on it now
            says so. It is what every surface outside a board calls a station
            (the move menu, the card detail, the loop map) and what an
            unlabelled column falls back to; the per-board labels above are the
            board-scoped half, and their one edit surface is the board editor
            this door links into. Two values, two scopes, two honest badges -
            which is what debt board-scope-still-in-settings-json asked for. */}
        <SchemaDoor door="boards" schema={schema} />
      </Frame>
    );
  }

  // ------------------------------------------------ door 3: Agenten/Autonomie
  if (door === "automation") {
    return (
      <Frame>
        {pmEnabled ? (
          <Panel>
            <SectionLabel text={tr("pm.title")} />
            <PMControls />
          </Panel>
        ) : null}
        <Panel>
          <SectionLabel text="build-loop" />
          <Text style={{ color: t.accent, fontWeight: "600", marginBottom: 2 }}>{curState ? tr("automation.now", { state: curState }) : "?"}</Text>
          {cur[0]?.action ? <Text style={{ color: t.txtSecondary, fontSize: 12, marginBottom: 8 }}>{cur[0].action}</Text> : null}
          <Pressable onPress={() => router.push("/loopmap" as never)}
            style={{ flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: t.surface2,
              borderColor: t.glassBorder, borderWidth: 1, borderRadius: 12, padding: 11 }}>
            <Ionicons name="git-network-outline" size={16} color={t.accent} />
            <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600", flex: 1 }}>{tr("automation.openMap")}</Text>
            <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
          </Pressable>
        </Panel>
        {/* policy + nightshift, both schema-rendered. This door is still the
            ONLY place nightshift.* is editable (the plan's dedup requirement);
            the old duplicate form in settings.tsx is long gone. */}
        <SchemaDoor door="automation" schema={schema} />
        <Panel>
          <SectionLabel text={tr("settings.night.repos")} />
          <TextInput value={nsRepos} onChangeText={setNsRepos} autoCapitalize="none" multiline
            placeholder={"C:\\Users\\you\\Downloads\\myrepo"} placeholderTextColor={t.txtPlaceholder}
            style={[field, { minHeight: 84, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", fontSize: 12 }]} />
          <View style={{ height: 12 }} />
          <Btn label={nsBusy ? "…" : tr("automation.save")} onPress={saveNsRepos} disabled={nsBusy} />
        </Panel>
        <HarnessSection />
        <Panel>
          <SectionLabel text={tr("automation.repos", { n: autoRepos.length })} />
          {autoRepos.length === 0 ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("automation.noRepos")}</Text> :
            autoRepos.map((r) => <Text key={r} style={{ color: t.txtSecondary, fontSize: 11.5 }}>{r}</Text>)}
        </Panel>
      </Frame>
    );
  }

  // ----------------------------------------------------------- door 4: Zellen
  if (door === "cells") {
    return (
      <Frame>
        <Panel>
          <CellsCatalog />
        </Panel>
        <SchemaDoor door="cells" schema={schema} />
      </Frame>
    );
  }

  // ------------------------------------------------------ door 5: Verbindungen
  if (door === "connections") {
    return (
      <Frame>
        <Panel>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <SectionLabel text={tr("nav.connectors")} />
            <Pressable onPress={() => router.push("/connectors" as never)}>
              <Text style={{ color: t.accent, fontSize: 12.5, fontWeight: "600" }}>{tr("ui.open")}</Text>
            </Pressable>
          </View>
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
        <SchemaDoor door="connections" schema={schema} />
      </Frame>
    );
  }

  // ---------------------------------------------------- door 6: Team & Geräte
  if (door === "team") {
    return (
      <Frame>
        <Panel>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <SectionLabel text={tr("settings.sec.mobile")} />
            <ScopeBadge scope="device" />
          </View>
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
          <SectionLabel text={tr("settings.sec.wearPair")} />
          <Hint text={tr("settings.wearPair.hint")} />
          <TextInput value={wearLabel} onChangeText={setWearLabel} autoCapitalize="words"
            placeholder={tr("settings.wearPair.label")} placeholderTextColor={t.txtPlaceholder} style={field} />
          <View style={{ height: 10 }} />
          <Btn label={wearBusy ? "…" : tr("settings.wearPair.pairWatch")} onPress={pairWatch} disabled={wearBusy} />
          {wearCode ? (
            <View style={{ marginTop: 10, gap: 8 }}>
              <Hint text={tr("settings.wearPair.ttl", { min: wearTtlMin })} />
              <View style={{ backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 8, padding: 14, alignItems: "center" }}>
                <Text selectable style={{ color: t.accent, fontSize: 22, letterSpacing: 4,
                  fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" }}>{wearCode}</Text>
              </View>
              <Btn label={tr("settings.wearPair.copyCode")} kind="ghost" onPress={async () => {
                await Clipboard.setStringAsync(wearCode);
                Alert.alert(tr("settings.pair.copiedTitle"), tr("settings.wearPair.codeCopied"));
              }} />
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
                    <View key={tk.id} style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <Text style={{ color: t.txtTertiary, fontSize: 11, flex: 1 }} numberOfLines={1}>
                        {tk.label} · …{tk.tail}
                        {tk.stale ? "  " : ""}
                      </Text>
                      {/* card 5 debt: >90d unused, computed server-side */}
                      {tk.stale ? (
                        <View style={{ borderWidth: 1, borderColor: t.warn + "66", borderRadius: 5, paddingHorizontal: 5, paddingVertical: 1 }}>
                          <Text style={{ color: t.warn, fontSize: 9.5, fontWeight: "600" }}>{tr("settings.users.stale")}</Text>
                        </View>
                      ) : null}
                      <Pressable onPress={() => revokeToken(u, tk.id)}><Text style={{ color: t.danger, fontSize: 11 }}>{tr("settings.users.revoke")}</Text></Pressable>
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
          <SectionLabel text={tr("settings.sec.devices", { n: devices?.length ?? 0 })} />
          <Hint text={tr("settings.devices.hint")} />
          {(devices ?? []).map((d) => (
            <View key={d.id} style={{ paddingVertical: 8, borderTopWidth: 1, borderTopColor: t.glassBorder, gap: 4 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Text style={{ color: t.txtPrimary, fontSize: 13.5, flex: 1 }} numberOfLines={1}>{d.label}</Text>
                <Chip text={tr(d.billing_scope === "shared" ? "settings.devices.scopeShared" : "settings.devices.scopeExternal")}
                      dot={d.billing_scope === "shared" ? t.ai : t.txtTertiary} />
                <Pressable onPress={() => revokeDeviceH(d)}><Text style={{ color: t.danger, fontSize: 12 }}>{tr("settings.devices.revoke")}</Text></Pressable>
              </View>
              <Text style={{ color: t.txtTertiary, fontSize: 11 }}>
                {d.last_seen ? tr("settings.devices.lastSeen", { when: String(d.last_seen).replace("T", " ").slice(0, 16) }) : tr("settings.devices.neverSeen")}
              </Text>
            </View>
          ))}
          {(tracks ?? []).filter((k) => k.device_stale).map((k) => (
            <View key={k.id} style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6, borderTopWidth: 1, borderTopColor: t.glassBorder }}>
              <Text style={{ color: t.danger, fontSize: 12, flex: 1 }} numberOfLines={1}>⚠ {k.task.slice(0, 50)}</Text>
              <Pressable onPress={() => reassignCard(k)}><Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{tr("settings.devices.reassign")}</Text></Pressable>
            </View>
          ))}
          <View style={{ height: 10 }} />
          <Btn label={tr("settings.devices.register")} kind="ghost" onPress={addDevice} />
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
        <SchemaDoor door="team" schema={schema} />
      </Frame>
    );
  }

  // -------------------------------------------------------------- door 7: System
  return (
    <Frame>
      <UsagePanel />
      {/* Business + machine knobs: schema-rendered since phase 4. This was a
          hand-built nine-field FormGrid with its own saveBusiness(). */}
      <SchemaDoor door="system" schema={schema} />

      {/* GxP-mode activation (rbac-gxp card 6) - defense in depth beyond this
          door already being owner-only: also checked against the live
          capability matrix, not assumed from the door. */}
      {can(me, "gxp.activate") ? (
        <Panel>
          <SectionLabel text={tr("gxp.openDialog")} />
          <Hint text={tr("gxp.openDialogSub")} />
          <Text style={{ color: gxpState?.active ? t.ok : t.txtTertiary, fontSize: 12, marginBottom: 8 }}>
            {gxpState?.active
              ? (gxpState.scope === "workspace"
                  ? tr("gxp.activeWorkspace", { who: gxpState.activated_by ?? "?" })
                  : tr("gxp.activeRepos", { who: gxpState.activated_by ?? "?", n: gxpState.repos?.length ?? 0 }))
              : tr("gxp.inactive")}
          </Text>
          {gxpMsg ? <Text style={{ color: t.ok, fontSize: 12, marginBottom: 8 }}>{gxpMsg}</Text> : null}
          <Btn label={tr("gxp.openDialog")} kind="ghost" onPress={() => { setGxpMsg(null); setShowGxp(true); }} />
        </Panel>
      ) : null}

      <DesktopUpdateBanner />
      <UpdatesPanel />
      {showGxp ? (
        <GxpActivate
          onClose={() => setShowGxp(false)}
          onActivated={(msg) => setGxpMsg(msg)}
        />
      ) : null}
    </Frame>
  );
}
