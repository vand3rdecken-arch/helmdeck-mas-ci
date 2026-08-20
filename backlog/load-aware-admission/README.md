# The box has a CPU/RAM limit and the harness doesn't know it exists

**Filed 2026-08-20 from an owner observation.** The desktop has a lock (one
global cursor, `_uses_desktop_control`, fail-safe) because two agents driving
the mouse COLLIDE visibly. Compute has nothing, because contention fails soft
- and today showed the gap clearly: a Gradle release build + the Android
emulator (qemu) + a 66-file sequential gate + rustdesk all ran at once, the
box sat at 100% CPU, and the daemon kept dispatching as if capacity were
infinite. The gate took 3-5x its normal time.

## Why this is a real failure class, not just slowness

- A gate test with an internal timeout reds under load it didn't cause ->
  phantom gate red, same smell as the daemon-restart bounce class.
- The 900s silence watchdog can kill a turn that is merely STARVED, not stuck.
- The owner reads "gate is slow/stuck" and starts debugging the card - the
  actual cause (a build on the same box) is invisible in the card's chat.

## Wanted: admission by OBSERVED load (the desktop-lock pattern, generalized)

NO MONKEY PATCHES - same law as everything else: derive load from the
runtime's own signals at event time, never a stored "busy" flag.

1. A `resources` seam (spine): sample CPU load + free RAM on demand
   (ctypes/winreg or psutil if vendored - NB `powershell.exe` is NOT on this
   box's PATH, never shell out to it).
2. Known-heavy operations declare themselves, like `_uses_desktop_control`
   declares the cursor: gate runs, APK/Gradle builds, emulator boots.
   A heavy op ADMITS only when load is below a policy threshold
   (`policy.load_admission`, data not code) - else it QUEUES with a visible
   note in the card chat ("wartet: Box ausgelastet durch <holder>"), exactly
   like the desktop lock's wait note.
3. The holder is NAMED: the seam records who is burning the box (card id /
   "apk-build" / "emulator") so a waiting card's chat says what it waits FOR
   - today's confusion was the invisibility, not the waiting.
4. Watchdog awareness: while a turn's card holds-or-waits under load
   admission, the 900s silence clock should not tick against starvation it
   didn't cause (same reasoning as the idle-watchdog fix - bound by silence,
   but not by SOMEONE ELSE'S noise).
5. Scope guard: this is ADMISSION (defer the start of heavy ops), not cgroup
   enforcement - do not try to throttle running processes.
6. GATE SINGLETON (measured 2026-08-20, Display-Glasses card): a worker,
   blind to WHY its gate was slow (box at 100% from a build it can't see),
   started a SECOND full gate in the same worktree - two 66-file suites then
   starved each other. The gate verdict for a tree is load-bearing state and
   briefly had two owners, violating the one-owner law. Paseo's
   replaceAgentRun is the precedent: a gate run per tree is a singleton -
   a second request JOINS the running one (or replaces it last-wins), never
   stacks beside it. This holds independently of load admission.
7. Gate cost is O(repo), not O(diff), and grows monotonically (66 files
   today). Out of scope here, but note the pressure: per-card gates that run
   everything are the structural reason this card exists. A diff-scoped
   fast gate + full suite only at accept is the eventual shape.

## Verify

- Two heavy ops requested concurrently -> second queues with a named-holder
  note, starts when load drops.
- Gate under synthetic load (a busy-loop holder) does not get watchdog-killed.
- Policy threshold change via settings takes effect without code edits.
