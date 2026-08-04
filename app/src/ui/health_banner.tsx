import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef } from "react";
import { Animated, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useHealth } from "@/data/health";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// Ambient connection state, mounted once above the whole app. Appears the
// moment a request fails at the TRANSPORT level (relay down, no network,
// crypto mismatch) and disappears on the first successful round-trip - so the
// daemon being gone is never silent, on any screen. Non-interactive: it never
// blocks touches; the long-poll in _layout reconnects on its own.
export function HealthBanner() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const { status, detail } = useHealth();
  const visible = status === "offline";
  const anim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(anim, { toValue: visible ? 1 : 0, duration: 220, useNativeDriver: true }).start();
  }, [visible, anim]);

  if (!visible) return null;
  return (
    <Animated.View pointerEvents="none"
      style={{ position: "absolute", top: insets.top + 6, left: 12, right: 12, zIndex: 1000, alignItems: "center",
        opacity: anim, transform: [{ translateY: anim.interpolate({ inputRange: [0, 1], outputRange: [-12, 0] }) }] }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, maxWidth: 520,
        backgroundColor: t.surface2, borderColor: t.danger + "88", borderWidth: 1, borderRadius: 10,
        paddingHorizontal: 12, paddingVertical: 8,
        shadowColor: "#000", shadowOpacity: 0.35, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 6 }}>
        <Ionicons name="cloud-offline-outline" size={15} color={t.danger} />
        <View style={{ flexShrink: 1 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "600" }}>
            {tr("health.reconnecting")}
          </Text>
          {detail ? (
            <Text numberOfLines={2} style={{ color: t.txtSecondary, fontSize: 11.5 }}>{detail}</Text>
          ) : null}
        </View>
      </View>
    </Animated.View>
  );
}
