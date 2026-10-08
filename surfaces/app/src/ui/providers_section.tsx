// Provider keys - "Zugänge". The account's OWN API key per provider, the one
// place a key is typed in (never settings.json, never an env text block).
//
// What the daemon guarantees, so this screen can stay dumb: GET /me/providers
// answers set / last 4 characters / last real test and NEVER the key; PUT stores
// it encrypted per account (spine/storage/usersecrets.py); owner and operator
// only. So the field here is write-only - after saving it clears and the row
// shows "gesetzt ...WXYZ" - and "Testen" sends ONE real request with that key
// (a key that is merely stored proves nothing).
//
// Row shape is the Engines list's (EnginesSection): chevron, name, status dot +
// label, the last test as a second line; tap to expand the key field + buttons.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";

import { api } from "@/data/client";
import type { ProviderEntry, ProvidersView } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { SectionLabel } from "@/ui/kit";
import { Btn, fieldStyle, Hint } from "@/ui/settings_sections";

const QUERY = ["me-providers"];

function testLine(p: ProviderEntry, tr: (k: string) => string): { tone: "ok" | "err" | "muted"; text: string } | null {
  const x = p.test;
  if (!x) return null;
  if (x.status === "running") return { tone: "muted", text: tr("prov.testing") };
  const secs = x.ms ? ` · ${(x.ms / 1000).toFixed(1)} s` : "";
  const model = x.model ? ` · ${x.model.split("/").pop()}` : "";
  if (x.ok) return { tone: "ok", text: `${tr("prov.t.ok")}${model}${secs}` };
  const label = tr(`prov.t.${x.status}`);
  return { tone: "err", text: `${label}${x.reason && x.status === "error" ? ": " + x.reason : ""}${model}` };
}

function ProviderRow({ p, view, onView }: { p: ProviderEntry; view: ProvidersView; onView: (v: ProvidersView) => void }) {
  const t = useTheme();
  const tr = useT();
  const field = fieldStyle(t);
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "test" | "delete">("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const free = p.id === "opencode";               // the Zen gateway's free models need no key
  const tl = testLine(p, tr);
  const running = p.test?.status === "running";
  const canTest = view.can_store && (p.set || free);

  // api.* THROWS a TransportError when the daemon cannot be reached - unhandled
  // it surfaced as an uncaught error overlay, so every call lands in `run`.
  async function run<T extends { error?: string }>(kind: "save" | "test" | "delete", call: () => Promise<T>, done: (r: T) => void) {
    setBusy(kind); setErr(""); setMsg("");
    try {
      const r = await call();
      if (r?.error) setErr(r.error); else done(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }
  const save = () => run("save", () => api.setProvider(p.id, key.trim()),
    (r) => { setKey(""); setMsg(tr("prov.saved")); onView(r); });
  const remove = () => run("delete", () => api.deleteProvider(p.id),
    (r) => { setMsg(tr("prov.deleted")); onView(r); });
  // The test is a BACKGROUND job on the daemon (a real request takes 10-80s):
  // this call only starts it. The result arrives on the row through the
  // daemon's event stream, which reloads ["me-providers"] - nothing polls.
  const test = () => run("test", () => api.testProvider(p.id), (r) => onView(r));

  const dot = p.set ? t.ok : free ? t.accent : t.txtTertiary;
  return (
    <View>
      <Pressable onPress={() => setOpen(!open)} accessibilityRole="button"
        style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10,
          borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
        <Text style={{ color: t.txtTertiary, fontSize: 12, width: 10 }}>{open ? "▾" : "▸"}</Text>
        <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{p.label}</Text>
            <Text style={{ color: t.txtTertiary }}>·</Text>
            <View style={{ width: 7, height: 7, borderRadius: 3.5, backgroundColor: dot }} />
            <Text style={{ color: t.txtSecondary, fontSize: 12 }}>
              {p.set ? `${tr("prov.set")} ${p.hint}` : free ? tr("prov.free") : tr("prov.unset")}
            </Text>
          </View>
          {tl ? <Text numberOfLines={2} style={{ color: tl.tone === "ok" ? t.ok : tl.tone === "muted" ? t.txtTertiary : t.danger, fontSize: 11.5 }}>{tl.text}</Text> : null}
        </View>
      </Pressable>
      {open ? (
        <View style={{ paddingLeft: 20, paddingBottom: 12, gap: 8 }}>
          {view.can_store && view.encrypted ? (
            <>
              <TextInput value={key} onChangeText={setKey} secureTextEntry autoCapitalize="none" autoCorrect={false}
                spellCheck={false} placeholder={p.set ? tr("prov.replace") : tr("prov.field")}
                placeholderTextColor={t.txtPlaceholder} style={field} />
              <Hint text={tr("prov.env").replace("{env}", p.env)} />
              {free ? <Hint text={tr("prov.freeHint")} /> : null}
            </>
          ) : (
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>
              {view.can_store ? tr("prov.noCrypto") : tr("prov.noRole")}
            </Text>
          )}
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            {view.can_store && view.encrypted ? (
              <Btn label={tr("prov.save")} onPress={() => { void save(); }} disabled={!key.trim() || busy !== ""} />
            ) : null}
            {canTest ? (
              <Btn kind="ghost" label={running ? tr("prov.testing") : tr("prov.test")}
                onPress={() => { void test(); }} disabled={busy !== "" || running} />
            ) : null}
            {p.set && view.can_store ? (
              <Btn kind="danger" label={tr("prov.delete")} onPress={() => { void remove(); }} disabled={busy !== ""} />
            ) : null}
            {running ? <ActivityIndicator color={t.accent} /> : null}
          </View>
          {err ? <Text style={{ color: t.danger, fontSize: 12 }}>{err}</Text> : null}
          {msg ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{msg}</Text> : null}
        </View>
      ) : null}
    </View>
  );
}

export function ProvidersSection() {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: QUERY, queryFn: () => api.providers(), staleTime: 30_000 });

  function onView(v: ProvidersView) {
    if (!v?.providers) return;
    qc.setQueryData(QUERY, { providers: v.providers, can_store: v.can_store, encrypted: v.encrypted });
    // a new key connects new models: the engine/model pickers re-read their catalog
    void qc.invalidateQueries({ queryKey: ["engines"] });
    void qc.invalidateQueries({ queryKey: ["models"] });
  }

  return (
    <View>
      <SectionLabel text={tr("prov.title")} />
      <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 6 }}>{tr("prov.hint")}</Text>
      {isLoading || !data ? <ActivityIndicator /> : data.providers.map((p) => (
        <ProviderRow key={p.id} p={p} view={data} onView={onView} />
      ))}
    </View>
  );
}
