import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";
import { Caption, ChipPick, fieldStyle } from "@/ui/settings_sections";

// Shape of one entry from claude_sessions.list_sessions (daemon/claude_sessions.py).
type ClaudeSession = { id: string; cwd: string; project: string; first: string; last_active: string };

// Ported from archive/web/components/modal.tsx (EXAMPLES). Tapping a chip seeds
// the task text and, where the web example set one, the driver. Both the chip
// label and the seeded prose are owner-facing, so both live in the dict; the
// driver id is technical and stays as-is.
const EXAMPLES = [
  { key: "bugfix", driver: "claude" },
  { key: "feature", driver: "claude" },
  { key: "desktop", driver: "claude-desktop" },
  { key: "browser", driver: "claude-desktop" },
  { key: "research", driver: "claude" },
] as const;

const PRIORITIES = ["low", "medium", "high"] as const;

export default function NewCard() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const [task, setTask] = useState("");
  const [repo, setRepo] = useState(metrics?.settings?.default_repo ?? "");
  const [priority, setPriority] = useState<string>("medium");
  const [due, setDue] = useState("");
  const [value, setValue] = useState("");
  const [client, setClient] = useState("");
  const [driver, setDriver] = useState("");
  const [busy, setBusy] = useState(false);
  // Adopt-an-existing-Claude-session flow (ported from archive/web modal). The
  // list is only fetched once the section is opened; picking a session flips the
  // submit action from "create card" to "continue session".
  const [showSess, setShowSess] = useState(false);
  const [adoptId, setAdoptId] = useState<string | null>(null);
  const [adoptCwd, setAdoptCwd] = useState("");
  const { data: sessions, isLoading: sessLoading } = useQuery<ClaudeSession[]>({
    queryKey: ["claude-sessions"], queryFn: api.claudeSessions, enabled: showSess,
  });

  const field = fieldStyle(t);
  // The app already knows the configured drivers via metrics.settings.drivers
  // (same source the web modal uses). Selector when present, text input otherwise.
  const drivers = Object.keys(metrics?.settings?.drivers ?? {});

  async function file() {
    setBusy(true);
    try {
      // A picked session -> adopt it as a card (mode "continue"), with any typed
      // text carried as the first steer. Same one button either way.
      if (adoptId) {
        const res = await api.adoptClaude({
          session_id: adoptId, cwd: adoptCwd, mode: "continue", first: task.trim(),
        });
        if (res?.error) { Alert.alert(tr("new.rejected"), res.error); return; }
        await qc.invalidateQueries({ queryKey: ["tracks"] });
        router.back();
        return;
      }
      if (!task.trim()) return;
      const body: Record<string, unknown> = {
        task: task.trim(), repo: repo.trim(), lane: "backlog", priority,
      };
      if (due.trim()) body.due = due.trim();
      if (value.trim()) body.value = parseFloat(value);
      if (client.trim()) body.client = client.trim();
      if (driver.trim()) body.driver = driver.trim();
      // The daemon can reject with a 200-body {error} (bad repo, WIP limit…),
      // so inspect it rather than assuming success.
      const res = await api.newTrack(body) as { error?: string };
      if (res?.error) { Alert.alert(tr("new.rejected"), res.error); return; }
      await qc.invalidateQueries({ queryKey: ["tracks"] });
      router.back();
    } catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
    finally { setBusy(false); }
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <Text style={{ color: t.txtPrimary, fontSize: 20, fontWeight: "700", padding: 16 }}>{tr("new.title")}</Text>
      <ScrollView contentContainerStyle={{ padding: 12, gap: 10 }}>
        <Panel>
          <Caption text={tr("new.examples")} />
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
            {EXAMPLES.map((ex) => (
              <Pressable key={ex.key} onPress={() => { setTask(tr(`new.ex.${ex.key}Task`)); setDriver(ex.driver); }}
                style={{ backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1,
                  borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 }}>
                <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "500" }}>{tr(`new.ex.${ex.key}`)}</Text>
              </Pressable>
            ))}
          </View>
          <Pressable onPress={() => setShowSess((v) => !v)}
            style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: showSess ? 8 : 4 }}>
            <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{showSess ? "▾" : "▸"}</Text>
            <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "500" }}>{tr("new.adoptSession")}</Text>
          </Pressable>
          {showSess && (
            <View style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 10, marginBottom: 10, overflow: "hidden" }}>
              {sessLoading && <Text style={{ color: t.txtTertiary, fontSize: 12, padding: 10 }}>{tr("new.readingSessions")}</Text>}
              {!sessLoading && (sessions?.length ?? 0) === 0 && (
                <Text style={{ color: t.txtTertiary, fontSize: 12, padding: 10 }}>{tr("new.noSessions")}</Text>
              )}
              {sessions?.map((s) => {
                const sel = s.id === adoptId;
                return (
                  <Pressable key={s.id}
                    onPress={() => { setAdoptId(sel ? null : s.id); setAdoptCwd(sel ? "" : s.cwd); }}
                    style={{ padding: 10, borderBottomWidth: 1, borderBottomColor: t.glassBorder,
                      borderLeftWidth: 2, borderLeftColor: sel ? t.accent : "transparent",
                      backgroundColor: sel ? t.surface2 : "transparent" }}>
                    <View style={{ flexDirection: "row", gap: 8, alignItems: "baseline" }}>
                      <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "600" }} numberOfLines={1}>{s.project || tr("new.session")}</Text>
                      <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{s.last_active}</Text>
                    </View>
                    <Text style={{ color: t.txtSecondary, fontSize: 11.5 }} numberOfLines={1}>{s.first || tr("new.noText")}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
          <SectionLabel text={tr(adoptId ? "new.firstInstruction" : "new.taskLabel")} />
          <TextInput value={task} onChangeText={setTask} multiline placeholder={tr("new.taskPlaceholder")}
            placeholderTextColor={t.txtPlaceholder} style={[field, { minHeight: 90 }]} />
          <View style={{ height: 10 }} />
          <SectionLabel text={tr("new.repo")} />
          <TextInput value={repo} onChangeText={setRepo} autoCapitalize="none" placeholder={tr("new.repoPlaceholder")}
            placeholderTextColor={t.txtPlaceholder} style={field} />
        </Panel>
        <Panel>
          <Caption text={tr("new.priority")} />
          <View style={{ marginBottom: 10 }}>
            <ChipPick options={PRIORITIES} selected={[priority]} onToggle={setPriority} single />
          </View>
          <Caption text={tr("new.due")} />
          <TextInput value={due} onChangeText={setDue} autoCapitalize="none" placeholder="2026-07-31"
            placeholderTextColor={t.txtPlaceholder} style={field} />
          <View style={{ height: 10 }} />
          <View style={{ flexDirection: "row", gap: 10 }}>
            <View style={{ flex: 1 }}>
              <Caption text={tr("new.value")} />
              <TextInput value={value} onChangeText={setValue} keyboardType="numeric" placeholder="50"
                placeholderTextColor={t.txtPlaceholder} style={field} />
            </View>
            <View style={{ flex: 1 }}>
              <Caption text={tr("new.client")} />
              <TextInput value={client} onChangeText={setClient} placeholder={tr("new.clientPlaceholder")}
                placeholderTextColor={t.txtPlaceholder} style={field} />
            </View>
          </View>
          <View style={{ height: 10 }} />
          <Caption text={tr("new.driver")} />
          {drivers.length > 0 ? (
            <ChipPick options={drivers} selected={[driver]} onToggle={setDriver} single />
          ) : (
            <TextInput value={driver} onChangeText={setDriver} autoCapitalize="none" placeholder="claude"
              placeholderTextColor={t.txtPlaceholder} style={field} />
          )}
        </Panel>
        <View style={{ flexDirection: "row", gap: 10 }}>
          <Pressable onPress={() => router.back()} style={{ flex: 1, borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, padding: 12, alignItems: "center" }}>
            <Text style={{ color: t.txtSecondary }}>{tr("ui.cancel")}</Text>
          </Pressable>
          <Pressable onPress={file} disabled={busy || (!adoptId && !task.trim())} style={{ flex: 1, backgroundColor: t.accent, borderRadius: 8, padding: 12, alignItems: "center", opacity: busy || (!adoptId && !task.trim()) ? 0.5 : 1 }}>
            <Text style={{ color: "#fff", fontWeight: "600" }}>{tr(adoptId ? "new.adopt" : "ui.create")}</Text>
          </Pressable>
        </View>
      </ScrollView>
    </View>
  );
}
