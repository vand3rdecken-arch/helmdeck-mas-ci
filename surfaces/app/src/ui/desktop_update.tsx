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
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { useT } from "@/i18n";
import { useTheme } from "@/theme";

type UpdateStatus = { state: string; version: string | null; message: string | null };

type HelmdeckNative = {
  getUpdateStatus: () => Promise<UpdateStatus>;
  onUpdateStatus: (cb: (status: UpdateStatus) => void) => () => void;
  installUpdate: () => void;
  getJsUpdateStatus: () => Promise<UpdateStatus>;
  onJsUpdateStatus: (cb: (status: UpdateStatus) => void) => () => void;
  applyJsUpdateNow: () => void;
};

function nativeBridge(): HelmdeckNative | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { helmdeckNative?: HelmdeckNative }).helmdeckNative ?? null;
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
