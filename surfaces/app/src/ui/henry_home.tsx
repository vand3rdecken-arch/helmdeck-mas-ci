import { useRouter } from "expo-router";
import { View } from "react-native";

import { ChatBody } from "@/app/chat";
import { useTheme } from "@/theme";
import { ThreadList } from "@/ui/chat_threads";
import { useResponsive } from "@/ui/responsive";

// The floating bottom tab bar's own height on the phone (the safe-area inset is
// already counted by the composer); measured against the Pixel screenshot of
// 2026-10-05 where the bar overlapped the last rows and the composer.
const TAB_BAR = 58;

/**
 * THE HENRY HOME (owner decree 2026-10-05: Henry is "the central and first place
 * to go"). The owner uses the Henry inbox as ONE LONG STREAM, not as one chat
 * among many - so the home IS that stream: the shipped chat body (same session,
 * same transcript, same composer), not a row in a list. The card threads (needs
 * you / working / today / this week / this month) are the list beside it on
 * desktop and one tap behind the menu button on the phone, where the button
 * carries the count of threads waiting on the owner.
 */
export function HenryHome() {
  const t = useTheme();
  const router = useRouter();
  const { wide } = useResponsive();

  if (!wide) return <ChatBody tab wide={false} tabClear={TAB_BAR} />;
  return (
    <View style={{ flex: 1, flexDirection: "row", backgroundColor: t.canvas }}>
      <View style={{ width: 300, borderRightWidth: 1, borderColor: t.glassBorder }}>
        <ThreadList current="inbox" timeBuckets embedded
          onPick={(id) => { if (id !== "inbox") router.push(`/card/${id}?tab=chat` as never); }} />
      </View>
      <View style={{ flex: 1 }}><ChatBody tab wide /></View>
    </View>
  );
}
