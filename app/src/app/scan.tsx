import { Ionicons } from "@expo/vector-icons";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { useRef } from "react";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useTheme } from "@/theme";

// QR pairing scanner: point the camera at the desktop's "Telefon koppeln" QR.
// The QR holds either a pair link (…/pair?c=CODE, https or helmdeck://) or the
// raw base64 code; we pull CODE out and hand it to /pair, which runs the same
// verified round-trip (api.me) as a tapped deep link. Camera-only, no typing.
export default function Scan() {
  const t = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [perm, requestPerm] = useCameraPermissions();
  const handled = useRef(false);

  function onScan({ data }: { data: string }) {
    if (handled.current || !data) return;
    handled.current = true;
    let code = data.trim();
    const m = /[?&]c=([^&\s]+)/.exec(code);   // …/pair?c=CODE -> CODE; else raw payload
    if (m) code = decodeURIComponent(m[1]);
    router.replace(`/pair?c=${encodeURIComponent(code)}`);
  }

  if (!perm) {
    return <View style={{ flex: 1, backgroundColor: "#000" }} />;
  }
  if (!perm.granted) {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", gap: 14, padding: 24 }}>
        <Ionicons name="camera-outline" size={40} color={t.txtSecondary} />
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>Kamera für QR-Scan</Text>
        <Text style={{ color: t.txtSecondary, fontSize: 13, textAlign: "center", lineHeight: 19 }}>
          HelmDeck braucht die Kamera nur, um den Pairing-QR vom Desktop zu lesen.
        </Text>
        <Pressable onPress={requestPerm} style={{ backgroundColor: t.accent, borderRadius: 10, paddingHorizontal: 20, paddingVertical: 12 }}>
          <Text style={{ color: "#fff", fontWeight: "700" }}>Kamera erlauben</Text>
        </Pressable>
        <Pressable onPress={() => router.back()} hitSlop={8}><Text style={{ color: t.txtTertiary }}>Abbrechen</Text></Pressable>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <CameraView style={{ flex: 1 }} facing="back"
        barcodeScannerSettings={{ barcodeTypes: ["qr"] }} onBarcodeScanned={onScan} />
      <View style={{ position: "absolute", top: insets.top + 8, left: 12, zIndex: 10 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}
          style={{ flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#0009", borderRadius: 20, paddingHorizontal: 12, paddingVertical: 8 }}>
          <Ionicons name="chevron-back" size={20} color="#fff" />
          <Text style={{ color: "#fff", fontWeight: "600" }}>Zurück</Text>
        </Pressable>
      </View>
      <View pointerEvents="none" style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, alignItems: "center", justifyContent: "center" }}>
        <View style={{ width: 240, height: 240, borderWidth: 3, borderColor: "#fff", borderRadius: 20, opacity: 0.85 }} />
        <Text style={{ color: "#fff", marginTop: 16, fontSize: 14, fontWeight: "600" }}>Pairing-QR vom Desktop scannen</Text>
      </View>
    </View>
  );
}
