import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { create } from "zustand";
import { t } from "@/i18n/core";

import { generateKeyPair } from "./e2ee";

// Where/how the app talks to the daemon:
//   - relay mode (relayUrl+room+daemonPub set): each request is NaCl-sealed and
//     POSTed to the relay (the phone's zero-knowledge tunnel to the desktop).
//   - direct mode: plain Bearer-token HTTP to baseUrl (LAN / web same host).
// Phase 0 defaulted to the mock; real use pairs via a code (applyPairing).
const DEV_HOST = Platform.OS === "android" ? "10.0.2.2" : "localhost";
const KEY = "helmdeck.config";

interface Persisted {
  baseUrl: string; token: string;
  relayUrl: string; room: string; daemonPub: string; mySec: string; myPub: string;
}
interface ConfigState extends Persisted {
  hydrated: boolean;
  relayMode: () => boolean;
  set: (patch: Partial<Persisted>) => void;
  applyPairing: (code: string) => PairResult;
  hydrate: () => Promise<void>;
}

// ok=false always carries WHY (bad format vs missing fields) - the screens
// show the reason instead of a generic "failed" (no silent fallback).
export type PairResult = { ok: true; mode: "relay" | "direct" } | { ok: false; reason: string };

const DEFAULTS: Persisted = {
  baseUrl: `http://${DEV_HOST}:8140`, token: "",   // the daemon serves on 8140
  relayUrl: "", room: "", daemonPub: "", mySec: "", myPub: "",
};

const isWeb = Platform.OS === "web";

async function persist(s: Persisted) {
  const json = JSON.stringify(s);
  try {
    if (isWeb) globalThis.localStorage?.setItem(KEY, json);
    else await SecureStore.setItemAsync(KEY, json);
  } catch { /* unavailable */ }
}

export const useConfig = create<ConfigState>((set, get) => ({
  ...DEFAULTS,
  hydrated: false,
  relayMode: () => !!(get().relayUrl && get().room && get().daemonPub),
  set: (patch) => { set(patch); const { baseUrl, token, relayUrl, room, daemonPub, mySec, myPub } = get(); persist({ baseUrl, token, relayUrl, room, daemonPub, mySec, myPub }); },

  // Pairing code (base64 JSON {u:relayUrl, r:room, k:daemonPub, t:deviceToken}),
  // matching daemon relay_client.pairing_payload() / the Kotlin HubStore parser.
  applyPairing: (raw) => {
    if (!raw.trim()) return { ok: false, reason: t("pair.empty") };
    let o: { b?: string; u?: string; r?: string; k?: string; t?: string };
    try {
      let code = raw.trim();
      if (code.includes("c=")) code = decodeURIComponent(code.split("c=")[1].split("&")[0]);
      const norm = code.replace(/-/g, "+").replace(/_/g, "/");
      o = JSON.parse(atob(norm)); // Hermes + web both provide atob
    } catch {
      return { ok: false, reason: t("pair.badFormat") };
    }
    // Direct invite {b: baseUrl, t: userToken} — same-LAN / desktop teammates.
    if (o.b) {
      get().set({ baseUrl: String(o.b).replace(/\/+$/, ""), token: o.t ?? "", relayUrl: "", room: "", daemonPub: "" });
      return { ok: true, mode: "direct" };
    }
    // Relay invite {u: relayUrl, r: room, k: daemonPub, t: userToken} — remote.
    if (!o.u || !o.r || !o.k) {
      const missing = [!o.u && t("pair.partRelayUrl"), !o.r && t("pair.partRoom"),
                       !o.k && t("pair.partKey")].filter(Boolean).join(", ");
      return { ok: false, reason: t("pair.incomplete", { missing }) };
    }
    let { mySec, myPub } = get();
    if (!mySec || !myPub) { const kp = generateKeyPair(); mySec = kp.sec; myPub = kp.pub; }
    get().set({ relayUrl: String(o.u).replace(/\/+$/, ""), room: o.r, daemonPub: o.k, token: o.t ?? "", mySec, myPub });
    return { ok: true, mode: "relay" };
  },

  hydrate: async () => {
    try {
      if (isWeb) {
        // Desktop (Electron) hands the daemon URL + a device token via the URL
        // hash (#cfg=base64{baseUrl,token}) on first load; otherwise localStorage.
        const hash = globalThis.location?.hash ?? "";
        const m = /[#&]cfg=([^&]+)/.exec(hash);
        if (m) get().set(JSON.parse(atob(decodeURIComponent(m[1]))));
        else { const raw = globalThis.localStorage?.getItem(KEY); if (raw) set({ ...JSON.parse(raw) }); }
      } else {
        const raw = await SecureStore.getItemAsync(KEY);
        if (raw) set({ ...JSON.parse(raw) });
      }
    } catch { /* ignore */ }
    set({ hydrated: true });
  },
}));
