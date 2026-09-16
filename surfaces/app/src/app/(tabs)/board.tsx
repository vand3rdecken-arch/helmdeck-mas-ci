import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Platform, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { CopilotOverlay } from "@/app/chat";
import { HenryFab, useAutoOpenHenryWelcome } from "@/ui/henry_chat";
import { BoardList } from "@/ui/board";
import { BoardSwitcher } from "@/ui/board_switcher";
import { GlowBackdrop } from "@/ui/glow";
import { useTheme } from "@/theme";
import { useResponsive } from "@/ui/responsive";

/** Capacity meter (old web header): WIP running / limit · attention touches ·
 *  headroom. Owner-facing at-a-glance load. */
function CapacityMeter() {
  const t = useTheme();
  const tr = useT();
  const { data } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 8000 });
  const c = data?.capacity;
  if (!c) return null;
  const Item = ({ label, value }: { label: string; value: string }) => (
    <Text style={{ color: t.txtTertiary, fontSize: 12 }}>
      <Text style={{ color: t.txtSecondary, fontWeight: "600" }}>{value}</Text> {label}
    </Text>
  );
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 14 }}>
      <Item label={tr("board.wip")} value={`${c.wip}/${c.wip_limit}`} />
      <Item label={tr("board.touches")} value={`${c.touches_today}/${c.touch_budget_day}`} />
      <Item label={tr("board.headroom")} value={`${c.headroom}`} />
    </View>
  );
}

export default function BoardTab() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { wide } = useResponsive();
  // Onboarding's guided sample card exists to be MET, not just found - see
  // useAutoOpenHenryWelcome's own docstring for why this is derived rather
  // than a stored "first run" flag.
  useAutoOpenHenryWelcome();
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <GlowBackdrop />
      {/* desktop header: title · capacity meter · + Neu */}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 16, paddingTop: insets.top + 10,
        paddingHorizontal: wide ? 20 : 16, paddingBottom: 6 }}>
        <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700" }}>{tr("nav.board")}</Text>
        {/* WHICH board (accounts-boards-prd phase 2) - next to the title on
            every width, because it NAMES what you are looking at and because on
            the phone it is the only way in. */}
        <BoardSwitcher />
        <View style={{ flex: 1 }} />
        {/* Capacity moved to the far right when the switcher joined this row:
            the two of them left-aligned pushed the meter under the centred
            HealthBanner, which overlays the header whenever the daemon blips
            and clipped "4 Luft" mid-word. Title + board name is one cluster
            (what am I looking at), load is another (how busy am I). */}
        {wide ? <CapacityMeter /> : null}
      </View>
      <BoardList />
      {/* floating board chat + new-request, bottom-right (works on desktop too).
          The chat launcher is the SHARED one (ui/henry_chat.tsx) - this screen
          set the pattern, it no longer owns a private copy of it. It self-gates
          on the copilot cell; "+ new card" is the Engineer cell and does not. */}
      <View style={{ position: "absolute", right: 18, bottom: wide ? 24 : 84, alignItems: "center", gap: 12 }}>
        <HenryFab />
        <Pressable onPress={() => router.push("/new")}
          style={{ width: 56, height: 56, borderRadius: 18, backgroundColor: t.accent, alignItems: "center", justifyContent: "center",
            ...(Platform.OS === "web" ? { boxShadow: "0 6px 18px rgba(0,0,0,0.35)" } as any : { elevation: 6 }) }}>
          <Ionicons name="add" size={26} color="#fff" />
        </Pressable>
      </View>
      {/* desktop: the copilot renders here as a right-side panel over the DIMMED,
          still-visible board (phone uses the /chat route instead). It self-guards
          on !wide || !open, and `open` can only be set by a launcher that already
          gated on the cell - so no second gate is needed here. */}
      <CopilotOverlay />
    </View>
  );
}
