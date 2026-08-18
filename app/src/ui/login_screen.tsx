// Restores the old Next.js web app's AuthGate (web/components/auth.tsx,
// archived at the Expo cutover, commit 6625edc) - a real username/password
// login, lost when that component was never ported to Expo. The old version
// worked on cookies (same-origin proxy); this one calls the SAME daemon
// routes but stores the TOKEN they now also return (routes_auth.py, see
// daemon/debt.py's expo-cutover-pipeline-login-regression), since the app's
// own request layer (client.ts) authenticates with a Bearer token, not a
// cookie. Styled like app/src/ui/onboard.tsx (same canvas/centered-card
// look, same button/skip conventions) so it reads as part of the same app.
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";

import { api } from "@/data/client";
import { useAuthGate } from "@/data/authgate";
import { useConfig } from "@/data/config";
import { fieldStyle, Hint } from "@/ui/settings_sections";
import { useTheme } from "@/theme";

type Mode = "in" | "up" | "setup";

export function LoginScreen() {
  const t = useTheme();
  const qc = useQueryClient();
  const field = fieldStyle(t);
  const [mode, setMode] = useState<Mode>("in");
  const [registrationOpen, setRegistrationOpen] = useState(false);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.authState()
      .then((s) => {
        if (s.setup_needed) setMode("setup");
        setRegistrationOpen(!!s.registration);
      })
      .catch(() => { /* daemon unreachable - stay on sign-in, the form itself will show a real error on submit */ });
  }, []);

  const applyToken = (token: string | undefined) => {
    if (!token) return;
    useConfig.getState().set({ token });
    useAuthGate.getState().clearAuthRequired();
    qc.invalidateQueries();
  };

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      const r = mode === "setup" ? await api.authSetup(name.trim(), password)
        : mode === "up" ? await api.authRegister(name.trim(), password, invite.trim())
        : await api.login(name.trim(), password);
      if (!r.ok || !r.token) {
        setErr(r.error || "Anmeldung fehlgeschlagen"); setBusy(false); return;
      }
      applyToken(r.token);
    } catch (e) {
      setErr(String((e as Error)?.message ?? e)); setBusy(false);
    }
  };

  const title = mode === "setup" ? "Owner-Konto anlegen" : mode === "up" ? "Konto erstellen" : "Anmelden";

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", padding: 28 }}>
      <View style={{ width: "100%", maxWidth: 420, gap: 14 }}>
        <View style={{ gap: 6 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 24, fontWeight: "700" }}>{title}</Text>
          {mode === "setup" ? (
            <Hint text="Erster Start - dieses Konto verwaltet alles, inklusive weiterer Benutzer." />
          ) : null}
        </View>

        {mode !== "setup" ? (
          <View style={{ flexDirection: "row", gap: 16 }}>
            <Pressable onPress={() => setMode("in")}>
              <Text style={{ color: mode === "in" ? t.accent : t.txtTertiary, fontSize: 13, fontWeight: "600" }}>Anmelden</Text>
            </Pressable>
            {registrationOpen ? (
              <Pressable onPress={() => setMode("up")}>
                <Text style={{ color: mode === "up" ? t.accent : t.txtTertiary, fontSize: 13, fontWeight: "600" }}>Konto erstellen</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}

        <TextInput placeholder="Benutzername" placeholderTextColor={t.txtTertiary} autoCapitalize="none"
          autoCorrect={false} autoFocus value={name} onChangeText={setName} style={field} />
        <TextInput placeholder={mode === "in" ? "Passwort" : "Passwort (mind. 8 Zeichen)"} placeholderTextColor={t.txtTertiary}
          secureTextEntry value={password} onChangeText={setPassword} style={field}
          onSubmitEditing={submit} />
        {mode === "up" && !registrationOpen ? (
          <TextInput placeholder="Einladungscode" placeholderTextColor={t.txtTertiary}
            value={invite} onChangeText={setInvite} style={field} />
        ) : null}

        {err ? <Text style={{ color: t.danger, fontSize: 12.5 }}>{err}</Text> : null}

        <Pressable onPress={submit} disabled={busy || !name.trim() || !password}
          style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
            backgroundColor: busy ? t.surface2 : t.accent, borderRadius: 14, paddingVertical: 14, opacity: !name.trim() || !password ? 0.6 : 1 }}>
          {busy ? <ActivityIndicator color="#fff" /> : null}
          <Text style={{ color: busy ? t.txtSecondary : "#fff", fontSize: 15, fontWeight: "600" }}>
            {mode === "setup" ? "Anlegen & anmelden" : mode === "up" ? "Konto erstellen" : "Anmelden"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}
