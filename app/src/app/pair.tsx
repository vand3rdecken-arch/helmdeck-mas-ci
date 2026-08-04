import { useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as Linking from "expo-linking";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { api, AuthRequired } from "@/data/client";
import { useConfig } from "@/data/config";
import { t as i18nT, useT } from "@/i18n";
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
  const tr = useT();
  const router = useRouter();
  const { c } = useLocalSearchParams<{ c?: string | string[] }>();
  const url = Linking.useURL();
  const applyPairing = useConfig((s) => s.applyPairing);
  const qc = useQueryClient();
  const [msg, setMsg] = useState(() => i18nT("pair.pairing"));
  const [state, setState] = useState<"busy" | "ok" | "fail">("busy");
  const ran = useRef("");   // guard: verify once per code, not per re-render

  useEffect(() => {
    const code = Array.isArray(c) ? c[0] : c;
    if (!code) { setState("fail"); setMsg(i18nT("pair.noCode")); return; }
    if (ran.current === code) return;
    let inner: { u?: string; r?: string; k?: string; t?: string };
    try {
      inner = JSON.parse(atob(code.replace(/-/g, "+").replace(/_/g, "/")));
    } catch {
      ran.current = code;
      setState("fail"); setMsg(i18nT("pair.badCode")); return;
    }
    const origin = (/^https?:\/\/[^/]+/i.exec(url ?? "") ?? [""])[0];
    // Relay url comes from the link's origin when the code omits it; if the
    // deep-link url hasn't been delivered yet, wait for the effect to re-run
    // instead of failing with "Relay-URL fehlt" (don't consume the guard).
    if (!inner.u && !origin) return;
    ran.current = code;
    (async () => {
      setState("busy"); setMsg(i18nT("pair.pairing"));
      const applied = applyPairing(btoa(JSON.stringify({
        u: inner.u || origin, r: inner.r, k: inner.k, t: inner.t,
      })));
      if (!applied.ok) { setState("fail"); setMsg(applied.reason); return; }
      setMsg(i18nT("pair.checking"));
      try {
        await api.me();   // proves relay + E2EE + Token in one round-trip
        // the board/dashboard queries ran BEFORE this pairing (unconfigured ->
        // empty/error) and won't refetch on their own; force every query to
        // reload against the now-working config, else the board stays blank.
        qc.invalidateQueries();
        setState("ok"); setMsg(i18nT("pair.ok"));
        setTimeout(() => router.replace("/"), 900);
      } catch (e) {
        setState("fail");
        setMsg(e instanceof AuthRequired
          ? i18nT("pair.tokenRejected")
          : i18nT("pair.noAnswer", { err: String((e as Error).message) }));
      }
    })();
  }, [c, url, applyPairing, router]);

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", gap: 10, padding: 24 }}>
      <Text style={{ color: t.txtPrimary, fontSize: 17, fontWeight: "600" }}>{tr("pair.title")}</Text>
      {state === "busy" ? <ActivityIndicator color={t.accent} /> : null}
      <Text style={{ color: state === "fail" ? t.danger : state === "ok" ? t.ok : t.txtSecondary,
        fontSize: 14, textAlign: "center", lineHeight: 20 }}>{msg}</Text>
      {state === "fail" ? (
        <Text style={{ color: t.txtTertiary, fontSize: 12, textAlign: "center" }}>
          {tr("pair.hint")}
        </Text>
      ) : null}
    </View>
  );
}
