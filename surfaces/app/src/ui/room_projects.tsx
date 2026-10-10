import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { MachineFolderPicker, folderName } from "@/ui/machine_folder_picker";
import { useTheme } from "@/theme";

// The project folders of a room (GET /projects/shared). A member sees the
// projects shared with THEM and, per project, its cards as the daemon's summary
// (title, status, result); the owner sees every project and can share one with
// the other members of this room. Nothing is decided here: the daemon derives
// who sees what from the project record on every call.
export function RoomProjects({ members, me, owner }: { members: string[]; me?: string; owner: boolean }) {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  // collapsed by default: the folder list is a side shelf, the conversation is the screen
  const [shelf, setShelf] = useState(false);
  const { data } = useQuery({ queryKey: ["projectsShared"], queryFn: api.projectsShared, retry: false });
  const projects = Array.isArray(data) ? data : [];
  const others = members.filter((m) => m !== me);

  // register a folder on the PC as a project (owner): the door a folder like
  // "Immobilien" needs before it can be shown to anyone
  const [adding, setAdding] = useState(false);
  const [path, setPath] = useState("");
  const [fname, setFname] = useState("");
  const [addErr, setAddErr] = useState("");
  const [picking, setPicking] = useState(false);
  const addFolder = useMutation({
    mutationFn: () => api.projectFolder(path.trim(), fname.trim()),
    onSuccess: () => {
      setPath(""); setFname(""); setAddErr(""); setAdding(false);
      void qc.invalidateQueries({ queryKey: ["projectsShared"] });
    },
    onError: (e: Error) => setAddErr(e.message),
  });

  const share = useMutation({
    mutationFn: (v: { id: string; on: boolean }) =>
      api.projectShare(v.id, v.on ? others : [], v.on ? [] : others),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["projectsShared"] }); },
  });

  return (
    <View style={{ marginHorizontal: 12, marginBottom: 8, borderRadius: 14, borderWidth: 1,
      borderColor: t.glassBorder, backgroundColor: t.surface1, maxHeight: 260 }}>
      <Pressable onPress={() => setShelf(!shelf)} accessibilityRole="button"
        style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingVertical: 9 }}>
        <Ionicons name="folder-outline" size={14} color={t.txtTertiary} />
        <Text style={{ color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6, flex: 1 }}>
          {tr("rooms.projects").toUpperCase() + (projects.length ? " · " + projects.length : "")}
        </Text>
        <Ionicons name={shelf ? "chevron-up" : "chevron-down"} size={14} color={t.txtTertiary} />
      </Pressable>
      {shelf ? <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 8, paddingTop: 0, gap: 4 }}>
        {projects.length === 0 ? (
          <Text style={{ color: t.txtTertiary, fontSize: 12.5, padding: 6 }}>
            {tr(owner ? "rooms.projectsEmptyOwner" : "rooms.projectsEmpty")}
          </Text>
        ) : null}
        {projects.map((p) => {
          const isOpen = open === p.id;
          const sharedAll = others.length > 0 && others.every((m) => p.geteilt_mit.includes(m));
          return (
            <View key={p.id} style={{ borderRadius: 10, backgroundColor: t.surface2 }}>
              <Pressable onPress={() => setOpen(isOpen ? null : p.id)}
                style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 10, paddingVertical: 9 }}>
                <Ionicons name="folder-outline" size={16} color={t.accent} />
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "600" }}>{p.name}</Text>
                  <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{p.card_count === 1 ? tr("rooms.projectCard1") : tr("rooms.projectCards", { n: p.card_count })}</Text>
                </View>
                {owner ? (
                  <Pressable accessibilityLabel={tr("rooms.projectShare")} disabled={share.isPending || others.length === 0}
                    onPress={() => share.mutate({ id: p.id, on: !sharedAll })}
                    style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4,
                      borderRadius: 999, borderWidth: 1, borderColor: sharedAll ? t.ok : t.accent + "88" }}>
                    <Ionicons name={sharedAll ? "checkmark" : "share-outline"} size={12} color={sharedAll ? t.ok : t.accent} />
                    <Text style={{ color: sharedAll ? t.ok : t.accent, fontSize: 11.5 }}>
                      {tr(sharedAll ? "rooms.projectShared" : "rooms.projectShare")}
                    </Text>
                  </Pressable>
                ) : null}
                <Ionicons name={isOpen ? "chevron-up" : "chevron-down"} size={14} color={t.txtTertiary} />
              </Pressable>
              {isOpen ? (
                <View style={{ paddingHorizontal: 10, paddingBottom: 8, gap: 2 }}>
                  {p.cards.length === 0 ? (
                    <Text style={{ color: t.txtTertiary, fontSize: 12.5, paddingVertical: 4 }}>{tr("rooms.projectNoCards")}</Text>
                  ) : null}
                  {p.cards.map((c) => (
                    <Pressable key={c.id}
                      onPress={() => router.push({ pathname: "/card/[id]", params: { id: c.id } } as never)}
                      style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6 }}>
                      <Text numberOfLines={2} style={{ color: t.txtSecondary, fontSize: 13, flex: 1 }}>{c.task}</Text>
                      <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{c.lane ? tr(("lane." + c.lane) as never) : c.status ?? ""}</Text>
                      <Ionicons name="chevron-forward" size={13} color={t.txtTertiary} />
                    </Pressable>
                  ))}
                  {owner ? <Text style={{ color: t.txtTertiary, fontSize: 11.5, paddingTop: 4 }}>{tr("rooms.projectHint")}</Text> : null}
                </View>
              ) : null}
            </View>
          );
        })}
        {owner ? (
          adding ? (
            <View style={{ gap: 8, padding: 8 }}>
              <Pressable onPress={() => setPicking(true)}
                style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 8 }}>
                <Ionicons name="folder-open-outline" size={18} color={t.accent} />
                <Text numberOfLines={2} style={{ color: path ? t.txtPrimary : t.accent, fontSize: 14, flex: 1 }}>
                  {path || tr("rooms.pickTitle")}
                </Text>
              </Pressable>
              <MachineFolderPicker visible={picking} onClose={() => setPicking(false)}
                onPick={(picked: string) => { setPath(picked); setPicking(false); if (!fname.trim()) setFname(folderName(picked)); }} />
              <TextInput value={fname} onChangeText={setFname} placeholder={tr("rooms.folderName")} maxLength={60}
                placeholderTextColor={t.txtPlaceholder}
                style={{ color: t.txtPrimary, fontSize: 14, borderBottomWidth: 1, borderBottomColor: t.borderSubtle, paddingVertical: 6 }} />
              {addErr ? <Text style={{ color: t.danger, fontSize: 12 }}>{addErr}</Text> : null}
              <Pressable disabled={!path.trim() || addFolder.isPending} onPress={() => addFolder.mutate()}
                style={{ alignSelf: "flex-start", paddingHorizontal: 12, paddingVertical: 7, borderRadius: 10,
                  backgroundColor: path.trim() ? t.accent : t.surface2 }}>
                <Text style={{ color: path.trim() ? "#fff" : t.txtTertiary, fontWeight: "600", fontSize: 12.5 }}>{tr("rooms.folderSave")}</Text>
              </Pressable>
            </View>
          ) : (
            <Pressable onPress={() => setAdding(true)}
              style={{ flexDirection: "row", alignItems: "center", gap: 6, padding: 8 }}>
              <Ionicons name="add" size={15} color={t.accent} />
              <Text style={{ color: t.accent, fontSize: 13 }}>{tr("rooms.folderAdd")}</Text>
            </Pressable>
          )
        ) : null}
        {owner && projects.length > 0 ? <Text style={{ color: t.txtTertiary, fontSize: 11.5, paddingHorizontal: 8, paddingBottom: 4 }}>{tr("rooms.projectsOnlyOne")}</Text> : null}
      </ScrollView> : null}
    </View>
  );
}
