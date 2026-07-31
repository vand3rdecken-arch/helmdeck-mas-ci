import { StyleSheet, View } from "react-native";
import Svg, { Defs, RadialGradient, Rect, Stop } from "react-native-svg";
import { useTheme } from "@/theme";

/** Ambient "aurora" backdrop — the richer, multi-hue mesh from the old desktop
 *  app (globals.css [data-backdrop="aurora"]): teal, violet, green and magenta
 *  radial blooms behind everything. Glass refracts these, which is what gave the
 *  old UI its colour. Cross-platform via svg; colour stays decorative (card /
 *  status colour stays semantic). Pre-resolved from the OKLCH source. */
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
