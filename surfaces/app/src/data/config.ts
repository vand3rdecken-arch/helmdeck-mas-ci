import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { create } from "zustand";
import { t } from "@/i18n/core";

import { track } from "./analytics";
import { useDemo } from "./demo";
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
  // A stable id for THIS installation, minted once on first hydrate and sent
  // with every sign-in. The daemon uses it to keep ONE live device token per
  // device (auth.issue_token(device=...)) instead of minting a fresh permanent
  // credential on every login - which is what grew the owner's Team panel into
  // a wall of indistinguishable "web-login" rows. Not a secret and not an
  // identity: it decides only which of the account's OWN tokens gets replaced.
  deviceId: string;
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
  relayUrl: "", room: "", daemonPub: "", mySec: "", myPub: "", deviceId: "",
};

const isWeb = Platform.OS === "web";

const newDeviceId = () =>
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

/** What this device calls itself in the owner's Team panel. Deliberately
 *  coarse (platform, not a fingerprint): it exists so a human can tell "my
 *  phone" from "the laptop", and anything sharper would be tracking. */
export function deviceLabel(): string {
  if (Platform.OS === "web") {
    const ua = (globalThis.navigator?.userAgent ?? "").toLowerCase();
    if (ua.includes("electron")) return "Desktop";
    return ua.includes("mobile") ? "Browser (mobil)" : "Browser";
  }
  return Platform.OS === "ios" ? "iPhone/iPad" : "Android";
}

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
  set: (patch) => { set(patch); const { baseUrl, token, relayUrl, room, daemonPub, mySec, myPub, deviceId } = get(); persist({ baseUrl, token, relayUrl, room, daemonPub, mySec, myPub, deviceId }); },

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
      useDemo.getState().disable();   // a real daemon wins over the sample board
      track("login", { mode: "direct" });   // pairing IS the app's login
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
    useDemo.getState().disable();     // a real daemon wins over the sample board
    track("login", { mode: "relay" });   // pairing IS the app's login
    return { ok: true, mode: "relay" };
  },

  hydrate: async () => {
    try {
      if (isWeb) {
        // Desktop (Electron) hands the daemon URL via the URL hash
        // (#cfg=base64{baseUrl,setup}); otherwise localStorage.
        //
        // MERGE, do not replace. The hash used to WIN outright, so anything it
        // omitted was silently dropped - harmless while surfaces/desktop/main.js minted a
        // fresh owner token into it at every launch. That mint is gone (it was a
        // credential-free owner login), so the only session that exists is the
        // one the user actually logged into, and it lives in localStorage.
        // Replacing would throw it away and demand a login at every launch,
        // which is the failure mode that gets a security fix reverted. Stored
        // config is the base; the hash overlays only the fields it really has.
        const raw = globalThis.localStorage?.getItem(KEY);
        if (raw) set({ ...JSON.parse(raw) });
        const m = /[#&]cfg=([^&]+)/.exec(globalThis.location?.hash ?? "");
        if (m) {
          const fromHash: Record<string, unknown> = JSON.parse(atob(decodeURIComponent(m[1])));
          for (const k of Object.keys(fromHash)) {
            if (fromHash[k] === "" || fromHash[k] == null) delete fromHash[k];
          }
          get().set(fromHash as Partial<Persisted>);
        }
      } else {
        const raw = await SecureStore.getItemAsync(KEY);
        if (raw) set({ ...JSON.parse(raw) });
      }
    } catch { /* ignore */ }
    // Mint the installation id once, here, so it survives every later set()
    // (which persists the whole Persisted shape). An existing install keeps
    // the id it already has; a reinstall gets a new one and shows up as a new
    // device in the panel, which is exactly what it is.
    if (!get().deviceId) get().set({ deviceId: newDeviceId() });
    set({ hydrated: true });
  },
}));

// Native pairing gate (2026-08-26). Desktop/web has useShowOnboard (setup.ts,
// Platform.OS==="web" only) - native had NOTHING: a fresh install (or a
// reinstall, which wipes SecureStore) falls straight through _layout.tsx into
// the tabbed UI with the untouched DEFAULTS above, whose baseUrl is the
// ANDROID EMULATOR loopback (10.0.2.2) - unreachable from a real phone. The
// Dashboard's query used to hang forever with no error (client.ts had no
// fetch timeout either); now it fails in ~8s, but a real phone should never
// even try that request before pairing has a chance to run. True only once,
// right after hydration, before any pairing/demo choice has been made -
// applying a pairing code or enabling demo both flip a field this checks.
//
// Both stores' OWN hydrated flags are required, not just config's: _layout.tsx
// awaits useConfig.hydrate() THEN useDemo.hydrate() in sequence (two separate
// SecureStore reads), so a returning demo-mode user would otherwise see
// config.hydrated=true, demo.active=false for a tick and flash this gate.
export function useNeedsPairing(): boolean {
  const configHydrated = useConfig((s) => s.hydrated);
  const relay = useConfig((s) => s.relayMode());
  const baseUrl = useConfig((s) => s.baseUrl);
  const token = useConfig((s) => s.token);
  const demoHydrated = useDemo((s) => s.hydrated);
  const demoActive = useDemo((s) => s.active);
  if (Platform.OS === "web") return false;   // desktop/web owns its own gate
  if (!configHydrated || !demoHydrated || demoActive || relay) return false;
  return baseUrl === DEFAULTS.baseUrl && !token;
}
