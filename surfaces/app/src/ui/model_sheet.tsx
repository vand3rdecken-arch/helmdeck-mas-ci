import { Ionicons } from "@expo/vector-icons";
import type { ReactNode } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";

import { useTheme } from "@/theme";

// THE model picker's look, shared: the chat composer and Settings > General (the
// polish model) open the SAME sheet and the same chip, so a model is chosen the
// same way everywhere (owner: "nicht wieder was komplett anderes"). The composer
// keeps its engine groups / probe state and passes them as `children`; Settings
// passes plain rows.

/** The little pill that opens the sheet (the composer's control-bar button). */
export function ModelChip({ label, active, onPress }: { label: string; active?: boolean; onPress: () => void }) {
  const t = useTheme();
  const c = active ? t.accent : t.txtSecondary;
  return (
    <Pressable onPress={onPress}
      style={{ flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start",
        backgroundColor: active ? t.accent + "26" : t.surface2,
        borderColor: active ? t.accent + "80" : t.borderSubtle, borderWidth: 1,
        borderRadius: 7, paddingHorizontal: 8, paddingVertical: 5 }}>
      <Ionicons name="sparkles-outline" size={13} color={c} />
      <Text style={{ color: c, fontSize: 12 }}>{label}</Text>
    </Pressable>
  );
}

/** The modal shell: dimmed backdrop, centred card, caption, scrolling rows. */
export function ModelSheet({ visible, onClose, title, children }: {
  visible: boolean; onClose: () => void; title: string; children: ReactNode;
}) {
  const t = useTheme();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable onPress={onClose} style={{ flex: 1, backgroundColor: t.backdrop, justifyContent: "center", padding: 24 }}>
        <View style={{ backgroundColor: t.surface1, borderRadius: 14, borderWidth: 1, borderColor: t.glassBorder,
          maxHeight: "70%", overflow: "hidden" }}>
          <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", padding: 12 }}>{title}</Text>
          <ScrollView>{children}</ScrollView>
        </View>
      </Pressable>
    </Modal>
  );
}

/** One radio row. `trailing` is for state the row owner knows (untested, testing...). */
export function ModelRow({ label, desc, selected, disabled, onPress, trailing }: {
  label: string; desc?: string; selected: boolean; disabled?: boolean; onPress: () => void; trailing?: ReactNode;
}) {
  const t = useTheme();
  return (
    <Pressable disabled={disabled} onPress={onPress}
      style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 14, paddingVertical: 11,
        borderTopWidth: 1, borderTopColor: t.borderSubtle, opacity: disabled ? 0.45 : 1 }}>
      <Ionicons name={selected ? "radio-button-on" : "radio-button-off"} size={16} color={selected ? t.accent : t.txtTertiary} />
      <View style={{ flex: 1 }}>
        <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{label}</Text>
        {desc ? <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{desc}</Text> : null}
      </View>
      {trailing}
    </Pressable>
  );
}
