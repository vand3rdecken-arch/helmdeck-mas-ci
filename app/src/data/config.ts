import { Platform } from "react-native";
import { create } from "zustand";

// Where the app talks to the daemon. On web the daemon is reachable at
// localhost; the Android emulator reaches the host machine via 10.0.2.2.
// Phase 0 defaults to the mock board (tools/mock_board.py, no auth) so the UI
// can be exercised before pairing/token auth lands in Phase 3.
const DEV_HOST = Platform.OS === "android" ? "10.0.2.2" : "localhost";

interface ConfigState {
  baseUrl: string;   // e.g. http://10.0.2.2:8140 (LAN) or a relay-backed URL
  token: string;     // device token (Bearer); empty in Phase 0 mock mode
  set: (patch: Partial<Pick<ConfigState, "baseUrl" | "token">>) => void;
}

export const useConfig = create<ConfigState>((set) => ({
  baseUrl: `http://${DEV_HOST}:8199`,
  token: "",
  set: (patch) => set(patch),
}));
