import * as WebBrowser from "expo-web-browser";

/** Public feedback board (owner picked Userjot). Empty string = the
 *  "Feedback geben" row in More stays hidden (no dead link for testers). */
export const FEEDBACK_BOARD_URL = "https://helmdeck.userjot.com";

/** In-app browser tab (Custom Tab / SFSafariViewController) so the tester
 *  stays "inside" the app; falls back to a normal tab on web. */
export function openFeedbackBoard() {
  if (!FEEDBACK_BOARD_URL) return;
  WebBrowser.openBrowserAsync(FEEDBACK_BOARD_URL).catch(() => {});
}
