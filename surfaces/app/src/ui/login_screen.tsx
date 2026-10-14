// Restores the old Next.js web app's AuthGate (web/components/auth.tsx,
// archived at the Expo cutover, commit 6625edc) - a real username/password
// login, lost when that component was never ported to Expo. The old version
// worked on cookies (same-origin proxy); this one calls the SAME daemon
// routes but stores the TOKEN they now also return (routes_auth.py, see
// daemon/debt.py's expo-cutover-pipeline-login-regression), since the app's
// own request layer (client.ts) authenticates with a Bearer token, not a
// cookie. Styled like surfaces/app/src/ui/onboard.tsx (same canvas/centered-card
// look, same button/skip conventions) so it reads as part of the same app.
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator, Keyboard, KeyboardAvoidingView, Platform, Pressable,
  ScrollView, Text, TextInput, TouchableWithoutFeedback, View,
} from "react-native";

import { api } from "@/data/client";
import { useAuthGate } from "@/data/authgate";
import { useConfig } from "@/data/config";
import { useDemo } from "@/data/demo";
import { useT } from "@/i18n";
import { fieldStyle, Hint } from "@/ui/settings_sections";
import { useTheme } from "@/theme";

// "choose" + "connect" are the first-run fork (no owner yet): this PC becomes the
// server (-> "setup"), or it only attaches to a server that already exists
// (-> "connect", the same pairing code the phone's PairingGate takes).
type Mode = "in" | "up" | "setup" | "choose" | "connect" | "reset";

const hasInviteLink = () =>
  !!new URLSearchParams(globalThis.location?.search ?? "").get("invite");

export function LoginScreen() {
  const t = useTheme();
  // Sign-in runs BEFORE there is a token, so useT()'s /me query cannot resolve a
  // workspace language here - it falls back to the device locale, which is the
  // right answer for a screen that greets someone who has not paired yet.
  const tr = useT();
  const qc = useQueryClient();
  const field = fieldStyle(t);
  const [mode, setMode] = useState<Mode>("in");
  // TWO different questions, and conflating them was a real dead end: `canSignUp`
  // = is there any way in at all (open registration OR a live invitation), which
  // decides whether the "Konto anlegen" tab exists; `noCodeNeeded` = the
  // workspace lets anyone in without one. The code field used to be hidden
  // whenever the FIRST was true, so a workspace that had only ever issued an
  // invite code showed the sign-up tab with nowhere to type the code.
  const [setupNeeded, setSetupNeeded] = useState(false);
  const [canSignUp, setCanSignUp] = useState(false);
  const [noCodeNeeded, setNoCodeNeeded] = useState(false);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<TextInput>(null);
  const inviteRef = useRef<TextInput>(null);

  useEffect(() => {
    api.authState()
      .then((s) => {
        setSetupNeeded(!!s.setup_needed);
        if (s.setup_needed) setMode(hasInviteLink() ? "setup" : "choose");
        setCanSignUp(!!s.registration);
        setNoCodeNeeded(!!s.registration_open);
      })
      .catch(() => { /* daemon unreachable - stay on sign-in, the form itself will show a real error on submit */ });
  }, []);

  // An invitation link (…/?invite=CODE) lands here: prefill the code and open
  // the sign-up tab, so the person who was invited never has to work out which
  // of three modes this screen is in. Web only - a deep link on native carries
  // the code through the pairing gate instead.
  useEffect(() => {
    const url = globalThis.location?.search ?? "";
    const code = new URLSearchParams(url).get("invite");
    if (code) { setInvite(code.trim().toUpperCase()); setMode("up"); setCanSignUp(true); }
  }, []);

  const applyToken = (token: string | undefined) => {
    if (!token) return;
    useConfig.getState().set({ token });
    // A real credential beats the sample board. The demo flag is persisted, so
    // one tap on "try the demo" (board invite, onboarding) would otherwise
    // answer every request from the fixture for good - the owner's real login
    // "always landed in demo" (2026-10-12). Pairing already does this (config.ts).
    useDemo.getState().disable();
    useAuthGate.getState().clearAuthRequired();
    qc.invalidateQueries();
  };

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      const r = mode === "setup" ? await api.authSetup(name.trim(), password)
        : mode === "up" ? await api.authRegister(name.trim(), password, invite.trim())
        : mode === "reset" ? await api.authReset(name.trim(), invite.trim(), password)
        : await api.login(name.trim(), password);
      if (!r.ok || !r.token) {
        setErr(r.error || tr("login.failed")); setBusy(false); return;
      }
      applyToken(r.token);
    } catch (e) {
      setErr(String((e as Error)?.message ?? e)); setBusy(false);
    }
  };

  const [pair, setPair] = useState("");

  const connect = async () => {
    const applied = useConfig.getState().applyPairing(pair);
    if (!applied.ok) { setErr(applied.reason); return; }
    setBusy(true); setErr("");
    try {
      await api.me();
      useAuthGate.getState().clearAuthRequired();
      qc.invalidateQueries();
    } catch (e) {
      setErr(String((e as Error)?.message ?? e)); setBusy(false);
    }
  };

  const title = tr(mode === "choose" ? "login.chooseTitle" : mode === "connect" ? "login.connectTitle"
    : mode === "setup" ? "login.setupTitle" : mode === "up" ? "login.createAccount"
    : mode === "reset" ? "login.resetTitle" : "login.signIn");
  // the code field: an invitation code on sign-up (unless sign-up is open), the
  // owner's reset code on a forgotten password - same field, same typing habits
  const showsInvite = (mode === "up" && !noCodeNeeded) || mode === "reset";
  const backLink = (
    <Pressable onPress={() => { setMode("choose"); setErr(""); }} style={{ paddingVertical: 6 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 13, fontWeight: "600" }}>← {tr("login.back")}</Text>
    </Pressable>
  );

  if (mode === "choose") {
    const card = (titleKey: string, bodyKey: string, onPress: () => void) => (
      <Pressable onPress={onPress}
        style={{ backgroundColor: t.surface1, borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 14, padding: 16, gap: 6 }}>
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "700" }}>{tr(titleKey)}</Text>
        <Text style={{ color: t.txtSecondary, fontSize: 13, lineHeight: 19 }}>{tr(bodyKey)}</Text>
      </Pressable>
    );
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", padding: 28 }}>
        <View style={{ width: "100%", maxWidth: 460, gap: 14 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 24, fontWeight: "700" }}>{title}</Text>
          <Hint text={tr("login.chooseHint")} />
          {card("login.chooseServerTitle", "login.chooseServerBody", () => setMode("setup"))}
          {card("login.chooseClientTitle", "login.chooseClientBody", () => setMode("connect"))}
        </View>
      </View>
    );
  }

  if (mode === "connect") {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", padding: 28 }}>
        <View style={{ width: "100%", maxWidth: 460, gap: 14 }}>
          {setupNeeded ? backLink : null}
          <Text style={{ color: t.txtPrimary, fontSize: 24, fontWeight: "700" }}>{title}</Text>
          <Text style={{ color: t.txtSecondary, fontSize: 13, lineHeight: 20 }}>{tr("login.connectSteps")}</Text>
          <TextInput value={pair} onChangeText={setPair} autoCapitalize="none" autoCorrect={false} multiline autoFocus
            placeholder={tr("settings.more.pairPh")} placeholderTextColor={t.txtTertiary}
            style={[field, { minHeight: 70 }]} />
          {err ? <Text style={{ color: t.danger, fontSize: 12.5 }}>{err}</Text> : null}
          <Pressable onPress={connect} disabled={busy || !pair.trim()}
            style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
              backgroundColor: busy ? t.surface2 : t.accent, borderRadius: 14, paddingVertical: 14, opacity: !pair.trim() ? 0.6 : 1 }}>
            {busy ? <ActivityIndicator color="#fff" /> : null}
            <Text style={{ color: busy ? t.txtSecondary : "#fff", fontSize: 15, fontWeight: "600" }}>{tr("login.connectBtn")}</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: t.canvas }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={{ flexGrow: 1, alignItems: "center", justifyContent: "center", padding: 28 }}
        keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive">
        {/* Tap-outside-to-dismiss is a touch-keyboard idiom. On web/desktop the
            click on a FIELD bubbles to this wrapper too, so Keyboard.dismiss
            blurred the input the instant the mouse focused it - the login
            fields could not be clicked into (owner report 2026-10-12, since
            d55ec188). A desktop has no on-screen keyboard to dismiss. */}
        <TouchableWithoutFeedback onPress={Platform.OS === "web" ? undefined : Keyboard.dismiss} accessible={false}>
          <View style={{ width: "100%", maxWidth: 420, gap: 14 }}>
            <View style={{ gap: 6 }}>
              {mode === "setup" ? backLink : null}
              <Text style={{ color: t.txtPrimary, fontSize: 24, fontWeight: "700" }}>{title}</Text>
              {mode === "setup" ? (
                <Hint text={tr("login.setupHint")} />
              ) : null}
              {mode === "reset" ? <Hint text={tr("login.resetHint")} /> : null}
            </View>

            {mode !== "setup" ? (
              <View style={{ flexDirection: "row", gap: 16 }}>
                <Pressable onPress={() => setMode("in")}>
                  <Text style={{ color: mode === "in" ? t.accent : t.txtTertiary, fontSize: 13, fontWeight: "600" }}>{tr("login.signIn")}</Text>
                </Pressable>
                {canSignUp ? (
                  <Pressable onPress={() => setMode("up")}>
                    <Text style={{ color: mode === "up" ? t.accent : t.txtTertiary, fontSize: 13, fontWeight: "600" }}>{tr("login.createAccount")}</Text>
                  </Pressable>
                ) : null}
              </View>
            ) : null}

            <TextInput placeholder={tr("login.user")} placeholderTextColor={t.txtTertiary} autoCapitalize="none"
              autoCorrect={false} autoFocus value={name} onChangeText={setName} style={field}
              returnKeyType="next" onSubmitEditing={() => passwordRef.current?.focus()} />
            <TextInput ref={passwordRef} placeholder={tr(mode === "in" ? "login.password" : "login.passwordNew")} placeholderTextColor={t.txtTertiary}
              secureTextEntry value={password} onChangeText={setPassword} style={field}
              returnKeyType={showsInvite ? "next" : "go"}
              onSubmitEditing={() => (showsInvite ? inviteRef.current?.focus() : submit())} />
            {showsInvite ? (
              <TextInput ref={inviteRef} placeholder={tr(mode === "reset" ? "login.resetCode" : "login.invite")} placeholderTextColor={t.txtTertiary}
                autoCapitalize="characters" autoCorrect={false}
                value={invite} onChangeText={(v) => setInvite(v.toUpperCase())} style={field}
                returnKeyType="go" onSubmitEditing={submit} />
            ) : null}

            {err ? <Text style={{ color: t.danger, fontSize: 12.5 }}>{err}</Text> : null}

            <Pressable onPress={submit} disabled={busy || !name.trim() || !password || (mode === "reset" && !invite.trim())}
              style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
                backgroundColor: busy ? t.surface2 : t.accent, borderRadius: 14, paddingVertical: 14, opacity: !name.trim() || !password ? 0.6 : 1 }}>
              {busy ? <ActivityIndicator color="#fff" /> : null}
              <Text style={{ color: busy ? t.txtSecondary : "#fff", fontSize: 15, fontWeight: "600" }}>
                {tr(mode === "setup" ? "login.setupSubmit" : mode === "up" ? "login.createAccount"
                  : mode === "reset" ? "login.resetSubmit" : "login.signIn")}
              </Text>
            </Pressable>

            {mode === "in" ? (
              <Pressable onPress={() => { setMode("reset"); setErr(""); setPassword(""); }} style={{ alignSelf: "center", paddingVertical: 6 }}>
                <Text style={{ color: t.txtTertiary, fontSize: 13, fontWeight: "600" }}>{tr("login.forgot")}</Text>
              </Pressable>
            ) : null}
          </View>
        </TouchableWithoutFeedback>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
