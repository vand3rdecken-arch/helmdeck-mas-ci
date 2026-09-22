// FIRST RUN, FIRST QUESTION: fresh, or take over from another machine?
//
// Owner 2026-09-22: "aus ux sicht würde ich jetzt das archive auf neuen pc
// rüber schieben und einfach neuinstallation". That is the right expectation
// and the product did not meet it - the takeover path existed only as a
// developer ritual (clone, run, restore, point a file at it).
//
// ORDERING IS THE WHOLE POINT and it is why this sits BEFORE the sign-in
// step: the archive carries the OWNER ACCOUNT. Restore after creating an
// account and you have made one, overwritten it with the old one, and are now
// wondering why your password changed. So: restore first, then sign in with
// the credentials you already had.
//
// The route behind this refuses unless the workspace has NO USERS AT ALL - a
// fact about the database, not a UI state - so this screen cannot cause harm
// even if it is reached by accident.
import { useState } from "react";
import { ActivityIndicator, Text, TextInput, View } from "react-native";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Btn, Caption, Hint } from "@/ui/settings_sections";

export function RestoreChoice({ onFresh, onRestored }:
  { onFresh: () => void; onRestored: () => void }) {
  const t = useTheme();
  const tr = useT();
  const [mode, setMode] = useState<"ask" | "path">("ask");
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string[]>([]);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);

  const card = {
    backgroundColor: t.surface1, borderRadius: 16, borderWidth: 1,
    borderColor: t.borderSubtle, padding: 18, gap: 10,
  } as const;

  const check = async () => {
    setBusy(true); setErr([]); setPreview(null);
    try {
      const r = await api.takeoutRestore(path, true);
      if (!r.ok) { setErr(r.problems?.length ? r.problems : [r.error ?? "?"]); }
      else setPreview((r.manifest as Record<string, unknown>) ?? {});
    } catch (e: unknown) {
      setErr([String(e).slice(0, 200)]);
    } finally { setBusy(false); }
  };

  const go = async () => {
    setBusy(true); setErr([]);
    try {
      const r = await api.takeoutRestore(path, false);
      if (!r.ok) setErr(r.problems?.length ? r.problems : [r.error ?? "?"]);
      else onRestored();
    } catch (e: unknown) {
      setErr([String(e).slice(0, 200)]);
    } finally { setBusy(false); }
  };

  if (mode === "ask") {
    return (
      <View style={{ gap: 12 }}>
        <View style={card}>
          <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700" }}>
            {tr("restore.freshTitle")}
          </Text>
          <Caption text={tr("restore.freshSub")} />
          <Btn label={tr("restore.freshBtn")} onPress={onFresh} />
        </View>
        <View style={card}>
          <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700" }}>
            {tr("restore.takeTitle")}
          </Text>
          <Caption text={tr("restore.takeSub")} />
          <Btn label={tr("restore.takeBtn")} kind="ghost"
            onPress={() => setMode("path")} />
        </View>
      </View>
    );
  }

  const counts = ((preview?.parts as Record<string, { tables?: Record<string, number> }>)
    ?.["db.json"]?.tables) ?? {};

  return (
    <View style={card}>
      <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700" }}>
        {tr("restore.takeTitle")}
      </Text>
      <Hint text={tr("restore.pathHint")} />
      <TextInput value={path} onChangeText={setPath} autoCapitalize="none"
        placeholder="D:\\umzug\\helmdeck-takeout-..." placeholderTextColor={t.txtPlaceholder}
        style={{ backgroundColor: t.surface2, color: t.txtPrimary, borderRadius: 10,
          paddingHorizontal: 12, paddingVertical: 10, fontSize: 13 }} />
      {busy ? <ActivityIndicator /> : null}

      {/* The check is a DRY RUN against the same code the real restore uses,
          so what it promises is what will happen. It shows the contents,
          because "131 MB" is not an answer to "are my notes in there". */}
      {preview ? (
        <Text style={{ color: t.ok, fontSize: 12.5 }}>
          {tr("restore.previewOk", {
            notes: counts.memory ?? 0, cards: counts.tracks ?? 0,
            users: counts.users ?? 0,
          })}
        </Text>
      ) : null}
      {err.map((e, i) => (
        <Text key={i} style={{ color: t.danger, fontSize: 12.5 }}>{e}</Text>
      ))}

      <Btn label={tr("restore.checkBtn")} kind="ghost"
        disabled={busy || !path.trim()} onPress={check} />
      {preview ? <Btn label={tr("restore.goBtn")} disabled={busy} onPress={go} /> : null}
      <Btn label={tr("restore.back")} kind="ghost" disabled={busy}
        onPress={() => { setMode("ask"); setErr([]); setPreview(null); }} />
    </View>
  );
}
