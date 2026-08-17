// Dev route: proves the plugin composition end-to-end. Boots the `phase2`
// profile, then renders whatever surface the profile registered — the board
// arrives via KEYS.SURFACES, not a hard import. This is the seed of the
// registry-driven navigator that replaces the (tabs) list in a later card.
//
// Reachable at /kernel-demo. Not in primary nav; safe to keep during the
// dual-path period (old (tabs) router still owns production navigation).

import React, { useEffect, useMemo } from "react";
import { Text, View } from "react-native";

import { KernelProvider, useSurfaces } from "@/kernel/react";
import { boot, dump } from "@/boot";
import { hydratePolicies } from "@/boot/hydrate";
import { attachDaemonTrackSink } from "@/boot/tracksink";

function RegistryHost() {
  const surfaces = useSurfaces();
  const first = surfaces.find((s) => s.component);
  if (!first?.component) return <Text style={{ color: "#fff", padding: 24 }}>no renderable surface</Text>;
  const Screen = first.component;
  return <Screen />;
}

export default function KernelDemo() {
  const kernel = useMemo(() => boot("phase2"), []);
  // Hydrate seeded policy/charter from the daemon's canonical source — itself a
  // tracked swap; falls back to the seeded defaults offline. Then dump the
  // reconfiguration journal so the glass box is visible in dev.
  useEffect(() => {
    const detach = attachDaemonTrackSink(kernel); // mirror swaps into daemon audit
    hydratePolicies(kernel).then(() => {
      if (__DEV__) console.log("kernel journal:", kernel.journal());
    });
    return detach;
  }, [kernel]);
  // Surfaced once in the console so the resolved composition is inspectable.
  if (__DEV__) console.log(dump("phase2"));
  return (
    <KernelProvider kernel={kernel}>
      <View style={{ flex: 1 }}>
        <RegistryHost />
      </View>
    </KernelProvider>
  );
}
