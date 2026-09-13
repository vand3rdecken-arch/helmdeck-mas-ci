// Engines - the Paseo "Settings > Providers" section, ported to HelmDeck.
//
// Layout copied from packages/app/src/screens/settings/providers-section.tsx
// (read 2026-09-13): one row per engine = chevron, name, status dot + label
// ("available · version" / "not installed" / "error" / "off"), the error text
// under it, and an enable switch on the trailing edge. Tapping a row opens
// what Paseo puts in its provider sheet (provider-diagnostic-sheet.tsx):
// a diagnostic block (resolved executable, version, driver verification) with
// a refresh, and the override editor. HelmDeck has no modal sheet primitive
// on every surface, so the "sheet" is an inline expansion under the row -
// same content, one screen.
//
// Mechanism copied too: Paseo patches daemon config `providers[id] = {enabled,
// command, env}` and the snapshot re-derives. Here the row is
// `settings.drivers[id]` (POST /settings, one-level merge per driver id, so
// the WHOLE row goes back), and GET /engines re-probes the binary.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Linking, Platform, Pressable, Switch, Text, TextInput, View } from "react-native";

import { api } from "@/data/client";
import type { EngineEntry } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { SectionLabel } from "@/ui/kit";
import { Btn, Caption, fieldStyle } from "@/ui/settings_sections";

// Paseo's catalog rows link to install instructions per provider; the
// commands are the ones surfaces/desktop/setup.js already uses (ENGINES).
const INSTALL: Record<string, { cmd: string; url: string }> = {
  claude: { cmd: "npm i -g @anthropic-ai/claude-code", url: "https://docs.anthropic.com/claude-code" },
  "claude-desktop": { cmd: "npm i -g @anthropic-ai/claude-code", url: "https://docs.anthropic.com/claude-code" },
  codex: { cmd: "npm i -g @openai/codex", url: "https://github.com/openai/codex" },
  opencode: { cmd: "npm i -g opencode-ai", url: "https://opencode.ai" },
  omp: { cmd: "", url: "https://github.com/ohmyprompt/omp" },
  pi: { cmd: "", url: "https://github.com/pi-cli/pi" },
};

const envToText = (env?: Record<string, string>) =>
  Object.entries(env ?? {}).map(([k, v]) => `${k}=${v}`).join("\n");
const textToEnv = (text: string): Record<string, string> => {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const i = line.indexOf("=");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
};

type Tone = "ok" | "warn" | "err" | "muted";
function statusOf(e: EngineEntry, tr: (k: string) => string): { tone: Tone; label: string } {
  if (!e.enabled) return { tone: "muted", label: tr("engines.st.disabled") };
  if (e.status === "ready") return { tone: "ok", label: tr("engines.st.available") };
  if (e.error && !/not installed/.test(e.error)) return { tone: "err", label: tr("engines.st.error") };
  return { tone: "warn", label: tr("engines.st.notInstalled") };
}

function EngineRow({ e, open, onOpen, onToggle, busy }: {
  e: EngineEntry; open: boolean; onOpen: () => void; onToggle: (v: boolean) => void; busy: boolean;
}) {
  const t = useTheme();
  const tr = useT();
  const st = statusOf(e, tr);
  const dot = { ok: t.ok, warn: t.warn, err: t.danger, muted: t.txtTertiary }[st.tone];
  const version = e.status === "ready" ? e.version.replace(/\s*\(.*\)\s*$/, "") : "";
  return (
    <Pressable onPress={onOpen} accessibilityRole="button"
      style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10,
        borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
      <Text style={{ color: t.txtTertiary, fontSize: 12, width: 10 }}>{open ? "▾" : "▸"}</Text>
      <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{e.label}</Text>
          <Text style={{ color: t.txtTertiary }}>·</Text>
          <View style={{ width: 7, height: 7, borderRadius: 3.5, backgroundColor: dot }} />
          <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{st.label}</Text>
          {version ? <><Text style={{ color: t.txtTertiary }}>·</Text>
            <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{version}</Text></> : null}
          {!e.verified ? <><Text style={{ color: t.txtTertiary }}>·</Text>
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("engines.untested")}</Text></> : null}
        </View>
        {e.enabled && st.tone === "err" ? (
          <Text numberOfLines={3} style={{ color: t.danger, fontSize: 11.5 }}>{e.error}</Text>
        ) : null}
      </View>
      <Switch value={e.enabled} onValueChange={onToggle} disabled={busy}
        accessibilityLabel={tr("engines.enable").replace("{name}", e.label)} />
    </Pressable>
  );
}

function EngineDetail({ e, onSaved }: { e: EngineEntry; onSaved: () => void }) {
  const t = useTheme();
  const tr = useT();
  const field = fieldStyle(t);
  const mono = { fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", fontSize: 12 };
  const [exe, setExe] = useState(e.config.exe ?? "");
  const [env, setEnv] = useState(envToText(e.config.env));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const install = INSTALL[e.id];

  async function save(reset = false) {
    setBusy(true); setMsg("");
    // the WHOLE row goes back (one-level merge per driver id, see header)
    const row: Record<string, unknown> = { ...e.config };
    if (reset) { delete row.exe; delete row.env; }
    else {
      if (exe.trim()) row.exe = exe.trim(); else delete row.exe;
      const envObj = textToEnv(env);
      if (Object.keys(envObj).length) row.env = envObj; else delete row.env;
    }
    const r = await api.saveSettings({ drivers: { [e.id]: { type: e.type, ...row } } }) as { error?: string } | null;
    setBusy(false);
    if (r && r.error) { setMsg(r.error); return; }
    if (reset) { setExe(""); setEnv(""); }
    setMsg(tr("engines.cfg.saved"));
    onSaved();
  }

  // paths/versions/errors are code (mono); the driver verdict is a sentence
  const kv = (k: string, v: string, prose = false) => (
    <View key={k} style={{ flexDirection: "row", gap: 8 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 12, width: 84 }}>{k}</Text>
      <Text selectable style={[{ color: t.txtSecondary, flex: 1, fontSize: 12 }, prose ? null : mono]}>{v || "—"}</Text>
    </View>
  );

  return (
    <View style={{ paddingLeft: 20, paddingBottom: 12, gap: 12 }}>
      <View style={{ gap: 6 }}>
        <Caption text={tr("engines.diag")} />
        {kv(tr("engines.diag.exe"), e.exe ?? "")}
        {kv(tr("engines.diag.version"), e.version)}
        {kv(tr("engines.diag.driver"), e.verified ? tr("engines.diag.verified") : tr("engines.diag.unverified"), true)}
        {e.error ? kv(tr("engines.st.error"), e.error) : null}
        {e.status !== "ready" && install ? (
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Text style={{ color: t.txtTertiary, fontSize: 12, width: 84 }}>{tr("engines.install")}</Text>
            {install.cmd ? <Text selectable style={{ color: t.txtSecondary, ...mono }}>{install.cmd}</Text> : null}
            <Pressable onPress={() => { void Linking.openURL(install.url); }}>
              <Text style={{ color: t.accent, fontSize: 12 }}>{install.url.replace(/^https?:\/\//, "")}</Text>
            </Pressable>
          </View>
        ) : null}
      </View>
      <View style={{ gap: 6 }}>
        <Caption text={tr("engines.cfg")} />
        <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("engines.cfg.exe")}</Text>
        <TextInput value={exe} onChangeText={setExe} autoCapitalize="none" autoCorrect={false}
          placeholder={e.exe ?? ""} placeholderTextColor={t.txtPlaceholder} style={[field, mono]} />
        <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("engines.cfg.env")}</Text>
        <TextInput value={env} onChangeText={setEnv} autoCapitalize="none" autoCorrect={false} multiline
          placeholder={"KEY=value"} placeholderTextColor={t.txtPlaceholder}
          style={[field, mono, { minHeight: 64 }]} />
        <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Btn label={busy ? "…" : tr("engines.cfg.save")} onPress={() => { void save(false); }} disabled={busy} />
          {e.config.exe || e.config.env ? (
            <Btn label={tr("engines.cfg.reset")} kind="ghost" onPress={() => { void save(true); }} disabled={busy} />
          ) : null}
          {msg ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{msg}</Text> : null}
        </View>
      </View>
    </View>
  );
}

export function EnginesSection() {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["engines"], queryFn: () => api.engines(), staleTime: 60_000,
  });
  const [open, setOpen] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const engines = data?.engines ?? [];

  async function refresh(reprobe: boolean) {
    if (reprobe) {
      const fresh = await api.engines(true);
      if (fresh) qc.setQueryData(["engines"], fresh);
    } else {
      await refetch();
    }
  }

  async function toggle(e: EngineEntry, on: boolean) {
    setToggling(e.id);
    // Paseo: patchConfig({providers: {[id]: {enabled}}}). Same shape, whole row.
    await api.saveSettings({ drivers: { [e.id]: { type: e.type, ...e.config, enabled: on } } });
    await refresh(false);
    setToggling(null);
  }

  return (
    <View>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <SectionLabel text={tr("engines.title")} />
        <Pressable onPress={() => { void refresh(true); }} disabled={isFetching} hitSlop={8}>
          <Text style={{ color: t.accent, fontSize: 12.5, fontWeight: "600", opacity: isFetching ? 0.5 : 1 }}>
            {tr("engines.recheck")}
          </Text>
        </Pressable>
      </View>
      <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 6 }}>{tr("engines.hint")}</Text>
      {isLoading ? <ActivityIndicator color={t.accent} /> : engines.map((e) => (
        <View key={e.id}>
          <EngineRow e={e} open={open === e.id} onOpen={() => setOpen(open === e.id ? null : e.id)}
            onToggle={(v) => { void toggle(e, v); }} busy={toggling === e.id} />
          {open === e.id ? <EngineDetail key={JSON.stringify(e.config)} e={e} onSaved={() => { void refresh(true); }} /> : null}
        </View>
      ))}
    </View>
  );
}
