import { useEffect, useRef, useState } from "react";
import { Keyboard, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import type { SteerOpts } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Composer, type Recipient } from "@/ui/card_composer";
import { Transcript, type TStep } from "@/ui/card_transcript";
import { ChatScroll, type ChatScrollHandle } from "@/ui/chat_scroll";
import { Empty } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

// THE conversation body: scroll + transcript + composer + keyboard spacer. Every
// thread kind that is "a chat with Henry" draws this and nothing else - a team
// room, a restricted account's private Henry, and (step by step) the board and
// card chats. A screen supplies its header, its rows (TStep[]) and how a send
// leaves the device; it never owns a scroller, a keyboard listener or a
// composer of its own (owner 2026-10-09: "ich will nicht verschiedene
// Chat-Module maintainen").
export interface ChatSurfaceProps {
  steps: TStep[];
  me?: string;
  loading?: boolean;
  /** shown instead of the transcript while there is nothing to show */
  empty?: React.ReactNode;
  onSend: (text: string, opts: SteerOpts) => void | Promise<void>;
  placeholder: string;
  draftKey: string;
  /** the @ roster; omitted = no popover and no recipient chip */
  recipients?: Recipient[];
  /** a send error line above the composer */
  error?: string;
  /** rendered between the header and the scroller (a panel that belongs to the thread) */
  top?: React.ReactNode;
  /** hide model / thinking / mode / attachment controls the answerer ignores */
  minimal?: boolean;
  busy?: boolean;
  onStop?: () => void;
  models?: React.ComponentProps<typeof Composer>["models"];
  /** bumped by the screen to pin the view to the newest message (own send) */
  scrollRef?: React.RefObject<ChatScrollHandle | null>;
}

export function ChatSurface({ steps, me, loading, empty, onSend, placeholder, draftKey, recipients, error,
  top, minimal, busy, onStop, models, scrollRef }: ChatSurfaceProps) {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const own = useRef<ChatScrollHandle>(null);
  const scroll = scrollRef ?? own;

  // manual keyboard spacer, same as chat.tsx (works on both platforms, no native lib)
  const [kb, setKb] = useState(0);
  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", (e) => setKb(e.endCoordinates.height));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(0));
    return () => { show.remove(); hide.remove(); };
  }, []);

  return (
    <View style={{ flex: 1 }}>
      {top}
      <View style={{ flex: 1 }}>
        <ChatScroll ref={scroll} label={tr("chat.latest")}
          contentContainerStyle={{ padding: 12, paddingBottom: 24, width: "100%", maxWidth: wide ? 760 : undefined, alignSelf: "center" }}>
          {steps.length === 0 && !loading
            ? (empty ?? <Empty text={tr("chat.empty")} />)
            : <Transcript me={me} steps={steps} onJump={(y) => scroll.current?.toY(y)} />}
        </ChatScroll>
        {error ? <Text style={{ color: t.danger, fontSize: 12, paddingHorizontal: 16, paddingBottom: 4 }}>{error}</Text> : null}
        <Composer onSend={(txt, o) => { scroll.current?.toBottom(); return onSend(txt, o); }}
          models={models ?? ["auto"]} minimal={minimal} busy={busy} onStop={onStop}
          placeholder={placeholder} draftKey={draftKey} recipients={recipients}
          bottomInset={kb > 0 ? insets.bottom + 10 : insets.bottom + 8} />
        {kb > 0 ? <View style={{ height: kb }} /> : null}
      </View>
    </View>
  );
}
