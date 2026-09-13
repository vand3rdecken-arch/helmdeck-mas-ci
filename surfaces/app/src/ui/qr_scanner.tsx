// The ONE QR pairing scanner, shared by app/scan.tsx (inside the Stack) and
// pairing_gate.tsx (no navigator mounted), so the camera-permission flow has a
// single owner.
//
// Permission flow follows App Review Guideline 5.1.1(iv) (rejection of
// 1.0.45, 2026-09-11): the explainer before the system prompt offers ONLY a
// "Continue" button - no cancel/exit that delays the request - and it always
// leads straight into the OS dialog. Once the camera was denied we never
// nudge again: a hint plus a link into the system settings, nothing else.
import { Ionicons } from "@expo/vector-icons";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useEffect, useRef } from "react";
import { AppState, Linking, Platform, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useT } from "@/i18n";
import { useTheme } from "@/theme";

export function QrScanner({ onCode, onCancel }: { onCode: (code: string) => void; onCancel: () => void }) {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const [perm, requestPerm, getPerm] = useCameraPermissions();
  const handled = useRef(false);

  // Coming back from the system settings: re-read the real permission state.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (s) => { if (s === "active") getPerm(); });
    return () => sub.remove();
  }, [getPerm]);

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
    const denied = perm.status === "denied";
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", gap: 14, padding: 24 }}>
        <Ionicons name="camera-outline" size={40} color={t.txtSecondary} />
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>
          {tr(denied ? "scan.deniedTitle" : "scan.permTitle")}
        </Text>
        <Text style={{ color: t.txtSecondary, fontSize: 13, textAlign: "center", lineHeight: 19 }}>
          {tr(denied ? "scan.deniedBody" : "scan.permBody")}
        </Text>
        {denied ? (
          <>
            {Platform.OS !== "web" ? (
              <Pressable onPress={() => Linking.openSettings()} style={{ backgroundColor: t.accent, borderRadius: 10, paddingHorizontal: 20, paddingVertical: 12 }}>
                <Text style={{ color: "#fff", fontWeight: "700" }}>{tr("scan.openSettings")}</Text>
              </Pressable>
            ) : null}
            <Pressable onPress={onCancel} hitSlop={8}><Text style={{ color: t.txtTertiary }}>{tr("ui.back")}</Text></Pressable>
          </>
        ) : (
          <Pressable onPress={requestPerm} style={{ backgroundColor: t.accent, borderRadius: 10, paddingHorizontal: 20, paddingVertical: 12 }}>
            <Text style={{ color: "#fff", fontWeight: "700" }}>{tr("scan.continue")}</Text>
          </Pressable>
        )}
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
