import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, Text, TextInput, type TextStyle, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { HarnessSection } from "@/ui/harness_section";
import { Panel, SectionLabel } from "@/ui/kit";
import { Btn, Caption, ChipPick, fieldStyle, FormGrid, Toggle } from "@/ui/settings_sections";

// One declarative knob from the daemon's config_schema ("policy is data"): the app
// renders it generically and writes it back, so a new knob is one daemon entry, not
// hand-wiring in two screens. The FIXED ops/harness/laws are not here - they live
// read-only in the Loop-Map (linked below).
type Ctl = "toggle" | "multi" | "single" | "text" | "number" | "labels";
interface ConfigItem {
  group: "policy" | "night";
  path: string;                 // e.g. "policy.auto_accept_green" (always 2 levels)
  control: Ctl;
  labelKey: string;
  value: unknown;
  options?: string[];
  keys?: string[];
  placeholder?: string;
}

// path "a.b" -> {a:{b:value}} — saveSettings deep-merges, so writing one field
// leaves the rest of that section intact.
function nest(path: string, value: unknown): Record<string, unknown> {
  const [a, b] = path.split(".");
  return { [a]: { [b]: value } };
}

// MODULE SCOPE, NOT INSIDE THE SCREEN. This was declared in the component body,
// which meant a NEW function identity on every render: React saw a different
// component type each keystroke, unmounted the old tree and mounted a fresh one,
// and the TextInput lost focus after exactly one character. Every text knob on
// this screen (night window, lane labels) was effectively unusable. Declaring it
// once keeps the element type stable, so the input keeps its focus and cursor.
function Control({ it, value, onChange, t, tr, field, wide }: {
  it: ConfigItem; value: unknown; onChange: (v: unknown) => void;
  t: ThemeTokens; tr: (k: string, p?: Record<string, string | number>) => string;
  field: TextStyle; wide: boolean;
}) {
  const label = tr(it.labelKey);
  if (it.control === "toggle")
    return <Toggle label={label} value={!!value} onChange={onChange} />;
  if (it.control === "text" || it.control === "number")
    return (
      <View>
        <Caption text={label} />
        <TextInput value={value == null ? "" : String(value)} style={field}
          keyboardType={it.control === "number" ? "numeric" : "default"}
          autoCapitalize="none" placeholder={it.placeholder} placeholderTextColor={t.txtPlaceholder}
          onChangeText={(x) => onChange(it.control === "number" ? (Number(x) || 0) : x)} />
      </View>
    );
  if (it.control === "single")
    return (
      <View>
        <Caption text={label} />
        <ChipPick options={it.options ?? []} selected={[String(value ?? "")]} single onToggle={onChange} />
      </View>
    );
  if (it.control === "multi") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <View>
        <Caption text={label} />
        <ChipPick options={it.options ?? []} selected={arr}
          onToggle={(x) => onChange(arr.includes(x) ? arr.filter((y) => y !== x) : [...arr, x])} />
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
      </View>
    );
  }
  return null;
}

export default function Automation() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { width } = useWindowDimensions();
  const wide = Platform.OS === "web" && width >= 900;
  const field = fieldStyle(t);
  // staleTime: this screen is a FORM. Without it react-query treats the data as
  // immediately stale and refetches on every remount/focus, which is exactly the
  // background refetch that used to clobber the draft (see `dirty` below).
  const { data, isLoading, error } = useQuery({
    queryKey: ["automation"], queryFn: api.automation, staleTime: 30000,
  });

  const cur = (data?.loop_current as { state: string; action: string }[]) ?? [];
  const curState = cur[0]?.state ?? "";
  const repos = (data?.repos as string[]) ?? [];
  const schema = (data?.config_schema as ConfigItem[]) ?? [];

  // local draft keyed by path; seeded from the schema, saved per group in one patch
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState<string>("");
  // Paths the owner has typed into but not yet saved. THE POINT: this effect
  // used to overwrite the whole draft on every `data` change, and the query had
  // no staleTime — so any background refetch (a window focus, a sibling
  // invalidate, a remount) silently reverted whatever was being typed, with no
  // error and no sign anything had happened. Now the server value is only
  // adopted for paths that are NOT dirty: an untouched knob still tracks the
  // daemon, an in-flight edit is never wiped from under the owner.
  const dirty = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!schema.length) return;
    setDraft((d) => {
      const next: Record<string, unknown> = {};
      for (const it of schema) {
        next[it.path] = dirty.current.has(it.path) && it.path in d ? d[it.path] : it.value;
      }
      return next;
    });
  }, [data, schema]);

  const set = (path: string, v: unknown) => {
    dirty.current.add(path);
    setDraft((d) => ({ ...d, [path]: v }));
  };

  async function saveGroup(group: "policy" | "night") {
    setBusy(group);
    try {
      // one merged patch for the whole group, then one write
      const patch: Record<string, any> = {};
      const saved = schema.filter((i) => i.group === group);
      for (const it of saved) {
        const [a, b] = it.path.split(".");
        (patch[a] ??= {})[b] = draft[it.path];
      }
      await api.saveSettings(patch);
      // these are now the server's values, so let them track it again
      for (const it of saved) dirty.current.delete(it.path);
      await qc.invalidateQueries({ queryKey: ["automation"] });
      await qc.invalidateQueries({ queryKey: ["loopmap"] });
      await qc.invalidateQueries({ queryKey: ["metrics"] });
    } catch (e) {
      Alert.alert("", String((e as Error).message));
    } finally {
      setBusy("");
    }
  }

  const policyItems = schema.filter((i) => i.group === "policy");
  const Gap = () => <View style={{ height: 10 }} />;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", padding: 10, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>{tr("automation.title")}</Text>
      </View>
      {/* paddingBottom clears the floating tab bar. 40 was too short — the last
          panel scrolled UNDER the bar and its text showed through, which the
          Harness section made obvious by making the page much longer. 120 is
          what the other tab screens (more, dashboard) already use. */}
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: wide ? 60 : 120, width: "100%", maxWidth: wide ? 860 : undefined, alignSelf: "center" }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>{tr("automation.errorOwner")}</Text> : null}
        {data ? (
          <>
            {/* live loop state + the reference map (no duplicated state list - it
                lives once in the Loop-Map) */}
            <Panel>
              <SectionLabel text="build-loop" />
              <Text style={{ color: t.accent, fontWeight: "600", marginBottom: 2 }}>{curState ? tr("automation.now", { state: curState }) : "?"}</Text>
              {cur[0]?.action ? <Text style={{ color: t.txtSecondary, fontSize: 12, marginBottom: 8 }}>{cur[0].action}</Text> : null}
              <Pressable onPress={() => router.push("/loopmap" as never)}
                style={{ flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: t.surface2,
                  borderColor: t.glassBorder, borderWidth: 1, borderRadius: 12, padding: 11 }}>
                <Ionicons name="git-network-outline" size={16} color={t.accent} />
                <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600", flex: 1 }}>{tr("automation.openMap")}</Text>
                <Ionicons name="chevron-forward" size={16} color={t.txtTertiary} />
              </Pressable>
            </Panel>

            {/* configurable policy - the ONE place, generic controls from the schema */}
            {policyItems.length ? (
              <Panel>
                <SectionLabel text={tr("automation.configPolicy")} />
                {policyItems.map((it, i) => (
                  <View key={it.path}>
                    {i ? <Gap /> : null}
                    <Control it={it} value={draft[it.path]} onChange={(v) => set(it.path, v)}
                      t={t} tr={tr} field={field} wide={wide} />
                  </View>
                ))}
                <View style={{ height: 12 }} />
                <Btn label={busy === "policy" ? "…" : tr("automation.save")} onPress={() => saveGroup("policy")} disabled={busy === "policy"} />
              </Panel>
            ) : null}

            {/* the harness: each surface's brief + settings layer, and the
                read-only proof of what a spawn really runs */}
            <HarnessSection />

            <Panel>
              <SectionLabel text={tr("automation.repos", { n: repos.length })} />
              {repos.length === 0 ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("automation.noRepos")}</Text> :
                repos.map((r) => <Text key={r} style={{ color: t.txtSecondary, fontSize: 11.5 }}>{r}</Text>)}
            </Panel>
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}
