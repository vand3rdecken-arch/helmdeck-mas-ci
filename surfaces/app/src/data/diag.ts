import { create } from "zustand";

// The black box.
//
// A packaged build has no console, so a request that fails leaves NO trace a
// human can reach - which is exactly how the onboarding connect button spent a
// release answering 403 to every click while the screen looked healthy. The one
// signal that would have named it in a second (`GET /setup/provision -> 403`)
// existed only inside Chromium's network tab, on a machine with no developer on
// it. This module is that signal, kept in memory and copyable.
//
// Deliberately NOT analytics (data/analytics.ts is opt-in, coarse and remote)
// and NOT the health store (data/health.ts keeps ONE overwritten string for the
// banner). This is a local ring buffer of what the app tried and what came
// back, and it never leaves the device unless the owner copies it out.
//
// It is a DEBUG AID, not a source of truth: nothing branches on its contents,
// so it cannot become load-bearing state (no monkey patches - the law).

export type DiagKind = "net" | "err" | "app";

export interface DiagEntry {
  ts: number;
  kind: DiagKind;
  label: string;    // short, greppable: "GET /setup/provision"
  detail: string;   // outcome: "403", "TransportError: ...", ""
  n: number;        // repeat count - see the dedupe rule below
}

// Big enough to hold a whole failed onboarding attempt, small enough that the
// buffer can never be the reason a low-memory phone dies.
const MAX = 300;

const buf: DiagEntry[] = [];

/** Bumped on every change so a mounted panel re-renders. The entries live in a
 *  plain module array, not in the store: a poll loop touching this ~2x/second
 *  must not push a new array identity through zustand on every tick. */
interface DiagState { seq: number; bump: () => void }
const useDiagSeq = create<DiagState>((set) => ({
  seq: 0,
  bump: () => set((s) => ({ seq: s.seq + 1 })),
}));

// ------------------------------------------------------------- redaction ---
// This log exists to be COPIED OUT - into a chat, a card, an email. So it must
// be impossible for it to carry a credential, and that has to hold by
// construction rather than by everyone remembering. Values are masked here, at
// the sink, so no caller can leak one by being careless.
//
// `n` is the setup nonce (surfaces/desktop/setup.js), `c` the pairing payload
// (onboard.tsx's deep link, which contains the device token), `t`/`k`/`token`
// the token and key fields inside it.
const SECRET_PARAMS = /([?&](?:n|c|t|k|token|password|pw|secret|key)=)[^&\s]+/gi;
const BEARER = /(Bearer\s+)[A-Za-z0-9._~+/-]+=*/gi;

export function redact(s: string): string {
  return String(s).replace(SECRET_PARAMS, "$1<redacted>").replace(BEARER, "$1<redacted>");
}

// ---------------------------------------------------------------- record ---
/** Append one observation, but only if it CHANGES what we already know.
 *
 *  The buffer records state transitions, not traffic. An unchanged outcome for
 *  a label bumps that label's existing line (repeat count + "last seen") in
 *  place instead of adding another one, so a healthy setup screen contributes
 *  three lines total - `/setup/state 200 (x412)` and friends - and a single
 *  `/setup/provision -> 403` sits there permanently instead of being buried.
 *
 *  Measured, not assumed: the first version of this compared only against the
 *  immediately PREVIOUS entry, which collapses nothing at all when three polls
 *  interleave (state, log, engines, state, ...). Driving the real screen showed
 *  the 403 scrolled out of view within seconds - a black box that loses the one
 *  line you opened it for. Hence the per-label comparison.
 *
 *  The scan is backwards over a <=300 entry array rather than a label->entry
 *  index, deliberately: no second structure means nothing to desync when the
 *  ring drops its oldest entries. */
export function diag(kind: DiagKind, label: string, detail = ""): void {
  const lbl = redact(label);
  const det = redact(detail);
  for (let i = buf.length - 1; i >= 0; i--) {
    const p = buf[i];
    if (p.kind !== kind || p.label !== lbl) continue;
    if (p.detail === det) { p.n += 1; p.ts = Date.now(); useDiagSeq.getState().bump(); return; }
    break;                            // same label, NEW outcome -> a real event
  }
  buf.push({ kind, label: lbl, detail: det, ts: Date.now(), n: 1 });
  if (buf.length > MAX) buf.splice(0, buf.length - MAX);
  useDiagSeq.getState().bump();
}

/** Newest last, a copy - callers must not be able to mutate the buffer. */
export function diagEntries(): DiagEntry[] {
  return buf.slice();
}

export function diagClear(): void {
  buf.length = 0;
  useDiagSeq.getState().bump();
}

/** Subscribe a component to changes. Returns the sequence number, which is
 *  meaningless except that it changes. */
export function useDiagSeqValue(): number {
  return useDiagSeq((s) => s.seq);
}

/** The whole buffer as plain text, for the clipboard. `head` lets the caller
 *  prepend environment facts it knows and this module deliberately does not
 *  (app version, platform) - keeping diag.ts free of expo imports so the
 *  transport layer can depend on it without dragging them along. */
export function dumpDiag(head: string[] = []): string {
  const line = (e: DiagEntry) =>
    `${new Date(e.ts).toISOString().slice(11, 23)}  ${e.kind.padEnd(3)}  ${e.label}` +
    `${e.detail ? "  -> " + e.detail : ""}${e.n > 1 ? `  (x${e.n})` : ""}`;
  return ["HelmDeck diagnostics", ...head, "", ...buf.map(line)].join("\n");
}

// -------------------------------------------------------- global capture ---
// An uncaught exception is the one failure that explains a frozen screen, and
// it is precisely the one nothing else records: _layout.tsx's ErrorBoundary
// renders a message and stores nothing, and a rejected promise outside React
// does not even reach it.
let armed = false;
export function armDiagCapture(): void {
  if (armed) return;
  armed = true;
  const g = globalThis as unknown as {
    addEventListener?: (t: string, cb: (e: unknown) => void) => void;
    ErrorUtils?: { getGlobalHandler?: () => unknown; setGlobalHandler?: (h: unknown) => void };
  };
  if (typeof g.addEventListener === "function") {
    g.addEventListener("error", (ev: unknown) => {
      const m = (ev as { message?: string; error?: Error })?.error?.message
        ?? (ev as { message?: string })?.message ?? "?";
      diag("err", "uncaught", String(m));
    });
    g.addEventListener("unhandledrejection", (ev: unknown) => {
      const r = (ev as { reason?: unknown })?.reason;
      diag("err", "unhandled rejection", String((r as Error)?.message ?? r ?? "?"));
    });
  }
  // React Native's own hook. Chained, never replaced: taking over the global
  // handler would swallow the red box in development.
  const prev = g.ErrorUtils?.getGlobalHandler?.();
  if (typeof g.ErrorUtils?.setGlobalHandler === "function") {
    g.ErrorUtils.setGlobalHandler((err: Error, fatal?: boolean) => {
      diag("err", fatal ? "fatal" : "uncaught", String(err?.message ?? err));
      if (typeof prev === "function") (prev as (e: Error, f?: boolean) => void)(err, fatal);
    });
  }
}
