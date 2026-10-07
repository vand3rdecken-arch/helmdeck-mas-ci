// Dictation cleanup, app half (daemon half: spine/media/dictation_cleanup.py).
//
// The flow is TWO-PHASE on purpose: the raw transcript is inserted the moment the
// recording ends (instant, what the owner expects), and the cleaned version swaps
// in a few seconds later - the model call is a 5-10 s CLI spawn, far too slow to
// wait for. That makes the swap the dangerous part: the owner may have typed on,
// sent, or started another dictation in those seconds. So the swap happens ONLY
// where the raw dictation still sits verbatim, and everything around it is kept.
// No React / react-native import: pure, run by data/__dictation_selftest__.ts.

export interface CleanResult { text: string; changed: boolean; skipped?: string | null; ms?: number }

/** Replace the LAST occurrence of `from` in `current` by `to`; null when `from`
 *  is gone (edited, sent, cleared) or the swap would change nothing. */
export function swapOnce(current: string, from: string, to: string): string | null {
  if (!from || !to || from === to) return null;
  const i = current.lastIndexOf(from);
  if (i < 0) return null;
  return current.slice(0, i) + to + current.slice(i + from.length);
}

/** raw -> cleaned, inside whatever the field holds now. */
export const applyCleanup = swapOnce;
/** cleaned -> raw again (the "Rückgängig" button). */
export const undoCleanup = swapOnce;
