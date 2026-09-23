// Connection diagnosis - the test for the four legs (owner 2026-09-23:
// "Haupt problem ist fehlender Diagnose"). Every case below is one of the
// real failures from that day, so the panel cannot regress into the single
// useless sentence ("Relay unreachable") it replaces.
//
// Plain node, no RN/expo:
//   npx tsc -p tsconfig.conncheck.json && node .conncheck-out/data/__connection_check_selftest__.js
// (from surfaces/app/). Exits non-zero on the first failed check.

import { checkConnection, verdictKey, type Leg } from "./connection_check";

let failures = 0;
function ok(cond: boolean, msg: string): void {
  if (cond) console.log(`  ok   - ${msg}`);
  else {
    failures++;
    console.log(`  FAIL - ${msg}`);
  }
}

const CFG = { relayUrl: "https://relay.helmdeck.de", room: "g1LnBAwB3LQYZK7B" };
const state = (legs: Leg[], id: string) => legs.find((l) => l.id === id)?.state;

function res(status: number, body = "{}"): Response {
  return { ok: status >= 200 && status < 300, status, text: async () => body,
           json: async () => JSON.parse(body) } as unknown as Response;
}

console.log("connection-check selftest");

(async () => {
  // 1. The phone cannot reach the relay at all (the 19:48 screenshot: fetch
  //    rejects, no HTTP status). Only the FIRST leg is blamed.
  {
    const legs = await checkConnection({
      ...CFG, fetchImpl: async () => { throw new TypeError("Network request failed"); },
      sealedPing: async () => { throw new Error("should not be reached"); },
    });
    ok(state(legs, "network") === "fail", "fetch rejects -> network leg fails");
    ok(state(legs, "relay") === "skip" && state(legs, "daemon") === "skip",
       "...and the legs behind it are SKIPPED, not blamed");
    ok(verdictKey(legs) === "check.verdict.network", "verdict names the phone's network");
    ok((legs[0].detail || "").includes("Network request failed"), "keeps the technical detail");
  }

  // 2. The relay answers but is broken (a bad deploy of the worker).
  {
    const legs = await checkConnection({
      ...CFG, fetchImpl: async () => res(500), sealedPing: async () => ({}),
    });
    ok(state(legs, "network") === "ok" && state(legs, "relay") === "fail",
       "HTTP 500 from /health -> network ok, RELAY fails");
    ok(verdictKey(legs) === "check.verdict.relay", "verdict names the relay");
  }

  // 3. THE ONE NOBODY COULD SEE: relay fine, but no daemon pulls the room.
  //    That is a daemon restart, a crashed daemon, a stopped PC.
  {
    const calls: string[] = [];
    const legs = await checkConnection({
      ...CFG,
      fetchImpl: (async (url, init) => {
        calls.push(`${init?.method ?? "GET"} ${String(url)}`);
        return String(url).includes("/health") ? res(200, '{"ok":true}') : res(503, '{"error":"no daemon connected for this room"}');
      }) as typeof fetch,
      sealedPing: async () => { throw new Error("should not be reached"); },
    });
    ok(state(legs, "relay") === "ok" && state(legs, "daemon") === "fail",
       "503 on the room -> relay ok, DAEMON fails");
    ok(verdictKey(legs) === "check.verdict.daemon", "verdict names the daemon");
    ok(state(legs, "e2e") === "skip", "no pointless sealed request once the daemon is known absent");
    ok(calls[1]?.startsWith("POST ") && calls[1].includes("room="),
       "the daemon probe is a POST to the ROOM, not another /health");
  }

  // 4. Daemon is attached: the room probe answers 400 ("bad json"), which is
  //    the PROOF - the relay only parses the body after the daemon gate.
  {
    const legs = await checkConnection({
      ...CFG,
      fetchImpl: (async (url) =>
        String(url).includes("/health") ? res(200, '{"ok":true}') : res(400, '{"error":"bad json"}')) as typeof fetch,
      sealedPing: async () => ({ me: "owner" }),
    });
    ok(state(legs, "daemon") === "ok", "400 on the room -> a bridge IS pulling it");
    ok(state(legs, "e2e") === "ok", "and the sealed round-trip closes the chain");
    ok(verdictKey(legs) === "check.verdict.ok", "all four legs ok -> ok verdict");
  }

  // 5. Everything reachable, but the keys do not match (stale pairing).
  {
    const legs = await checkConnection({
      ...CFG,
      fetchImpl: (async (url) =>
        String(url).includes("/health") ? res(200, '{"ok":true}') : res(400)) as typeof fetch,
      sealedPing: async () => { throw new Error("Encryption mismatch"); },
    });
    ok(state(legs, "daemon") === "ok" && state(legs, "e2e") === "fail",
       "daemon reachable but the sealed request fails -> only the LAST leg is blamed");
    ok(verdictKey(legs) === "check.verdict.e2e", "verdict names the end-to-end leg");
  }

  // 6. Not paired / direct mode: one honest line, no four red crosses.
  {
    const legs = await checkConnection({
      relayUrl: "", room: "", fetchImpl: async () => res(200), sealedPing: async () => ({}),
    });
    ok(legs.length === 1 && legs[0].state === "skip", "unpaired -> a single skipped leg");
    ok(verdictKey(legs) === "check.notPaired", "...and a verdict that says so");
  }

  // 7. A hanging relay must not hang the panel.
  {
    const t0 = Date.now();
    const legs = await checkConnection({
      ...CFG, timeoutMs: 150,
      fetchImpl: ((_u, init) => new Promise<Response>((_res, rej) => {
        init?.signal?.addEventListener("abort", () => rej(new Error("Aborted")));
      })) as typeof fetch,
      sealedPing: async () => ({}),
    });
    ok(Date.now() - t0 < 2000, "a hanging relay aborts on the timeout instead of hanging");
    ok(state(legs, "network") === "fail", "...and is reported as a failed first leg");
  }

  console.log(failures ? `\n${failures} FAIL` : "\nall ok");
  process.exit(failures ? 1 : 0);
})();
