import { useLocalSearchParams, useRouter } from "expo-router";
import * as Linking from "expo-linking";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { useConfig } from "@/data/config";
import { useTheme } from "@/theme";

// Handles the pairing App Link (https://<relay>/pair?c=…, verified via
// assetlinks.json) and the helmdeck://pair?c=… scheme. Same mechanism as the
// old SwarmDeck app: the phone camera opens the https link, Android routes it
// straight here, and we pair. `c` is base64 {r,k,t} — the relay URL is the
// link's own origin (kept out of the QR so the code stays a valid https link).
export default function Pair() {
  const t = useTheme();
  const router = useRouter();
  const { c } = useLocalSearchParams<{ c?: string | string[] }>();
  const url = Linking.useURL();
  const applyPairing = useConfig((s) => s.applyPairing);
  const [msg, setMsg] = useState("Koppeln…");

  useEffect(() => {
    try {
      const code = Array.isArray(c) ? c[0] : c;
      if (!code) { setMsg("Kein Pairing-Code."); return; }
      const origin = (/^https?:\/\/[^/]+/i.exec(url ?? "") ?? [""])[0];
      const inner = JSON.parse(atob(code.replace(/-/g, "+").replace(/_/g, "/")));
      const ok = applyPairing(btoa(JSON.stringify({
        u: inner.u || origin, r: inner.r, k: inner.k, t: inner.t,
      })));
      setMsg(ok ? "Gekoppelt! ✓" : "Kopplung fehlgeschlagen.");
      if (ok) setTimeout(() => router.replace("/"), 1200);
    } catch { setMsg("Ungültiger Pairing-Code."); }
  }, [c, url, applyPairing, router]);

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", gap: 8 }}>
      <Text style={{ color: t.txtPrimary, fontSize: 17, fontWeight: "600" }}>HelmDeck koppeln</Text>
      <Text style={{ color: t.txtSecondary, fontSize: 14 }}>{msg}</Text>
    </View>
  );
}
