import * as WebBrowser from "expo-web-browser";

/** Public feedback board (Canny or Userjot). Owner decides the tool and board;
 *  paste the board URL here and the "Feedback geben" row in More appears.
 *  Empty string = feature hidden (no dead link for testers). */
export const FEEDBACK_BOARD_URL = "";

/** In-app browser tab (Custom Tab / SFSafariViewController) so the tester
 *  stays "inside" the app; falls back to a normal tab on web. */
export function openFeedbackBoard() {
  if (!FEEDBACK_BOARD_URL) return;
  WebBrowser.openBrowserAsync(FEEDBACK_BOARD_URL).catch(() => {});
}
