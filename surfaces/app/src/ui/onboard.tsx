import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import * as util from "tweetnacl-util";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Image, Platform, Pressable, ScrollView, Text, View } from "react-native";

import { api, AuthRequired } from "@/data/client";
import { qrDataUrl } from "@/data/qrgen";
import {
  setupApi, setupAvailable, useOnboard,
  type EngineStatus, type SetupLine, type SetupState,
} from "@/data/setup";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// ONE screen. One button.
//
// Everything the old path made the user do by hand — install a runtime, start
// the instance, create an owner, dig the pairing QR out of Settings — happens
// behind this single action, with Claude Code doing the installing once it is
// available. The screen only ever shows three things: what it is doing, what it
// needs from the user (only ever "connect Claude"), and finally the QR.
export function Onboard() {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const dismiss = useOnboard((s) => s.dismiss);
  const [st, setSt] = useState<SetupState | null>(null);
  const [lines, setLines] = useState<SetupLine[]>([]);
  const [engines, setEngines] = useState<EngineStatus[]>([]);
  // "claude" is always in here: it is the only engine that can finish
  // provisioning (setup.js ENGINES docstring), so the picker cannot remove
  // it - only add optional extras on top.
  const [selected, setSelected] = useState<Set<string>>(new Set(["claude"]));
  const [qr, setQr] = useState("");
  const [pairLink, setPairLink] = useState("");
  const [pairErr, setPairErr] = useState("");
  const paired = useRef(false);
  const scroller = useRef<ScrollView>(null);

  // Poll state + log. Cheap (loopback) and it keeps the screen honest about a
  // provisioning run that was started by an earlier window.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const [s, l, e] = await Promise.all([setupApi.state(), setupApi.log(), setupApi.engines()]);
      if (!alive) return;
      if (s) setSt(s);
      if (l) setLines(l.log);
      if (e) setEngines(e.engines);
    };
    tick();
    const iv = setInterval(tick, 1200);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  // The instance is up -> mint the pairing artifact. One link, shown as a QR and
  // as copyable text: the same string works as scan, tap-link and deep link.
  const makePairing = useCallback(async () => {
    if (paired.current) return;
    paired.current = true;
    try {
      const r = await api.post<{ url?: string; room?: string; daemon_pub?: string; device_token?: string; error?: string }>(
        "/relay/pair", {});
      if (r.error || !r.url) { setPairErr(r.error || tr("onboard.pairFailed")); paired.current = false; return; }
      const code = util.encodeBase64(util.decodeUTF8(JSON.stringify({
        u: r.url, r: r.room, k: r.daemon_pub, t: r.device_token,
      })));
      const link = `${r.url.replace(/\/$/, "")}/pair?c=${code}`;
      setPairLink(link);
      setQr(await qrDataUrl(link));
    } catch (e) {
      // Not being logged in is the EXPECTED state here now that the shell hands
      // out no free owner token, so it must not read like a breakage: pairing a
      // phone binds it to an account, and there is no account until someone
      // signs in. The auth gate takes the screen from here.
      setPairErr(e instanceof AuthRequired
        ? tr("onboard.pairNeedsLogin")
        : String((e as Error).message));
      paired.current = false;
    }
  }, [tr]);

  // "claude" can't be removed - it's the only engine that can finish
  // provisioning (see setup.js ENGINES). Everything else is a free toggle.
  const toggleEngine = useCallback((id: string) => {
    if (id === "claude") return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  useEffect(() => {
    if (st?.daemon && !qr && !pairErr) {
      qc.invalidateQueries();
      makePairing();
    }
  }, [st?.daemon, qr, pairErr, makePairing, qc]);

  const busy = !!st?.running;
  const needsClaude = st && !st.claude;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", padding: 28 }}>
      <View style={{ width: "100%", maxWidth: 560, gap: 18 }}>
        <View style={{ gap: 6 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 26, fontWeight: "700" }}>{tr("onboard.title")}</Text>
          <Text style={{ color: t.txtSecondary, fontSize: 14, lineHeight: 20 }}>
            {qr ? tr("onboard.subScan") : needsClaude ? tr("onboard.subClaude") : tr("onboard.sub")}
          </Text>
        </View>

        {/* engine picker — claude is pinned (only it can finish setup, see
            setup.js ENGINES); the rest are optional CLIs to also fetch.
            Hidden once paired, disabled (not hidden) while running so the
            selection stays visible but can't change mid-provision. */}
        {!qr && engines.length > 0 ? (
          <View style={{ gap: 8 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 11.5, fontWeight: "600",
              textTransform: "uppercase", letterSpacing: 0.4 }}>
              {tr("onboard.enginesTitle")}
            </Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
              {engines.map((e) => {
                const isSelected = selected.has(e.id);
                const locked = e.id === "claude";
                return (
                  <Pressable key={e.id} disabled={locked || busy} onPress={() => toggleEngine(e.id)}
                    style={{ flexDirection: "row", alignItems: "center", gap: 7,
                      borderRadius: 10, borderWidth: 1,
                      borderColor: isSelected ? t.accent : t.borderSubtle,
                      backgroundColor: isSelected ? t.accent + "1a" : t.surface1,
                      paddingHorizontal: 12, paddingVertical: 8, opacity: locked ? 0.85 : 1 }}>
                    <View style={{ width: 7, height: 7, borderRadius: 3.5,
                      backgroundColor: e.installed ? t.ok : t.txtTertiary }} />
                    <View>
                      <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600" }}>{e.label}</Text>
                      <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>
                        {locked ? tr("onboard.engineRequired") : tr("onboard.engineTier." + e.tier)}
                      </Text>
                    </View>
                  </Pressable>
                );
              })}
            </View>
          </View>
        ) : null}

        {/* the pairing artifact — the end state of the whole screen */}
        {qr ? (
          <View style={{ alignItems: "center", gap: 12, backgroundColor: t.surface1, borderRadius: 16,
            borderWidth: 1, borderColor: t.borderSubtle, padding: 18 }}>
            <Image source={{ uri: qr }} style={{ width: 232, height: 232, borderRadius: 10, backgroundColor: "#fff" }} />
            <Text selectable numberOfLines={2} style={{ color: t.accent, fontSize: 11.5, textAlign: "center" }}>
              {pairLink}
            </Text>
            <Pressable onPress={dismiss}
              style={{ backgroundColor: t.accent, borderRadius: 12, paddingHorizontal: 20, paddingVertical: 11 }}>
              <Text style={{ color: "#fff", fontWeight: "600", fontSize: 14 }}>{tr("onboard.openBoard")}</Text>
            </Pressable>
          </View>
        ) : (
          <Pressable
            onPress={() => { setLines([]); setupApi.provision(Array.from(selected)); }}
            disabled={busy}
            style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
              backgroundColor: busy ? t.surface2 : t.accent, borderRadius: 14, paddingVertical: 15 }}>
            {busy ? <ActivityIndicator color={t.accent} /> : <Ionicons name="sparkles-outline" size={18} color="#fff" />}
            <Text style={{ color: busy ? t.txtSecondary : "#fff", fontSize: 15, fontWeight: "600" }}>
              {busy ? tr("onboard.working") : tr("onboard.start")}
            </Text>
          </Pressable>
        )}

        {pairErr ? <Text style={{ color: t.danger, fontSize: 13 }}>{pairErr}</Text> : null}

        {/* progress: the same one screen, just more of it */}
        {lines.length > 0 ? (
          <ScrollView ref={scroller} style={{ maxHeight: 220 }}
            onContentSizeChange={() => scroller.current?.scrollToEnd({ animated: true })}
            contentContainerStyle={{ gap: 4, paddingVertical: 4 }}>
            {lines.map((l, i) => (
              <Text key={i} numberOfLines={2}
                style={{ fontSize: 12, lineHeight: 17,
                  color: l.kind === "err" ? t.danger : l.kind === "ok" ? t.ok : l.kind === "hint" ? t.accent : t.txtTertiary,
                  ...(Platform.OS === "web" ? { fontFamily: "ui-monospace, monospace" } as any : {}) }}>
                {l.line}
              </Text>
            ))}
          </ScrollView>
        ) : null}

        <Pressable onPress={dismiss}>
          <Text style={{ color: t.txtTertiary, fontSize: 12.5, textAlign: "center" }}>{tr("onboard.skip")}</Text>
        </Pressable>
      </View>
    </View>
  );
}

/** Desktop shell + instance not serving yet => onboarding owns the window.
 *
 *  Deliberately NOT keyed off the health store: on a cold start `lastOkAt` is 0
 *  for everyone, so that would flash onboarding into every normal launch. We ask
 *  the control plane instead and stay silent until it has actually answered
 *  (`null` = unknown = show nothing). */
export function useShowOnboard() {
  const dismissed = useOnboard((s) => s.dismissed);
  const [daemonUp, setDaemonUp] = useState<boolean | null>(null);
  useEffect(() => {
    if (!setupAvailable()) return;
    let alive = true;
    const tick = async () => {
      const s = await setupApi.state();
      if (alive && s) setDaemonUp(s.daemon);
    };
    tick();
    const iv = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return setupAvailable() && !dismissed && daemonUp === false;
}
