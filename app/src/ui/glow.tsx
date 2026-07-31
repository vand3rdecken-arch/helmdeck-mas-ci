import { StyleSheet, View } from "react-native";
import Svg, { Defs, RadialGradient, Rect, Stop } from "react-native-svg";
import { useTheme } from "@/theme";

/** Ambient "aurora" backdrop — the richer, multi-hue mesh from the old desktop
 *  app (globals.css [data-backdrop="aurora"]): teal, violet, green and magenta
 *  radial blooms behind everything. Glass refracts these, which is what gave the
 *  old UI its colour. Cross-platform via svg; colour stays decorative (card /
 *  status colour stays semantic). Pre-resolved from the OKLCH source. */
const AUR = {
  teal: "rgb(0,154,166)",
  violet: "rgb(147,94,223)",
  green: "rgb(0,164,108)",
  magenta: "rgb(179,87,173)",
};

export function GlowBackdrop() {
  const t = useTheme();
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <Svg width="100%" height="100%">
        <Defs>
          <RadialGradient id="a1" cx="8%" cy="-8%" r="60%">
            <Stop offset="0" stopColor={AUR.teal} stopOpacity={0.38} />
            <Stop offset="1" stopColor={AUR.teal} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="a2" cx="92%" cy="4%" r="52%">
            <Stop offset="0" stopColor={AUR.violet} stopOpacity={0.32} />
            <Stop offset="1" stopColor={AUR.violet} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="a3" cx="45%" cy="112%" r="62%">
            <Stop offset="0" stopColor={AUR.green} stopOpacity={0.28} />
            <Stop offset="1" stopColor={AUR.green} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="a4" cx="70%" cy="55%" r="40%">
            <Stop offset="0" stopColor={AUR.magenta} stopOpacity={0.18} />
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
