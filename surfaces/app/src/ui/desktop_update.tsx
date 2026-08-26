/** The desktop-shell counterpart to apk_update.tsx's ApkUpdateBanner: the
 *  phone already shows "update available" (checked against the relay's own
 *  version.json), but the Electron desktop app's native updater
 *  (surfaces/desktop/native-updater.js, electron-updater) only ever logged
 *  its state to a file - invisible in the app itself (owner report,
 *  2026-08-26). preload.js exposes it as window.helmdeckNative on the
 *  desktop build only; everywhere else (phone, plain web) that global is
 *  undefined and this component silently renders nothing, same guard shape
 *  as isWeb/Platform.OS checks elsewhere in the app. */
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { useT } from "@/i18n";
import { useTheme } from "@/theme";

type NativeUpdateStatus = { state: "checking" | "downloading" | "downloaded" | "current" | "error" | "unavailable";
  version: string | null; message: string | null };

type HelmdeckNative = {
  getUpdateStatus: () => Promise<NativeUpdateStatus>;
  onUpdateStatus: (cb: (status: NativeUpdateStatus) => void) => () => void;
  installUpdate: () => void;
};

function nativeBridge(): HelmdeckNative | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { helmdeckNative?: HelmdeckNative }).helmdeckNative ?? null;
}

function useNativeUpdateStatus(): NativeUpdateStatus | null {
  const [status, setStatus] = useState<NativeUpdateStatus | null>(null);
  useEffect(() => {
    const bridge = nativeBridge();
    if (!bridge) return;
    let alive = true;
    bridge.getUpdateStatus().then((s) => { if (alive) setStatus(s); }).catch(() => {});
    const off = bridge.onUpdateStatus((s) => { if (alive) setStatus(s); });
    return () => { alive = false; off(); };
  }, []);
  return status;
}

/** Only rendered on the packaged desktop build (window.helmdeckNative unset
 *  everywhere else). Silent for checking/current/error/unavailable, matching
 *  ApkUpdateBanner's "a network hiccup here is not worth surfacing" - only a
 *  REAL, actionable state (downloading or ready to install) shows anything. */
export function DesktopUpdateBanner() {
  const t = useTheme();
  const tr = useT();
  const status = useNativeUpdateStatus();
  if (!status || (status.state !== "downloading" && status.state !== "downloaded")) return null;
  return (
    <View style={{
      backgroundColor: t.accent + "18", borderColor: t.accent + "55", borderWidth: 1,
      borderRadius: 10, padding: 12, gap: 8, marginBottom: 12,
    }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        {status.state === "downloading" ? <ActivityIndicator size="small" color={t.accent} /> : null}
        <Text style={{ color: t.txtPrimary, fontSize: 13, lineHeight: 18, flex: 1 }}>
          {status.state === "downloading"
            ? tr("updates.native.downloading", { version: status.version ?? "?" })
            : tr("updates.native.downloaded", { version: status.version ?? "?" })}
        </Text>
      </View>
      {status.state === "downloaded" ? (
        <Pressable onPress={() => nativeBridge()?.installUpdate()}
          style={{ backgroundColor: t.accent, borderRadius: 8, padding: 10, alignItems: "center" }}>
          <Text style={{ color: "#fff", fontWeight: "600" }}>{tr("updates.native.installNow")}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
