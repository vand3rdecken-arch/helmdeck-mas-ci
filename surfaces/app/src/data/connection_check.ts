// WHICH LEG IS BROKEN - the diagnosis the owner did not have (2026-09-23:
// "Haupt problem ist fehlender Diagnose").
//
// "Relay unreachable" appeared three times that day with THREE different
// causes: an Android build starving the daemon's CPU, the gap during a daemon
// restart, and two daemons sharing the port. Each time the phone said the same
// sentence and each time it took a manual expedition on the PC to find out
// which half of the chain was down. The chain has four legs and every one of
// them can fail on its own:
//
//   phone --(1 network/DNS)--> relay --(2 relay itself)--> room
//        --(3 a daemon pulling that room)--> daemon --(4 keys + serving)-->
//
// Leg 3 is the one nobody could see. It is free to ask: the relay's room
// object checks "is a daemon connected" BEFORE it parses the body, so an
// EMPTY POST answers the question without queueing a frame - 400 means a
// bridge is pulling, 503 means there is nobody home. That is exactly the
// probe that found the split-brain by hand; here it is, wired up.
//
// No React, no expo, no crypto imports: plain fetch + injected deps, so the
// whole thing runs under node in __connection_check_selftest__.ts.

export type LegId = "network" | "relay" | "daemon" | "e2e";
export type LegState = "ok" | "fail" | "skip";

export interface Leg {
  id: LegId;
  state: LegState;
  /** i18n key for the one-line verdict. */
  key: string;
  /** technical detail (status, error text) - never translated, may be "". */
  detail: string;
}

export interface CheckDeps {
  relayUrl: string;
  room: string;
  fetchImpl: typeof fetch;
  /** A REAL sealed round-trip through the normal client. Resolves = ok. */
  sealedPing: () => Promise<unknown>;
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT = 8000;

function leg(id: LegId, state: LegState, key: string, detail = ""): Leg {
  return { id, state, key, detail };
}

function err(e: unknown): string {
  const m = (e as Error)?.message ?? String(e);
  return m.length > 120 ? m.slice(0, 117) + "…" : m;
}

async function withTimeout<T>(p: (signal: AbortSignal) => Promise<T>, ms: number): Promise<T> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    return await p(ctl.signal);
  } finally {
    clearTimeout(timer);
  }
}

/** The four legs, in order, each one only asked when the one before it held. */
export async function checkConnection(d: CheckDeps): Promise<Leg[]> {
  const ms = d.timeoutMs ?? DEFAULT_TIMEOUT;
  const base = (d.relayUrl || "").replace(/\/+$/, "");
  if (!base || !d.room) {
    // Direct/LAN mode or not paired at all: say so instead of running four
    // relay probes that would all fail for the same uninteresting reason.
    return [leg("network", "skip", "check.notPaired")];
  }

  const out: Leg[] = [];

  // 1 + 2: the phone's own network, then the relay itself. One request
  // answers both - a rejected fetch is the phone's side, a bad status is the
  // relay's.
  let health: Response;
  try {
    health = await withTimeout((signal) => d.fetchImpl(`${base}/health`, { signal }), ms);
  } catch (e) {
    out.push(leg("network", "fail", "check.networkFail", err(e)));
    out.push(leg("relay", "skip", "check.skipped"));
    out.push(leg("daemon", "skip", "check.skipped"));
    out.push(leg("e2e", "skip", "check.skipped"));
    return out;
  }
  out.push(leg("network", "ok", "check.networkOk", base));
  if (!health.ok) {
    out.push(leg("relay", "fail", "check.relayFail", `HTTP ${health.status}`));
    out.push(leg("daemon", "skip", "check.skipped"));
    out.push(leg("e2e", "skip", "check.skipped"));
    return out;
  }
  out.push(leg("relay", "ok", "check.relayOk"));

  // 3: is a daemon actually pulling THIS room? Empty body on purpose - the
  // room object answers "no daemon" before it ever looks at the body, so this
  // asks the question without putting a frame in the queue.
  let daemonOk = false;
  try {
    const r = await withTimeout((signal) => d.fetchImpl(`${base}/relay?room=${encodeURIComponent(d.room)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "", signal,
    }), ms);
    if (r.status === 503) {
      out.push(leg("daemon", "fail", "check.daemonOffline", `HTTP 503`));
    } else {
      // 400 (bad json) is the EXPECTED answer: it means the request got past
      // the "is a daemon connected" gate.
      daemonOk = true;
      out.push(leg("daemon", "ok", "check.daemonOk", `HTTP ${r.status}`));
    }
  } catch (e) {
    out.push(leg("daemon", "fail", "check.daemonProbeFail", err(e)));
  }
  if (!daemonOk) {
    out.push(leg("e2e", "skip", "check.skipped"));
    return out;
  }

  // 4: a real sealed round-trip - proves the keys match and the daemon serves.
  try {
    await d.sealedPing();
    out.push(leg("e2e", "ok", "check.e2eOk"));
  } catch (e) {
    out.push(leg("e2e", "fail", "check.e2eFail", err(e)));
  }
  return out;
}

/** The one line to show at the top: the FIRST broken leg is the diagnosis. */
export function verdictKey(legs: Leg[]): string {
  const bad = legs.find((l) => l.state === "fail");
  if (bad) return `check.verdict.${bad.id}`;
  if (legs.length === 1 && legs[0].state === "skip") return "check.notPaired";
  return "check.verdict.ok";
}
