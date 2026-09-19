/** WHERE a tapped notification lands.
 *
 *  Pure and import-free on purpose. This decision used to live inline in the
 *  response listener in app/_layout.tsx, where the only way to check it was to
 *  install a build and tap a real notification - and it is a five-way decision
 *  whose two subtle cases have BOTH already been reported as bugs:
 *
 *    * a tap we cannot read must navigate NOWHERE. Android bundles same-titled
 *      notifications into a stack and tapping the stack's own summary line
 *      delivers empty data; that used to land on the dashboard even when a real
 *      card push had just opened (measured 2026-08-24).
 *    * a Henry answer (kind "chat") carries NO card by construction, so the
 *      trackless fallback would drop the owner on the dashboard - one tab away
 *      from the answer he tapped (owner report 2026-08-29).
 *
 *  Returns a descriptor instead of calling the router, so it cannot acquire a
 *  dependency on one and a test can read the destination directly.
 *  Exercised by surfaces/app/test_push_route.js.
 */
export interface PushRoute {
  pathname: string;
  params?: Record<string, string>;
}

/** The sealed payload's routable fields, as notify.py writes them. */
export interface PushTarget {
  track?: string;
  kind?: string;
  body?: string;
}

export function pushRoute(m: PushTarget): PushRoute | null {
  const track = m.track || "";
  const kind = m.kind || "";
  // Nothing to route on: the bundled-summary tap above. Deliberately null and
  // not a dashboard fallback - "we could not read this" is not a destination.
  if (!track && !kind) return null;
  // A finished task lands in the board chat: since c50097e8 (2026-09-18) the
  // card's own result is written there when it is accepted, so a DONE tap just
  // opens the chat where the answer already sits. Until then it opened voice
  // mode with a synthetic "sag mir kurz das Ergebnis" question in the owner's
  // name (owner 2026-08-22) - now a duplicate, and one the owner asked to have
  // removed (2026-09-19): a fake question of his plus a spoken re-summary of a
  // result he can already read.
  if (kind === "done" && track) return { pathname: "/chat" };
  // HENRY ANSWERED (notify.chat_reply): the news IS the chat, so land in it.
  if (kind === "chat") return { pathname: "/chat" };
  // A question/needs_you/bounced push is news in THAT CARD's chat, so land
  // there directly instead of the overview tab he would have to switch past.
  if (track) return { pathname: "/card/[id]", params: { id: track, tab: "chat" } };
  // Read, but about no card - a goal-level PM escalation. The dashboard IS the
  // index tab (since 2026-08-17) and carries the PM summary.
  return { pathname: "/(tabs)" };
}
