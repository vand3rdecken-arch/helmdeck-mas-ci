import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, Text, TextInput, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";
import { Btn, Caption, ChipPick, fieldStyle, FormGrid, Toggle } from "@/ui/settings_sections";

// One declarative knob from the daemon's config_schema ("policy is data"): the app
// renders it generically and writes it back, so a new knob is one daemon entry, not
// hand-wiring in two screens. The FIXED harness/laws are not here - they live
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

export default function Automation() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { width } = useWindowDimensions();
  const wide = Platform.OS === "web" && width >= 900;
  const field = fieldStyle(t);
  const { data, isLoading, error } = useQuery({ queryKey: ["automation"], queryFn: api.automation });

  const cur = (data?.loop_current as { state: string; action: string }[]) ?? [];
  const curState = cur[0]?.state ?? "";
  const repos = (data?.repos as string[]) ?? [];
  const schema = (data?.config_schema as ConfigItem[]) ?? [];

  // local draft keyed by path; seeded from the schema, saved per group in one patch
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState<string>("");
  useEffect(() => {
    if (schema.length) setDraft(Object.fromEntries(schema.map((i) => [i.path, i.value])));
  }, [data]);   // reseed when the server payload changes

  const set = (path: string, v: unknown) => setDraft((d) => ({ ...d, [path]: v }));

  async function saveGroup(group: "policy" | "night") {
    setBusy(group);
    try {
      // one merged patch for the whole group, then one write
      const patch: Record<string, any> = {};
      for (const it of schema.filter((i) => i.group === group)) {
        const [a, b] = it.path.split(".");
        (patch[a] ??= {})[b] = draft[it.path];
      }
      await api.saveSettings(patch);
      await qc.invalidateQueries({ queryKey: ["automation"] });
      await qc.invalidateQueries({ queryKey: ["loopmap"] });
      await qc.invalidateQueries({ queryKey: ["metrics"] });
    } catch (e) {
      Alert.alert("", String((e as Error).message));
    } finally {
      setBusy("");
    }
  }

  function Control({ it }: { it: ConfigItem }) {
    const v = draft[it.path];
    const label = tr(it.labelKey);
    if (it.control === "toggle")
      return <Toggle label={label} value={!!v} onChange={(x) => set(it.path, x)} />;
    if (it.control === "text" || it.control === "number")
      return (
        <View>
          <Caption text={label} />
          <TextInput value={v == null ? "" : String(v)} style={field}
            keyboardType={it.control === "number" ? "numeric" : "default"}
            autoCapitalize="none" placeholder={it.placeholder} placeholderTextColor={t.txtPlaceholder}
            onChangeText={(x) => set(it.path, it.control === "number" ? (Number(x) || 0) : x)} />
        </View>
      );
    if (it.control === "single")
      return (
        <View>
          <Caption text={label} />
          <ChipPick options={it.options ?? []} selected={[String(v ?? "")]} single onToggle={(x) => set(it.path, x)} />
        </View>
      );
    if (it.control === "multi") {
      const arr = Array.isArray(v) ? (v as string[]) : [];
      return (
        <View>
          <Caption text={label} />
          <ChipPick options={it.options ?? []} selected={arr}
            onToggle={(x) => set(it.path, arr.includes(x) ? arr.filter((y) => y !== x) : [...arr, x])} />
        </View>
      );
    }
    if (it.control === "labels") {
      const obj = (v && typeof v === "object" ? v : {}) as Record<string, string>;
      return (
        <View>
          <Caption text={label} />
          <FormGrid wide={wide}>
            {(it.keys ?? []).map((k) => (
              <View key={k}>
                <Text style={{ color: t.txtTertiary, fontSize: 11, marginBottom: 3 }}>{k}</Text>
                <TextInput value={obj[k] ?? ""} style={field}
                  onChangeText={(x) => set(it.path, { ...obj, [k]: x })} />
              </View>
            ))}
          </FormGrid>
        </View>
      );
    }
    return null;
  }

  const policyItems = schema.filter((i) => i.group === "policy");
  const Gap = () => <View style={{ height: 10 }} />;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", padding: 10, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>{tr("automation.title")}</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 40, width: "100%", maxWidth: wide ? 860 : undefined, alignSelf: "center" }}>
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
                {policyItems.map((it, i) => <View key={it.path}>{i ? <Gap /> : null}<Control it={it} /></View>)}
                <View style={{ height: 12 }} />
                <Btn label={busy === "policy" ? "…" : tr("automation.save")} onPress={() => saveGroup("policy")} disabled={busy === "policy"} />
              </Panel>
            ) : null}

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
