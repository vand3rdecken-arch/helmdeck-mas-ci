/** PRESENCE heartbeat (Paseo adoption, Phase 2.1).
 *
 *  Tells the daemon whether the owner is actually here and which card is on
 *  screen, so it can stay quiet about a card he is already looking at instead
 *  of buzzing his phone about his own work. The policy itself lives in
 *  daemon/presence.py + notify.should_push; this file only reports facts.
 *
 *  The one subtlety worth keeping: the heartbeat TICK never counts as user
 *  activity. `lastActivityAt` moves only when the human actually does
 *  something (opens a card, sends, switches to the app), so an app left open
 *  on a desk goes stale after the daemon's freshness window and notifications
 *  resume - which is the correct behaviour, and the reason presence is not
 *  simply "is a socket connected".
 */
import { useEffect, useRef } from "react";
import { AppState, Platform } from "react-native";
import { create } from "zustand";

import { api } from "./client";
import { useConfig } from "./config";

/** Daemon counts a client as present for 3 minutes after its last real
 *  activity; beat well inside that so a few dropped beats are harmless. */
const BEAT_MS = 15_000;

/** The Henry chat reports focus like a card screen does, so the daemon can tell
 *  "he is reading the answer" from "a window is open somewhere" - the
 *  distinction notify.chat_reply needs and did not have (every Henry reply was
 *  suppressed as 'inapp' for a day). Must equal presence.CHAT in
 *  spine/comms/presence.py; no card id can collide, they all start with a date. */
export const CHAT_FOCUS = "chat";

interface PresenceState {
  focusedCard: string | null;
  lastActivityAt: number;
  /** the card currently on screen (null when the owner is elsewhere) */
  setFocusedCard: (id: string | null) => void;
  /** the human did something - the only thing that refreshes presence */
  noteActivity: () => void;
}

export const usePresence = create<PresenceState>((set) => ({
  focusedCard: null,
  lastActivityAt: Date.now(),
  setFocusedCard: (id) => set({ focusedCard: id, lastActivityAt: Date.now() }),
  noteActivity: () => set({ lastActivityAt: Date.now() }),
}));

async function beat(visible: boolean): Promise<void> {
  const { focusedCard, lastActivityAt } = usePresence.getState();
  try {
    await api.post("/presence", {
      device: Platform.OS,
      focused_card: focusedCard,
      app_visible: visible,
      // seconds, to match the daemon's time.time()
      last_activity_at: lastActivityAt / 1000,
    });
  } catch {
    // Presence is an optimisation, never a user-visible failure: offline or a
    // sleeping relay simply means the daemon assumes we are away and pushes,
    // which is the safe direction to be wrong in.
  }
}

/** Mount once in the root layout. */
export function usePresenceHeartbeat(): void {
  const visible = useRef(true);
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer) return;
      timer = setInterval(() => {
        if (useConfig.getState().hydrated) void beat(visible.current);
      }, BEAT_MS);
    };
    const stop = () => {
      if (timer) { clearInterval(timer); timer = null; }
    };
    start();
    void beat(true);

    const sub = AppState.addEventListener("change", (st) => {
      const active = st === "active";
      visible.current = active;
      if (active) {
        // coming back IS user activity, and the daemon should learn we are
        // here immediately rather than up to a beat later
        usePresence.getState().noteActivity();
        start();
      } else {
        // Tell the daemon we are gone BEFORE we stop beating, so a card that
        // finishes while the phone is in a pocket actually pushes.
        stop();
        void beat(false);
      }
    });
    return () => { stop(); sub.remove(); };
  }, []);
}
