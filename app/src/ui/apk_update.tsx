/** Detects when a newer native APK build is live on the relay but this
 *  install hasn't caught up yet - the exact "phone silently stops receiving
 *  OTA forever after a native bump" trap (incident 2026-08-15: stuck on an
 *  old build for days, invisible until the owner happened to check the
 *  version footer). OTA itself can never surface this on its own - an old
 *  APK's runtimeVersion mismatch just looks like "no update" to
 *  expo-updates, silently, forever. Only a versionCode compare against the
 *  relay's own record can catch it. Best-effort and silent on failure: a
 *  network hiccup here is not worth surfacing, only a REAL newer build is. */
import Constants from "expo-constants";
import { useEffect, useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";

import { useT } from "@/i18n";
import { useTheme } from "@/theme";

const build = (Constants.expoConfig as { android?: { versionCode?: number } } | null)?.android?.versionCode;

// Reuse the relay origin the app already trusts for OTA (app.json's
// updates.url) instead of a second config value - this needs no daemon
// pairing of its own and works even for a phone fully orphaned from OTA.
function relayOrigin(): string | null {
  const url = (Constants.expoConfig as { updates?: { url?: string } } | null)?.updates?.url;
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

type ApkInfo = { versionCode: number; versionName: string; url: string };

function useApkUpdateCheck(): ApkInfo | null {
  const [info, setInfo] = useState<ApkInfo | null>(null);
  useEffect(() => {
    if (!build) return;              // dev/Expo Go build - no versionCode to compare
    const origin = relayOrigin();
    if (!origin) return;
    let alive = true;
    // No AbortSignal.timeout dependency (portability over polish) - a plain
    // race against a timer works the same and can't throw on an RN/Hermes
    // build where that API isn't present.
    const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), 8000));
    Promise.race([
      fetch(origin + "/apk/version.json").then((r) => (r.ok ? r.json() : null)),
      timeout,
    ])
      .then((d: { versionCode?: number; versionName?: string; url?: string } | null) => {
        if (alive && d?.versionCode && build && d.versionCode > build && d.url) {
          setInfo({ versionCode: d.versionCode, versionName: d.versionName ?? "?", url: origin + d.url });
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return info;
}

export function ApkUpdateBanner() {
  const t = useTheme();
  const tr = useT();
  const info = useApkUpdateCheck();
  if (!info) return null;
  return (
    <View style={{
      backgroundColor: t.accent + "18", borderColor: t.accent + "55", borderWidth: 1,
      borderRadius: 10, padding: 12, gap: 8, marginBottom: 12,
    }}>
      <Text style={{ color: t.txtPrimary, fontSize: 13, lineHeight: 18 }}>
        {tr("updates.apkAvailable", { build: String(info.versionCode) })}
      </Text>
      <Pressable onPress={() => Linking.openURL(info.url)}
        style={{ backgroundColor: t.accent, borderRadius: 8, padding: 10, alignItems: "center" }}>
        <Text style={{ color: "#fff", fontWeight: "600" }}>{tr("updates.apkInstall")}</Text>
      </Pressable>
    </View>
  );
}
