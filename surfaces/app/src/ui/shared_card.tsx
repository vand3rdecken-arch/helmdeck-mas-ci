import { cardTitle } from "@/ui/card_title";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import type { Track } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Chip, Empty, ScreenHeader } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

const LANE_KEY: Record<string, string> = {
  backlog: "lane.backlog", working: "lane.working", review: "lane.review", done: "lane.done",
};
const STATUS_KEY: Record<string, string> = {
  queued: "status.queued", running: "status.running", gating: "status.gating",
  needs_you: "status.needsYou", bounced: "status.bounced",
  submitted: "status.submitted", accepted: "status.accepted",
};

// A card somebody SHARED with me (cells/engineer, auth.shared_view): title,
// status and result - and nothing else. The daemon sends only that whitelist, so
// this screen must not pretend to have more: no editable fields, no price or due
// date filled in from defaults, no chat tab. (The full card screen rendered all
// of those for a shared card, with invented values - found in the screenshot
// review of the team-rooms work.)
export function SharedCardView({ k }: { k: Track }) {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const lane = LANE_KEY[k.lane] ? tr(LANE_KEY[k.lane]) : k.lane;
  const status = STATUS_KEY[k.status] ? tr(STATUS_KEY[k.status]) : String(k.status ?? "").replace(/_/g, " ");
  const card = { backgroundColor: t.surface1, borderWidth: 1, borderColor: t.glassBorder, borderRadius: 14, padding: 14, gap: 8 } as const;
  const label = { color: t.txtTertiary, fontSize: 11, letterSpacing: 0.6 } as const;
  const sharedWith = Array.isArray((k as { geteilt_mit?: string[] }).geteilt_mit)
    ? (k as { geteilt_mit?: string[] }).geteilt_mit! : [];
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={cardTitle(k.task)} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 14, gap: 12, paddingBottom: insets.bottom + 24,
        width: "100%", maxWidth: wide ? 720 : undefined, alignSelf: "center" }}>
        <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
          <Chip text={lane} />
          {status ? <Chip text={status} /> : null}
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Ionicons name="share-social-outline" size={16} color={t.txtTertiary} />
          <Text style={{ color: t.txtTertiary, fontSize: 12.5, flex: 1, lineHeight: 18 }}>{tr("shared.hint")}</Text>
        </View>
        <View style={card}>
          <Text style={label}>{tr("shared.result").toUpperCase()}</Text>
          {k.last_reply ? (
            <Text selectable style={{ color: t.txtPrimary, fontSize: 14.5, lineHeight: 21 }}>{k.last_reply}</Text>
          ) : <Empty text={tr("shared.noResult")} />}
        </View>
        <View style={card}>
          {k.client ? <Text style={{ color: t.txtSecondary, fontSize: 13 }}>{tr("shared.by", { name: k.client })}</Text> : null}
          {sharedWith.length > 0 ? (
            <Text style={{ color: t.txtSecondary, fontSize: 13 }}>{tr("shared.with", { names: sharedWith.join(", ") })}</Text>
          ) : null}
          {k.created ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("shared.created", { t: String(k.created).slice(0, 16) })}</Text> : null}
        </View>
      </ScrollView>
    </View>
  );
}
