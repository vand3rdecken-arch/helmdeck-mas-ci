// Universal tracking, app -> daemon. The kernel journal() is the app-side glass
// box; this streams every app reconfiguration (user/agent swap in the UI) to
// the daemon's append-only events sink via POST /reconfig/track, so swaps in
// EITHER runtime land in the same audit. Best-effort: a failed post never
// blocks the swap (the app journal is still the durable local record).

import { KEYS, type Kernel } from "@/kernel";

/** Attach a daemon audit sink to the kernel. Returns a disposer. */
export function attachDaemonTrackSink(kernel: Kernel): () => void {
  const api = kernel.get(KEYS.API) as { post?: (p: string, b?: unknown) => Promise<unknown> } | undefined;
  if (!api?.post) return () => {};
  return kernel.onTracked((e) => {
    // fire-and-forget; swallow errors so audit-sink latency never gates a swap.
    void Promise.resolve(api.post!("/reconfig/track", e)).catch(() => {});
  });
}
