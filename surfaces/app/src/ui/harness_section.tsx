import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { api, type HarnessDocument, type HarnessHook, type HarnessPreview } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Panel, SectionLabel } from "@/ui/kit";
import { Btn, Caption } from "@/ui/settings_sections";

const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }) as string;

// Flags whose VALUE is a secret-ish or huge blob we render as a chip rather than
// inline. The daemon already replaces the system prompt with "<brief>", so this
// is only about keeping the argv readable on a phone.
const VALUE_FLAGS = new Set(["--permission-mode", "--append-system-prompt", "--setting-sources",
  "--settings", "--model", "--resume", "--allowedTools", "--output-format", "--input-format"]);

/** The resolved argv, one flag per line. A wrapped single-line command string is
 *  unreadable at phone width and hides exactly the flag you are looking for. */
function Argv({ argv, t }: { argv: string[]; t: ThemeTokens }) {
  const lines = useMemo(() => {
    const out: { flag: string; value: string }[] = [];
    for (let i = 0; i < argv.length; i++) {
      const a = argv[i];
      if (i === 0) { out.push({ flag: a, value: "" }); continue; }
      if (a.startsWith("--") && VALUE_FLAGS.has(a) && i + 1 < argv.length && !argv[i + 1].startsWith("--")) {
        out.push({ flag: a, value: argv[++i] });
      } else out.push({ flag: a, value: "" });
    }
    return out;
  }, [argv]);
  return (
    <View style={{ backgroundColor: t.canvas, borderColor: t.borderSubtle, borderWidth: 1,
      borderRadius: 10, padding: 10, gap: 2 }}>
      {lines.map((l, i) => (
        <View key={i} style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "baseline", gap: 6 }}>
          <Text style={{ fontFamily: MONO, fontSize: 11.5, lineHeight: 17,
            color: i === 0 ? t.txtTertiary : t.accent, fontWeight: i === 0 ? "400" : "700" }}>
            {l.flag}
          </Text>
          {l.value ? (
            <Text selectable style={{ fontFamily: MONO, fontSize: 11.5, lineHeight: 17,
              color: t.txtSecondary, flexShrink: 1 }}>{l.value}</Text>
          ) : null}
        </View>
      ))}
    </View>
  );
}

/** One settings layer: included or excluded, and WHY. The excluded rows are the
 *  informative ones — "the operator's personal config exists and is dropped" is
 *  a different fact from "there is no such file". */
function LayerRow({ l, t }: { l: HarnessPreview["layers"][number]; t: ThemeTokens }) {
  const on = l.included;
  const color = on ? t.ok : t.txtTertiary;
  return (
    <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 8, paddingVertical: 5 }}>
      <Ionicons name={on ? "checkmark-circle" : "close-circle-outline"} size={15} color={color}
        style={{ marginTop: 1 }} />
      <View style={{ flex: 1 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "700" }}>{l.layer}</Text>
          <Text style={{ color: t.txtTertiary, fontSize: 11, fontFamily: MONO, flexShrink: 1 }}>{l.path}</Text>
          {!l.exists ? (
            <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontStyle: "italic" }}>(nicht vorhanden)</Text>
          ) : null}
        </View>
        <Text style={{ color: t.txtSecondary, fontSize: 11.5, lineHeight: 16, marginTop: 1 }}>{l.note}</Text>
      </View>
    </View>
  );
}

/** event x matcher x command x origin — the sharpest end of a settings layer.
 *  Excluded hooks are shown struck-through rather than hidden. */
function HookRow({ h, t }: { h: HarnessHook; t: ThemeTokens }) {
  const on = h.included;
  return (
    <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 7, paddingVertical: 5,
      opacity: on ? 1 : 0.55 }}>
      <Ionicons name={on ? "flash" : "flash-off-outline"} size={13}
        color={on ? t.accent2 : t.txtTertiary} style={{ marginTop: 2 }} />
      <View style={{ flex: 1 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <Text style={{ color: on ? t.txtPrimary : t.txtTertiary, fontSize: 12, fontWeight: "700" }}>
            {h.event}
          </Text>
          <Text style={{ color: t.txtTertiary, fontSize: 11, fontFamily: MONO }}>{h.matcher}</Text>
        </View>
        <Text selectable style={{ color: on ? t.txtSecondary : t.txtTertiary, fontSize: 11,
          fontFamily: MONO, lineHeight: 16, marginTop: 1,
          textDecorationLine: on ? "none" : "line-through" }}>
          {h.command}
        </Text>
        <Text style={{ color: t.txtTertiary, fontSize: 10.5, marginTop: 1 }}>{h.origin}</Text>
      </View>
    </View>
  );
}

/** The read-only half: what a spawn on this surface ACTUALLY runs. */
function SpawnPreview({ p, t, tr }: {
  p: HarnessPreview; t: ThemeTokens; tr: (k: string, v?: Record<string, string | number>) => string;
}) {
  const [openHooks, setOpenHooks] = useState(false);
  const excluded = p.hooks.length - p.hooks_active;
  return (
    <View style={{ gap: 10 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        <Ionicons name="terminal-outline" size={14} color={t.txtTertiary} />
        <Text style={{ color: t.txtTertiary, fontSize: 11, flex: 1 }}>
          {tr("harness.builtBy", { fn: p.builder })}
        </Text>
      </View>

      {p.argv_error ? (
        <Text style={{ color: t.danger, fontSize: 12 }}>{p.argv_error}</Text>
      ) : <Argv argv={p.exec ?? p.argv} t={t} />}
      {/* the .cmd -> .exe rewrite is the single most consequential detail of how
          this process starts (the cmd.exe form once ate --resume), so say it */}
      {p.exec_rewritten ? (
        <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 6 }}>
          <Ionicons name="git-compare-outline" size={12} color={t.txtTertiary} style={{ marginTop: 2 }} />
          <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 16, flex: 1 }}>
            {tr("harness.execRewritten", { from: p.argv[0] })}
          </Text>
        </View>
      ) : null}
      {p.note ? (
        <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 16 }}>{p.note}</Text>
      ) : null}

      {/* brief provenance: which file, and the hash of what actually runs */}
      <View style={{ gap: 3 }}>
        <Caption text={tr("harness.briefSource")} />
        <Text selectable style={{ color: t.txtSecondary, fontSize: 11.5, fontFamily: MONO }}>
          {p.brief.source}
        </Text>
        <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontFamily: MONO }}>
          {tr("harness.resolvedHash", {
            n: p.brief.resolved_chars, h: p.brief.resolved_sha256.slice(0, 12),
          })}
        </Text>
        {p.brief.ask_protocol ? (
          <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{tr("harness.askSpliced")}</Text>
        ) : null}
      </View>

      {/* the settings layers */}
      <View>
        <Caption text={tr("harness.layers")} />
        {p.layers.map((l) => <LayerRow key={l.layer} l={l} t={t} />)}
        {p.settings_layer.active ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 5 }}>
            <Ionicons name="checkmark-circle" size={15} color={t.ok} />
            <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "700" }}>explicit</Text>
            <Text style={{ color: t.txtTertiary, fontSize: 11, fontFamily: MONO, flexShrink: 1 }}>
              {p.settings_layer.path}
            </Text>
          </View>
        ) : null}
        {p.settings_layer.note ? (
          <Text style={{ color: t.warn, fontSize: 11.5, lineHeight: 16 }}>{p.settings_layer.note}</Text>
        ) : null}
      </View>

      {/* memory isolation: every surface shares ONE ~/.claude/projects/.../memory
          directory with no git history behind it - unlike everything else on
          this screen, a bad write there is not reversible. Read directly out of
          this surface's own settings file at preview time (harness.py's
          _memory_isolation), so an edit that removes the deny shows up here. */}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Ionicons name={p.memory.denied ? "lock-closed-outline" : "warning-outline"}
          size={14} color={p.memory.denied ? t.txtTertiary : t.danger} />
        <Text style={{ color: t.txtTertiary, fontSize: 11.5, flex: 1 }}>
          {tr("harness.memory")}
        </Text>
        <Text style={{ color: p.memory.denied ? t.ok : t.danger, fontSize: 11, fontWeight: "700" }}>
          {tr(p.memory.denied ? "harness.memoryProtected" : "harness.memoryWritable")}
        </Text>
      </View>
      {!p.memory.denied ? (
        <Text style={{ color: t.danger, fontSize: 11.5, lineHeight: 16 }}>{p.memory.note}</Text>
      ) : null}

      {/* the hook matrix */}
      <Pressable onPress={() => setOpenHooks((v) => !v)}
        style={{ flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: t.surface2,
          borderColor: t.glassBorder, borderWidth: 1, borderRadius: 10, padding: 10 }}>
        <Ionicons name="flash-outline" size={15} color={t.accent2} />
        <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "600", flex: 1 }}>
          {tr("harness.hookMatrix", { on: p.hooks_active, off: excluded })}
        </Text>
        <Ionicons name={openHooks ? "chevron-up" : "chevron-down"} size={15} color={t.txtTertiary} />
      </Pressable>
      {openHooks ? (
        <View style={{ borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 10, padding: 10 }}>
          {(p.hooks_disabled_by?.length ?? 0) > 0 ? (
            <View style={{ flexDirection: "row", gap: 6, marginBottom: 8 }}>
              <Ionicons name="warning-outline" size={14} color={t.warn} style={{ marginTop: 1 }} />
              <Text style={{ color: t.warn, fontSize: 11.5, lineHeight: 16, flex: 1 }}>
                {tr("harness.hooksDisabled", { files: p.hooks_disabled_by!.join(", ") })}
              </Text>
            </View>
          ) : null}
          {p.hooks.length === 0 ? (
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("harness.noHooks")}</Text>
          ) : p.hooks.map((h, i) => <HookRow key={i} h={h} t={t} />)}
        </View>
      ) : null}
    </View>
  );
}

/** A monospace editor over one harness file, with dirty tracking and rollback.
 *  Same discipline as the policy form: the server value is only adopted while
 *  the owner is NOT mid-edit, so a refetch can never eat what he is typing. */
function DocEditor({ kind, name, path, text, versions, onSaved, t, tr }: {
  kind: "agents" | "settings"; name: string; path: string; text: string;
  versions: { id: string; ts: string; actor: string }[];
  onSaved: (d: HarnessDocument) => void;
  t: ThemeTokens; tr: (k: string, v?: Record<string, string | number>) => string;
}) {
  const [val, setVal] = useState(text);
  const [err, setErr] = useState("");
  const [showVers, setShowVers] = useState(false);
  const touched = useRef(false);
  useEffect(() => {
    if (!touched.current) setVal(text);
  }, [text]);

  const save = useMutation({
    mutationFn: (b: { text?: string; restore?: string }) => api.harnessSave({ kind, name, ...b }),
    onSuccess: (r) => {
      setErr(""); touched.current = false; setShowVers(false);
      onSaved(r.document);
      if (Platform.OS !== "web") Alert.alert("", tr("harness.saved", { p: r.path }));
    },
    onError: (e: Error) => setErr(String(e.message)),
  });

  const dirty = val !== text;
  return (
    <View style={{ gap: 8 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <Text style={{ color: t.txtTertiary, fontSize: 11, fontFamily: MONO, flex: 1 }}>{path}</Text>
        {dirty ? (
          <Text style={{ color: t.warn, fontSize: 10.5, fontWeight: "700" }}>{tr("harness.unsaved")}</Text>
        ) : null}
      </View>
      <TextInput
        value={val}
        onChangeText={(x) => { touched.current = true; setVal(x); }}
        multiline
        autoCapitalize="none"
        autoCorrect={false}
        spellCheck={false}
        style={{
          color: t.txtPrimary, backgroundColor: t.canvas, borderColor: dirty ? t.warn : t.borderSubtle,
          borderWidth: 1, borderRadius: 10, padding: 10, fontFamily: MONO, fontSize: 11.5,
          lineHeight: 17, minHeight: 190, textAlignVertical: "top",
        }}
      />
      {err ? (
        <View style={{ flexDirection: "row", gap: 6, backgroundColor: t.surface2, borderColor: t.danger,
          borderWidth: 1, borderRadius: 10, padding: 9 }}>
          <Ionicons name="alert-circle" size={15} color={t.danger} style={{ marginTop: 1 }} />
          <Text style={{ color: t.danger, fontSize: 12, lineHeight: 17, flex: 1 }}>{err}</Text>
        </View>
      ) : null}
      <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
        <View style={{ flex: 1 }}>
          <Btn label={save.isPending ? "…" : tr("harness.save")}
            onPress={() => save.mutate({ text: val })}
            disabled={save.isPending || !dirty} />
        </View>
        {versions.length ? (
          <Pressable onPress={() => setShowVers((v) => !v)} hitSlop={8}
            style={{ flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10,
              paddingVertical: 9, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 10 }}>
            <Ionicons name="time-outline" size={14} color={t.txtSecondary} />
            <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{versions.length}</Text>
          </Pressable>
        ) : null}
      </View>
      {showVers ? (
        <View style={{ borderColor: t.borderSubtle, borderWidth: 1, borderRadius: 10, overflow: "hidden" }}>
          {versions.map((v, i) => (
            <View key={v.id} style={{ flexDirection: "row", alignItems: "center", gap: 8, padding: 9,
              borderTopWidth: i === 0 ? 0 : 1, borderTopColor: t.borderSubtle }}>
              <View style={{ flex: 1 }}>
                <Text style={{ color: t.txtSecondary, fontSize: 11.5 }}>{v.ts}</Text>
                <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{v.actor}</Text>
              </View>
              <Pressable onPress={() => save.mutate({ restore: v.id })} hitSlop={6}
                style={{ paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8,
                  borderColor: t.glassBorder, borderWidth: 1 }}>
                <Text style={{ color: t.accent, fontSize: 11.5, fontWeight: "600" }}>
                  {tr("harness.restore")}
                </Text>
              </Pressable>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

/**
 * The Harness section of the Automatik hub.
 *
 * "Structure is code, parameters are data" — and that boundary is enforced by
 * the DAEMON, not by this screen. Everything editable here goes through
 * POST /harness, which validates against ops/harness/schema/*.schema.json, archives
 * the file it replaces and writes an audit event. The UI showing an editor is a
 * hint; the server rejecting a bad brief is the actual guarantee.
 */
export function HarnessSection() {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const [surface, setSurface] = useState<string>("card");
  const { data, isLoading, error } = useQuery<HarnessDocument>({
    queryKey: ["harness"], queryFn: api.harness, staleTime: 30000,
  });

  const put = (d: HarnessDocument) => qc.setQueryData(["harness"], d);

  if (isLoading) return <Panel><ActivityIndicator color={t.accent} /></Panel>;
  if (error || !data) return null;         // non-owner or unreachable: stay silent

  const sur = data.surfaces.find((s) => s.key === surface) ?? data.surfaces[0];
  const prev = data.previews.find((p) => p.key === sur?.key);
  const agent = data.agents.find((a) => a.name === sur?.agent);
  const setKey = String(agent?.frontmatter?.settings ?? "");
  const setDoc = data.settings.find((s) => s.key === setKey);
  const errs = Object.entries(data.errors ?? {});

  return (
    <Panel>
      <SectionLabel text={tr("harness.section")} />
      <Text style={{ color: t.txtSecondary, fontSize: 12, lineHeight: 17, marginBottom: 10 }}>
        {tr("harness.intro")}
      </Text>

      {errs.length ? (
        <View style={{ backgroundColor: t.surface2, borderColor: t.danger, borderWidth: 1,
          borderRadius: 10, padding: 10, marginBottom: 10, gap: 3 }}>
          <Text style={{ color: t.danger, fontSize: 12, fontWeight: "700" }}>{tr("harness.brokenFiles")}</Text>
          {errs.map(([p, m]) => (
            <Text key={p} style={{ color: t.txtSecondary, fontSize: 11, fontFamily: MONO }}>{p}: {m}</Text>
          ))}
        </View>
      ) : null}

      {/* surface picker */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ gap: 7, paddingBottom: 2 }}>
        {data.surfaces.map((s) => {
          const on = s.key === sur?.key;
          return (
            <Pressable key={s.key} onPress={() => setSurface(s.key)}
              style={{ paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999,
                backgroundColor: on ? t.accent : t.surface2,
                borderColor: on ? t.accent : t.glassBorder, borderWidth: 1 }}>
              <Text style={{ color: on ? "#fff" : t.txtSecondary, fontSize: 12, fontWeight: "600" }}>
                {s.label}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>

      {prev ? (
        <View style={{ gap: 14, marginTop: 12 }}>
          {/* --- the editable brief --- */}
          <View style={{ gap: 6 }}>
            <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "700" }}>
              {tr("harness.brief")}
            </Text>
            <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 16 }}>
              {tr("harness.briefHint")}
            </Text>
            {agent ? (
              <DocEditor kind="agents" name={agent.name} path={agent.path} text={agent.text}
                versions={agent.versions} onSaved={put} t={t} tr={tr} />
            ) : null}
          </View>

          {/* --- the settings layer --- */}
          {setDoc ? (
            <View style={{ gap: 6 }}>
              <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "700" }}>
                {tr("harness.settings")}
              </Text>
              <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 16 }}>
                {tr("harness.settingsHint")}
              </Text>
              <DocEditor kind="settings" name={setDoc.key} path={setDoc.path} text={setDoc.text}
                versions={setDoc.versions} onSaved={put} t={t} tr={tr} />
            </View>
          ) : null}

          {/* --- read-only: what actually runs --- */}
          <View style={{ gap: 6 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Ionicons name="lock-closed" size={13} color={t.txtTertiary} />
              <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "700", flex: 1 }}>
                {tr("harness.preview")}
              </Text>
            </View>
            <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 16 }}>
              {tr("harness.previewHint")}
            </Text>
            <SpawnPreview p={prev} t={t} tr={tr} />
          </View>
        </View>
      ) : null}
    </Panel>
  );
}
