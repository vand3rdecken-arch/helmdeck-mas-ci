import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import * as util from "tweetnacl-util";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Image, Platform, Pressable, ScrollView, Text, View } from "react-native";

import { api, AuthRequired } from "@/data/client";
import { useConfig } from "@/data/config";
import { qrDataUrl } from "@/data/qrgen";
import {
  setupApi, setupAvailable, useOnboard,
  type EngineStatus, type SetupLine, type SetupState,
} from "@/data/setup";
import { useT } from "@/i18n";
import { LoginScreen } from "@/ui/login_screen";
import { RepoTypePicker, useRepoTypeOutstanding } from "@/ui/repo_type_picker";
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
  // A token means someone is signed in; the QR is owner-only (/relay/pair,
  // routes_relay.py), so on a fresh machine the last provisioning step is
  // creating that account. `authRejected` covers the other case - a persisted
  // token the daemon no longer accepts - so a stale credential lands on the
  // same sign-in step instead of a red error under a dead button.
  const token = useConfig((s) => s.token);
  const [authRejected, setAuthRejected] = useState(false);
  const paired = useRef(false);
  const scroller = useRef<ScrollView>(null);

  // Poll state + log. Cheap (loopback) and it keeps the screen honest about a
  // provisioning run that was started by an earlier window.
  //
  // CHAINED, not setInterval: /setup/state probes for Python/Claude with
  // SYNCHRONOUS spawns on the shell side, so on a slow first run a fixed
  // interval stacks requests faster than they answer and the screen ends up
  // rendering whichever reply happens to land last.
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      const [s, l, e] = await Promise.all([setupApi.state(), setupApi.log(), setupApi.engines()]);
      if (!alive) return;
      if (s) setSt(s);
      if (l) setLines(l.log);
      if (e) setEngines(e.engines);
      timer = setTimeout(tick, 1200);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, []);

  // A fresh sign-in earns a fresh pairing attempt: clear the rejection and drop
  // the once-only latch so the effect below can mint the QR that the missing
  // account was blocking.
  useEffect(() => {
    setAuthRejected(false);
    paired.current = false;
  }, [token]);

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
      // signs in. That is a STEP of onboarding, not the end of it - so route it
      // to the sign-in step rather than parking an error message on a screen
      // whose only remaining button re-runs provisioning that already worked.
      if (e instanceof AuthRequired) setAuthRejected(true);
      else setPairErr(String((e as Error).message));
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

  // The instance runs, but the pairing artifact is owner-only - so this is the
  // one thing still missing before the screen can show its end state.
  const needsAuth = !!st?.daemon && (!token || authRejected);

  // The repo step: only once the daemon is up AND someone is signed in (the
  // /repo/templates call is authenticated), only while a repo type is actually
  // outstanding, and only until the user moves past it. `=== true` on purpose -
  // the hook returns undefined until the query answers, and treating that as
  // "outstanding" would flash this step into every launch.
  const [repoDone, setRepoDone] = useState(false);
  const repoOutstanding = useRepoTypeOutstanding();
  const repoStep = !!st?.daemon && !needsAuth && !repoDone && repoOutstanding === true;

  useEffect(() => {
    if (st?.daemon && !needsAuth && !qr && !pairErr) {
      qc.invalidateQueries();
      makePairing();
    }
  }, [st?.daemon, needsAuth, qr, pairErr, makePairing, qc]);

  const busy = !!st?.running;
  const needsClaude = st && !st.claude;

  // Still onboarding, just its third step - NOT a different screen. LoginScreen
  // already IS this step: its "setup" mode is "Owner-Konto anlegen", picked from
  // the daemon's own setup_needed, and it is drawn on the same centered canvas.
  // Reusing it keeps ONE sign-in surface; a second copy here would be the same
  // mistake as maintaining two chat UIs.
  if (needsAuth) return <LoginScreen />;

  // FOURTH STEP: which kind of repo is this?
  //
  // Provisioning installs an instance; it does not tell HelmDeck what the user
  // actually works on. Without this step a new user finished onboarding with no
  // repo at all, landed on an empty board, and never met the choice that decides
  // whether their cards get a worktree, a gate command and a deploy hook - the
  // "manuelles Nacharbeiten" this flow exists to remove. Asking it HERE, once
  // the daemon is up and someone is signed in, is the first moment it can be
  // both asked and answered.
  //
  // Skipped entirely for anyone who already chose (useRepoTypeOutstanding is
  // false), and skippable by hand - a user who wants to point HelmDeck at a repo
  // later must not be trapped on a form. `undefined` means the query has not
  // answered yet, and is deliberately NOT treated as "outstanding": flashing
  // this step into a returning user's launch would be the same bug the
  // useShowOnboard docstring below describes.
  if (repoStep) {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", padding: 28 }}>
        <ScrollView style={{ width: "100%", maxWidth: 620 }}
          contentContainerStyle={{ gap: 18, paddingVertical: 24 }}>
          <View style={{ gap: 6 }}>
            <Text style={{ color: t.txtPrimary, fontSize: 26, fontWeight: "700" }}>
              {tr("onboard.repoTitle")}
            </Text>
            <Text style={{ color: t.txtSecondary, fontSize: 14, lineHeight: 20 }}>
              {tr("onboard.repoSub")}
            </Text>
          </View>

          <RepoTypePicker wide={false} intro={tr("onboard.repoIntro")} />

          <Pressable onPress={() => setRepoDone(true)}
            style={{ backgroundColor: t.accent, borderRadius: 14, paddingVertical: 15, alignItems: "center" }}>
            <Text style={{ color: "#fff", fontSize: 15, fontWeight: "600" }}>{tr("onboard.repoNext")}</Text>
          </Pressable>
          <Pressable onPress={() => setRepoDone(true)}>
            <Text style={{ color: t.txtTertiary, fontSize: 12.5, textAlign: "center" }}>
              {tr("onboard.repoLater")}
            </Text>
          </Pressable>
        </ScrollView>
      </View>
    );
  }

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

/** Desktop shell, first run => onboarding owns the window.
 *
 *  Deliberately NOT keyed off the health store: on a cold start `lastOkAt` is 0
 *  for everyone, so that would flash onboarding into every normal launch. We ask
 *  the control plane instead and stay silent until it has actually answered
 *  (`null` = unknown = show nothing).
 *
 *  Onboarding is ENTERED because the instance is not serving - but it is NOT
 *  LEFT the moment it starts serving, which is the middle of the flow, not the
 *  end of it. Provisioning starts the daemon at step 3 of 5; keying purely on
 *  `!daemon` tore the screen down right there, taking the still-streaming
 *  progress log, the owner-account step and the pairing QR - the whole promised
 *  end state - with it, and dropped the user on a bare login screen instead.
 *
 *  So the condition also honours the control plane's OWN `running`/`done`, the
 *  runtime's real signals about a provisioning run, rather than a local flag we
 *  set ourselves: they live in the Electron main process, so a reload mid-run
 *  lands back on the same step with the same log, and a plain later launch
 *  (fresh process => running/done false, daemon up) correctly shows nothing. */
export function useShowOnboard() {
  const dismissed = useOnboard((s) => s.dismissed);
  const [owns, setOwns] = useState<boolean | null>(null);
  useEffect(() => {
    if (!setupAvailable()) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      const s = await setupApi.state();
      if (!alive) return;
      if (s) setOwns(!s.daemon || s.running || s.done);
      timer = setTimeout(tick, 2000);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  return setupAvailable() && !dismissed && owns === true;
}
