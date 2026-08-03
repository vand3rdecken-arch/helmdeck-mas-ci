import { useLocalSearchParams, useRouter } from "expo-router";
import * as Linking from "expo-linking";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { api, AuthRequired } from "@/data/client";
import { useConfig } from "@/data/config";
import { useTheme } from "@/theme";

// Handles the pairing App Link (https://<relay>/pair?c=…, verified via
// assetlinks.json) and the helmdeck://pair?c=… scheme. Same mechanism as the
// old SwarmDeck app: the phone camera opens the https link, Android routes it
// straight here, and we pair. `c` is base64 {r,k,t} — the relay URL is the
// link's own origin (kept out of the QR so the code stays a valid https link).
//
// "Gekoppelt ✓" is only shown after a real round-trip through the tunnel
// (api.me()). A code that parses but can't reach the daemon (expired pairing
// window, dead relay, wrong keys) used to claim success and fail silently on
// the board — the exact bug class this screen now surfaces.
export default function Pair() {
  const t = useTheme();
  const router = useRouter();
  const { c } = useLocalSearchParams<{ c?: string | string[] }>();
  const url = Linking.useURL();
  const applyPairing = useConfig((s) => s.applyPairing);
  const [msg, setMsg] = useState("Koppeln…");
  const [state, setState] = useState<"busy" | "ok" | "fail">("busy");
  const ran = useRef("");   // guard: verify once per code, not per re-render

  useEffect(() => {
    const code = Array.isArray(c) ? c[0] : c;
    if (!code) { setState("fail"); setMsg("Kein Pairing-Code im Link."); return; }
    if (ran.current === code) return;
    let inner: { u?: string; r?: string; k?: string; t?: string };
    try {
      inner = JSON.parse(atob(code.replace(/-/g, "+").replace(/_/g, "/")));
    } catch {
      ran.current = code;
      setState("fail"); setMsg("Ungültiger Pairing-Code."); return;
    }
    const origin = (/^https?:\/\/[^/]+/i.exec(url ?? "") ?? [""])[0];
    // Relay url comes from the link's origin when the code omits it; if the
    // deep-link url hasn't been delivered yet, wait for the effect to re-run
    // instead of failing with "Relay-URL fehlt" (don't consume the guard).
    if (!inner.u && !origin) return;
    ran.current = code;
    (async () => {
      setState("busy"); setMsg("Koppeln…");
      const applied = applyPairing(btoa(JSON.stringify({
        u: inner.u || origin, r: inner.r, k: inner.k, t: inner.t,
      })));
      if (!applied.ok) { setState("fail"); setMsg(applied.reason); return; }
      setMsg("Verbindung prüfen…");
      try {
        await api.me();   // proves relay + E2EE + Token in one round-trip
        setState("ok"); setMsg("Gekoppelt ✓ – Desktop erreichbar.");
        setTimeout(() => router.replace("/"), 900);
      } catch (e) {
        setState("fail");
        setMsg(e instanceof AuthRequired
          ? "Gekoppelt, aber der Token wurde abgelehnt – am Desktop einen neuen Code erzeugen."
          : `Code übernommen, aber der Desktop antwortet nicht:\n${String((e as Error).message)}`);
      }
    })();
  }, [c, url, applyPairing, router]);

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", gap: 10, padding: 24 }}>
      <Text style={{ color: t.txtPrimary, fontSize: 17, fontWeight: "600" }}>HelmDeck koppeln</Text>
      {state === "busy" ? <ActivityIndicator color={t.accent} /> : null}
      <Text style={{ color: state === "fail" ? t.danger : state === "ok" ? t.ok : t.txtSecondary,
        fontSize: 14, textAlign: "center", lineHeight: 20 }}>{msg}</Text>
      {state === "fail" ? (
        <Text style={{ color: t.txtTertiary, fontSize: 12, textAlign: "center" }}>
          Desktop: Settings → Mobile app → „Telefon koppeln" erzeugt einen frischen Code (15 Min gültig, einmal verwendbar).
        </Text>
      ) : null}
    </View>
  );
}
