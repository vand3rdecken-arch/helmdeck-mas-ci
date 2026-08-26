// Native pairing gate (2026-08-26) - see data/config.ts useNeedsPairing() for
// why this exists: a fresh/reinstalled Android app previously fell straight
// through into the tabbed UI with no daemon configured, and the Dashboard's
// query hung indefinitely against the (emulator-only) default address. This
// screen is what a fresh install should see FIRST instead - same three
// choices already offered deeper in the app (more.tsx's pair panel, board.tsx's
// DemoInvite), just surfaced before anything tries to load real data.
// Styled like login_screen.tsx (same canvas/centered-card look).
import { useState } from "react";
import { useRouter } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { AuthRequired, api } from "@/data/client";
import { useConfig } from "@/data/config";
import { useDemo } from "@/data/demo";
import { useT } from "@/i18n";
import { fieldStyle } from "@/ui/settings_sections";
import { useTheme } from "@/theme";

export function PairingGate() {
  const t = useTheme();
  const tr = useT();   // pre-pairing: falls back to device locale, same as LoginScreen
  const router = useRouter();
  const qc = useQueryClient();
  const applyPairing = useConfig((s) => s.applyPairing);
  const enableDemo = useDemo((s) => s.enable);
  const field = fieldStyle(t);
  const [pair, setPair] = useState("");
  const [msg, setMsg] = useState("");
  const [kind, setKind] = useState<"info" | "ok" | "err">("info");
  const [busy, setBusy] = useState(false);

  async function doPair() {
    const applied = applyPairing(pair);
    if (!applied.ok) { setKind("err"); setMsg(applied.reason); return; }
    setBusy(true); setKind("info"); setMsg(tr("settings.more.verifying"));
    try {
      await api.me();
      qc.invalidateQueries();
      setKind("ok");
      setMsg(applied.mode === "relay" ? tr("settings.more.pairedRelayOk") : tr("settings.more.pairedLanOk"));
      setPair("");
    } catch (e) {
      setKind("err");
      setMsg(e instanceof AuthRequired
        ? tr("settings.more.tokenRejected")
        : tr("settings.more.noAnswer", { err: String((e as Error).message) }));
    } finally { setBusy(false); }
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", padding: 28 }}>
      <View style={{ width: "100%", maxWidth: 420, gap: 14 }}>
        <View style={{ gap: 6 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 24, fontWeight: "700" }}>{tr("gate.title")}</Text>
          <Text style={{ color: t.txtSecondary, fontSize: 13, lineHeight: 19 }}>{tr("gate.hint")}</Text>
        </View>

        <Pressable onPress={() => router.push("/scan" as never)}
          style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
            backgroundColor: t.accent, borderRadius: 14, paddingVertical: 14 }}>
          <Ionicons name="qr-code-outline" size={18} color="#fff" />
          <Text style={{ color: "#fff", fontSize: 15, fontWeight: "600" }}>{tr("settings.more.scanQr")}</Text>
        </Pressable>

        <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("settings.more.orPaste")}</Text>
        <TextInput value={pair} onChangeText={setPair} autoCapitalize="none" multiline
          placeholder={tr("settings.more.pairPh")} placeholderTextColor={t.txtPlaceholder}
          style={[field, { minHeight: 60 }]} />
        <Pressable onPress={doPair} disabled={busy || !pair.trim()}
          style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
            backgroundColor: busy ? t.surface2 : t.surface1, borderWidth: 1, borderColor: t.borderSubtle,
            borderRadius: 14, paddingVertical: 13, opacity: !pair.trim() ? 0.6 : 1 }}>
          {busy ? <ActivityIndicator color={t.txtSecondary} /> : null}
          <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{tr("settings.more.pairBtn")}</Text>
        </Pressable>
        {msg ? <Text style={{ color: kind === "ok" ? t.ok : kind === "info" ? t.txtSecondary : t.danger, fontSize: 12 }}>{msg}</Text> : null}

        <View style={{ height: 1, backgroundColor: t.borderSubtle, marginVertical: 4 }} />

        <Pressable onPress={() => { enableDemo(); qc.invalidateQueries(); }}
          style={{ alignItems: "center", paddingVertical: 10 }}>
          <Text style={{ color: t.accent, fontSize: 13.5, fontWeight: "600" }}>{tr("demo.cta")}</Text>
        </Pressable>
      </View>
    </View>
  );
}
