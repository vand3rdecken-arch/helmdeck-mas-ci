import { Ionicons } from "@expo/vector-icons";
import React, { useMemo, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useTheme } from "@/theme";
import type { SteerOpts } from "@/data/client";

export interface SlashCommand { name: string; hint: string; insert: string }
export interface ModeOption { id: string; label: string }

// thinking levels — each maps to a real Claude Code budget keyword server-side
const THINK: { id: string; short: string }[] = [
  { id: "", short: "off" }, { id: "think", short: "think" },
  { id: "think-hard", short: "hard" }, { id: "ultrathink", short: "ultra" },
];

// Card steer composer — ported from the archived web Composer, rebuilt for RN.
// Model picker (from api.models()), thinking-level cycle, agent/permission mode
// cycle, slash-command affordance. Wires into api.steer(id, text, {model,thinking,mode}).
export function Composer({
  onSend, busy, onStop, models, modeOptions, slashCommands, placeholder, seed, bottomInset = 0,
}: {
  onSend: (text: string, opts: SteerOpts) => void | Promise<void>;
  busy?: boolean;
  onStop?: () => void;
  models: string[];
  modeOptions?: ModeOption[];
  slashCommands?: SlashCommand[];
  placeholder?: string;
  seed?: { text: string; key: number };
  bottomInset?: number;
}) {
  const t = useTheme();
  const [text, setText] = useState("");
  const [model, setModel] = useState("auto");
  const [thinking, setThinking] = useState("");
  const [mode, setMode] = useState(modeOptions?.[0]?.id ?? "");
  const [picker, setPicker] = useState(false);
  const [seedKey, setSeedKey] = useState(0);

  // external injection (rewind from transcript)
  if (seed && seed.key !== seedKey) { setSeedKey(seed.key); setText(seed.text); }

  const matches = useMemo(() => {
    if (!slashCommands) return [];
    const m = text.match(/^\/(\S*)$/);
    return m ? slashCommands.filter((c) => c.name.startsWith(m[1].toLowerCase())) : [];
  }, [text, slashCommands]);

  const thinkShort = THINK.find((x) => x.id === thinking)?.short ?? "off";
  const modeLabel = modeOptions?.find((m) => m.id === mode)?.label;
  const modelLabel = model === "auto" ? "Auto" : model.replace("claude-", "").replace(/-\d{8}$/, "");

  function fire() {
    const v = text.trim();
    if (!v || busy) return;
    onSend(v, { model, thinking, ...(modeOptions ? { mode } : {}) });
    setText("");
  }

  const toolBtn = (active: boolean) => ({
    flexDirection: "row" as const, alignItems: "center" as const, gap: 4,
    backgroundColor: active ? t.accent + "26" : t.surface2,
    borderColor: active ? t.accent + "80" : t.borderSubtle, borderWidth: 1,
    borderRadius: 7, paddingHorizontal: 8, paddingVertical: 5,
  });

  return (
    <View style={{ borderTopWidth: 1, borderTopColor: t.glassBorder, paddingBottom: bottomInset }}>
      {/* slash-command popover */}
      {matches.length > 0 ? (
        <View style={{ backgroundColor: t.surface1, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
          {matches.map((c) => (
            <Pressable key={c.name} onPress={() => setText(c.insert)}
              style={{ flexDirection: "row", gap: 8, paddingHorizontal: 12, paddingVertical: 8, alignItems: "baseline" }}>
              <Text style={{ color: t.accent, fontWeight: "700", fontSize: 13 }}>/{c.name}</Text>
              <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{c.hint}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      {/* control bar */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ gap: 6, paddingHorizontal: 8, paddingTop: 8, alignItems: "center" }}>
        <Pressable onPress={() => setPicker(true)} style={toolBtn(model !== "auto")}>
          <Ionicons name="sparkles-outline" size={13} color={model !== "auto" ? t.accent : t.txtSecondary} />
          <Text style={{ color: model !== "auto" ? t.accent : t.txtSecondary, fontSize: 12 }}>{modelLabel}</Text>
        </Pressable>
        <Pressable onPress={() => { const i = THINK.findIndex((x) => x.id === thinking); setThinking(THINK[(i + 1) % THINK.length].id); }}
          style={toolBtn(thinking !== "")}>
          <Ionicons name="bulb-outline" size={13} color={thinking !== "" ? t.accent : t.txtSecondary} />
          <Text style={{ color: thinking !== "" ? t.accent : t.txtSecondary, fontSize: 12 }}>{thinkShort}</Text>
        </Pressable>
        {modeOptions && modeOptions.length > 1 ? (
          <Pressable onPress={() => { const i = modeOptions.findIndex((m) => m.id === mode); setMode(modeOptions[(i + 1) % modeOptions.length].id); }}
            style={toolBtn(true)}>
            <Ionicons name="options-outline" size={13} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 12 }}>{modeLabel}</Text>
          </Pressable>
        ) : null}
      </ScrollView>

      {/* input row */}
      <View style={{ flexDirection: "row", padding: 8, gap: 8, alignItems: "flex-end" }}>
        <TextInput value={text} onChangeText={setText} multiline
          placeholder={placeholder ?? "Nachricht an den Agenten…"} placeholderTextColor={t.txtPlaceholder}
          style={{ flex: 1, color: t.txtPrimary, backgroundColor: t.surface2, borderRadius: 10, padding: 10, maxHeight: 120,
            borderWidth: 1, borderColor: t.borderSubtle }} />
        {busy && onStop ? (
          <Pressable onPress={onStop}
            style={{ backgroundColor: t.danger, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
            <Ionicons name="stop" size={20} color="#fff" />
          </Pressable>
        ) : (
          <Pressable onPress={fire} disabled={busy || !text.trim()}
            style={{ backgroundColor: t.accent, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center", opacity: busy || !text.trim() ? 0.5 : 1 }}>
            {busy ? <ActivityIndicator color="#fff" /> : <Ionicons name="arrow-up" size={22} color="#fff" />}
          </Pressable>
        )}
      </View>

      {/* model picker modal */}
      <Modal visible={picker} transparent animationType="fade" onRequestClose={() => setPicker(false)}>
        <Pressable onPress={() => setPicker(false)} style={{ flex: 1, backgroundColor: t.backdrop, justifyContent: "center", padding: 24 }}>
          <View style={{ backgroundColor: t.surface1, borderRadius: 14, borderWidth: 1, borderColor: t.glassBorder, maxHeight: "70%", overflow: "hidden" }}>
            <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", padding: 12 }}>MODEL</Text>
            <ScrollView>
              {["auto", ...models].map((m) => (
                <Pressable key={m} onPress={() => { setModel(m); setPicker(false); }}
                  style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 14, paddingVertical: 11, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
                  <Ionicons name={m === model ? "radio-button-on" : "radio-button-off"} size={16} color={m === model ? t.accent : t.txtTertiary} />
                  <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{m === "auto" ? "Auto (route by task)" : m}</Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}
