import { useEffect, useRef, useState } from "react";
import { Keyboard, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import type { ReplyRef, SteerOpts } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Composer, type Recipient } from "@/ui/card_composer";
import { Transcript, type TStep } from "@/ui/card_transcript";
import { ChatScroll, type ChatScrollHandle } from "@/ui/chat_scroll";
import { Empty } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

type ComposerProps = React.ComponentProps<typeof Composer>;

// THE conversation body: scroll + transcript + composer + keyboard spacer. Every
// thread kind that is "a chat with Henry" draws this and nothing else - a team
// room, a restricted account's private Henry, the board chat (and, in a later
// step, the card chat). A screen supplies its header, its rows (TStep[]) and how
// a send leaves the device; it never owns a scroller, a keyboard listener or a
// composer of its own (owner 2026-10-09: "ich will nicht verschiedene
// Chat-Module maintainen"). What only one thread has (a live thinking row, a
// pending question, a context meter) rides in through the slots below - the
// body stays one component.
export interface ChatSurfaceProps {
  steps: TStep[];
  me?: string;
  loading?: boolean;
  /** shown instead of the transcript while there is nothing to show */
  empty?: React.ReactNode;
  /** the caller's own "nothing to show" verdict (a welcome row, a live stream);
   *  default: no steps and not loading */
  isEmpty?: boolean;
  onSend: ComposerProps["onSend"];
  placeholder: string;
  draftKey: string;
  /** the @ roster; omitted = no popover and no recipient chip */
  recipients?: Recipient[];
  /** a send error line above the composer */
  error?: string;
  /** rendered between the header and the scroller (a panel that belongs to the thread) */
  top?: React.ReactNode;
  /** inside the scroller, after the transcript (a live "thinking" row) */
  afterTranscript?: React.ReactNode;
  /** above the composer, in the thread's column (meter, question panel, strips) */
  aboveComposer?: React.ReactNode;
  /** hide model / thinking / mode / attachment controls the answerer ignores */
  minimal?: boolean;
  busy?: boolean;
  onStop?: () => void;
  models?: ComposerProps["models"];
  /** the rest of the composer's own props a thread may set (quote, mode, recipients' default ...) */
  composer?: Partial<Omit<ComposerProps, "onSend" | "placeholder" | "draftKey" | "models" | "busy" | "onStop" | "minimal" | "bottomInset" | "recipients">>;
  /** Transcript extras */
  ctxWindow?: number;
  /** messenger-style replies (swipe / arrow on a bubble -> quote bar -> `reply_to`
   *  on the next send). The surface owns the state; a thread turns it on only if
   *  its backend stores the quote. */
  replies?: boolean;
  /** widest the column grows on a wide window (default 760); null = never capped (the card pane) */
  colMax?: number | null;
  /** room under the last message (default 24; the card pane keeps its 20) */
  scrollPad?: number;
  /** the screen's own bottom inset when it is not the plain safe-area one */
  bottomInset?: number;
  /** a user row's "rewind": put its text back into the composer */
  onRewind?: React.ComponentProps<typeof Transcript>["onRewind"];
  /** space reserved under the composer for a floating tab bar */
  tabClear?: number;
  /** the screen may hold the scroll handle (pin to newest after its own send) */
  scrollRef?: React.RefObject<ChatScrollHandle | null>;
  /** older history: called when the reader reaches the top; `topNote` sits above the transcript */
  onReachTop?: () => void;
  topNote?: React.ReactNode;
}

export function ChatSurface({ steps, me, loading, empty, isEmpty, onSend, placeholder, draftKey, recipients, error,
  top, afterTranscript, aboveComposer, minimal, busy, onStop, models, composer, ctxWindow, replies, onRewind, colMax, tabClear,
  bottomInset, scrollPad, scrollRef, onReachTop, topNote }: ChatSurfaceProps) {
  const t = useTheme();
  // THE MESSAGE BEING ANSWERED (owner 2026-09-25): attached to exactly the next
  // send (or live steer) and cleared by it. A mirrored card message answers THAT card.
  const [replyTo, setReplyTo] = useState<ReplyRef | null>(null);
  const withReply = (o: SteerOpts): SteerOpts => {
    if (!replies || !replyTo) return o;
    const q = replyTo;
    setReplyTo(null);
    return { ...o, reply_to: { text: q.text, by: q.by, seq: q.seq }, ...(q.card ? { to: `card:${q.card}` } : {}) };
  };
  const onReply = replies
    ? (st: TStep) => setReplyTo({ text: (st.text || st.label || "").trim().slice(0, 300),
        by: st.by || (st.byKind === "henry" ? "Henry" : undefined), seq: st.seq, card: st.card })
    : undefined;
  const tr = useT();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const own = useRef<ChatScrollHandle>(null);
  const scroll = scrollRef ?? own;
  const col = colMax === null ? undefined : (colMax ?? (wide ? 760 : undefined));

  // manual keyboard spacer (Android edge-to-edge ignores adjustResize): works on
  // both platforms without a native lib
  const [kb, setKb] = useState(0);
  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", (e) => setKb(e.endCoordinates.height));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(0));
    return () => { show.remove(); hide.remove(); };
  }, []);

  const nothing = isEmpty ?? (steps.length === 0 && !loading);
  return (
    <View style={{ flex: 1 }}>
      {top}
      <View style={{ flex: 1 }}>
        <ChatScroll ref={scroll} label={tr("chat.latest")} onReachTop={onReachTop}
          contentContainerStyle={{ padding: 12, paddingBottom: scrollPad ?? 24, width: "100%", maxWidth: col, alignSelf: "center" }}>
          {nothing ? null : topNote}
          {nothing
            ? (empty ?? <Empty text={tr("chat.empty")} />)
            : <Transcript me={me} steps={steps} ctxWindow={ctxWindow} onReply={onReply} onRewind={onRewind}
                onJump={(y) => scroll.current?.toY(y)} />}
          {afterTranscript}
        </ChatScroll>
        <View style={{ width: "100%", maxWidth: col, alignSelf: "center" }}>
          {aboveComposer}
          {error ? <Text style={{ color: t.danger, fontSize: 12, paddingHorizontal: 16, paddingBottom: 4 }}>{error}</Text> : null}
          <Composer {...composer} quote={replyTo} onClearQuote={() => setReplyTo(null)}
            onSteerLive={composer?.onSteerLive ? (txt, o) => composer.onSteerLive!(txt, withReply(o)) : undefined}
            onSend={(txt, o) => { scroll.current?.toBottom(); return onSend(txt, withReply(o)); }} models={models ?? ["auto"]} minimal={minimal} busy={busy} onStop={onStop}
            placeholder={placeholder} draftKey={draftKey} recipients={recipients}
            bottomInset={kb > 0 ? (bottomInset ?? insets.bottom) + 10 : (bottomInset ?? insets.bottom + 8)} />
        </View>
        {kb > 0 ? <View style={{ height: kb }} /> : tabClear ? <View style={{ height: tabClear }} /> : null}
      </View>
    </View>
  );
}
