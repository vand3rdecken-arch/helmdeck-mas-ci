// The direct-LAN path's decisions (data/direct.ts), driven with a fake probe
// and a fake clock: usable only on evidence, down on failure or network change,
// a late probe answer about the OLD network ignored, re-probe throttled.
//
// Run: npx tsc -p tsconfig.invalidate.json && node .invalidate-out/data/__direct_selftest__.js
import { DirectPath, REPROBE_MS } from "./direct";

let fails = 0;
const check = (ok: boolean, msg: string) => {
  console.log((ok ? "  ok  " : "  FAIL ") + msg);
  if (!ok) fails++;
};
const tick = () => new Promise((r) => setTimeout(r, 0));

(async () => {
  let now = 1_000_000;
  const probes: string[] = [];
  let answer = true;
  let release: (() => void) | null = null;
  let hold = false;
  const d = new DirectPath(async (url) => {
    probes.push(url);
    const said = answer;                     // what THIS probe's network said, fixed at its start
    if (hold) await new Promise<void>((r) => { release = r; });
    return said;
  }, () => now);

  check(d.usable() === null, "nothing offered: relay");
  d.offer(["http://192.168.178.22:8140"]);
  check(d.usable() === null, "offered but not yet probed: still relay");
  await tick(); await tick();
  check(d.usable() === "http://192.168.178.22:8140", "after the probe answered: direct");

  d.failed();
  check(d.usable() === null, "a failed request: relay at once");
  const before = probes.length;
  d.usable();
  check(probes.length === before, "no re-probe hammering right after a failure");
  now += REPROBE_MS;
  d.usable();
  await tick(); await tick();
  check(probes.length === before + 1 && d.usable() !== null, "re-probed after REPROBE_MS, and up again");

  // network change while a probe is in flight: its answer is about the OLD
  // network. The stale probe says "reachable", the next one "not" - the path
  // must end DOWN, which only happens if the stale answer was ignored.
  hold = true;
  answer = true;
  const p0 = probes.length;
  d.networkChanged();                        // probe P1 starts, held
  check(d.usable() === null, "network changed: relay at once");
  d.networkChanged();                        // changed AGAIN before P1 answered
  answer = false;                            // what the NEW network really says
  const releaseP1 = release as unknown as () => void;
  releaseP1();                               // P1 answers "reachable" - stale; P2 starts, held
  for (let i = 0; i < 6; i++) await tick();
  check(probes.length === p0 + 2, "the stale probe was followed by a fresh one (" + (probes.length - p0) + " probes)");
  check(!d.up && d.usable() === null, "while the fresh probe runs, the stale 'reachable' was NOT taken");
  hold = false;
  (release as unknown as () => void)();      // P2 answers "not reachable"
  for (let i = 0; i < 4; i++) await tick();
  check(!d.up, "the fresh answer decides: down");

  answer = false;
  d.networkChanged();
  await tick(); await tick();
  check(d.usable() === null, "on mobile data the probe fails: stays on the relay");

  d.offer(["ftp://nope", "not a url"]);
  check(d.url === null && d.usable() === null, "only http(s) addresses are taken");

  console.log(fails ? `\n${fails} FAILED` : "\nall ok");
  process.exit(fails ? 1 : 0);
})();
