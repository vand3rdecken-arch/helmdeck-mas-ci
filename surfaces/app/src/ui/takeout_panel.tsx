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

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";
import { Btn, Caption, Hint } from "@/ui/settings_sections";

function mb(bytes: number | undefined): string {
  const b = bytes ?? 0;
  if (b < 1024 * 1024) return `${Math.max(1, Math.round(b / 1024))} KB`;
  return `${(b / 1e6).toFixed(1)} MB`;
}

export function TakeoutPanel() {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const { data } = useQuery({
    queryKey: ["takeout"],
    queryFn: api.takeout,
    // an export takes tens of seconds; poll while one runs, idle otherwise
    refetchInterval: (q) => (q.state.data?.job?.state === "running" ? 2000 : 30000),
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
