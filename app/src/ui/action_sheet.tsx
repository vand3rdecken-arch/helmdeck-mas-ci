import React, { useCallback, useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useTheme } from "@/theme";

// Why this exists: Android's native Alert.alert only reliably renders THREE
// buttons - a 4th (e.g. a "cancel") is silently dropped, which trapped users in
// the board "move" and card menus with no way to dismiss. This bottom sheet has
// no such limit, dismisses on backdrop tap / back button, and always shows an
// explicit Cancel. It also just looks like the rest of the app.

export type SheetOption = { label: string; destructive?: boolean; onPress?: () => void };
export type SheetSpec = { title?: string; message?: string; options: SheetOption[] };

function ActionSheet({ spec, onClose }: { spec: SheetSpec | null; onClose: () => void }) {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const visible = !!spec;
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <Pressable onPress={onClose} style={{ flex: 1, backgroundColor: t.backdrop, justifyContent: "flex-end" }}>
        {/* stop the inner press from bubbling to the backdrop */}
        <Pressable onPress={() => {}} style={{ backgroundColor: t.surface1, borderTopLeftRadius: 18, borderTopRightRadius: 18,
          borderWidth: 1, borderColor: t.glassBorder, paddingTop: 8, paddingBottom: insets.bottom + 8, paddingHorizontal: 8 }}>
          {spec?.title ? (
            <Text numberOfLines={2} style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "700", paddingHorizontal: 12, paddingTop: 8 }}>
              {spec.title}
            </Text>
          ) : null}
          {spec?.message ? (
            <Text style={{ color: t.txtTertiary, fontSize: 12.5, paddingHorizontal: 12, paddingTop: 4, paddingBottom: 4 }}>{spec.message}</Text>
          ) : null}
          <View style={{ height: 6 }} />
          {spec?.options.map((o, i) => (
            <Pressable key={i} onPress={() => { onClose(); o.onPress?.(); }}
              style={({ pressed }) => ({ paddingVertical: 14, paddingHorizontal: 12, borderRadius: 10,
                backgroundColor: pressed ? t.layer2 : "transparent" })}>
              <Text style={{ color: o.destructive ? t.danger : t.txtPrimary, fontSize: 15.5, fontWeight: "500" }}>{o.label}</Text>
            </Pressable>
          ))}
          <View style={{ height: 6 }} />
          <Pressable onPress={onClose}
            style={({ pressed }) => ({ paddingVertical: 14, paddingHorizontal: 12, borderRadius: 10, alignItems: "center",
              backgroundColor: pressed ? t.layer2 : t.surface2 })}>
            <Text style={{ color: t.txtSecondary, fontSize: 15.5, fontWeight: "600" }}>Abbrechen</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/** Controlled action sheet. `show(spec)` opens it; render `node` once at the
 *  root of the screen. Replaces Alert.alert for multi-option menus. */
export function useActionSheet() {
  const [spec, setSpec] = useState<SheetSpec | null>(null);
  const show = useCallback((s: SheetSpec) => setSpec(s), []);
  const node = <ActionSheet spec={spec} onClose={() => setSpec(null)} />;
  return { show, node };
}
