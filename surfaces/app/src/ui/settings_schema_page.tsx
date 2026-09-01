import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Alert, Pressable, Text, TextInput, type TextStyle, View } from "react-native";

import { api } from "@/data/client";
import { saveProfile } from "@/data/profile";
import { type ConfigItem, type Section, nest, placeRows, scopeBadgeKey } from "@/data/settings_schema";
import type { Me } from "@/data/types";
import { useT } from "@/i18n";
import { can } from "@/kernel";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Panel, SectionLabel } from "@/ui/kit";
import { Btn, Caption, ChipPick, fieldStyle, FormGrid, Hint, Toggle } from "@/ui/settings_sections";
import { useResponsive } from "@/ui/responsive";

/**
 * THE GENERIC SettingsPage RENDERER (accounts-boards-prd phase 4).
 *
 * Point C of settings-ia-redesign, finally load-bearing: a door's rows are a
 * SCHEMA FILTER, not a hand-built panel. Every placement decision - which
 * door, which section, that section's heading, basic vs. behind "Erweitert",
 * the scope badge, and which endpoint the Save button posts to - is read off
 * the knob's own metadata (data/settings_schema.ts). Adding a knob, a whole
 * section, or a knob in a door that had none is a daemon-side edit in
 * spine/http/apimeta.py with NO client change. That is this card's acceptance
 * criterion, and it is checked without a browser by
 * src/data/__settings_hub_selftest__.ts.
 *
 * TWO SOURCES, one table. /automation carries the settings.json-backed rows
 * and is owner-only; /me carries the account's own rows and is readable by
 * every role. useSchema() concatenates them, so door 1 works for a `client`
 * (who 403s on /automation) and the renderer never learns there were two.
 */

/** Both halves of the schema, concatenated. A role without settings.read
 *  simply gets the rows it owns - which is the right rendering of "you may
 *  not read workspace policy", rather than an error banner on the one door
 *  that is theirs. */
export function useSchema(): ConfigItem[] {
  const { data: me } = useQuery<Me>({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  // GATED, not merely allowed-to-fail: /automation is settings.read, and a
  // client opening door 1 must not spend a request - and a red console line -
  // learning that again on every mount. Their half of the schema is on /me.
  const { data: auto } = useQuery({ queryKey: ["automation"], queryFn: api.automation,
    staleTime: 30000, retry: false, enabled: can(me, "settings.read") });
  const ws = (auto?.config_schema as ConfigItem[] | undefined) ?? [];
  const mine = (me?.config_schema as ConfigItem[] | undefined) ?? [];
  return [...mine, ...ws];
}

/** A row's silent owner badge. Renders nothing for a scope this bundle does
 *  not know - see scopeBadgeKey: a missing badge is honest, a wrong one lies
 *  about who a change affects. */
export function ScopeBadge({ scope }: { scope: string | undefined }) {
  const t = useTheme();
  const tr = useT();
  const key = scopeBadgeKey(scope);
  if (!key) return null;
  return (
    <View style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 5,
      paddingHorizontal: 5, paddingVertical: 1, backgroundColor: t.surface2 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 9.5, fontWeight: "600" }}>{tr(key)}</Text>
    </View>
  );
}

// Module scope, not component body - see automation.tsx's original incident
// note: a component function redeclared every render loses text-input focus
// after one keystroke, because React treats it as a brand new component type.
function Control({ it, value, onChange, t, tr, field, wide }: {
  it: ConfigItem; value: unknown; onChange: (v: unknown) => void;
  t: ThemeTokens; tr: (k: string, p?: Record<string, string | number>) => string;
  field: TextStyle; wide: boolean;
}) {
  const label = tr(it.labelKey);
  const desc = it.descKey ? tr(it.descKey) : "";
  const optLabel = it.optionLabels
    ? (v: string) => (it.optionLabels?.[v] ? tr(it.optionLabels[v]) : v)
    : undefined;
  if (it.control === "toggle")
    return <View><Toggle label={label} value={!!value} onChange={onChange} />{desc ? <Hint text={desc} /> : null}</View>;
  if (it.control === "text" || it.control === "number")
    return (
      <View>
        <Caption text={label} />
        <TextInput value={value == null ? "" : String(value)} style={field}
          keyboardType={it.control === "number" ? "numeric" : "default"}
          autoCapitalize="none" placeholder={it.placeholder} placeholderTextColor={t.txtPlaceholder}
          onChangeText={(x) => onChange(it.control === "number" ? (Number(x) || 0) : x)} />
        {desc ? <Hint text={desc} /> : null}
      </View>
    );
  if (it.control === "single")
    return (
      <View>
        <Caption text={label} />
        <ChipPick options={it.options ?? []} selected={[String(value ?? "")]} single
          labelFor={optLabel} onToggle={onChange} />
        {desc ? <Hint text={desc} /> : null}
      </View>
    );
  if (it.control === "multi") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <View>
        <Caption text={label} />
        <ChipPick options={it.options ?? []} selected={arr} labelFor={optLabel}
          onToggle={(x) => onChange(arr.includes(x) ? arr.filter((y) => y !== x) : [...arr, x])} />
        {desc ? <Hint text={desc} /> : null}
      </View>
    );
  }
  if (it.control === "labels") {
    const obj = (value && typeof value === "object" ? value : {}) as Record<string, string>;
    return (
      <View>
        <Caption text={label} />
        <FormGrid wide={wide}>
          {(it.keys ?? []).map((k) => (
            <View key={k}>
              <Text style={{ color: t.txtTertiary, fontSize: 11, marginBottom: 3 }}>{k}</Text>
              <TextInput value={obj[k] ?? ""} style={field}
                onChangeText={(x) => onChange({ ...obj, [k]: x })} />
            </View>
          ))}
        </FormGrid>
        {desc ? <Hint text={desc} /> : null}
      </View>
    );
  }
  return null;
}

/** One row: the control plus its owner badge. The badge sits above the
 *  control rather than beside it because a `labels` row is four fields tall
 *  and a right-aligned badge would float next to the wrong one. */
function Row({ it, value, onChange, t, tr, field, wide }: {
  it: ConfigItem; value: unknown; onChange: (v: unknown) => void;
  t: ThemeTokens; tr: (k: string, p?: Record<string, string | number>) => string;
  field: TextStyle; wide: boolean;
}) {
  return (
    <View style={{ gap: 4 }}>
      <View style={{ flexDirection: "row", justifyContent: "flex-end" }}>
        <ScopeBadge scope={it.scope} />
      </View>
      <Control it={it} value={value} onChange={onChange} t={t} tr={tr} field={field} wide={wide} />
    </View>
  );
}

/** Merge a list of per-knob patches into one nested object. Two knobs under
 *  `capacity` must arrive as ONE `capacity` object or the second overwrites
 *  the first - the daemon deep-merges what it receives, but only against what
 *  is already stored, not against a sibling key in the same request body. */
function mergePatch(base: Record<string, unknown>, add: Record<string, unknown>): Record<string, unknown> {
  for (const [k, v] of Object.entries(add)) {
    const cur = base[k];
    if (v && typeof v === "object" && !Array.isArray(v)
        && cur && typeof cur === "object" && !Array.isArray(cur)) {
      base[k] = mergePatch({ ...(cur as Record<string, unknown>) }, v as Record<string, unknown>);
    } else {
      base[k] = v;
    }
  }
  return base;
}

function SchemaSection({ sec }: { sec: Section }) {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const { wide } = useResponsive();
  const field = fieldStyle(t);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  // Which paths the USER has touched since the last save. Server values must
  // keep flowing into the draft (another device writing must re-render this
  // one), but never over a field somebody is mid-way through typing.
  const dirty = useRef<Set<string>>(new Set());

  useEffect(() => {
    setDraft((d) => {
      const next: Record<string, unknown> = {};
      for (const it of sec.items) next[it.path] = dirty.current.has(it.path) && it.path in d ? d[it.path] : it.value;
      return next;
    });
    // Re-seeds when the server values move. `sec` is rebuilt per render, so
    // the dependency is the values themselves, not the object identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(sec.items.map((i) => [i.path, i.value]))]);

  async function commit(patches: Record<string, unknown>[], paths: string[]) {
    let body: Record<string, unknown> = {};
    for (const p of patches) body = mergePatch(body, p);
    if (sec.target === "profile") await saveProfile(body);
    else await api.saveSettings(body);
    for (const p of paths) dirty.current.delete(p);
    await qc.invalidateQueries({ queryKey: ["me"] });
    await qc.invalidateQueries({ queryKey: ["automation"] });
    await qc.invalidateQueries({ queryKey: ["settings"] });
    await qc.invalidateQueries({ queryKey: ["metrics"] });
  }

  // An autosaving row (scope profile) writes on the spot and rolls back on
  // failure, so the chip can never show a value the account does not have.
  async function change(it: ConfigItem, v: unknown) {
    const prev = draft[it.path];
    dirty.current.add(it.path);
    setDraft((d) => ({ ...d, [it.path]: v }));
    if (!sec.autosave) return;
    try {
      await commit([nest(it.path, v)], [it.path]);
    } catch (e) {
      setDraft((d) => ({ ...d, [it.path]: prev }));
      dirty.current.delete(it.path);
      Alert.alert(tr("ui.error"), String((e as Error).message));
    }
  }

  async function save() {
    setBusy(true);
    try {
      await commit(sec.items.map((it) => nest(it.path, draft[it.path])), sec.items.map((it) => it.path));
    } catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
    finally { setBusy(false); }
  }

  const row = (it: ConfigItem, i: number) => (
    <View key={it.path} style={{ marginTop: i ? 12 : 0 }}>
      <Row it={it} value={draft[it.path]} onChange={(v) => void change(it, v)}
        t={t} tr={tr} field={field} wide={wide} />
    </View>
  );

  return (
    <Panel>
      <SectionLabel text={tr(sec.groupKey)} />
      {sec.basic.map(row)}
      {sec.advanced.length ? (
        <View style={{ marginTop: sec.basic.length ? 12 : 0 }}>
          <Pressable onPress={() => setOpen((o) => !o)}
            style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 6 }}>
            <Ionicons name={open ? "chevron-down" : "chevron-forward"} size={14} color={t.txtTertiary} />
            <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>
              {tr("hub.advanced", { n: sec.advanced.length })}
            </Text>
          </Pressable>
          {open ? sec.advanced.map(row) : null}
        </View>
      ) : null}
      {sec.autosave ? null : (
        <>
          <View style={{ height: 12 }} />
          <Btn label={busy ? "…" : tr("automation.save")} onPress={save} disabled={busy} />
        </>
      )}
    </Panel>
  );
}

/** Every schema-driven section of one door. Renders nothing when the door has
 *  no rows, so a door that is entirely hand-built (team, cells) costs nothing
 *  by mounting this - and starts rendering the moment a knob is tagged with
 *  its id, which is the acceptance criterion. */
export function SchemaDoor({ door, schema }: { door: string; schema: ConfigItem[] }) {
  const sections = placeRows(schema, door);
  if (!sections.length) return null;
  return <>{sections.map((s) => <SchemaSection key={s.group} sec={s} />)}</>;
}
