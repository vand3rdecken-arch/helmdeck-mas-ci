/** Build/OTA identity, shown in Settings (panel) and More (footer). With silent
 *  updates there is no prompt, so THIS is how a human verifies what's running:
 *  the OTA id/date moves each time an update applied - if it moved, you updated. */
import * as Clipboard from "expo-clipboard";
import Constants from "expo-constants";
import * as Updates from "expo-updates";
import { useCallback, useEffect, useState } from "react";
import { Platform, Pressable, ScrollView, Text, View } from "react-native";

import { otaPending } from "@/data/ota";
import { t as i18nT, useT } from "@/i18n";
import { useTheme } from "@/theme";
import { DesktopUpdatesPanel, isDesktopShell } from "@/ui/desktop_update";
import { DiagPanel, useSecretTap } from "@/ui/diag_panel";
import { KVRow, Panel, SectionLabel } from "@/ui/kit";

// expoConfig is null in release/OTA builds - fall back to the updates
// runtimeVersion (policy: appVersion), which equals the app version there.
const version = Constants.expoConfig?.version ?? Updates.runtimeVersion ?? "?";
const build = (Constants.expoConfig as { android?: { versionCode?: number } } | null)?.android?.versionCode;

function bundleLabel(): string {
  return Updates.isEmbeddedLaunch
    ? i18nT("updates.embedded")
    : Updates.updateId
    ? `OTA ${Updates.updateId.slice(0, 8)} · ${Updates.createdAt ? new Date(Updates.createdAt).toLocaleString() : "?"}`
    : "Dev";
}

/** Version + the running JS bundle, so silent OTA updates are visible.
 *
 *  Also the app's way into the black box: 7 taps on the version line opens the
 *  diagnostics panel (ui/diag_panel.tsx). The version line is the conventional
 *  home for that gesture (Android's build-number tap), it is already rendered
 *  on the More tab, and hanging it here means no new nav row, no new route and
 *  nothing a normal user can wander into. */
export function VersionFooter() {
  const t = useTheme();
  const diagTap = useSecretTap();
  return (
    <View style={{ alignItems: "center", paddingVertical: 16, gap: 3 }}>
      <Text onPress={diagTap.onPress} suppressHighlighting
        style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>HelmDeck v{version}{build ? ` · Build ${build}` : ""}</Text>
      <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{bundleLabel()}</Text>
      {diagTap.open ? (
        <View style={{ width: "100%", maxWidth: 620, paddingTop: 12 }}>
          <DiagPanel onClose={diagTap.close} />
        </View>
      ) : null}
    </View>
  );
}

/** Settings panel: the same identity as rows, plus a manual check. The manual
 *  path reports inline (this is an ops surface, verifying pushes/rollbacks) but
 *  applies exactly like the silent path: reload in the background, or on tap. */
export function UpdatesPanel() {
  // The Electron shell serves the web export, where expo-updates is inert:
  // everything below would show the bundle version as "the" version, an
  // empty runtime and a check that can only say "no update". The desktop has
  // its own two update lines - show those instead (desktop_update.tsx).
  if (isDesktopShell()) return <DesktopUpdatesPanel />;
  return <PhoneUpdatesPanel />;
}

function PhoneUpdatesPanel() {
  const t = useTheme();
  const tr = useT();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [failed, setFailed] = useState(false);
  const [staged, setStaged] = useState(otaPending.current);

  const [raw, setRaw] = useState("");   // the check/fetch result as returned, for diagnosis

  async function checkNow() {
    setBusy(true); setFailed(false); setMsg(tr("updates.checking")); setRaw("");
    try {
      const r = await Updates.checkForUpdateAsync();
      setRaw(`check: isAvailable=${r.isAvailable} rollback=${r.isRollBackToEmbedded} reason=${r.reason ?? "-"} manifest=${(r.manifest as { id?: string } | undefined)?.id ?? "-"}`);
      if (!r.isAvailable && !r.isRollBackToEmbedded) { setMsg(tr("updates.upToDateNoServer")); return; }
      setMsg(tr("updates.downloading"));
      const f = await Updates.fetchUpdateAsync();
      setRaw((s) => `${s}\nfetch: isNew=${f.isNew} rollback=${f.isRollBackToEmbedded} manifest=${(f.manifest as { id?: string } | undefined)?.id ?? "-"}`);
      if (f.isNew || f.isRollBackToEmbedded) {
        otaPending.current = true; setStaged(true);
        setMsg(f.isRollBackToEmbedded
          ? tr("updates.rollbackLoaded")
          : tr("updates.updateLoaded"));
      } else setMsg(tr("updates.upToDate"));
    } catch (e) {
      setFailed(true);
      const err = e as Error & { code?: string };
      setMsg(tr("updates.checkFailed", { err: `${err.code ? err.code + ": " : ""}${String(err.message)}` }));
    } finally { setBusy(false); }
  }

  return (
    <Panel>
      <SectionLabel text={tr("updates.section")} />
      <KVRow k={tr("updates.version")} v={`v${version}${build ? ` · Build ${build}` : ""}`} />
      <KVRow k={tr("updates.runtime")} v={Updates.runtimeVersion ?? "—"} />
      <KVRow k={tr("updates.channel")} v={Updates.channel || (Updates.isEnabled ? "production" : "— (dev)")} />
      <KVRow k={tr("updates.bundle")} v={bundleLabel()} />
      <Text style={{ color: t.txtTertiary, fontSize: 11.5, marginTop: 4, marginBottom: 8 }}>
        {tr("updates.silentNote")}
      </Text>
      {Updates.isEnabled ? (
        <>
          <Pressable onPress={checkNow} disabled={busy}
            style={{ backgroundColor: t.accent, borderRadius: 8, padding: 11, alignItems: "center", opacity: busy ? 0.6 : 1 }}>
            <Text style={{ color: "#fff", fontWeight: "600" }}>{busy ? tr("updates.checking") : tr("updates.checkNow")}</Text>
          </Pressable>
          {staged ? (
            <Pressable onPress={() => Updates.reloadAsync().catch(() => {})}
              style={{ marginTop: 8, borderColor: t.accent, borderWidth: 1, borderRadius: 8, padding: 11, alignItems: "center" }}>
              <Text style={{ color: t.accent, fontWeight: "600" }}>{tr("updates.restartApply")}</Text>
            </Pressable>
          ) : null}
          {msg ? <Text style={{ color: failed ? t.danger : t.txtSecondary, fontSize: 12, marginTop: 6 }}>{msg}</Text> : null}
          {raw ? <Text selectable style={{ color: t.txtTertiary, fontSize: 11, marginTop: 4, ...MONO }}>{raw}</Text> : null}
          <UpdatesDiag />
        </>
      ) : (
        <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("updates.otaReleaseOnly")}</Text>
      )}
    </Panel>
  );
}

const MONO = Platform.OS === "web" ? { fontFamily: "ui-monospace, monospace" } as const : {};

/** Why an OTA never applies, from expo-updates' OWN signals (SDK 57 API): the
 *  launch facts, the startup check/download errors useUpdates() carries, and
 *  the native log store - which also records a launch that crashed and was
 *  rolled back to the embedded bundle (error recovery), the one case no JS on
 *  the phone ever gets to observe. */
function UpdatesDiag() {
  const t = useTheme();
  const tr = useT();
  const u = Updates.useUpdates();
  const [log, setLog] = useState<string[] | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(() => {
    Updates.readLogEntriesAsync(7 * 24 * 3600 * 1000)
      .then((es) => setLog(es.slice(-50).map((e) =>
        `${new Date(e.timestamp).toISOString().slice(5, 19)} ${e.level} ${e.code}${e.updateId ? ` [${e.updateId.slice(0, 8)}]` : ""} ${e.message}`)))
      .catch((e) => setLog([`readLogEntriesAsync failed: ${String((e as Error).message)}`]));
  }, []);
  useEffect(load, [load]);

  const facts = [
    `updateId   ${Updates.updateId ?? "-"}`,
    `createdAt  ${Updates.createdAt ? Updates.createdAt.toISOString() : "-"}`,
    `runtime    ${Updates.runtimeVersion ?? "-"} · channel ${Updates.channel ?? "-"}`,
    `embedded   ${Updates.isEmbeddedLaunch} · emergency ${Updates.isEmergencyLaunch}${Updates.emergencyLaunchReason ? ` (${Updates.emergencyLaunchReason})` : ""}`,
    `startup    running=${u.isStartupProcedureRunning} lastCheck=${u.lastCheckForUpdateTimeSinceRestart?.toISOString() ?? "-"}`,
    `available  ${u.availableUpdate?.updateId ?? "-"} · downloaded ${u.downloadedUpdate?.updateId ?? "-"}`,
    `checkErr   ${u.checkError?.message ?? "-"}`,
    `downloadErr ${u.downloadError?.message ?? "-"}`,
  ];

  const copy = async () => {
    await Clipboard.setStringAsync([...facts, "", ...(log ?? [])].join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };

  return (
    <View style={{ marginTop: 12, gap: 6 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
        <View style={{ flex: 1 }}><SectionLabel text={tr("updates.diag.section")} /></View>
        <Pressable onPress={load}><Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("updates.diag.logReload")}</Text></Pressable>
        <Pressable onPress={copy} style={{ backgroundColor: t.accent, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6 }}>
          <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>{copied ? tr("updates.diag.copied") : tr("updates.diag.copy")}</Text>
        </Pressable>
      </View>
      {facts.map((l) => (
        <Text key={l} selectable style={{ color: t.txtSecondary, fontSize: 10.5, lineHeight: 15, ...MONO }}>{l}</Text>
      ))}
      <Text style={{ color: t.txtSecondary, fontSize: 12, marginTop: 4 }}>{tr("updates.diag.log")}</Text>
      <ScrollView nestedScrollEnabled style={{ maxHeight: 280 }} contentContainerStyle={{ gap: 3 }}>
        {log === null ? null : log.length === 0 ? (
          <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("updates.diag.logEmpty")}</Text>
        ) : log.map((l, i) => (
          <Text key={i} selectable style={{ color: / (error|fatal) /.test(l) ? t.danger : t.txtTertiary, fontSize: 10.5, lineHeight: 14.5, ...MONO }}>{l}</Text>
        ))}
      </ScrollView>
    </View>
  );
}
