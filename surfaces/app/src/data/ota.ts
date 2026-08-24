/** Silent OTA (Paseo model): the app keeps itself current without ever asking.
 *
 *  - launch:   expo-updates checks on its own (checkAutomatically: ON_LOAD)
 *  - resume:   this hook checks again when the app returns to the foreground
 *              (throttled), downloads in the background, says nothing
 *  - apply:    a downloaded update reloads while the app is BACKGROUNDED - the
 *              one moment a reload is invisible - or on the next cold start
 *  - rollback: the server can answer with a rollBackToEmbedded directive
 *              (ops/deploy/rollback_update.sh --embedded); it rides the exact same
 *              fetch -> pending -> background-reload path
 *
 *  Everything is fire-and-forget: offline, a dead relay or a manifest 404 must
 *  never surface in the UI. Verification that an update landed is the version
 *  panel (Settings) / footer (More), not a prompt. */
import * as Updates from "expo-updates";
import { useEffect, useRef } from "react";
import { AppState } from "react-native";

// Resume-check throttle. Foreground flips happen constantly (notification
// shade, app switcher); one manifest HEAD-sized request per 10 min is plenty.
const MIN_CHECK_MS = 10 * 60 * 1000;

/** True when an update/rollback was downloaded and waits for a reload. Module
 *  state (not React) so the Settings panel can read it without re-render plumbing. */
export const otaPending = { current: false };

async function checkAndFetch(): Promise<void> {
  const r = await Updates.checkForUpdateAsync();
  if (!r.isAvailable && !r.isRollBackToEmbedded) return;
  const f = await Updates.fetchUpdateAsync();
  if (f.isNew || f.isRollBackToEmbedded) otaPending.current = true;
}

/** Mount once in the root layout. No-op in dev / Expo Go / web (isEnabled). */
export function useSilentOta(): void {
  const lastCheck = useRef(0);
  useEffect(() => {
    if (__DEV__ || !Updates.isEnabled) return;
    const sub = AppState.addEventListener("change", (st) => {
      if (st === "active") {
        const now = Date.now();
        if (otaPending.current || now - lastCheck.current < MIN_CHECK_MS) return;
        lastCheck.current = now;
        checkAndFetch().catch(() => {});
      } else if (st === "background" && otaPending.current) {
        // backgrounded with an update staged: reload NOW, out of sight. If the
        // OS kills us before it finishes, the next launch boots the new bundle
        // anyway (it's already on disk). NOT on "inactive" - iOS reports that
        // while the app is still visible (control center, app switcher) and a
        // reload there would be anything but silent.
        Updates.reloadAsync().catch(() => {});
      }
    });
    return () => sub.remove();
  }, []);
}
