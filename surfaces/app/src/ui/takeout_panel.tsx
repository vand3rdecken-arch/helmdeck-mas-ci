// Settings > System > Umzug: make a container of everything, see what is in
// it, and - the part that matters - see what is NOT in it.
//
// Owner 2026-09-21: "needs to be like actual feature with ui and all". The
// engine and the routes existed; this is the surface.
//
// The screen's job is NOT to be a button. Every shipped takeout that was
// studied for this (Signal's on-device backup, WhatsApp chat transfer, Google
// Takeout) publishes its EXCLUSION LIST at the same prominence as the feature
// itself, because the thing that ruins a migration is the part you did not
// know was missing. So the handover list is not behind a link and not in a
// tooltip: it is on the panel, under the button, permanently.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Alert, Text, View } from "react-native";

import { api, type TakeoutBox } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";
import { Btn, Caption, Hint } from "@/ui/settings_sections";

function mb(bytes: number | undefined): string {
  const b = bytes ?? 0;
  if (b < 1024 * 1024) return `${Math.max(1, Math.round(b / 1024))} KB`;
  return `${(b / 1e6).toFixed(1)} MB`;
}

/** One line naming what the container holds. Only rows that exist are named,
 *  so an archive without, say, recordings simply does not mention them rather
 *  than claiming a zero. */
function contentLine(box: TakeoutBox, tr: (k: string, v?: Record<string, string | number>) => string): string {
  const tables = box.parts?.["db.json"]?.tables ?? {};
  const auto = box.parts?.["auto-memory/"];
  const bits: string[] = [];
  const add = (n: number | undefined, key: string) => {
    if (n && n > 0) bits.push(tr(key, { n }));
  };
  add((tables.memory ?? 0) + (auto?.notes ?? 0), "takeout.cNotes");
  add(tables.tracks, "takeout.cCards");
  add(tables.chat, "takeout.cChat");
  add(tables.users, "takeout.cUsers");
  const rec = box.parts?.["recordings/"]?.files;
  add(rec, "takeout.cRecordings");
  return bits.join(" · ");
}

export function TakeoutPanel() {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const { data } = useQuery({
    queryKey: ["takeout"],
    queryFn: api.takeout,
    // An export takes tens of seconds and its progress is not a db write, so
    // it is watched ONLY while one runs - Paseo polls a live CI pipeline the
    // same way. Idle there is nothing to watch: starting one invalidates this.
    refetchInterval: (q) => (q.state.data?.job?.state === "running" ? 2000 : false),
    retry: false,
  });

  const job = data?.job;
  const running = job?.state === "running" || busy;
  const boxes = data?.boxes ?? [];
  const latest = boxes[0];

  const start = async () => {
    setBusy(true);
    try {
      const r = await api.takeoutStart(false);
      if (!r.ok) Alert.alert(tr("takeout.failedTitle"), r.error ?? "?");
    } catch (e: unknown) {
      Alert.alert(tr("takeout.failedTitle"), String(e).slice(0, 200));
    } finally {
      setBusy(false);
      void qc.invalidateQueries({ queryKey: ["takeout"] });
    }
  };

  const verify = async (name: string) => {
    try {
      const r = await api.takeoutVerify(name);
      Alert.alert(
        r.ok ? tr("takeout.verifyOkTitle") : tr("takeout.verifyBadTitle"),
        r.ok ? tr("takeout.verifyOkBody") : (r.problems ?? []).join("\n"),
      );
    } catch (e: unknown) {
      Alert.alert(tr("takeout.failedTitle"), String(e).slice(0, 200));
    }
  };

  return (
    <Panel>
      <SectionLabel text={tr("takeout.title")} />
      <Hint text={tr("takeout.hint")} />

      {job?.state === "failed" ? (
        <Text style={{ color: t.danger, fontSize: 12.5, marginBottom: 8 }}>
          {tr("takeout.failed", { why: job.error ?? "?" })}
        </Text>
      ) : null}

      {latest ? (
        <View style={{ marginBottom: 10 }}>
          <Text style={{ color: t.txtSecondary, fontSize: 12.5 }}>
            {tr("takeout.latest", {
              when: (latest.created ?? "").slice(0, 16).replace("T", " "),
              size: mb(latest.bytes),
            })}
          </Text>
          {/* WHAT is in it, not just how big. "131,7 MB" tells you nothing
              about whether your notes are safe; "115 Notizen, 406 Karten"
              does. Counts come straight from the manifest the export already
              wrote - nothing is recomputed here, so the line cannot claim
              more than the container actually holds. */}
          <Text style={{ color: t.txtTertiary, fontSize: 12, marginTop: 2 }}>
            {contentLine(latest, tr)}
          </Text>
          {!latest.complete ? (
            <Text style={{ color: t.danger, fontSize: 12.5, marginTop: 2 }}>
              {tr("takeout.incomplete")}
            </Text>
          ) : null}
        </View>
      ) : (
        <Text style={{ color: t.txtTertiary, fontSize: 12.5, marginBottom: 10 }}>
          {tr("takeout.none")}
        </Text>
      )}

      <Btn label={running ? tr("takeout.running") : tr("takeout.start")}
        onPress={start} disabled={running} />
      {latest ? (
        <>
          <View style={{ height: 8 }} />
          <Btn label={tr("takeout.verify")} kind="ghost"
            onPress={() => verify(latest.name)} />
        </>
      ) : null}

      {/* THE EXCLUSION LIST. Permanent, not conditional on having an archive:
          the owner has to know what he must carry by hand BEFORE he wipes a
          machine, which is exactly the moment there is no archive yet. */}
      <View style={{ height: 14 }} />
      <Caption text={tr("takeout.notIncluded")} />
      {(data?.handover ?? []).map((h) => (
        <View key={h.what} style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
          <Text style={{ color: t.txtTertiary, fontSize: 12.5 }}>•</Text>
          <View style={{ flex: 1 }}>
            <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>
              {h.what}
            </Text>
            <Text style={{ color: t.txtTertiary, fontSize: 12, lineHeight: 17 }}>
              {h.why}
            </Text>
          </View>
        </View>
      ))}
    </Panel>
  );
}
