/** Build/OTA identity, shown in Settings (panel) and More (footer). With silent
 *  updates there is no prompt, so THIS is how a human verifies what's running:
 *  the OTA id/date moves each time an update applied - if it moved, you updated. */
import Constants from "expo-constants";
import * as Updates from "expo-updates";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { otaPending } from "@/data/ota";
import { useTheme } from "@/theme";
import { KVRow, Panel, SectionLabel } from "@/ui/kit";

// expoConfig is null in release/OTA builds - fall back to the updates
// runtimeVersion (policy: appVersion), which equals the app version there.
const version = Constants.expoConfig?.version ?? Updates.runtimeVersion ?? "?";
const build = (Constants.expoConfig as { android?: { versionCode?: number } } | null)?.android?.versionCode;

function bundleLabel(): string {
  return Updates.isEmbeddedLaunch
    ? "Basis-Build (eingebettet, kein OTA)"
    : Updates.updateId
    ? `OTA ${Updates.updateId.slice(0, 8)} · ${Updates.createdAt ? new Date(Updates.createdAt).toLocaleString() : "?"}`
    : "Dev";
}

/** Version + the running JS bundle, so silent OTA updates are visible. */
export function VersionFooter() {
  const t = useTheme();
  return (
    <View style={{ alignItems: "center", paddingVertical: 16, gap: 3 }}>
      <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>HelmDeck v{version}{build ? ` · Build ${build}` : ""}</Text>
      <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{bundleLabel()}</Text>
    </View>
  );
}

/** Settings panel: the same identity as rows, plus a manual check. The manual
 *  path reports inline (this is an ops surface, verifying pushes/rollbacks) but
 *  applies exactly like the silent path: reload in the background, or on tap. */
export function UpdatesPanel() {
  const t = useTheme();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [staged, setStaged] = useState(otaPending.current);

  async function checkNow() {
    setBusy(true); setMsg("Prüfe…");
    try {
      const r = await Updates.checkForUpdateAsync();
      if (!r.isAvailable && !r.isRollBackToEmbedded) { setMsg("Aktuell - kein Update auf dem Server."); return; }
      setMsg("Lade…");
      const f = await Updates.fetchUpdateAsync();
      if (f.isNew || f.isRollBackToEmbedded) {
        otaPending.current = true; setStaged(true);
        setMsg(f.isRollBackToEmbedded
          ? "Rollback geladen - zurück zum eingebetteten Build."
          : "Update geladen - aktiviert sich beim nächsten Wechsel in den Hintergrund.");
      } else setMsg("Aktuell.");
    } catch (e) {
      setMsg(`Check fehlgeschlagen: ${String((e as Error).message)}`);
    } finally { setBusy(false); }
  }

  return (
    <Panel>
      <SectionLabel text="app & updates" />
      <KVRow k="Version" v={`v${version}${build ? ` · Build ${build}` : ""}`} />
      <KVRow k="Runtime" v={Updates.runtimeVersion ?? "—"} />
      <KVRow k="Kanal" v={Updates.channel || (Updates.isEnabled ? "production" : "— (dev)")} />
      <KVRow k="Bundle" v={bundleLabel()} />
      <Text style={{ color: t.txtTertiary, fontSize: 11.5, marginTop: 4, marginBottom: 8 }}>
        Updates installieren sich still: Check beim Start und beim Zurückkehren in die App,
        aktiv nach dem nächsten Hintergrund-Wechsel. Kein Dialog - dieser Abschnitt ist der Beleg.
      </Text>
      {Updates.isEnabled ? (
        <>
          <Pressable onPress={checkNow} disabled={busy}
            style={{ backgroundColor: t.accent, borderRadius: 8, padding: 11, alignItems: "center", opacity: busy ? 0.6 : 1 }}>
            <Text style={{ color: "#fff", fontWeight: "600" }}>{busy ? "Prüfe…" : "Jetzt auf Update prüfen"}</Text>
          </Pressable>
          {staged ? (
            <Pressable onPress={() => Updates.reloadAsync().catch(() => {})}
              style={{ marginTop: 8, borderColor: t.accent, borderWidth: 1, borderRadius: 8, padding: 11, alignItems: "center" }}>
              <Text style={{ color: t.accent, fontWeight: "600" }}>Jetzt neu starten & anwenden</Text>
            </Pressable>
          ) : null}
          {msg ? <Text style={{ color: msg.startsWith("Check fehlgeschlagen") ? t.danger : t.txtSecondary, fontSize: 12, marginTop: 6 }}>{msg}</Text> : null}
        </>
      ) : (
        <Text style={{ color: t.txtTertiary, fontSize: 12 }}>OTA ist nur im Release-Build aktiv (Dev/Expo Go: aus).</Text>
      )}
    </Panel>
  );
}
