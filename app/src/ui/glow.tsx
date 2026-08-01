import { Platform, StyleSheet, View } from "react-native";
import Svg, { Defs, RadialGradient, Rect, Stop } from "react-native-svg";
import { LinearGradient } from "expo-linear-gradient";
import { useTheme } from "@/theme";

/** Ambient "aurora" backdrop — the richer, multi-hue mesh from the old desktop
 *  app (globals.css [data-backdrop="aurora"]): teal, violet, green and magenta
 *  radial blooms behind everything. Glass refracts these, which is what gave the
 *  old UI its colour. Colour stays decorative (card / status colour stays
 *  semantic). Pre-resolved from the OKLCH source. */
// Cohesive blue -> violet aurora (analogous scheme). The old mesh mixed teal +
// green + magenta + violet — four fighting hues; this keeps everything in the
// blue/indigo/violet family so the backdrop reads as one calm gradient.
const AUR = {
  teal: "rgb(46,143,204)",     // accent blue (top-left bloom)
  violet: "rgb(155,135,232)",  // violet (top-right bloom)
  green: "rgb(84,104,224)",    // indigo (bottom bloom, replaces green)
  magenta: "rgb(120,110,214)", // periwinkle (centre, replaces magenta)
};

export function GlowBackdrop() {
  const t = useTheme();
  // Native (Android/iOS): a fullscreen react-native-svg RadialGradient surface
  // black-screens on some Android GPUs under the New Architecture (Fabric) -
  // reported on Xiaomi/HyperOS. expo-linear-gradient is a native, GPU-safe view,
  // so approximate the aurora with stacked diagonal blooms over the canvas.
  if (Platform.OS !== "web") {
    return (
      <View style={[StyleSheet.absoluteFill, { backgroundColor: t.canvas }]} pointerEvents="none">
        {/* dark canvas dominant; gentle blooms concentrated at the edges and
            faded to transparent well before centre, so text stays readable */}
        <LinearGradient
          colors={[AUR.teal + "1C", "transparent"]}
          locations={[0, 0.5]}
          start={{ x: 0, y: 0 }} end={{ x: 0.85, y: 0.75 }}
          style={StyleSheet.absoluteFill}
        />
        <LinearGradient
          colors={[AUR.violet + "14", "transparent"]}
          locations={[0, 0.45]}
          start={{ x: 1, y: 0 }} end={{ x: 0.25, y: 0.6 }}
          style={StyleSheet.absoluteFill}
        />
        <LinearGradient
          colors={["transparent", AUR.green + "18"]}
          locations={[0.6, 1]}
          start={{ x: 0.4, y: 0.2 }} end={{ x: 0.6, y: 1 }}
          style={StyleSheet.absoluteFill}
        />
      </View>
    );
  }
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <Svg width="100%" height="100%">
        <Defs>
          <RadialGradient id="a1" cx="6%" cy="-6%" r="66%">
            <Stop offset="0" stopColor={AUR.teal} stopOpacity={0.60} />
            <Stop offset="1" stopColor={AUR.teal} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="a2" cx="94%" cy="2%" r="60%">
            <Stop offset="0" stopColor={AUR.violet} stopOpacity={0.55} />
            <Stop offset="1" stopColor={AUR.violet} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="a3" cx="45%" cy="112%" r="66%">
            <Stop offset="0" stopColor={AUR.green} stopOpacity={0.45} />
            <Stop offset="1" stopColor={AUR.green} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="a4" cx="72%" cy="52%" r="46%">
            <Stop offset="0" stopColor={AUR.magenta} stopOpacity={0.30} />
            <Stop offset="1" stopColor={AUR.magenta} stopOpacity={0} />
          </RadialGradient>
        </Defs>
        <Rect x="0" y="0" width="100%" height="100%" fill={t.canvas} />
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#a1)" />
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#a2)" />
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#a3)" />
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#a4)" />
      </Svg>
    </View>
  );
}
