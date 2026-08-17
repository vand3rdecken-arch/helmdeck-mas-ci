// Dev route: proves the plugin composition end-to-end. Boots the `phase2`
// profile, then renders whatever surface the profile registered — the board
// arrives via KEYS.SURFACES, not a hard import. This is the seed of the
// registry-driven navigator that replaces the (tabs) list in a later card.
//
// Reachable at /kernel-demo. Not in primary nav; safe to keep during the
// dual-path period (old (tabs) router still owns production navigation).

import React, { useMemo } from "react";
import { Text, View } from "react-native";

import { KernelProvider, useSurfaces } from "@/kernel/react";
import { boot, dump } from "@/boot";

function RegistryHost() {
  const surfaces = useSurfaces();
  const first = surfaces[0];
  if (!first) return <Text style={{ color: "#fff", padding: 24 }}>no surfaces registered</Text>;
  const Screen = first.component;
  return <Screen />;
}

export default function KernelDemo() {
  const kernel = useMemo(() => boot("phase2"), []);
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
