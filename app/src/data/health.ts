import { create } from "zustand";

// Connection health, fed by every request in client.ts. One rule: transport
// failures are NEVER silent (the req-dispatch-failure class of bug) - the
// HealthBanner surfaces this store the moment the daemon stops answering, and
// clears it on the first successful round-trip. "Transport" means the wire
// (relay/LAN/crypto), not app-level 4xx errors - a 409 proves the daemon is
// reachable and is shown by the caller, not the banner.
export type ConnStatus = "ok" | "offline";

interface HealthState {
  status: ConnStatus;
  detail: string;        // last transport error, human-readable (German, UI-ready)
  failures: number;      // consecutive transport failures
  lastOkAt: number;      // ms epoch of the last successful round-trip (0 = never)
  reportOk: () => void;
  reportFail: (detail: string) => void;
}

export const useHealth = create<HealthState>((set, get) => ({
  status: "ok",
  detail: "",
  failures: 0,
  lastOkAt: 0,
  reportOk: () => {
    if (get().status !== "ok" || !get().lastOkAt) set({ status: "ok", detail: "", failures: 0, lastOkAt: Date.now() });
    else set({ lastOkAt: Date.now() });
  },
  reportFail: (detail) => set((s) => ({ status: "offline", detail, failures: s.failures + 1 })),
}));
