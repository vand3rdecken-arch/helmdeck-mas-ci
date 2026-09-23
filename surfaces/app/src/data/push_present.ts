/** WHETHER a decrypted push should be shown as a visible notification, and
 *  whether it should wake the chat transcript.
 *
 *  Pure and import-free, same reasoning as push_route.ts: this used to be
 *  inline in the foreground listener in app/_layout.tsx, where the only way
 *  to check the WhatsApp/Slack-style "don't buzz the screen you're already
 *  reading" rule was a real device with the chat open and a real Henry turn
 *  in flight - and the daemon has its OWN version of this same call
 *  (spine/comms/presence.py chat_readers) that races a 15s/30s heartbeat, so
 *  the client re-deciding it from what is certainly on screen RIGHT NOW is
 *  the belt to that suspenders' braces, not a duplicate of it.
 *
 *  `wake` fires on every chat reply regardless of focus - the push IS the
 *  daemon's own proof the transcript moved, and arrives over FCM, a channel
 *  independent of the app's own long-poll/relay session; asking the chat
 *  query to refetch the moment the push lands closes whatever gap that
 *  session is behind by (owner report 2026-09-23, "Push kommt sofort, Chat
 *  laedt per Spinner nach"), instead of waiting on that poll to catch up on
 *  its own.
 *
 *  Exercised by surfaces/app/test_push_present.js.
 */
export interface ChatPushDecision {
  /** Refetch the chat transcript now - the push is the wake-up signal. */
  wake: boolean;
  /** Show/announce the notification. False only when the owner is
   *  demonstrably reading the chat this instant. */
  present: boolean;
}

export function decideChatPush(
  kind: string | undefined,
  focusedCard: string | null | undefined,
  chatFocusValue: string,
  appActive: boolean,
): ChatPushDecision {
  const isChatReply = kind === "chat";
  const readingItNow = appActive && focusedCard === chatFocusValue;
  return { wake: isChatReply, present: !(isChatReply && readingItNow) };
}
