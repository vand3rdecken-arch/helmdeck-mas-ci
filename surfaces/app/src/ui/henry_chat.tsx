import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useRef } from "react";
import { Platform, Pressable, View, type ViewStyle } from "react-native";

import { CopilotOverlay, useCopilotPanel, type ChatContext } from "@/app/chat";
import { api } from "@/data/client";
import { useCellEnabled } from "@/data/cells";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { useResponsive } from "@/ui/responsive";

/**
 * THE ONE HENRY ENTRY POINT (owner decree 2026-09-03: "das soll ein
 * Chat-Fenster wie auf dem Board sein, nicht ein Button überall").
 *
 * Board, dashboard, Prozesse and the harness map had each hand-copied the same
 * 20 lines of FAB - five copies of one decision, so the sixth screen that
 * wanted a chat entry had to copy it again, and any correction had to be made
 * five times. This is that decision, once. It is NOT a second chat: it opens
 * the SHIPPED CopilotOverlay hosting the SHIPPED chat body (same session, same
 * transcript, same composer), exactly as every copy did.
 *
 * The `context` a screen hands over is what the chat was opened ABOUT - it
 * renders as the chip above the composer and rides along with the turn, so
 * Henry knows WHICH door/connector/board without the owner naming it. That is
 * what makes a settings screen's chat entry worth more than a link to /chat:
 * "mach das aus" is answerable on the Autonomie door and meaningless on a bare
 * chat screen.
 */

/** Open Henry carrying an optional subject. Desktop docks the in-page panel
 *  over the dimmed screen; the phone takes the /chat route - one chat, two
 *  hosts, the split the board FAB has always used. */
export function useOpenHenry(): (ctx?: ChatContext) => void {
  const router = useRouter();
  const { wide } = useResponsive();
  return useCallback((ctx?: ChatContext) => {
    const panel = useCopilotPanel.getState();
    // On the phone only the CONTEXT is handed over. show() would additionally
    // set `open`, which the phone never reads - and which would then arm the
    // desktop overlay behind the /chat route for the next resize.
    if (wide) panel.show(ctx);
    else { panel.setContext(ctx); router.push("/chat" as never); }
  }, [router, wide]);
}

/** First-run nudge, mirroring Jira/Trello's guided sample board: Henry drives
 * himself out instead of waiting for a tap, the one time there is something
 * to introduce. DERIVED, not a stored "have we shown this" flag (CLAUDE.md) -
 * it fires exactly while BOTH facts the runtime already owns are still true:
 * the seeded onboarding card (dispatch.seed_example_card, `example: true`) is
 * still on the board, and Henry has never actually been talked to
 * (/chat/history empty). Either one clearing - the owner deletes the sample
 * card, or sends a real message - retires the nudge on its own; nothing here
 * has to remember it already ran. `firedRef` only stops it opening twice for
 * the SAME still-true condition within one mount (e.g. a stray refetch),
 * never suppresses a later, still-warranted open. */
export function useAutoOpenHenryWelcome() {
  const open = useOpenHenry();
  const enabled = useCellEnabled("copilot");
  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks, enabled, staleTime: 5000 });
  const hasExample = (tracks ?? []).some((k) => k.example);
  const { data: history } = useQuery({
    queryKey: ["chatHistory"], queryFn: api.chatHistory,
    enabled: enabled && hasExample, staleTime: 60000,
  });
  const firedRef = useRef(false);
  useEffect(() => {
    if (!enabled || !hasExample || firedRef.current || !history) return;
    if ((history.messages?.length ?? 0) > 0) return;
    firedRef.current = true;
    open();
  }, [enabled, hasExample, history, open]);
}

/** The launcher button itself, unpositioned - for a screen that already has a
 *  FAB stack to sit in (the board's "+ Neu" column). Self-gates on the copilot
 *  cell: Henry's entry point is a FAB, not a route, so it has no nav.tabs entry
 *  for (tabs)/_layout.tsx to hide and must gate itself. */
export function HenryFab({ context, style, testID }:
  { context?: ChatContext; style?: ViewStyle; testID?: string }) {
  const t = useTheme();
  const tr = useT();
  const open = useOpenHenry();
  const enabled = useCellEnabled("copilot");
  if (!enabled) return null;
  return (
    <Pressable testID={testID} onPress={() => open(context)}
      accessibilityLabel={tr("chat.askHenry")}
      style={[{ width: 48, height: 48, borderRadius: 15, backgroundColor: t.surface1,
        borderWidth: 1, borderColor: t.borderSubtle, alignItems: "center", justifyContent: "center",
        ...(Platform.OS === "web" ? { boxShadow: "0 4px 14px rgba(0,0,0,0.3)" } as any : { elevation: 4 }) }, style]}>
      <Ionicons name="chatbubble-ellipses-outline" size={20} color={t.accent} />
    </Pressable>
  );
}

/** The whole entry point for a plain screen: the floating launcher bottom-right
 *  plus the overlay it opens. Drop ONE of these at the end of a screen's root
 *  View and that screen has the board's chat.
 *
 *  `bottom` defaults to the tab-bar-aware offset a (tabs) screen needs; a root
 *  route (no tab bar) passes 24, which is what loopmap.tsx used. */
export function HenryChat({ context, bottom, testID }:
  { context?: ChatContext; bottom?: number; testID?: string }) {
  const { wide } = useResponsive();
  return (
    <>
      <View style={{ position: "absolute", right: 18, bottom: bottom ?? (wide ? 24 : 84) }}>
        <HenryFab context={context} testID={testID} />
      </View>
      {/* self-guards on !wide || !open (chat.tsx), so mounting it costs nothing
          on the phone and nothing while the panel is closed. */}
      <CopilotOverlay />
    </>
  );
}
