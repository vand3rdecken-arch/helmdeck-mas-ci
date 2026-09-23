import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { api } from "@/data/client";
import { useConfig } from "@/data/config";
import { useHealth } from "@/data/health";
import { checkConnection, verdictKey, type Leg } from "@/data/connection_check";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// WHICH LEG IS BROKEN, on the device that is complaining (owner 2026-09-23:
// "Haupt problem ist fehlender Diagnose"). The banner can only ever say "the
// request failed"; this says whether the phone, the relay, the PC or the
// pairing is the one that is down - and it runs on the phone, which is the
// only place that can test the phone's own leg.
//
// The logic lives in data/connection_check.ts (no React, self-tested under
// plain node); this file is the button and the list.
export function ConnectionCheck() {
  const t = useTheme();
  const tr = useT();
  const [legs, setLegs] = useState<Leg[] | null>(null);
  const [busy, setBusy] = useState(false);
  const cfg = useConfig();

  async function run() {
    setBusy(true);
    setLegs(null);
    try {
      const out = await checkConnection({
        relayUrl: cfg.relayUrl,
        room: cfg.room,
        fetchImpl: fetch,
        // The cheapest REAL round-trip: sealed, authenticated, tiny answer.
        sealedPing: () => api.me(),
      });
      setLegs(out);
      // health.ts stays the ONE owner of the connection state - the probe
      // reports INTO it so the ambient banner names the same leg this panel
      // just found (a passing check clears it by itself: sealedPing goes
      // through the ordinary client, which calls reportOk).
      useHealth.getState().reportCheck(verdictKey(out));
    } finally {
      setBusy(false);
    }
  }

  const verdict = legs ? tr(verdictKey(legs)) : "";
  const allOk = !!legs && legs.every((l) => l.state === "ok");

  return (
    <View style={{ gap: 8 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
        <Pressable onPress={run} disabled={busy}
          style={{ borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 7,
            borderColor: t.borderSubtle, backgroundColor: t.surface2, opacity: busy ? 0.6 : 1 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "600" }}>
            {busy ? tr("check.running") : tr("check.run")}
          </Text>
        </Pressable>
        {busy ? <ActivityIndicator color={t.accent} /> : null}
        {verdict ? (
          <Text style={{ color: allOk ? t.ok : t.danger, fontSize: 12.5, fontWeight: "600", flexShrink: 1 }}>
            {verdict}
          </Text>
        ) : null}
      </View>

      {legs?.map((l) => {
        const colour = l.state === "ok" ? t.ok : l.state === "fail" ? t.danger : t.txtTertiary;
        const icon = l.state === "ok" ? "checkmark-circle" : l.state === "fail" ? "close-circle" : "remove-circle-outline";
        return (
          <View key={l.id} style={{ flexDirection: "row", gap: 8, alignItems: "flex-start" }}>
            <Ionicons name={icon as never} size={15} color={colour} style={{ marginTop: 1 }} />
            <View style={{ flexShrink: 1 }}>
              <Text style={{ color: t.txtPrimary, fontSize: 12.5 }}>
                {tr(`check.leg.${l.id}`)}
              </Text>
              <Text style={{ color: t.txtSecondary, fontSize: 11.5 }}>
                {tr(l.key, { 0: l.detail })}
              </Text>
              {/* the raw status/error stays visible - it is what a bug report needs */}
              {l.detail && l.state !== "ok" ? (
                <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{l.detail}</Text>
              ) : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}
