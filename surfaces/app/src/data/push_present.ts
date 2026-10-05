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
  room?: string,
): ChatPushDecision {
  const isChatReply = kind === "chat";
  const readingItNow = appActive && focusedCard === chatFocusValue;
  // A TEAM-ROOM push (@mention / Henry's answer to you): same WhatsApp/Slack
  // rule - the room screen announces itself as focus "room:<id>", so a push for
  // the room you are reading does not buzz over it. Either way the push is proof
  // that a room message landed, so it wakes the queries.
  const isRoom = kind === "room";
  const readingRoom = isRoom && !!room && appActive && focusedCard === "room:" + room;
  return { wake: isChatReply || isRoom, present: !((isChatReply && readingItNow) || readingRoom) };
}

/** Whether the BACKGROUND notification task should present a data push.
 *
 *  expo-notifications 57 runs that task on EVERY FCM message, foreground
 *  included (FirebaseMessagingDelegate.onMessageReceived calls
 *  runTaskManagerTasks unconditionally) - so while the app was open the task
 *  raised the banner on its own, right past decideChatPush, and a Henry reply
 *  buzzed the very phone showing the chat (owner report 2026-09-25, once the
 *  daemon stopped withholding it). In the foreground the received-listener
 *  in app/_layout.tsx is the one owner of display; the task only covers a
 *  backgrounded or killed app, where no listener runs. A headless start
 *  reports "background" or no state at all - never "active". */
export function backgroundTaskPresents(appState: string | null | undefined): boolean {
  return appState !== "active";
}
