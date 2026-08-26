import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import { useLocalSearchParams, useRouter } from "expo-router";
import util from "tweetnacl-util";
import { useConfig } from "@/data/config";
import { qrDataUrl } from "@/data/qrgen";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, Image, Platform, Pressable, ScrollView, Text, TextInput, type TextStyle, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useAuthGate } from "@/data/authgate";
import { useCellEnabled } from "@/data/cells";
import type { UserRow } from "@/data/types";
import { LANGS, useT, type Lang } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Chip, KVRow, Panel, ScreenHeader, SectionLabel } from "@/ui/kit";
import { UsagePanel } from "@/ui/dash_panels";
import { HarnessSection } from "@/ui/harness_section";
import { PMControls } from "@/ui/pm_panel";
import { Btn, Caption, ChipPick, confirmAsync, fieldStyle, FormGrid, Hint, isWeb, promptText, Toggle } from "@/ui/settings_sections";
import { DesktopUpdateBanner } from "@/ui/desktop_update";
import { UpdatesPanel } from "@/ui/updates_info";
import { useResponsive } from "@/ui/responsive";

// ---------------------------------------------------------------------------
// settings-ia-redesign (ops/docs/backlog/settings-ia-redesign) - the hub.
//
// ONE route ("settings"), an internal door list + door detail, addressable
// via ?door=<id> (so /automation and /modules can redirect here instead of
// living as their own screens - see automation.tsx/modules.tsx). This
// replaces the old flat 10-panel settings.tsx: doors group by USER GOAL
// (Home-Assistant pattern), not by which daemon key backs a field.
//
// Deliberate scope for THIS pass (see the backlog doc for the full phase
// plan): doors 2/5/6 below are fully built here. Door "cells" (3) links out
// to the existing modules.tsx, which already renders a live, registry-driven
// cell catalog (GET /cells) with per-cell diagrams - not rebuilt here, it
// already does the job. Door "connections" (4) folds in Jira/import (moved
// from the old settings.tsx) and links to connectors.tsx. Search and the
// guided connect wizards are later cards (settings-search,
// connect-wizards) - not here.
//
// Nightshift dedup (a named requirement of the plan): this hub is now the
// ONLY place nightshift.* is editable - the old settings.tsx had a second,
// duplicate form for the exact same keys. That second form is gone.
type DoorId = "general" | "automation" | "cells" | "connections" | "team" | "system";
const DOORS: readonly { id: DoorId; labelKey: string; subKey: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { id: "general", labelKey: "hub.door.general", subKey: "hub.door.general.sub", icon: "options-outline" },
  { id: "automation", labelKey: "hub.door.automation", subKey: "hub.door.automation.sub", icon: "flash-outline" },
  { id: "cells", labelKey: "hub.door.cells", subKey: "hub.door.cells.sub", icon: "grid-outline" },
  { id: "connections", labelKey: "hub.door.connections", subKey: "hub.door.connections.sub", icon: "extension-puzzle-outline" },
  { id: "team", labelKey: "hub.door.team", subKey: "hub.door.team.sub", icon: "people-outline" },
  { id: "system", labelKey: "hub.door.system", subKey: "hub.door.system.sub", icon: "hardware-chip-outline" },
];

const BACKDROPS = ["mesh", "aurora", "ember", "forest", "mono"] as const;
const LANG_LABELS = LANGS.map((l) => l.label);
const langId = (label: string): Lang => (LANGS.find((l) => l.label === label)?.id ?? "de");

type Ctl = "toggle" | "multi" | "single" | "text" | "number" | "labels";
interface ConfigItem {
  group: "policy" | "night";
  path: string;
  control: Ctl;
  labelKey: string;
  descKey?: string;
  level?: "basic" | "advanced";
  door?: string;
  value: unknown;
  options?: string[];
  keys?: string[];
  placeholder?: string;
}

function nest(path: string, value: unknown): Record<string, unknown> {
  const [a, b] = path.split(".");
  return { [a]: { [b]: value } };
}

// Module scope, not component body - see automation.tsx's incident note this
// was copied from: a function redeclared every render loses text-input focus
// after one keystroke (React treats it as a brand new component type).
function Control({ it, value, onChange, t, tr, field, wide }: {
  it: ConfigItem; value: unknown; onChange: (v: unknown) => void;
  t: ThemeTokens; tr: (k: string, p?: Record<string, string | number>) => string;
  field: TextStyle; wide: boolean;
}) {
  const label = tr(it.labelKey);
  const desc = it.descKey ? tr(it.descKey) : "";
  if (it.control === "toggle")
    return <View><Toggle label={label} value={!!value} onChange={onChange} />{desc ? <Hint text={desc} /> : null}</View>;
  if (it.control === "text" || it.control === "number")
    return (
      <View>
        <Caption text={label} />
        <TextInput value={value == null ? "" : String(value)} style={field}
          keyboardType={it.control === "number" ? "numeric" : "default"}
          autoCapitalize="none" placeholder={it.placeholder} placeholderTextColor={t.txtPlaceholder}
          onChangeText={(x) => onChange(it.control === "number" ? (Number(x) || 0) : x)} />
        {desc ? <Hint text={desc} /> : null}
      </View>
    );
  if (it.control === "single")
    return (
      <View>
        <Caption text={label} />
        <ChipPick options={it.options ?? []} selected={[String(value ?? "")]} single onToggle={onChange} />
        {desc ? <Hint text={desc} /> : null}
      </View>
    );
  if (it.control === "multi") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <View>
        <Caption text={label} />
        <ChipPick options={it.options ?? []} selected={arr}
          onToggle={(x) => onChange(arr.includes(x) ? arr.filter((y) => y !== x) : [...arr, x])} />
        {desc ? <Hint text={desc} /> : null}
      </View>
    );
  }
  if (it.control === "labels") {
    const obj = (value && typeof value === "object" ? value : {}) as Record<string, string>;
    return (
      <View>
        <Caption text={label} />
        <FormGrid wide={wide}>
          {(it.keys ?? []).map((k) => (
            <View key={k}>
              <Text style={{ color: t.txtTertiary, fontSize: 11, marginBottom: 3 }}>{k}</Text>
              <TextInput value={obj[k] ?? ""} style={field}
                onChangeText={(x) => onChange({ ...obj, [k]: x })} />
            </View>
          ))}
        </FormGrid>
        {desc ? <Hint text={desc} /> : null}
      </View>
    );
  }
  return null;
}

type PlanRepo = { items?: { title: string; priority?: string }[]; error?: string | null };
type NightPlan = { made?: string; actor?: string; repos?: Record<string, PlanRepo> };

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

  const { data: s, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const { data: auto } = useQuery({ queryKey: ["automation"], queryFn: api.automation, staleTime: 30000 });
  const { data: users, refetch: refetchUsers } = useQuery({ queryKey: ["users"], queryFn: api.users });
  const { data: devices, refetch: refetchDevices } = useQuery({ queryKey: ["devices"], queryFn: api.devices });
  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks });
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 8000 });
  const actors = metrics?.capacity?.actors ?? {};
  const pmEnabled = useCellEnabled("pm");

  const field = fieldStyle(t);

  // ---- business (door: system) ----
  const [repo, setRepo] = useState("");
  const [wip, setWip] = useState("");
  const [value, setValue] = useState("");
  const [budget, setBudget] = useState("");
  const [tSteer, setTSteer] = useState(""); const [tReview, setTReview] = useState(""); const [tBounce, setTBounce] = useState("");

  // ---- language / appearance (door: general) ----
  const [lang, setLangSel] = useState<Lang>("de");
  const [backdrop, setBackdrop] = useState("mesh");

  // ---- jira / imports (door: connections) ----
  const [jBase, setJBase] = useState(""); const [jEmail, setJEmail] = useState("");
  const [jToken, setJToken] = useState(""); const [jJql, setJJql] = useState("");
  const [impUrl, setImpUrl] = useState(""); const [busyImp, setBusyImp] = useState(false);

  // ---- automation: schema-driven draft (door: automation) ----
  const schema = ((auto?.config_schema as ConfigItem[]) ?? []);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [busyGroup, setBusyGroup] = useState<string>("");
  const dirty = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!schema.length) return;
    setDraft((d) => {
      const next: Record<string, unknown> = {};
      for (const it of schema) next[it.path] = dirty.current.has(it.path) && it.path in d ? d[it.path] : it.value;
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto]);
  const setKnob = (path: string, v: unknown) => { dirty.current.add(path); setDraft((d) => ({ ...d, [path]: v })); };
  // nightshift.repos is NOT a schema knob (a newline list, not a control the
  // schema's flat model covers yet) - kept as one extra field here so this
  // stays the ONLY nightshift edit surface (the plan's dedup requirement),
  // saved in the same patch as the schema knobs below.
  const [nsRepos, setNsRepos] = useState("");
  useEffect(() => { if (s) setNsRepos((s.nightshift?.repos ?? []).join("\n")); }, [s]);
  async function saveAutomationGroup(group: "policy" | "night") {
    setBusyGroup(group);
    try {
      const patch: Record<string, any> = {};
      const items = schema.filter((i) => i.group === group);
      for (const it of items) { const [a, b] = it.path.split("."); (patch[a] ??= {})[b] = draft[it.path]; }
      if (group === "night") {
        patch.nightshift = { ...(patch.nightshift ?? {}), repos: nsRepos.split("\n").map((r) => r.trim()).filter(Boolean) };
      }
      await api.saveSettings(patch);
      for (const it of items) dirty.current.delete(it.path);
      await qc.invalidateQueries({ queryKey: ["automation"] });
      await qc.invalidateQueries({ queryKey: ["settings"] });
      await qc.invalidateQueries({ queryKey: ["metrics"] });
    } catch (e) { Alert.alert("", String((e as Error).message)); } finally { setBusyGroup(""); }
  }
  const policyItems = schema.filter((i) => i.group === "policy");
  const nightItems = schema.filter((i) => i.group === "night");
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

  // ---- add user (door: team) ----
  const [uName, setUName] = useState(""); const [uPw, setUPw] = useState(""); const [uRole, setURole] = useState("operator");

  // ---- registration (door: team) ----
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
    setRegOpen(!!s.registration?.open); setRegCode(s.registration?.invite_code ?? "");
    setRegRole(s.registration?.default_role ?? "client");
  }, [s]);

  const ok = (msg: string) => Alert.alert(tr("settings.savedTitle"), msg);
  const fail = (e: unknown) => Alert.alert(tr("ui.error"), String((e as Error).message));
  async function invalidate() { await qc.invalidateQueries({ queryKey: ["settings"] }); }

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
    useAuthGate.getState().reportAuthRequired();
  };

  const goDoor = (d: DoorId) => { setDoor(d); router.setParams({ door: d }); };
  const goList = () => { setDoor(null); router.setParams({ door: undefined }); };

  const content = { padding: 12, gap: 10, paddingBottom: 60, width: "100%" as const,
    maxWidth: wide ? 1100 : undefined, alignSelf: "center" as const };

  // -------------------------------------------------------------- door list
  if (!door) {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
        <ScreenHeader title={tr("nav.settings")} onBack={() => router.back()} />
        <ScrollView contentContainerStyle={content}>
          <Pressable onPress={logout} style={{ alignSelf: "flex-start", marginBottom: 4 }}>
            <Text style={{ color: t.danger, fontSize: 13, fontWeight: "600" }}>Abmelden</Text>
          </Pressable>
          {isLoading ? <ActivityIndicator color={t.accent} /> : null}
          {error ? <Text style={{ color: t.danger }}>{tr("settings.ownerOnly")}</Text> : null}
          <Panel style={{ padding: 0 }}>
            {DOORS.map((d, i) => (
              <Pressable key={d.id}
                onPress={() => (d.id === "cells" ? router.push("/modules" as never) : goDoor(d.id))}
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
          <DesktopUpdateBanner />
          <UpdatesPanel />
        </ScrollView>
      </View>
    );
  }

  const doorMeta = DOORS.find((d) => d.id === door)!;

  // ------------------------------------------------------------- door: general
  if (door === "general") {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
        <ScreenHeader title={tr(doorMeta.labelKey)} onBack={goList} />
        <ScrollView contentContainerStyle={content}>
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
        </ScrollView>
      </View>
    );
  }

  // ---------------------------------------------------------- door: automation
  if (door === "automation") {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
        <ScreenHeader title={tr(doorMeta.labelKey)} onBack={goList} />
        <ScrollView contentContainerStyle={content}>
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
          {policyItems.length ? (
            <Panel>
              <SectionLabel text={tr("automation.configPolicy")} />
              {policyItems.map((it, i) => (
                <View key={it.path} style={{ marginTop: i ? 10 : 0 }}>
                  <Control it={it} value={draft[it.path]} onChange={(v) => setKnob(it.path, v)} t={t} tr={tr} field={field} wide={wide} />
                </View>
              ))}
              <View style={{ height: 12 }} />
              <Btn label={busyGroup === "policy" ? "…" : tr("automation.save")} onPress={() => saveAutomationGroup("policy")} disabled={busyGroup === "policy"} />
            </Panel>
          ) : null}
          {/* nightshift: the ONLY edit surface now (dedup - the old settings.tsx
              had a second, duplicate form for these same daemon keys). */}
          {nightItems.length ? (
            <Panel>
              <SectionLabel text={tr("automation.nightSection")} />
              {nightItems.map((it, i) => (
                <View key={it.path} style={{ marginTop: i ? 10 : 0 }}>
                  <Control it={it} value={draft[it.path]} onChange={(v) => setKnob(it.path, v)} t={t} tr={tr} field={field} wide={wide} />
                </View>
              ))}
              <View style={{ height: 10 }} />
              <Caption text={tr("settings.night.repos")} />
              <TextInput value={nsRepos} onChangeText={setNsRepos} autoCapitalize="none" multiline
                placeholder={"C:\\Users\\you\\Downloads\\myrepo"} placeholderTextColor={t.txtPlaceholder}
                style={[field, { minHeight: 84, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", fontSize: 12 }]} />
              <View style={{ height: 12 }} />
              <Btn label={busyGroup === "night" ? "…" : tr("automation.save")} onPress={() => saveAutomationGroup("night")} disabled={busyGroup === "night"} />
            </Panel>
          ) : null}
          <HarnessSection />
          <Panel>
            <SectionLabel text={tr("automation.repos", { n: autoRepos.length })} />
            {autoRepos.length === 0 ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("automation.noRepos")}</Text> :
              autoRepos.map((r) => <Text key={r} style={{ color: t.txtSecondary, fontSize: 11.5 }}>{r}</Text>)}
          </Panel>
        </ScrollView>
      </View>
    );
  }

  // --------------------------------------------------------- door: connections
  if (door === "connections") {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
        <ScreenHeader title={tr(doorMeta.labelKey)} onBack={goList} />
        <ScrollView contentContainerStyle={content}>
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
        </ScrollView>
      </View>
    );
  }

  // ---------------------------------------------------------------- door: team
  if (door === "team") {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
        <ScreenHeader title={tr(doorMeta.labelKey)} onBack={goList} />
        <ScrollView contentContainerStyle={content}>
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
                      <View key={tk.id} style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                        <Text style={{ color: t.txtTertiary, fontSize: 11, flex: 1 }} numberOfLines={1}>{tk.label} · …{tk.tail}</Text>
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
        </ScrollView>
      </View>
    );
  }

  // -------------------------------------------------------------- door: system
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr(doorMeta.labelKey)} onBack={goList} />
      <ScrollView contentContainerStyle={content}>
        <UsagePanel />
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
            <View style={{ flex: 1 }}><TextInput value={tSteer} onChangeText={setTSteer} keyboardType="numeric" style={field} /></View>
            <View style={{ flex: 1 }}><TextInput value={tReview} onChangeText={setTReview} keyboardType="numeric" style={field} /></View>
            <View style={{ flex: 1 }}><TextInput value={tBounce} onChangeText={setTBounce} keyboardType="numeric" style={field} /></View>
          </View>
          <View style={{ height: 12 }} />
          <Btn label={tr("ui.save")} onPress={saveBusiness} />
        </Panel>
        <DesktopUpdateBanner />
        <UpdatesPanel />
      </ScrollView>
    </View>
  );
}
