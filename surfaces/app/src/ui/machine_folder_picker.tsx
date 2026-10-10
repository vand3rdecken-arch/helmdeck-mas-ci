import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// A real folder browser for the machine HelmDeck runs on (GET /projects/browse:
// sub-folder names only, owner only). Tap a folder to go in, "up" or a drive to
// go out, "use this folder" to pick the one you are looking at. It returns a
// path and nothing else - what happens with it is the caller's business.
export function MachineFolderPicker({ visible, onClose, onPick }: {
  visible: boolean; onClose: () => void; onPick: (path: string) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const [path, setPath] = useState("");          // "" = the daemon's start folder (home)
  const { data, isFetching } = useQuery({
    queryKey: ["projectBrowse", path], queryFn: () => api.projectBrowse(path), enabled: visible, retry: false,
    staleTime: 5000,
  });
  const join = (base: string, name: string) => base.replace(/[\\/]+$/, "") + (base.includes("\\") ? "\\" : "/") + name;

  const row = (key: string, icon: React.ComponentProps<typeof Ionicons>["name"], label: string, onPress: () => void, tint?: string) => (
    <Pressable key={key} onPress={onPress}
      style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 14, paddingVertical: 12,
        borderBottomWidth: 1, borderBottomColor: t.borderSubtle }}>
      <Ionicons name={icon} size={18} color={tint ?? t.accent} />
      <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 15, flex: 1 }}>{label}</Text>
      <Ionicons name="chevron-forward" size={14} color={t.txtTertiary} />
    </Pressable>
  );

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top, paddingBottom: insets.bottom }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10, padding: 14 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 17, fontWeight: "700", flex: 1 }}>{tr("rooms.pickTitle")}</Text>
          <Pressable onPress={onClose} accessibilityLabel={tr("rooms.pickClose")} hitSlop={10}>
            <Ionicons name="close" size={24} color={t.txtSecondary} />
          </Pressable>
        </View>
        <Text numberOfLines={2} style={{ color: t.txtSecondary, fontSize: 12.5, paddingHorizontal: 14, paddingBottom: 8 }}>
          {data?.path ?? path}
        </Text>
        {data?.drives?.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0 }}
            contentContainerStyle={{ gap: 6, paddingHorizontal: 12, paddingBottom: 8 }}>
            {data.drives.map((d) => (
              <Pressable key={d} onPress={() => setPath(d)}
                style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1,
                  borderColor: data.path.toUpperCase().startsWith(d.toUpperCase()) ? t.accent : t.borderSubtle }}>
                <Text style={{ color: t.txtPrimary, fontSize: 13 }}>{d.replace(/[\\/]+$/, "")}</Text>
              </Pressable>
            ))}
          </ScrollView>
        ) : null}
        <ScrollView style={{ flex: 1, borderTopWidth: 1, borderTopColor: t.borderSubtle }} keyboardShouldPersistTaps="handled">
          {data?.parent ? row("up", "arrow-up-outline", tr("rooms.pickUp"), () => setPath(data.parent), t.txtSecondary) : null}
          {(data?.dirs ?? []).map((n) => row(n, "folder-outline", n, () => setPath(join(data!.path, n))))}
          {isFetching && !data ? <ActivityIndicator color={t.accent} style={{ marginTop: 24 }} /> : null}
          {data && !data.error && data.dirs.length === 0 ? (
            <Text style={{ color: t.txtTertiary, fontSize: 13, padding: 16 }}>{tr("rooms.pickEmpty")}</Text>
          ) : null}
          {data?.error ? <Text style={{ color: t.danger, fontSize: 13, padding: 16 }}>{data.error}</Text> : null}
        </ScrollView>
        <Pressable disabled={!data?.path || !!data?.error} onPress={() => { if (data?.path) onPick(data.path); }}
          style={{ margin: 14, paddingVertical: 14, borderRadius: 12, alignItems: "center",
            backgroundColor: data?.path && !data.error ? t.accent : t.surface2 }}>
          <Text style={{ color: data?.path && !data.error ? "#fff" : t.txtTertiary, fontWeight: "700", fontSize: 15 }}>
            {tr("rooms.pickUse")}
          </Text>
        </Pressable>
      </View>
    </Modal>
  );
}

/** the last segment of a folder path, either separator ("C:\Work\Immobilien" -> "Immobilien") */
export function folderName(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] ?? "";
}
