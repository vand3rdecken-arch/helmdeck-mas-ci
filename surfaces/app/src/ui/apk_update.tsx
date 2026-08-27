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
import * as Updates from "expo-updates";
import { useEffect, useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";

import appJson from "../../app.json";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// Constants.expoConfig is NULL in release/OTA builds (same fact
// updates_info.tsx works around for the version string) - so a release
// install had build===undefined and the check below silently never ran:
// the exact phone this banner exists for (orphaned after a native bump)
// was the one phone that could not see it (incident 2026-08-21, stuck on
// 1.0.12 while build 53 sat on the relay). versionCode has no runtime
// source without a native module, so releases fall back to comparing the
// relay's versionName against Updates.runtimeVersion - the runtime's OWN
// report of the installed native version (policy: appVersion), which is
// exactly the value whose mismatch orphans the phone from OTA.
const build = (Constants.expoConfig as { android?: { versionCode?: number } } | null)?.android?.versionCode;
const installedVer = Constants.expoConfig?.version ?? Updates.runtimeVersion ?? null;

// "1.0.13" > "1.0.12" done numerically per segment - a string compare would
// call 1.0.9 newer than 1.0.10.
function verNewer(a: string, b: string): boolean {
  const pa = a.split(".").map(Number), pb = b.split(".").map(Number);
  if (pa.some(isNaN) || pb.some(isNaN)) return false;
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d > 0;
  }
  return false;
}

// Reuse the relay origin the app already trusts for OTA (app.json's
// updates.url) instead of a second config value - this needs no daemon
// pairing of its own and works even for a phone fully orphaned from OTA.
// app.json is bundled as the fallback because expoConfig is null in release;
// the URL is build-time config, not runtime state, so the static read is fine.
function relayOrigin(): string | null {
  const url = (Constants.expoConfig as { updates?: { url?: string } } | null)?.updates?.url
    ?? (appJson as { expo?: { updates?: { url?: string } } }).expo?.updates?.url;
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
    // dev/Expo Go: no versionCode AND no release runtimeVersion - nothing to compare
    if (!build && !installedVer) return;
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
        if (!alive || !d?.versionCode || !d.url) return;
        // dev builds compare versionCode (exact); release builds compare the
        // relay's versionName against the installed runtimeVersion (catches
        // every OTA-orphaning bump - versionCode-only rebumps ride the same
        // runtime and still reach the phone via OTA, so missing those is fine).
        const newer = build ? d.versionCode > build
          : (installedVer && d.versionName) ? verNewer(d.versionName, installedVer) : false;
        if (newer) {
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
