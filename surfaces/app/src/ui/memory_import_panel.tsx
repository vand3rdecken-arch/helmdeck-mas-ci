// "Bring your memory along" - ONE component, two homes: the last step of
// onboarding (surfaces/app/src/ui/onboard.tsx) and Settings > System.
//
// One component on purpose. The house rule that came out of the chat UI
// ("never maintain two chat UIs") applies here for the same reason: the
// onboarding copy is the copy that matters most, and a second implementation
// is the one that goes stale.
//
// The ABSENT list is rendered, not hidden. A user who came from Cursor and
// sees no mention of Cursor cannot tell whether we looked - and at first run
// he has no way to check. Saying "Cursor: nothing found at the known
// locations" costs one line and turns a silence into a fact.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIndicator, Alert, Text, View } from "react-native";

import { api, type ForeignSource } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";
import { Btn, Caption, Hint } from "@/ui/settings_sections";

export function MemoryImportPanel({ bare = false }: { bare?: boolean }) {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<Record<string, number>>({});

  const { data, isLoading } = useQuery({
    queryKey: ["foreignMemory"],
    queryFn: api.foreignMemory,
    retry: false,
  });

  // Biggest first, and only the first row wears the loud button. Judged on a
  // real screen (2026-09-22): eight identical blue "Übernehmen" buttons gave a
  // 1-entry scratch folder exactly the same weight as a 91-note memory, so the
  // list read as a wall of equal choices instead of one obvious one.
  const sources = [...(data?.sources ?? [])].sort((a, b) => b.count - a.count);
  const absent = data?.absent ?? [];

  const run = async (src: ForeignSource) => {
    setBusy(src.id);
    try {
      const r = await api.foreignImport(src.id);
      const n = r.result?.imported?.length ?? 0;
      const skipped = r.result?.skipped?.length ?? 0;
      setDone((d) => ({ ...d, [src.id]: n }));
      // The skip count is SHOWN, never swallowed: a note that did not come
      // across because the name was taken is the one thing the user would
      // otherwise discover weeks later, looking for something that is not there.
      if (skipped) {
        Alert.alert(tr("mimport.doneTitle"),
          tr("mimport.doneBody", { n, skipped }));
      }
    } catch (e: unknown) {
      Alert.alert(tr("mimport.failedTitle"), String(e).slice(0, 200));
    } finally {
      setBusy(null);
      void qc.invalidateQueries({ queryKey: ["foreignMemory"] });
    }
  };

  const body = (
    <>
      {!bare ? <SectionLabel text={tr("mimport.title")} /> : null}
      <Hint text={tr("mimport.hint")} />
      {isLoading ? <ActivityIndicator style={{ marginVertical: 12 }} /> : null}

      {!isLoading && sources.length === 0 ? (
        <Text style={{ color: t.txtTertiary, fontSize: 12.5, marginVertical: 8 }}>
          {tr("mimport.noneFound")}
        </Text>
      ) : null}

      {sources.map((s, i) => (
        <View key={s.id} style={{ marginTop: 10 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <View style={{ flex: 1 }}>
              <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600" }}>
                {s.label}
              </Text>
              <Text style={{ color: t.txtTertiary, fontSize: 12 }} numberOfLines={2}>
                {tr("mimport.count", { n: s.count })} · {s.note}
              </Text>
            </View>
            {done[s.id] !== undefined ? (
              <Text style={{ color: t.ok, fontSize: 12.5, fontWeight: "600" }}>
                {tr("mimport.imported", { n: done[s.id] })}
              </Text>
            ) : null}
          </View>
          <View style={{ height: 6 }} />
          <Btn
            label={busy === s.id ? tr("mimport.running") : tr("mimport.take")}
            kind={done[s.id] !== undefined || i > 0 ? "ghost" : "primary"}
            disabled={busy !== null}
            onPress={() => run(s)}
          />
        </View>
      ))}

      {absent.length ? (
        <>
          <View style={{ height: 14 }} />
          <Caption text={tr("mimport.absent")} />
          {absent.map((a) => (
            <Text key={a.id} style={{ color: t.txtTertiary, fontSize: 12, marginTop: 3 }}>
              {a.label}: {a.why}
            </Text>
          ))}
        </>
      ) : null}
    </>
  );

  return bare ? <View>{body}</View> : <Panel>{body}</Panel>;
}
