import React from "react";
import { Alert, Platform, Pressable, Text, TextInput, View, type TextStyle, type ViewStyle } from "react-native";

import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { hasPromptHost, openPrompt } from "@/ui/prompt_host";

export const isWeb = Platform.OS === "web";

/** Shared dark text-input styling, matching the existing settings screens. */
export function fieldStyle(t: ThemeTokens): TextStyle {
  return { color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle,
    borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 14 };
}

/** A small tertiary caption above an input. */
export function Caption({ text }: { text: string }) {
  const t = useTheme();
  return <Text style={{ color: t.txtTertiary, fontSize: 12, marginBottom: 4 }}>{text}</Text>;
}

export function Hint({ text }: { text: string }) {
  const t = useTheme();
  return <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16, marginBottom: 6 }}>{text}</Text>;
}

/** Filled primary action button. */
export function Btn({ label, onPress, kind = "primary", disabled }:
  { label: string; onPress: () => void; kind?: "primary" | "ghost" | "danger"; disabled?: boolean }) {
  const t = useTheme();
  const bg = kind === "primary" ? t.accent : "transparent";
  const border = kind === "danger" ? t.danger : kind === "ghost" ? t.borderStrong : t.accent;
  const fg = kind === "primary" ? "#fff" : kind === "danger" ? t.danger : t.accent;
  return (
    <Pressable onPress={disabled ? undefined : onPress} style={{ opacity: disabled ? 0.5 : 1,
      backgroundColor: bg, borderColor: border, borderWidth: kind === "primary" ? 0 : 1,
      borderRadius: 8, paddingVertical: 10, paddingHorizontal: 14, alignItems: "center" }}>
      <Text style={{ color: fg, fontWeight: "600", fontSize: 13.5 }}>{label}</Text>
    </Pressable>
  );
}

/** Checkbox-style boolean row. */
export function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  const t = useTheme();
  return (
    <Pressable onPress={() => onChange(!value)}
      style={{ flexDirection: "row", alignItems: "center", gap: 9, paddingVertical: 6 }}>
      <View style={{ width: 20, height: 20, borderRadius: 5, borderWidth: 1.5,
        borderColor: value ? t.accent : t.borderStrong, backgroundColor: value ? t.accent : "transparent",
        alignItems: "center", justifyContent: "center" }}>
        {value ? <Text style={{ color: "#fff", fontSize: 13, fontWeight: "700", lineHeight: 15 }}>✓</Text> : null}
      </View>
      <Text style={{ color: t.txtPrimary, fontSize: 13, flex: 1 }}>{label}</Text>
    </Pressable>
  );
}

/** A row of selectable pills; multi-select toggles, single-select replaces. */
export function ChipPick({ options, selected, onToggle, single }:
  { options: readonly string[]; selected: string[]; onToggle: (v: string) => void; single?: boolean }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
      {options.map((o) => {
        const on = single ? selected[0] === o : selected.includes(o);
        return (
          <Pressable key={o} onPress={() => onToggle(o)}
            style={{ backgroundColor: on ? t.accent + "29" : t.surface2, borderColor: on ? t.accent + "80" : t.borderSubtle,
              borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 }}>
            <Text style={{ color: on ? t.accent : t.txtSecondary, fontSize: 12.5, fontWeight: on ? "600" : "500" }}>{o}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Two-column form grid on wide (desktop-web) layouts, stacked otherwise. */
export function FormGrid({ children, wide, style }: { children: React.ReactNode; wide?: boolean; style?: ViewStyle }) {
  const kids = React.Children.toArray(children);
  if (!wide) return <View style={[{ gap: 10 }, style]}>{kids}</View>;
  const left: React.ReactNode[] = [], right: React.ReactNode[] = [];
  kids.forEach((c, i) => (i % 2 === 0 ? left : right).push(c));
  return (
    <View style={[{ flexDirection: "row", gap: 16 }, style]}>
      <View style={{ flex: 1, gap: 10 }}>{left}</View>
      <View style={{ flex: 1, gap: 10 }}>{right}</View>
    </View>
  );
}

// Cross-platform text prompt: web uses window.prompt, iOS uses Alert.prompt,
// Android has no native single-field prompt so callers must fall back to inline
// inputs (returns null -> handled by the caller).
export function promptText(title: string, def = ""): Promise<string | null> {
  if (isWeb && typeof window !== "undefined" && window.prompt) return Promise.resolve(window.prompt(title, def));
  // Native: use the modal PromptHost mounted at the app root. This covers
  // Android, which has no native Alert.prompt. iOS keeps Alert.prompt as a
  // fallback only if the host somehow isn't mounted.
  if (hasPromptHost()) return openPrompt(title, def);
  return new Promise((resolve) => {
    const A = Alert as unknown as { prompt?: (t: string, m: string | undefined, cbs: unknown, type?: string, d?: string) => void };
    if (Platform.OS === "ios" && A.prompt) {
      A.prompt(title, undefined, [
        { text: "Abbrechen", style: "cancel", onPress: () => resolve(null) },
        { text: "OK", onPress: (v?: string) => resolve(v ?? null) },
      ], "plain-text", def);
    } else resolve(null);
  });
}

export function confirmAsync(title: string, msg: string): Promise<boolean> {
  if (isWeb && typeof window !== "undefined" && window.confirm) return Promise.resolve(window.confirm(`${title}\n\n${msg}`));
  return new Promise((resolve) => {
    Alert.alert(title, msg, [
      { text: "Abbrechen", style: "cancel", onPress: () => resolve(false) },
      { text: "OK", style: "destructive", onPress: () => resolve(true) },
    ]);
  });
}

export { TextInput };
