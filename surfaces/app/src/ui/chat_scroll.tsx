import { Ionicons } from "@expo/vector-icons";
import React, { forwardRef, useCallback, useImperativeHandle, useRef, useState } from "react";
import type { StyleProp, ViewStyle } from "react-native";
import { Platform, Pressable, ScrollView, Text, View } from "react-native";

import { useTheme } from "@/theme";

/**
 * THE CHAT SCROLLER - one implementation, every chat surface.
 *
 * The board chat and the card chat had HAND-COPIED versions of this (a ref, an
 * `atBottom` flag, an effect keyed on message count, a "↓ Neueste" pill). Two
 * copies of one behaviour is exactly the shape the owner already ruled out for
 * the transcript and the composer ("never maintain two chat UIs"), and both
 * copies had the same class of defect - so the fix is one component, not two
 * patches.
 *
 * Two bugs died here, and both were the same mistake:
 *
 *  1. THE PILL WAS UNTAPPABLE (owner report 2026-08-31, phone). In the board
 *     chat it was positioned against a wrapper that also held the whole
 *     composer stack - context meter, usage line, QuestionPanel, composer.
 *     Measured on the real UI at 390x700: that stack is 549px tall, so
 *     `bottom: 96` put the pill INSIDE it. The pill still SHOWED (Android
 *     `elevation` and a transparent composer background both paint it), but
 *     hit-testing follows TREE order, not paint order: the composer stack is a
 *     later sibling, so it swallowed every tap. `document.elementFromPoint` at
 *     the pill's own centre returned the QuestionPanel, not the pill.
 *     The pill now lives INSIDE this component, whose only other child is the
 *     ScrollView - there is no sibling left that can cover it.
 *
 *  2. AUTO-SCROLL WAS KEYED ON A PROXY. Both copies ran an effect on
 *     `messages.length`, which is not the thing that moves the bottom edge.
 *     Content grows without the count changing - a streaming reply, a markdown
 *     block laying out, a tool card expanding, the keyboard shrinking the
 *     viewport - and every one of those left the newest text below the fold.
 *     `onContentSizeChange`/`onLayout` are the runtime's OWN signals for
 *     "the scrollable geometry moved" and are what this pins to now
 *     (CLAUDE.md: derived from the runtime, never reconstructed from a proxy).
 */

/** Distance from the bottom (px) still counted as "following the conversation".
 *  One line of body text - below that a reader is at the end, not browsing. */
const PIN_SLACK = 60;

export interface ChatScrollHandle {
  /** Jump to the newest message. Used for the owner's OWN send, which pins
   *  unconditionally: he just wrote it, he wants to see it land. */
  toBottom: (animated?: boolean) => void;
}

export const ChatScroll = forwardRef<ChatScrollHandle, {
  children: React.ReactNode;
  /** "Neueste" / "Latest" - passed in so this owns no dictionary key and the
   *  two callers keep the strings they already ship. */
  label: string;
  contentContainerStyle?: StyleProp<ViewStyle>;
  style?: StyleProp<ViewStyle>;
}>(function ChatScroll({ children, label, contentContainerStyle, style }, ref) {
  const t = useTheme();
  const scroll = useRef<ScrollView>(null);
  // The pill's visibility is STATE (it renders); the same fact is mirrored in a
  // ref because the scroll callbacks below fire outside React's render cycle
  // and a stale closure there is how "it scrolled once and then stopped" gets
  // written.
  const pinned = useRef(true);
  const [atBottom, setAtBottom] = useState(true);

  const toBottom = useCallback((animated = true) => {
    pinned.current = true;
    setAtBottom(true);
    scroll.current?.scrollToEnd({ animated });
  }, []);
  useImperativeHandle(ref, () => ({ toBottom }), [toBottom]);

  // The runtime says the content (or the viewport) moved. If the reader was at
  // the end, keep him there - unanimated, because this fires mid-stream and an
  // animation per token reads as a shudder.
  const follow = useCallback(() => {
    if (pinned.current) scroll.current?.scrollToEnd({ animated: false });
  }, []);

  const onScroll = (e: {
    nativeEvent: { contentOffset: { y: number }; contentSize: { height: number };
                   layoutMeasurement: { height: number } };
  }) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    const next = contentSize.height - contentOffset.y - layoutMeasurement.height < PIN_SLACK;
    pinned.current = next;
    setAtBottom((prev) => (prev === next ? prev : next));
  };

  return (
    <View style={{ flex: 1 }}>
      <ScrollView ref={scroll} onScroll={onScroll} scrollEventThrottle={16}
        onContentSizeChange={follow} onLayout={follow}
        style={[{ flex: 1 }, style]} contentContainerStyle={contentContainerStyle}>
        {children}
      </ScrollView>
      {/* Sibling of the ScrollView and of NOTHING else - see the note above.
          Positioned against this wrapper, whose bottom edge IS the top of
          whatever the screen stacks below (composer, question panel), so a
          small inset is all it ever needs and there is no keyboard maths. */}
      {!atBottom ? (
        <Pressable onPress={() => toBottom(true)} accessibilityRole="button" accessibilityLabel={label}
          style={{ position: "absolute", right: 14, bottom: 12, flexDirection: "row", alignItems: "center", gap: 4,
            backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 16,
            paddingHorizontal: 12, paddingVertical: 7,
            ...(Platform.OS === "web" ? {} : { elevation: 6 }) }}>
          <Ionicons name="arrow-down" size={14} color={t.accent} />
          <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{label}</Text>
        </Pressable>
      ) : null}
    </View>
  );
});
