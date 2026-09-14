import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import * as util from "tweetnacl-util";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ActivityIndicator, Image, Linking, Platform, Pressable, ScrollView, Text, View } from "react-native";

import { api, AuthRequired } from "@/data/client";
import { useConfig } from "@/data/config";
import { useDemo } from "@/data/demo";
import { qrDataUrl } from "@/data/qrgen";
import {
  setupApi, setupAvailable, useOnboard,
  type EngineStatus, type SetupLine, type SetupState,
} from "@/data/setup";
import { useT } from "@/i18n";
import { DiagPanel, useSecretTap } from "@/ui/diag_panel";
import { LoginScreen } from "@/ui/login_screen";
import { RepoTypePicker, useRepoTypeOutstanding } from "@/ui/repo_type_picker";
import { useTheme } from "@/theme";

// A dead end still needs a way out: the "no npm" hint from setup.js
// ("Installiere Node.js von https://nodejs.org, dann hier erneut starten.")
// is the terminal state for a machine with nothing on it at all, and until
// now that URL was inert text the user had to retype into a browser by hand.
// Trailing punctuation ("nodejs.org," - the hint reads as a sentence) is
// excluded from the match so the link doesn't carry the comma into the URL.
const URL_RE = /https?:\/\/[^\s,]+/g;
function linkify(line: string, key: string): ReactNode {
  const parts = line.split(URL_RE);
  const urls = line.match(URL_RE) || [];
  if (!urls.length) return line;
  const out: ReactNode[] = [];
  parts.forEach((part, i) => {
    if (part) out.push(part);
    if (urls[i]) out.push(
      <Text key={key + "-u" + i} style={{ textDecorationLine: "underline" }}
        onPress={() => Linking.openURL(urls[i]).catch(() => {})}>{urls[i]}</Text>);
  });
  return out;
}

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
  const enableDemo = useDemo((s) => s.enable);
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
  // Optimistic feedback for the gap between a click and the first poll that
  // reports the run (see the tick() effect below - it hands over on the control
  // plane's own running/done, never merely because a tick happened), and a hard
  // error for when the click's own request never came back at all (the loopback
  // control plane unreachable, a rejected nonce, etc.) - previously that case
  // failed into total silence: setupApi.provision() was fired without awaiting
  // or checking its result.
  const [clicking, setClicking] = useState(false);
  const [startErr, setStartErr] = useState("");
  // Consecutive failed state-polls -> the control plane itself is unreachable,
  // not just one bad request. missRef persists across ticks without re-running
  // the effect; connErr is what actually renders.
  const missRef = useRef(0);
  const [connErr, setConnErr] = useState(false);
  // A token means someone is signed in; the QR is owner-only (/relay/pair,
  // routes_relay.py), so on a fresh machine the last provisioning step is
  // creating that account. `authRejected` covers the other case - a persisted
  // token the daemon no longer accepts - so a stale credential lands on the
  // same sign-in step instead of a red error under a dead button.
  const token = useConfig((s) => s.token);
  const [authRejected, setAuthRejected] = useState(false);
  const paired = useRef(false);
  const scroller = useRef<ScrollView>(null);
  // The black box, revealed by tapping the title 7x. THIS screen needs it most:
  // it runs before there is a daemon, an account or any navigation, on a
  // packaged build with no console - the exact conditions under which the
  // connect button spent a release silently answering 403.
  const diagTap = useSecretTap();

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
      if (s) { setSt(s); missRef.current = 0; setConnErr(false); }
      else if (++missRef.current >= 3) { setConnErr(true); setClicking(false); }
      if (l) setLines(l.log);
      if (e) setEngines(e.engines);
      // The optimistic spinner hands over on EVIDENCE, not on the next tick.
      // Clearing it for ANY poll result meant a tick landing milliseconds after
      // the click put the button straight back to its idle label while the
      // provision request was still in flight - a click that visibly did
      // nothing. `running`/`done` are the control plane's own signals about its
      // own run (setup.js sets `running` synchronously, before it answers the
      // provision call, so the very next poll already carries it); the
      // unreachable case is handled above, where connErr takes over the message.
      if (s?.running || s?.done) setClicking(false);
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

  const busy = !!st?.running || clicking;
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
          <Text onPress={diagTap.onPress} suppressHighlighting
            style={{ color: t.txtPrimary, fontSize: 26, fontWeight: "700" }}>{tr("onboard.title")}</Text>
          <Text style={{ color: t.txtSecondary, fontSize: 14, lineHeight: 20 }}>
            {qr ? tr("onboard.subScan") : needsClaude ? tr("onboard.subClaude") : tr("onboard.sub")}
          </Text>
        </View>

        {diagTap.open ? <DiagPanel onClose={diagTap.close} /> : null}

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
            onPress={async () => {
              setLines([]); setStartErr(""); setClicking(true);
              // Awaited + checked, unlike the old fire-and-forget call: a
              // failed request (endpoint unreachable, stale nonce) used to
              // vanish into setup.ts's call() catch with no trace on screen.
              const r = await setupApi.provision(Array.from(selected));
              if (!r) { setClicking(false); setStartErr(tr("onboard.startFailed")); }
            }}
            disabled={busy}
            // Windows contrast themes make Chromium repaint filled buttons to
            // OS colors, which can swallow the hardcoded white label below
            // (ops/docs/new-user-flow-ux-review-20260910.md P1.1) - opt this
            // one out (webstyles.tsx) and keep a visible border as a backstop
            // so it never collapses into a flat, textless area.
            {...(Platform.OS === "web" ? { dataSet: { hcGuard: "" } } : {})}
            style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
              backgroundColor: busy ? t.surface2 : t.accent, borderRadius: 14, paddingVertical: 15,
              borderWidth: 1, borderColor: busy ? t.borderSubtle : t.accent }}>
            {busy ? <ActivityIndicator color={t.accent} /> : <Ionicons name="sparkles-outline" size={18} color="#fff" />}
            <Text style={{ color: busy ? t.txtSecondary : "#fff", fontSize: 15, fontWeight: "600" }}>
              {busy ? tr("onboard.working") : tr("onboard.start")}
            </Text>
          </Pressable>
        )}

        {startErr ? <Text style={{ color: t.danger, fontSize: 13 }}>{startErr}</Text> : null}
        {connErr ? <Text style={{ color: t.danger, fontSize: 13 }}>{tr("onboard.connErr")}</Text> : null}
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
                {linkify(l.line, String(i))}
              </Text>
            ))}
          </ScrollView>
        ) : null}

        <Pressable
          onPress={() => {
            // Dismissing alone used to hand a not-yet-provisioned user straight
            // to index.tsx (the Dashboard tab), which has no offline/empty
            // fallback (unlike board.tsx's DemoInvite) - just a spinner that
            // never resolves against a daemon that was never started. Skipping
            // BEFORE the daemon came up is exactly demo mode's use case (see
            // data/demo.ts), so mirror PairingGate's own skip-to-demo choice
            // instead of landing on that blank screen. A daemon already up
            // (skip after a completed/partial provision) means there is a real
            // board to show, so leave it alone.
            if (!st?.daemon) { enableDemo(); qc.invalidateQueries(); }
            dismiss();
          }}>
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
 *  ROOT CAUSE FIX (2026-09-14, owner report: a fresh install with Python + Claude
 *  already on the machine skipped the engine picker and the create-owner screen
 *  entirely, landing straight on a login form). The OLD condition -
 *  `!s.daemon || s.running || s.done` - asked the LOCAL installer's own bookkeeping
 *  about a provisioning run, which was never the real question. main.js starts
 *  the daemon unconditionally on every launch (it has to - the daemon holds the
 *  phone's relay bridge, see its own comment), so `!s.daemon` goes false the
 *  instant the daemon answers, REGARDLESS of whether an owner account exists yet.
 *  On a machine with nothing to install, that happens on the very first tick,
 *  before the user ever gets a chance to pick engines or create an account, and
 *  `running`/`done` never go true either because no provisioning run was ever
 *  triggered. The picker and the create-owner step were reachable ONLY on a
 *  machine slow enough to install something first - an accident of timing, not a
 *  designed gate.
 *
 *  The actual question this screen exists to answer - is there still first-run
 *  setup outstanding - has an authoritative answer sitting on the daemon itself:
 *  `/auth/state`'s `setup_needed` (no owner account created yet) and whether every
 *  repo still lacks a chosen type (the step right after it in the same flow, see
 *  Onboard's repoStep). Ask those directly instead of inferring them from
 *  provisioning-process side effects.
 *
 *  Once genuinely entered, LATCH true rather than recomputing a fresh readout
 *  every poll: the moment `setup_needed` clears (an owner account was just
 *  created inside THIS flow) is also the moment the repo-type step and the
 *  pairing QR are due to render, and re-evaluating from scratch would tear the
 *  screen down mid-flow the same way the pre-2026-08-* `!daemon`-only condition
 *  once did (see the git history of this file). The one real exit is `dismiss()`
 *  (the Skip button, or the QR card's "open the board" button) - the return
 *  expression below already ANDs on `!dismissed`, so nothing else needs to
 *  un-latch `owns`. A plain later launch of an already-provisioned machine never
 *  latches it at all: `setup_needed` is false and every repo already has a type,
 *  so this hook stays silent and the normal app renders straight away.
 *
 *  Returns `unresolved` alongside `show` so the caller can hold the SAME
 *  blank canvas it already holds for cache hydration (_layout.tsx's
 *  `!restored` gate) until this has a real answer, instead of defaulting to
 *  "show the normal app" while the question is still open. That default was
 *  the other half of the 2026-09-14 bug: even once `owns` correctly resolves
 *  to true, React had already rendered one frame with `owns === null` (the
 *  initial state, before the first poll lands), and THAT frame took the
 *  `showOnboard === false` branch straight into the normal app tree, whose
 *  screens fire real queries (`/tracks`, `/cells`, `/dashboard/data`, ...)
 *  before the poll's answer arrives and flips the branch back to Onboard - a
 *  visible flash of 401s on a machine with nothing to provision, where the
 *  first poll can resolve before `!restored` even clears. `unresolved` closes
 *  that gap by name instead of by lucky timing.
 *
 *  Bounded: MAX_UNRESOLVED_MS caps how long "unknown" can hold the app back.
 *  A wedged/unreachable control plane (crashed setup.js, a rejected nonce)
 *  must fail OPEN into "no onboarding" - the pre-2026-08 shape, and the only
 *  safe default when the real answer cannot be had - never fail closed into a
 *  permanently blank window, which would be a worse bug than the one this
 *  fixes. */
const MAX_UNRESOLVED_MS = 8000;

export function useShowOnboard(): { show: boolean; unresolved: boolean } {
  const dismissed = useOnboard((s) => s.dismissed);
  const [owns, setOwns] = useState<boolean | null>(null);
  useEffect(() => {
    if (!setupAvailable() || dismissed) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const giveUp = setTimeout(() => { if (alive) setOwns((cur) => (cur === null ? false : cur)); }, MAX_UNRESOLVED_MS);
    const tick = async () => {
      const s = await setupApi.state();
      if (!alive) return;
      if (!s) { timer = setTimeout(tick, 2000); return; }
      // The instance itself isn't up, or is actively installing something -
      // definitely still onboarding, no need to ask the daemon anything.
      if (!s.daemon || s.running) { setOwns(true); timer = setTimeout(tick, 2000); return; }
      // The daemon answers: ask IT the real question. setup_needed alone can
      // decide "still onboarding" here - repoTemplates needs a token, which
      // does not exist yet while an owner account is still outstanding, and
      // the repo step is unreachable in Onboard() until AFTER needsAuth clears
      // anyway (same ordering: auth, then repo).
      try {
        const auth = await api.authState();
        if (!alive) return;
        if (auth.setup_needed) { setOwns(true); timer = setTimeout(tick, 2000); return; }
        const repos = await api.repoTemplates().catch(() => null);
        if (!alive) return;
        const repoOutstanding = !!repos && (!repos.repos.length || repos.repos.some((r) => !r.template));
        // LATCH: once true, a later tick landing right after setup_needed/
        // repoOutstanding themselves clear must not flip this back to false
        // out from under a user still looking at the repo-type step or the
        // pairing QR - see the docstring above. Only the FIRST resolution
        // (from null) may land on false; once true, stay true until dismiss().
        setOwns((cur) => cur === true || repoOutstanding);
      } catch {
        // daemon answered /setup/state but not the real API yet - retry, but
        // don't leave `owns` stuck at null forever on a persistent failure
        // (giveUp above already covers that on its own timer).
      }
      timer = setTimeout(tick, 2000);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); clearTimeout(giveUp); };
  }, [dismissed]);
  return {
    show: setupAvailable() && !dismissed && owns === true,
    unresolved: setupAvailable() && !dismissed && owns === null,
  };
}
