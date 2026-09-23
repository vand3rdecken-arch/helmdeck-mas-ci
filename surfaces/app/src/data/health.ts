import { create } from "zustand";

// Connection health, fed by every request in client.ts. One rule: transport
// failures are NEVER silent (the req-dispatch-failure class of bug) - the
// HealthBanner surfaces this store the moment the daemon stops answering, and
// clears it on the first successful round-trip. "Transport" means the wire
// (surfaces/relay/LAN/crypto), not app-level 4xx errors - a 409 proves the daemon is
// reachable and is shown by the caller, not the banner.
export type ConnStatus = "ok" | "reconnecting" | "offline";

// A single dropped long-poll or a relay blip is normal - reconnect SILENTLY
// first (no banner at all) and only go soft ("reconnecting") once failures
// PERSIST past a grace window, escalating to the red "offline" alarm only if
// that persists further still. This is the Paseo behaviour: a brief hiccup -
// one missed long-poll, a WiFi handoff, a relay retry - must never flash a
// banner; only a reconnect that is actually failing shows anything.
const RECONNECT_GRACE_MS = 5_000;    // silent below this - status stays "ok"
const OFFLINE_AFTER_MS = 20_000;     // amber below this, red "offline" above

interface HealthState {
  status: ConnStatus;
  detail: string;        // last transport error, human-readable (German, UI-ready)
  failures: number;      // consecutive transport failures
  lastOkAt: number;      // ms epoch of the last successful round-trip (0 = never)
  firstFailAt: number;   // ms epoch the current failure streak started (0 = none)
  // The last DIAGNOSIS (data/connection_check.ts): an i18n key naming WHICH
  // leg is broken - phone network, relay, daemon, or this device's pairing.
  // This store stays the one owner of "what is the connection state" (owner
  // 2026-09-23: "ist aber nicht health verantwortlich fuer diagnose"); the
  // check is a PROBE that feeds it, not a second source of truth. reportOk
  // clears it, because a working round-trip outranks any older verdict.
  verdictKey: string;
  verdictAt: number;
  reportOk: () => void;
  reportFail: (detail: string) => void;
  reportCheck: (verdictKey: string) => void;
}

export const useHealth = create<HealthState>((set, get) => ({
  status: "ok",
  detail: "",
  failures: 0,
  lastOkAt: 0,
  firstFailAt: 0,
  verdictKey: "",
  verdictAt: 0,
  reportOk: () => {
    if (get().status !== "ok" || !get().lastOkAt) set({ status: "ok", detail: "", failures: 0, firstFailAt: 0, lastOkAt: Date.now(), verdictKey: "", verdictAt: 0 });
    else set({ lastOkAt: Date.now() });
  },
  reportFail: (detail) => set((s) => {
    const now = Date.now();
    const firstFailAt = s.firstFailAt || now;
    const elapsed = now - firstFailAt;
    const status: ConnStatus =
      elapsed < RECONNECT_GRACE_MS ? "ok" : elapsed < OFFLINE_AFTER_MS ? "reconnecting" : "offline";
    return { status, detail, failures: s.failures + 1, firstFailAt };
  }),
  // Written by the diagnosis panel only. It does NOT move `status`: whether
  // the app can talk to the daemon is decided by real traffic, never by a
  // probe's opinion - the check's own sealed round-trip goes through the
  // ordinary client, so a passing check clears the banner via reportOk by
  // itself. This only makes the banner SAY which leg, instead of repeating
  // the generic transport sentence that covered three different causes in
  // one day.
  reportCheck: (verdictKey) => set({ verdictKey, verdictAt: Date.now() }),
}));
