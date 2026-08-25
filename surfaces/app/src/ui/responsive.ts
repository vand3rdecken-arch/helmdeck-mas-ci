import { Platform, useWindowDimensions } from "react-native";

// One breakpoint for the whole app - desktop/wide-web layout kicks in above
// this width. Was hand-copied as a literal `900` in 13+ files; this is the
// single place that changes it.
export const WIDE_BREAKPOINT = 900;

export const isWeb = Platform.OS === "web";

/** wide = desktop-class web viewport (two-column layouts, sidebars, etc).
 *  Native phone/tablet apps are never "wide" - the web target is the only
 *  one wide enough to earn a different layout today. */
export function useResponsive() {
  const { width, height } = useWindowDimensions();
  const wide = isWeb && width >= WIDE_BREAKPOINT;
  return { width, height, isWeb, wide };
}
