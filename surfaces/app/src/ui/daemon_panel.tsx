// Settings > System > Daemon: what is running, whether the code on disk is
// newer than it, and the ONE restart button (owner request 2026-09-12: "im
// settings unter health, so dass es checken kann und per Button neustarten").
// Everything shown is the daemon's own derived status (spine/ops/daemonctl);
// the button calls POST /admin/restart, which refuses while a card turn is
// live unless the owner confirms the force.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Alert, Text, View } from "react-native";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Panel, SectionLabel } from "@/ui/kit";
import { Btn, confirmAsync, Hint } from "@/ui/settings_sections";

function since(startedSec: number | undefined, now: number): string {
  if (!startedSec) return "";
  const s = Math.max(0, Math.round(now / 1000 - startedSec));
  if (s < 90) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86400) return `${(s / 3600).toFixed(1)} h`;
  return `${Math.round(s / 86400)} d`;
}

export function DaemonPanel() {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const [phase, setPhase] = useState<"idle" | "firing" | "waiting" | "back">("idle");
  const firedFrom = useRef<number | undefined>(undefined);
  const { data, error } = useQuery({
    queryKey: ["daemonStatus"],
    queryFn: api.daemonStatus,
    // while a restart is in flight the old daemon dies and the new one boots:
    // poll fast and treat fetch errors as "still restarting", not as failure
    refetchInterval: phase === "waiting" ? 3000 : 15000,
    retry: false,
  });
  const now = Date.now();

  // the restart is DONE when the reported boot time moved past the one we fired from
  useEffect(() => {
    if (phase !== "waiting" || !data?.started) return;
    if (firedFrom.current && data.started > firedFrom.current) {
      setPhase("back");
      qc.invalidateQueries();
    }
  }, [phase, data?.started, qc]);

  const live = data?.running_turns?.length ?? 0;
  const stale = !!data?.stale;

  const fire = async (force: boolean) => {
    setPhase("firing");
    try {
      const r = await api.daemonRestart(force);
      if (!r.ok) {
        // background_active: the turn is over but the card's background tasks
        // still run - the same "this kills running work" confirm, same force.
        if (r.reason === "turn_active" || r.reason === "background_active") {
          const go = await confirmAsync(tr("daemon.restart.busyTitle"),
            tr("daemon.restart.busyBody", { n: r.turns?.length ?? live }));
          if (go) return fire(true);
        } else {
          Alert.alert(tr("daemon.restart.failedTitle"), r.detail || r.reason || "?");
        }
        setPhase("idle");
        return;
      }
      firedFrom.current = data?.started;
      setPhase("waiting");
    } catch (e) {
      Alert.alert(tr("daemon.restart.failedTitle"), String(e));
      setPhase("idle");
    }
  };

  const dot = error && phase !== "waiting" ? t.danger : stale ? t.warn : t.ok;
  const headline = phase === "waiting" ? tr("daemon.restarting")
    : phase === "back" ? tr("daemon.restarted")
    : error ? tr("daemon.unreachable")
    : stale ? tr("daemon.stale") : tr("daemon.current");

  return (
    <Panel>
      <SectionLabel text={tr("daemon.section")} />
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 }}>
        <View style={{ width: 9, height: 9, borderRadius: 5, backgroundColor: dot }} />
        <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600", flex: 1 }}>{headline}</Text>
      </View>
      {data ? (
        <View style={{ marginTop: 6, gap: 2 }}>
          <Text style={{ color: t.txtSecondary, fontSize: 12 }}>
            {tr("daemon.line.running", { since: since(data.started, now), pid: data.pid })}
          </Text>
          <Text style={{ color: t.txtSecondary, fontSize: 12 }}>
            {tr("daemon.line.commit", { commit: data.commit || "?", head: data.repo_head || "?" })}
          </Text>
          {live > 0 ? (
            <Text style={{ color: t.warn, fontSize: 12 }}>{tr("daemon.line.turns", { n: live })}</Text>
          ) : null}
          {data.relay_latency ? (() => {
            const rl = data.relay_latency;
            const n = rl.slow_daemon + rl.bridge_stalls;
            return n > 0
              ? <Text style={{ color: t.warn, fontSize: 12 }}>{tr("daemon.line.latency", { n, min: rl.window_min, worst: rl.worst_s.toFixed(0) })}</Text>
              : <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{tr("daemon.line.latencyOk", { min: rl.window_min })}</Text>;
          })() : null}
          {data.last_restart ? (
            <Text numberOfLines={2} style={{ color: t.txtTertiary, fontSize: 11 }}>{data.last_restart}</Text>
          ) : null}
        </View>
      ) : null}
      {stale && phase === "idle" ? <Hint text={tr("daemon.stale.hint")} /> : null}
      <View style={{ height: 10 }} />
      <Btn
        label={phase === "firing" ? "…" : phase === "waiting" ? tr("daemon.restart.waiting") : tr("daemon.restart")}
        kind={stale ? "primary" : "ghost"}
        disabled={phase === "firing" || phase === "waiting"}
        onPress={() => fire(false)} />
    </Panel>
  );
}
