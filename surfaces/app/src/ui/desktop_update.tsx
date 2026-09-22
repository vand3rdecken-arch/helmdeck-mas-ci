/** The desktop-shell counterpart to apk_update.tsx's ApkUpdateBanner: the
 *  phone already shows "update available" (checked against the relay's own
 *  version.json), but the Electron desktop app had TWO separate update
 *  mechanisms that both only ever logged to a file - invisible in the app
 *  itself (owner report, 2026-08-26; the confusing symptom was the app
 *  showing stale UI while its own "check for update" button, which checks a
 *  THIRD, unrelated thing - expo-updates, meaningful on the phone's native
 *  OTA, not here - insisted everything was current):
 *
 *   - surfaces/desktop/native-updater.js (electron-updater): replaces the
 *     WHOLE app (main.js, app.asar, node_modules) - applies on quit.
 *   - surfaces/desktop/updater.js (Paseo-style): syncs the JS bundle
 *     (app-dist) that carries screens like this one - downloads silently,
 *     but the RUNNING window keeps serving the OLD bundle until the app is
 *     closed and reopened, so a fully-downloaded update could sit staged
 *     for hours looking identical to "nothing shipped".
 *
 *  preload.js exposes both as window.helmdeckNative on the desktop build
 *  only; everywhere else (phone, plain web) that global is undefined and
 *  this component silently renders nothing, same guard shape as
 *  isWeb/Platform.OS checks elsewhere in the app. */
import Constants from "expo-constants";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { KVRow, Panel, SectionLabel } from "@/ui/kit";

type UpdateStatus = { state: string; version: string | null; message: string | null };

type HelmdeckNative = {
  getUpdateStatus: () => Promise<UpdateStatus>;
  onUpdateStatus: (cb: (status: UpdateStatus) => void) => () => void;
  installUpdate: () => void;
  getJsUpdateStatus: () => Promise<UpdateStatus>;
  onJsUpdateStatus: (cb: (status: UpdateStatus) => void) => () => void;
  applyJsUpdateNow: () => void;
  // added 2026-09-22 (main.js "native:app-info"); optional because a JS
  // bundle can arrive by OTA before the shell that exposes it is installed
  getAppInfo?: () => Promise<{ shellVersion?: string | null }>;
};

function nativeBridge(): HelmdeckNative | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { helmdeckNative?: HelmdeckNative }).helmdeckNative ?? null;
}

/** True inside the packaged Electron shell (the preload bridge is the proof). */
export function isDesktopShell(): boolean {
  return nativeBridge() !== null;
}

/** The shell's own version (0.2.x - the installer / electron-updater line),
 *  as opposed to the JS bundle version (1.0.x). Electron's default User-Agent
 *  carries "<productName>/<version>", which every shipped shell already sends,
 *  so this works before the bridge method exists; the bridge wins when present. */
function shellVersionFromUA(): string | null {
  if (typeof navigator === "undefined") return null;
  const m = /HelmDeck\/(\d+(?:\.\d+)+)/i.exec(navigator.userAgent || "");
  return m ? m[1] : null;
}

// Shared by both channels: subscribe to the bridge's get+onChange pair, or
// stay null forever off-desktop (the bridge is simply absent there).
function useBridgeStatus(
  get: (b: HelmdeckNative) => Promise<UpdateStatus>,
  on: (b: HelmdeckNative, cb: (s: UpdateStatus) => void) => () => void,
): UpdateStatus | null {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  useEffect(() => {
    const bridge = nativeBridge();
    if (!bridge) return;
    let alive = true;
    get(bridge).then((s) => { if (alive) setStatus(s); }).catch(() => {});
    const off = on(bridge, (s) => { if (alive) setStatus(s); });
    return () => { alive = false; off(); };
  }, [get, on]);
  return status;
}

function Row({ busy, text, actionLabel, onAction }: {
  busy?: boolean; text: string; actionLabel?: string; onAction?: () => void;
}) {
  const t = useTheme();
  return (
    <View style={{
      backgroundColor: t.accent + "18", borderColor: t.accent + "55", borderWidth: 1,
      borderRadius: 10, padding: 12, gap: 8, marginBottom: 12,
    }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        {busy ? <ActivityIndicator size="small" color={t.accent} /> : null}
        <Text style={{ color: t.txtPrimary, fontSize: 13, lineHeight: 18, flex: 1 }}>{text}</Text>
      </View>
      {actionLabel && onAction ? (
        <Pressable onPress={onAction}
          style={{ backgroundColor: t.accent, borderRadius: 8, padding: 10, alignItems: "center" }}>
          <Text style={{ color: "#fff", fontWeight: "600" }}>{actionLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/** Only rendered on the packaged desktop build (window.helmdeckNative unset
 *  everywhere else). Silent unless a channel has something ACTIONABLE -
 *  matching ApkUpdateBanner's "a network hiccup here is not worth
 *  surfacing": checking/current/error stay invisible, only
 *  downloading/staged/downloaded show anything. Both channels are
 *  independent and can both be true at once, so both rows can show. */
export function DesktopUpdateBanner() {
  const tr = useT();
  const native = useBridgeStatus((b) => b.getUpdateStatus(), (b, cb) => b.onUpdateStatus(cb));
  const js = useBridgeStatus((b) => b.getJsUpdateStatus(), (b, cb) => b.onJsUpdateStatus(cb));

  const rows: React.ReactNode[] = [];
  if (js?.state === "downloading") {
    rows.push(<Row key="js-dl" busy text={tr("updates.native.downloading", { version: js.version ?? "?" })} />);
  } else if (js?.state === "staged") {
    rows.push(<Row key="js-staged" text={tr("updates.js.staged", { version: js.version ?? "?" })}
      actionLabel={tr("updates.native.installNow")} onAction={() => nativeBridge()?.applyJsUpdateNow()} />);
  }
  if (native?.state === "downloading") {
    rows.push(<Row key="native-dl" busy text={tr("updates.native.downloading", { version: native.version ?? "?" })} />);
  } else if (native?.state === "downloaded") {
    rows.push(<Row key="native-dl-done" text={tr("updates.native.downloaded", { version: native.version ?? "?" })}
      actionLabel={tr("updates.native.installNow")} onAction={() => nativeBridge()?.installUpdate()} />);
  }
  return rows.length ? <>{rows}</> : null;
}

/** Settings "App & Updates" for the DESKTOP shell. Replaces the phone panel
 *  there (owner, 2026-09-22: "warum steht im Desktop die Handy-Version, das
 *  macht keinen Sinn"): that panel reads expo-updates, which is the phone's
 *  native OTA and is inert in the web export the shell serves, so it showed
 *  the bundle version as "the" version, an empty runtime and a check button
 *  that could only ever say "no update". The desktop has TWO real update
 *  lines, and this shows exactly those:
 *    shell  - the installer / electron-updater (native-updater.js, 0.2.x)
 *    bundle - the JS bundle synced from the relay's desktop channel
 *             (updater.js, 1.0.x) */
export function DesktopUpdatesPanel() {
  const t = useTheme();
  const tr = useT();
  const native = useBridgeStatus((b) => b.getUpdateStatus(), (b, cb) => b.onUpdateStatus(cb));
  const js = useBridgeStatus((b) => b.getJsUpdateStatus(), (b, cb) => b.onJsUpdateStatus(cb));
  const [shell, setShell] = useState<string | null>(shellVersionFromUA());
  useEffect(() => {
    const b = nativeBridge();
    if (!b?.getAppInfo) return;
    let alive = true;
    b.getAppInfo().then((i) => { if (alive && i?.shellVersion) setShell(i.shellVersion); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  const bundleVersion = Constants.expoConfig?.version ?? "?";

  const line = (s: UpdateStatus | null, kind: "native" | "js") => {
    if (!s) return tr("updates.desktop.unknown");
    const v = s.version ?? "?";
    switch (s.state) {
      case "checking":    return tr("updates.checking");
      case "downloading": return tr("updates.native.downloading", { version: v });
      case "downloaded":  return tr("updates.native.downloaded", { version: v });
      case "staged":      return tr("updates.js.staged", { version: v });
      case "error":       return tr("updates.checkFailed", { err: s.message ?? "?" });
      case "unavailable": return tr("updates.desktop.unavailable");
      default:            return kind === "native" ? tr("updates.desktop.shellCurrent") : tr("updates.desktop.bundleCurrent");
    }
  };
  const action = (label: string, onPress: () => void) => (
    <Pressable onPress={onPress}
      style={{ marginTop: 6, backgroundColor: t.accent, borderRadius: 8, padding: 11, alignItems: "center" }}>
      <Text style={{ color: "#fff", fontWeight: "600" }}>{label}</Text>
    </Pressable>
  );

  return (
    <Panel>
      <SectionLabel text={tr("updates.section")} />
      <KVRow k={tr("updates.desktop.shell")} v={shell ? `v${shell}` : "—"} />
      <KVRow k={tr("updates.desktop.bundle")} v={`v${bundleVersion}`} />
      <KVRow k={tr("updates.channel")} v="desktop" />
      <Text style={{ color: t.txtTertiary, fontSize: 11.5, marginTop: 4, marginBottom: 10 }}>
        {tr("updates.desktop.note")}
      </Text>
      <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>{tr("updates.desktop.shellLine")}</Text>
      <Text style={{ color: native?.state === "error" ? t.danger : t.txtSecondary, fontSize: 12, marginBottom: 8 }}>{line(native, "native")}</Text>
      {native?.state === "downloaded" ? action(tr("updates.native.installNow"), () => nativeBridge()?.installUpdate()) : null}
      <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>{tr("updates.desktop.bundleLine")}</Text>
      <Text style={{ color: js?.state === "error" ? t.danger : t.txtSecondary, fontSize: 12 }}>{line(js, "js")}</Text>
      {js?.state === "staged" ? action(tr("updates.native.installNow"), () => nativeBridge()?.applyJsUpdateNow()) : null}
    </Panel>
  );
}
