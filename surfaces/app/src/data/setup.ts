import { Platform } from "react-native";
import { create } from "zustand";

import { diag } from "./diag";

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

// The nonce is a QUERY parameter, so it has to be joined with the separator the
// path actually needs. Hardcoding "?" was fine for the three param-less polls
// and silently broke the one endpoint that carries its own query: /setup/provision
// became ".../provision?engines=claude?n=<nonce>", where the second "?" is just a
// literal, so the whole tail parses as ONE value (engines="claude?n=<nonce>") and
// `n` is absent. setup.js gates every request on `searchParams.get("n") !== nonce`,
// so provision answered 403 to every single click while state/log/engines kept
// working - the "dead primary button" on a fresh machine. Fixed at the one place
// the nonce is attached, so any future endpoint with parameters is covered too.
/** What diag() stores as the outcome of one call. The duration is deliberately
 *  NOT part of it while the call is fast: diag() collapses repeats by comparing
 *  the outcome text, so a millisecond count that drifts 4ms->6ms->5ms turns
 *  every single poll into its own line and buries the one that failed (measured
 *  on the real screen - see diag.ts). A SLOW call is a finding in its own right,
 *  so that keeps a coarse, second-resolution note. */
function outcome(what: string, ms: number): string {
  return ms >= 1000 ? `${what} · ${Math.round(ms / 1000)}s` : what;
}

async function call<T>(path: string): Promise<T | null> {
  if (!ep) return null;
  const started = Date.now();
  const label = "GET " + path.split("?")[0];
  try {
    const sep = path.includes("?") ? "&" : "?";
    const r = await fetch(`http://127.0.0.1:${ep.port}${path}${sep}n=${ep.nonce}`);
    // EVERY outcome is recorded, not just the thrown ones. `!r.ok` returning
    // null is the shape that hid the 403: to the screen a rejected request and
    // a slow one look identical, and this is the only place that can still
    // tell them apart.
    diag("net", label, outcome(String(r.status), Date.now() - started));
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch (e) {
    diag("net", label, outcome((e as Error)?.message || "fetch failed", Date.now() - started));
    return null;
  }
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
