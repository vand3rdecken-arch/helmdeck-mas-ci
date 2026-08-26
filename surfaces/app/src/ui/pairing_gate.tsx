// Native pairing gate (2026-08-26) - see data/config.ts useNeedsPairing() for
// why this exists: a fresh/reinstalled Android app previously fell straight
// through into the tabbed UI with no daemon configured, and the Dashboard's
// query hung indefinitely against the (emulator-only) default address. This
// screen is what a fresh install should see FIRST instead - same three
// choices already offered deeper in the app (more.tsx's pair panel, board.tsx's
// DemoInvite), just surfaced before anything tries to load real data.
// Styled like login_screen.tsx (same canvas/centered-card look).
//
// The QR scan is INLINE, not a push to the app/scan.tsx route (2026-08-26,
// fixed same day as it shipped): this component renders in _layout.tsx's
// early-return branch, same as Onboard/LoginScreen - NO <Stack> navigator is
// mounted there. router.push("/scan") had nowhere to navigate to, so the
// button silently did nothing and the camera permission prompt never fired -
// measured live: the owner only ever saw the OS permission dialog once
// already paired and inside the real app (where the Stack exists). Embedding
// the same CameraView + useCameraPermissions logic here, and finishing with
// the SAME applyPairing()+api.me() round trip the paste-code path already
// uses (not a route replace), sidesteps needing a navigator entirely.
import { useRef, useState } from "react";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useQueryClient } from "@tanstack/react-query";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { AuthRequired, api } from "@/data/client";
import { useConfig } from "@/data/config";
import { useDemo } from "@/data/demo";
import { useT } from "@/i18n";
import { fieldStyle } from "@/ui/settings_sections";
import { useTheme } from "@/theme";

export function PairingGate() {
  const t = useTheme();
  const tr = useT();   // pre-pairing: falls back to device locale, same as LoginScreen
  const qc = useQueryClient();
  const applyPairing = useConfig((s) => s.applyPairing);
  const enableDemo = useDemo((s) => s.enable);
  const field = fieldStyle(t);
  const [pair, setPair] = useState("");
  const [msg, setMsg] = useState("");
  const [kind, setKind] = useState<"info" | "ok" | "err">("info");
  const [busy, setBusy] = useState(false);
  const [scanning, setScanning] = useState(false);

  async function submit(code: string) {
    const applied = applyPairing(code);
    if (!applied.ok) { setKind("err"); setMsg(applied.reason); return; }
    setBusy(true); setKind("info"); setMsg(tr("settings.more.verifying"));
    try {
      await api.me();
      qc.invalidateQueries();
      setKind("ok");
      setMsg(applied.mode === "relay" ? tr("settings.more.pairedRelayOk") : tr("settings.more.pairedLanOk"));
      setPair("");
    } catch (e) {
      setKind("err");
      setMsg(e instanceof AuthRequired
        ? tr("settings.more.tokenRejected")
        : tr("settings.more.noAnswer", { err: String((e as Error).message) }));
    } finally { setBusy(false); }
  }

  if (scanning) {
    return <InlineScanner onCode={(code) => { setScanning(false); submit(code); }} onCancel={() => setScanning(false)} />;
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", padding: 28 }}>
      <View style={{ width: "100%", maxWidth: 420, gap: 14 }}>
        <View style={{ gap: 6 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 24, fontWeight: "700" }}>{tr("gate.title")}</Text>
          <Text style={{ color: t.txtSecondary, fontSize: 13, lineHeight: 19 }}>{tr("gate.hint")}</Text>
        </View>

        <Pressable onPress={() => setScanning(true)}
          style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
            backgroundColor: t.accent, borderRadius: 14, paddingVertical: 14 }}>
          <Ionicons name="qr-code-outline" size={18} color="#fff" />
          <Text style={{ color: "#fff", fontSize: 15, fontWeight: "600" }}>{tr("settings.more.scanQr")}</Text>
        </Pressable>

        <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("settings.more.orPaste")}</Text>
        <TextInput value={pair} onChangeText={setPair} autoCapitalize="none" multiline
          placeholder={tr("settings.more.pairPh")} placeholderTextColor={t.txtPlaceholder}
          style={[field, { minHeight: 60 }]} />
        <Pressable onPress={() => submit(pair)} disabled={busy || !pair.trim()}
          style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
            backgroundColor: busy ? t.surface2 : t.surface1, borderWidth: 1, borderColor: t.borderSubtle,
            borderRadius: 14, paddingVertical: 13, opacity: !pair.trim() ? 0.6 : 1 }}>
          {busy ? <ActivityIndicator color={t.txtSecondary} /> : null}
          <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{tr("settings.more.pairBtn")}</Text>
        </Pressable>
        {msg ? <Text style={{ color: kind === "ok" ? t.ok : kind === "info" ? t.txtSecondary : t.danger, fontSize: 12 }}>{msg}</Text> : null}

        <View style={{ height: 1, backgroundColor: t.borderSubtle, marginVertical: 4 }} />

        <Pressable onPress={() => { enableDemo(); qc.invalidateQueries(); }}
          style={{ alignItems: "center", paddingVertical: 10 }}>
          <Text style={{ color: t.accent, fontSize: 13.5, fontWeight: "600" }}>{tr("demo.cta")}</Text>
        </Pressable>
      </View>
    </View>
  );
}

/** Same camera/permission/QR-decode logic as app/scan.tsx, inlined so it can
 *  render with no navigator mounted. Hands the raw pairing code to the
 *  caller instead of pushing to /pair. */
function InlineScanner({ onCode, onCancel }: { onCode: (code: string) => void; onCancel: () => void }) {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const [perm, requestPerm] = useCameraPermissions();
  const handled = useRef(false);

  function onScan({ data }: { data: string }) {
    if (handled.current || !data) return;
    handled.current = true;
    let code = data.trim();
    const m = /[?&]c=([^&\s]+)/.exec(code);   // …/pair?c=CODE -> CODE; else raw payload
    if (m) code = decodeURIComponent(m[1]);
    onCode(code);
  }

  if (!perm) {
    return <View style={{ flex: 1, backgroundColor: "#000" }} />;
  }
  if (!perm.granted) {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", gap: 14, padding: 24 }}>
        <Ionicons name="camera-outline" size={40} color={t.txtSecondary} />
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>{tr("scan.permTitle")}</Text>
        <Text style={{ color: t.txtSecondary, fontSize: 13, textAlign: "center", lineHeight: 19 }}>
          {tr("scan.permBody")}
        </Text>
        <Pressable onPress={requestPerm} style={{ backgroundColor: t.accent, borderRadius: 10, paddingHorizontal: 20, paddingVertical: 12 }}>
          <Text style={{ color: "#fff", fontWeight: "700" }}>{tr("scan.allow")}</Text>
        </Pressable>
        <Pressable onPress={onCancel} hitSlop={8}><Text style={{ color: t.txtTertiary }}>{tr("ui.cancel")}</Text></Pressable>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <CameraView style={{ flex: 1 }} facing="back"
        barcodeScannerSettings={{ barcodeTypes: ["qr"] }} onBarcodeScanned={onScan} />
      <View style={{ position: "absolute", top: insets.top + 8, left: 12, zIndex: 10 }}>
        <Pressable onPress={onCancel} hitSlop={10}
          style={{ flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#0009", borderRadius: 20, paddingHorizontal: 12, paddingVertical: 8 }}>
          <Ionicons name="chevron-back" size={20} color="#fff" />
          <Text style={{ color: "#fff", fontWeight: "600" }}>{tr("ui.back")}</Text>
        </Pressable>
      </View>
      <View pointerEvents="none" style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, alignItems: "center", justifyContent: "center" }}>
        <View style={{ width: 240, height: 240, borderWidth: 3, borderColor: "#fff", borderRadius: 20, opacity: 0.85 }} />
        <Text style={{ color: "#fff", marginTop: 16, fontSize: 14, fontWeight: "600" }}>{tr("scan.hint")}</Text>
      </View>
    </View>
  );
}
