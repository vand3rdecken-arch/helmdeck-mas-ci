import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pressable, Text, View } from "react-native";

import { api } from "@/data/client";
import type { Track } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";

// WHO may reach this card (owner only; the daemon enforces it again). Two
// different grants, kept apart on purpose:
//   * assigned (operators): they WORK on the card - steer it, move it, read its
//     transcript. cells/engineer sessions.assign, written by the owner alone.
//   * shared (anyone): they SEE title, status and result and nothing else
//     (auth.shared_view). A guest is only ever shared, never assigned.
export function CardAccessPanel({ k }: { k: Track }) {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["roomAccounts"], queryFn: api.roomAccounts });
  const accounts = (Array.isArray(data) ? data : []).filter((a) => a.role !== "owner");
  const assigned = k.zugewiesen_an ?? [];
  const shared = k.geteilt_mit ?? [];
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["tracks"] }); };
  const assign = useMutation({
    mutationFn: (v: { name: string; on: boolean }) => api.trackAssign(k.id, v.on ? [v.name] : [], v.on ? [] : [v.name]),
    onSuccess: refresh,
  });
  const share = useMutation({
    mutationFn: (v: { name: string; on: boolean }) => api.trackShare(k.id, v.on ? [v.name] : [], v.on ? [] : [v.name]),
    onSuccess: refresh,
  });
  const chip = (name: string, on: boolean, onPress: () => void) => (
    <Pressable key={name} onPress={onPress} style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999,
      borderWidth: 1, borderColor: on ? t.accent : t.borderSubtle, backgroundColor: on ? t.accent + "26" : "transparent" }}>
      <Text style={{ color: on ? t.txtPrimary : t.txtSecondary, fontSize: 12.5 }}>{name}</Text>
    </Pressable>
  );
  const operators = accounts.filter((a) => a.role === "operator");
  if (accounts.length === 0) return null;
  return (
    <Panel>
      <SectionLabel text={tr("card.access.title")} />
      {operators.length > 0 ? (
        <View style={{ gap: 6, marginBottom: 8 }}>
          <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("card.access.assigned")}</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
            {operators.map((a) => chip(a.name, assigned.includes(a.name),
              () => assign.mutate({ name: a.name, on: !assigned.includes(a.name) })))}
          </View>
        </View>
      ) : null}
      <View style={{ gap: 6 }}>
        <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("card.access.shared")}</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
          {accounts.map((a) => chip(a.name, shared.includes(a.name),
            () => share.mutate({ name: a.name, on: !shared.includes(a.name) })))}
        </View>
      </View>
    </Panel>
  );
}
