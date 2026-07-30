import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { create } from "zustand";
import { generateKeyPair } from "./e2ee";

// Where/how the app talks to the daemon:
//   - relay mode (relayUrl+room+daemonPub set): each request is NaCl-sealed and
//     POSTed to the relay (the phone's zero-knowledge tunnel to the desktop).
//   - direct mode: plain Bearer-token HTTP to baseUrl (LAN / web same host).
// Phase 0 defaulted to the mock; real use pairs via a code (applyPairing).
const DEV_HOST = Platform.OS === "android" ? "10.0.2.2" : "localhost";
const KEY = "swarmdeck.config";

interface Persisted {
  baseUrl: string; token: string;
  relayUrl: string; room: string; daemonPub: string; mySec: string; myPub: string;
}
interface ConfigState extends Persisted {
  hydrated: boolean;
  relayMode: () => boolean;
  set: (patch: Partial<Persisted>) => void;
  applyPairing: (code: string) => boolean;
  hydrate: () => Promise<void>;
}

const DEFAULTS: Persisted = {
  baseUrl: `http://${DEV_HOST}:8199`, token: "",
  relayUrl: "", room: "", daemonPub: "", mySec: "", myPub: "",
};

async function persist(s: Persisted) {
  try { await SecureStore.setItemAsync(KEY, JSON.stringify(s)); } catch { /* web / unavailable */ }
}

export const useConfig = create<ConfigState>((set, get) => ({
  ...DEFAULTS,
  hydrated: false,
  relayMode: () => !!(get().relayUrl && get().room && get().daemonPub),
  set: (patch) => { set(patch); const { baseUrl, token, relayUrl, room, daemonPub, mySec, myPub } = get(); persist({ baseUrl, token, relayUrl, room, daemonPub, mySec, myPub }); },

  // Pairing code (base64 JSON {u:relayUrl, r:room, k:daemonPub, t:deviceToken}),
  // matching daemon relay_client.pairing_payload() / the Kotlin HubStore parser.
  applyPairing: (raw) => {
    try {
      let code = raw.trim();
      if (code.includes("c=")) code = decodeURIComponent(code.split("c=")[1].split("&")[0]);
      const norm = code.replace(/-/g, "+").replace(/_/g, "/");
      const o = JSON.parse(atob(norm)); // Hermes + web both provide atob
      if (!o.u || !o.r || !o.k) return false;
      let { mySec, myPub } = get();
      if (!mySec || !myPub) { const kp = generateKeyPair(); mySec = kp.sec; myPub = kp.pub; }
      get().set({ relayUrl: String(o.u).replace(/\/+$/, ""), room: o.r, daemonPub: o.k, token: o.t ?? "", mySec, myPub });
      return true;
    } catch { return false; }
  },

  hydrate: async () => {
    try {
      const raw = await SecureStore.getItemAsync(KEY);
      if (raw) set({ ...JSON.parse(raw) });
    } catch { /* ignore */ }
    set({ hydrated: true });
  },
}));
