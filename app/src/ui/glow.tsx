import { StyleSheet, View } from "react-native";
import Svg, { Defs, RadialGradient, Rect, Stop } from "react-native-svg";
import { useTheme } from "@/theme";

/** The desktop's ambient glow backdrop (globals.css body::before): soft radial
 *  glows — accent-blue top-left, purple top-right, blue low-centre — over the
 *  canvas. Cross-platform (svg), the real version of this session's Haze glow. */
export function GlowBackdrop() {
  const t = useTheme();
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <Svg width="100%" height="100%">
        <Defs>
          <RadialGradient id="g1" cx="8%" cy="0%" r="60%">
            <Stop offset="0" stopColor={t.accent} stopOpacity={0.26} />
            <Stop offset="1" stopColor={t.accent} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="g2" cx="98%" cy="4%" r="55%">
            <Stop offset="0" stopColor={t.accent2} stopOpacity={0.22} />
            <Stop offset="1" stopColor={t.accent2} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="g3" cx="50%" cy="104%" r="60%">
            <Stop offset="0" stopColor={t.accent} stopOpacity={0.18} />
            <Stop offset="1" stopColor={t.accent} stopOpacity={0} />
          </RadialGradient>
        </Defs>
        <Rect x="0" y="0" width="100%" height="100%" fill={t.canvas} />
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#g1)" />
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#g2)" />
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#g3)" />
      </Svg>
    </View>
  );
}
