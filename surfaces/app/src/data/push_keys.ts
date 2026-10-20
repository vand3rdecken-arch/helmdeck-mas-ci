// WHICH paired PC sealed this push? Pure (no expo, no store) so the decision
// is testable in plain node (__push_keys_selftest__.ts) and push.ts's
// decryptPush only feeds it the live config.
//
// The sealing key IS the sender's identity: a push opens under exactly one
// pinned daemon key. The ACTIVE pairing is tried first (the common case, one
// attempt); then every other saved pairing - their pushes keep arriving while
// another PC is active. `daemon` is set only when it was NOT the active one,
// so the tap knows to switch first.
export interface PairingKey { daemonPub: string }

export function openFromPairings<T>(
  cipher: string, mySec: string, activePub: string, activeId: string,
  saved: Record<string, PairingKey>, open: (cipher: string, sec: string, pub: string) => string,
): (T & { daemon?: string }) | null {
  if (!cipher || !mySec) return null;
  if (activePub) {
    try { return JSON.parse(open(cipher, mySec, activePub)) as T & { daemon?: string }; } catch { /* not the active PC */ }
  }
  for (const [id, d] of Object.entries(saved ?? {})) {
    if (id === activeId || !d?.daemonPub || d.daemonPub === activePub) continue;
    try { return { ...(JSON.parse(open(cipher, mySec, d.daemonPub)) as T), daemon: id }; } catch { /* next */ }
  }
  return null;
}
