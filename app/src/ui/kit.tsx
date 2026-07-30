import React from "react";
import { StyleSheet, Text, View, type ViewStyle } from "react-native";
import { useTheme } from "@/theme";

/** The desktop chip: 5px rounded rectangle on surface-2, subtle border, neutral
 *  secondary text + optional coloured status dot. */
export function Chip({ text, dot }: { text: string; dot?: string }) {
  const t = useTheme();
  return (
    <View style={[s.chip, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
      {dot ? <Dot color={dot} /> : null}
      <Text style={[s.chipText, { color: t.txtSecondary }]}>{text}</Text>
    </View>
  );
}

export function Dot({ color, size = 7 }: { color: string; size?: number }) {
  return <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: color }} />;
}

export function Panel({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  const t = useTheme();
  return <View style={[s.panel, { backgroundColor: t.surface1, borderColor: t.glassBorder }, style]}>{children}</View>;
}

export function SectionLabel({ text }: { text: string }) {
  const t = useTheme();
  return <Text style={[s.section, { color: t.txtTertiary }]}>{text.toUpperCase()}</Text>;
}

export function KVRow({ k, v, color }: { k: string; v: string; color?: string }) {
  const t = useTheme();
  return (
    <View style={s.kv}>
      <Text style={{ color: t.txtTertiary, fontSize: 12.5, flex: 1 }}>{k}</Text>
      <Text style={{ color: color ?? t.txtPrimary, fontSize: 13, fontWeight: "500" }}>{v}</Text>
    </View>
  );
}

export function Empty({ text }: { text: string }) {
  const t = useTheme();
  return <Text style={{ color: t.txtTertiary, fontSize: 12, paddingVertical: 6 }}>{text}</Text>;
}

// Shared pushed-screen header: back chevron + title. Imported lazily to avoid a
// hard dependency cycle with expo-router in the pure-UI kit.
export function ScreenHeader({ title, onBack }: { title: string; onBack: () => void }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", padding: 10, gap: 8 }}>
      <Text onPress={onBack} style={{ color: t.txtSecondary, fontSize: 24, paddingHorizontal: 4 }}>‹</Text>
      <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>{title}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  chip: { flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1, borderRadius: 5, paddingHorizontal: 7, paddingVertical: 2 },
  chipText: { fontSize: 11, fontWeight: "500" },
  panel: { borderWidth: 1, borderRadius: 14, padding: 14, gap: 4 },
  section: { fontSize: 11, letterSpacing: 0.8, marginBottom: 6 },
  kv: { flexDirection: "row", paddingVertical: 2 },
});
