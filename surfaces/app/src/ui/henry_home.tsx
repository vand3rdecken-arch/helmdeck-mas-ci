import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { CopilotOverlay } from "@/app/chat";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { ThreadList } from "@/ui/chat_threads";
import { useOpenHenry } from "@/ui/henry_chat";
import { useResponsive } from "@/ui/responsive";

/**
 * THE HENRY HOME (owner decree 2026-10-05: Henry is "the central and first place
 * to go", not a 48px button). ONE screen, no second panel: the ask bar on top,
 * then the one thread list (ui/chat_threads.tsx, Paseo's status grouping) with
 * finished threads bucketed Today / This week / This month by last activity.
 * "Needs you" is the top group of that list, so it needs no tab of its own.
 *
 * The bar is the entry to the SHIPPED chat (useOpenHenry: /chat on the phone, the
 * docked panel on desktop) - not a second composer to keep in sync.
 */
export function HenryHome() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const open = useOpenHenry();

  const ask = (
    <Pressable onPress={() => open()} accessibilityLabel={tr("chat.askHenry")} testID="henry-home-ask"
      style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", gap: 10, marginHorizontal: 8, marginBottom: 10,
        paddingHorizontal: 14, minHeight: 48, borderRadius: 16, borderWidth: 1, borderColor: t.borderSubtle,
        backgroundColor: pressed ? t.surface2 : t.surface1 })}>
      <Ionicons name="sparkles" size={18} color={t.accent} />
      <Text numberOfLines={1} style={{ flex: 1, color: t.txtTertiary, fontSize: 15 }}>{tr("home.ask")}</Text>
      <Ionicons name="arrow-up-circle" size={26} color={t.accent} />
    </Pressable>
  );

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", paddingTop: insets.top + 10, paddingHorizontal: 16, paddingBottom: 10 }}>
        {tr("nav.henry")}
      </Text>
      <View style={{ flex: 1, width: "100%", maxWidth: wide ? 760 : undefined, alignSelf: "center" }}>
        <ThreadList timeBuckets header={ask}
          onPick={(id) => router.push((id === "inbox" ? "/chat" : `/card/${id}?tab=chat`) as never)} />
      </View>
      {/* self-guards on !wide || !open - the desktop panel the ask bar opens */}
      <CopilotOverlay />
    </View>
  );
}
