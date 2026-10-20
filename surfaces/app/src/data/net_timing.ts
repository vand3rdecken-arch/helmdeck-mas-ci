// Where a relay request's time goes (2026-10-20, owner: "wie kann man den Weg
// noch verkürzen"). The daemon seals {q, h} into every reply
// (relay_client._serve_one): q = ms the frame waited in the relay queue before
// the bridge pulled it, h = ms in the handler. The phone knows its own round
// trip; what is left is the network legs (phone <-> Cloudflare <-> bridge).
// Measured per request, kept for the last WINDOW requests, read as medians in
// the hidden DiagPanel - so "is a direct LAN path worth it" is answered by the
// phone's own numbers, not a guess.
//
// No React/expo imports: plain module state, read on demand.
export interface DaemonTiming { q: number; h: number }
interface Sample { path: string; total: number; q: number; h: number; via: "direct" | "socket" | "http" }

const WINDOW = 100;
const samples: Sample[] = [];

export function recordTiming(path: string, totalMs: number, tm: DaemonTiming | undefined, via: "direct" | "socket" | "http") {
  if (!tm || typeof tm.q !== "number" || typeof tm.h !== "number") return;   // older daemon: nothing to split
  samples.push({ path: path.split("?")[0], total: totalMs, q: tm.q, h: tm.h, via });
  if (samples.length > WINDOW) samples.splice(0, samples.length - WINDOW);
}

const median = (xs: number[]) => {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
};

/** One line per transport: n requests, median total = queue + daemon + network. */
export function timingSummary(): string[] {
  return (["direct", "socket", "http"] as const).flatMap((via) => {
    const xs = samples.filter((s) => s.via === via);
    if (!xs.length) return [];
    const net = xs.map((s) => Math.max(0, s.total - s.q - s.h));
    return [`${via.padEnd(6)} n=${xs.length}  total ${median(xs.map((s) => s.total))} ms = queue ${median(xs.map((s) => s.q))}`
      + ` + daemon ${median(xs.map((s) => s.h))} + network ${median(net)}`];
  });
}

/** The slowest paths by median total - where shortening would pay. */
export function slowestPaths(n = 3): string[] {
  const by = new Map<string, number[]>();
  for (const s of samples) by.set(s.path, [...(by.get(s.path) ?? []), s.total]);
  return [...by.entries()]
    .map(([p, xs]) => [p, median(xs), xs.length] as const)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([p, m, c]) => `  ${m} ms  ${p} (x${c})`);
}

export function _resetTimingForTest() { samples.length = 0; }
