import AsyncStorage from "@react-native-async-storage/async-storage";
import type { SteerOpts } from "./client";

// THE outbox: owner messages that never reached the daemon.
//
// Before this, a send that failed (no internet, relay 503, daemon asleep) lost
// the message outright - the composer clears its input in the SAME TICK it
// fires the request (card_composer.fire), the persisted draft is deleted with
// it, and the optimistic echo lives only in component state, so backing out of
// the chat took the text with it. Owner report 2026-08-28: "die Nachricht ist
// einfach weg, kein Fehler, keine Anzeige".
//
// So an outbound message is only allowed to leave the composer once it is
// SOMEWHERE durable. The send path writes it here first and deletes it only on
// a confirmed daemon answer - the same evidence rule the rest of the harness
// uses (a thing is done when the runtime says so, not when we dispatched it).
//
// AsyncStorage, not SecureStore (which drafts.ts uses): a chat message is not a
// credential, and SecureStore's ~2048-byte practical ceiling on Android would
// silently drop exactly the long messages that most deserve saving.
const KEY = "helmdeck.outbox.v1";

/** A message that has NOT been acknowledged by the daemon. */
export interface Outbound {
  id: string;
  /** "board" for the Henry board chat, `card:<id>` for a card chat. */
  scope: string;
  text: string;
  /** Scalar send options only - see stripOpts(). */
  opts: SteerOpts;
  /** epoch ms, for stable ordering and the "seit wann" label. */
  at: number;
  tries: number;
  /** last transport/API message, shown next to the stuck bubble. */
  error?: string;
}

// Attachments are deliberately NOT persisted: they are base64 blobs that can run
// to megabytes, and a retry that silently dropped them would be worse than one
// that says so. Only the scalars that decide HOW the message runs survive.
function stripOpts(o: SteerOpts): SteerOpts {
  const { model, thinking, mode, to } = o as SteerOpts & { mode?: string };
  return { ...(model ? { model } : {}), ...(thinking ? { thinking } : {}),
    ...(mode ? { mode } : {}), ...(to ? { to } : {}) } as SteerOpts;
}

// Change notification at EVENT TIME, from the one place that mutates the queue -
// not a poll that re-scans storage hoping to notice. Nothing outside this app
// writes the outbox, so every change passes through writeAll() and there is
// nothing a scan could find that a notify would miss.
type Listener = () => void;
const listeners = new Set<Listener>();

export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

async function readAll(): Promise<Outbound[]> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? (v as Outbound[]) : [];
  } catch { return []; }
}

async function writeAll(items: Outbound[]): Promise<void> {
  try {
    if (!items.length) await AsyncStorage.removeItem(KEY);
    else await AsyncStorage.setItem(KEY, JSON.stringify(items));
  } catch { /* storage unavailable - nothing better to do than keep going */ }
  // Fires even when the write threw: the in-memory truth changed either way, and
  // a listener that re-reads is more useful than one left showing a stale queue.
  for (const fn of [...listeners]) { try { fn(); } catch { /* a bad listener must not break a send */ } }
}

// Every mutation is read-modify-write over ONE storage key, and AsyncStorage is
// async - so two failures landing together (board send + a card send, or a retry
// racing a fresh park) would interleave and one would overwrite the other's row.
// Serialising the edits is what makes "the message is never lost" actually true
// rather than usually true.
let chain: Promise<unknown> = Promise.resolve();
function edit<T>(fn: (all: Outbound[]) => { next: Outbound[]; result: T }): Promise<T> {
  const run = chain.then(async () => {
    const { next, result } = fn(await readAll());
    await writeAll(next);
    return result;
  });
  // the chain must survive a rejected link, or one failure freezes the queue
  chain = run.catch(() => {});
  return run;
}

/** Everything still unsent for one surface, oldest first. */
export async function pending(scope: string): Promise<Outbound[]> {
  return (await readAll()).filter((m) => m.scope === scope).sort((a, b) => a.at - b.at);
}

/** Park a message that failed to send. Returns the stored row. */
export function park(
  scope: string, text: string, opts: SteerOpts, error: string, at: number,
): Promise<Outbound> {
  const row: Outbound = {
    // `at` is passed in (not read here) so the caller owns the clock and a test
    // can drive it; the suffix keeps two sends in the same millisecond apart.
    id: `${at}-${Math.random().toString(36).slice(2, 8)}`,
    scope, text, opts: stripOpts(opts), at, tries: 1, error,
  };
  return edit((all) => ({ next: [...all, row], result: row }));
}

/** Drop a message - called ONLY when the daemon actually answered. */
export function settle(id: string): Promise<void> {
  return edit((all) => ({ next: all.filter((m) => m.id !== id), result: undefined }));
}

/** A retry failed again: keep it, count the attempt, refresh the reason. */
export function retried(id: string, error: string): Promise<void> {
  return edit((all) => ({
    next: all.map((m) => m.id === id ? { ...m, tries: m.tries + 1, error } : m),
    result: undefined,
  }));
}

/** Owner gave up on this one. Same storage edit as settle, different intent. */
export const discard = settle;
