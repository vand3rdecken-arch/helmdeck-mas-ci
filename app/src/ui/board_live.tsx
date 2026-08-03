import React, { useEffect, useState } from "react";
import { Image, Text, View } from "react-native";

import { useConfig } from "@/data/config";
import { useTheme } from "@/theme";

/** The flight recorder on the board: while a screen-recorded agent works a card
 *  the daemon writes a fresh live.jpg; we poll `/tracks/<id>/live` and show the
 *  newest frame. A 404 (no fresh frame, older than 20s) hides it automatically.
 *
 *  Frames come straight off the daemon's HTTP surface (auth via `?token=`), so
 *  they only work in direct mode — the relay tunnel only carries sealed JSON. */
export function LiveThumb({ trackId, big = false }: { trackId: string; big?: boolean }) {
  const t = useTheme();
  const { baseUrl, token, relayMode } = useConfig();
  const [tick, setTick] = useState(0);
  const [dead, setDead] = useState(false);

  useEffect(() => {
    setDead(false);
    const iv = setInterval(() => setTick((x) => x + 1), 1600);
    return () => clearInterval(iv);
  }, [trackId]);

  if (relayMode() || !baseUrl || dead) return null;

  const qs = `?t=${tick}` + (token ? `&token=${encodeURIComponent(token)}` : "");
  const uri = `${baseUrl}/tracks/${trackId}/live${qs}`;

  return (
    <View style={{ position: "relative", marginTop: big ? 0 : 4 }}>
      <Image
        source={{ uri }}
        onError={() => setDead(true)}
        onLoad={() => setDead(false)}
        resizeMode="cover"
        style={{
          width: "100%", height: big ? 240 : 120, borderRadius: big ? 10 : 8,
          borderWidth: 1, borderColor: t.glassBorder, backgroundColor: t.surface2,
        }}
      />
      <View style={{
        position: "absolute", top: 6, left: 6, flexDirection: "row", alignItems: "center",
        gap: 5, backgroundColor: "rgba(0,0,0,0.55)", borderRadius: 5, paddingHorizontal: 7, paddingVertical: 2,
      }}>
        <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: t.danger }} />
        <Text style={{ color: "#fff", fontSize: 9.5, fontWeight: "700", letterSpacing: 0.8 }}>LIVE</Text>
      </View>
    </View>
  );
}
