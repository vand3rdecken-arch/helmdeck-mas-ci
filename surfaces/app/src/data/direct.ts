// The phone's direct path to the daemon on the same WiFi (2026-10-20).
//
// Measured on the phone that morning: 829 ms per request, daemon 29 ms, the
// Cloudflare legs 710 ms. The daemon advertises where it is reachable on the
// LAN (sealed, in the socket's join event: relay_client lan_endpoints) and
// serves the SAME sealed frame there (POST /relay/direct). This module only
// decides WHETHER the direct path is usable right now - the transport itself
// lives in client.ts. Paseo's shape (host-runtime.ts probes every connection,
// fails over on "unavailable") with two differences: the address arrives by
// itself instead of being typed in, and a network change re-decides at once
// instead of on a 2-minute probe tick.
//
// Rules - the evidence, never an assumption:
//   - usable only after a probe ANSWERED over that address;
//   - any failed direct request marks it down (the caller falls back);
//   - a network change (WiFi <-> mobile) marks it down and re-probes;
//   - a down path is re-probed lazily, at most every REPROBE_MS, on use;
//   - a probe answer that arrives after the network changed is ignored.
//
// No React/expo imports: the node self-test drives it with a fake probe.
export const REPROBE_MS = 30_000;

export class DirectPath {
  url: string | null = null;
  up = false;
  private probing: Promise<void> | null = null;
  private checkedAt = 0;
  private gen = 0;                      // bumps on every network/address change

  constructor(
    private probeFn: (url: string) => Promise<boolean>,
    private now: () => number = () => Date.now(),
    private onChange: () => void = () => {},
  ) {}

  /** The daemon told us where it is (the join event's `lan`). */
  offer(urls: readonly string[] | undefined) {
    const u = urls?.find((x) => typeof x === "string" && /^https?:\/\//.test(x)) ?? null;
    if (u !== this.url) {
      this.url = u;
      this.setUp(false);
      this.gen++;
    }
    if (u && !this.up) void this.probe();
  }

  /** The phone's network changed: whatever we knew about reachability is void. */
  networkChanged() {
    this.gen++;
    this.setUp(false);
    if (this.url) void this.probe();
  }

  /** A direct request failed: fall back now, re-probe later. */
  failed() {
    this.setUp(false);
    this.checkedAt = this.now();
  }

  /** The base URL to send to right now, or null = use the relay. */
  usable(): string | null {
    if (this.up && this.url) return this.url;
    if (this.url && !this.probing && this.now() - this.checkedAt >= REPROBE_MS) void this.probe();
    return null;
  }

  probe(): Promise<void> {
    if (this.probing) return this.probing;
    const url = this.url;
    if (!url) return Promise.resolve();
    const g = this.gen;
    this.probing = this.probeFn(url)
      .then((ok) => { if (g === this.gen && url === this.url) this.setUp(ok); })
      .catch(() => { if (g === this.gen) this.setUp(false); })
      .finally(() => {
        this.probing = null;
        this.checkedAt = this.now();
        // the network changed while we probed: that answer was about the old one
        if (g !== this.gen && this.url) void this.probe();
      });
    return this.probing;
  }

  private setUp(v: boolean) {
    if (this.up === v) return;
    this.up = v;
    this.onChange();
  }
}
