import { Platform } from "react-native";
import { create } from "zustand";

// Client for the desktop onboarding control plane (surfaces/desktop/setup.js).
//
// It is deliberately SEPARATE from data/client.ts: that one talks to the daemon,
// and onboarding exists precisely for the moment the daemon does not run yet.
// The endpoint + per-launch nonce arrive in the same #cfg hash the Electron shell
// already uses to hand over baseUrl/token (surfaces/desktop/main.js createWindow).

export interface SetupState {
  python: boolean; pythonBundled: boolean;
  claude: boolean; claudeVersion: string;
  daemon: boolean;
  running: boolean; done: boolean;
  // No `token` field: provisioning used to end by minting an owner device token
  // and handing it here, which logged the SPA in as owner with no credential.
  // Provisioning installs an instance; who may drive it is settled by logging in.
}
export interface SetupLine { ts: number; kind: string; line: string }

/** Mirrors surfaces/desktop/setup.js's ENGINES catalog - `tier` is what
 *  actually decides what the picker can promise for each engine (see that
 *  file's own docstring): "full" (claude) finishes the whole flow,
 *  "npm-install"/"agent-install" get their CLI fetched, "detect-only" is
 *  status with no install action at all. Keep in sync by hand - it is a tiny,
 *  rarely-changing list on the other side of a loopback HTTP call, not worth
 *  a shared-schema package for. */
export interface EngineStatus {
  id: string; label: string;
  tier: "full" | "npm-install" | "agent-install" | "detect-only";
  installed: boolean; version: string;
}

interface Endpoint { port: number; nonce: string }

function readEndpoint(): Endpoint | null {
  if (Platform.OS !== "web") return null;   // desktop-only surface
  try {
    const hash = globalThis.location?.hash ?? "";
    const m = /[#&]cfg=([^&]+)/.exec(hash);
    if (!m) return null;
    const cfg = JSON.parse(atob(decodeURIComponent(m[1])));
    return cfg?.setup?.port ? cfg.setup as Endpoint : null;
  } catch { return null; }
}

const ep = readEndpoint();
export const setupAvailable = () => !!ep;

async function call<T>(path: string): Promise<T | null> {
  if (!ep) return null;
  try {
    const r = await fetch(`http://127.0.0.1:${ep.port}${path}?n=${ep.nonce}`);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch { return null; }
}

export const setupApi = {
  state: () => call<SetupState>("/setup/state"),
  log: () => call<{ log: SetupLine[]; running: boolean; done: boolean }>("/setup/log"),
  engines: () => call<{ engines: EngineStatus[] }>("/setup/engines"),
  // `engines` is the picker's selection; "claude" is force-included
  // server-side regardless (setup.js provision() - it is the only engine
  // that can finish provisioning), so omitting it here still works.
  provision: (engines: string[]) =>
    call<{ started: boolean }>("/setup/provision?engines=" + encodeURIComponent(engines.join(","))),
};

/** Whether the onboarding screen should take over. It does so only on the
 *  desktop shell and only while the instance is not actually serving. */
interface OnboardState { dismissed: boolean; dismiss: () => void }
export const useOnboard = create<OnboardState>((set) => ({
  dismissed: false,
  dismiss: () => set({ dismissed: true }),
}));
