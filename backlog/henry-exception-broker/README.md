# Dual architecture: Henry as the full-context layer over context-poor workers

> **CORE SHIPPED 2026-08-21 (~05:30, owner: "baue direkt hier")**:
> `spine/registry/escalations.py` - append-only store (state FOLDED,
> never flagged), emit seams at aborted-by-restart / conflict-unresolved /
> deploy-red, broker loop via the pm._ask headless seam, bounded verbs
> (rerun_deploy | steer | notify_owner | ignore), 2-attempt cap, policy =
> settings.json `henry_policy` (data). Pinned once by
> `daemon/test_escalations.py`. Open: more emit points (ship collision wait
> note, starved-gate), a UI surface for the escalation log, richer snapshot
> (box load once the load-aware-admission seam exists).

**Owner decree 2026-08-21 (~05:15), after the double-ship night.** The system
must exist DUALLY, Paseo-style: card workers stay deliberately context-poor
(worktree + own chat - isolation is correct), and above them ONE Paseo-like
agent with FULL system context - Henry, the existing board copilot/PM - to
whom the harness ESCALATES everything that needs judgement. In Paseo that
layer is the human; HelmDeck left the seat empty and tried to fill it with
code hooks.

## The failure mode this replaces

Tonight's chain: accept hook fired a second ship into a running one (code
has no awareness), a daemon restart orphaned a Gradle tree that wedged the
next build (nobody observes), a worker double-started a 66-file gate because
it couldn't see WHY the first was slow (worktree-only context), a conflict
parked at 4am for the owner (dead-end). Each got a point-fix in code - ship
lock, gradle guard, resolve ladder, admission punch list. That path ends in
thousands of rules. Rules encode invariants well and judgement badly.

## The split

- CODE keeps only hard invariants - what must NEVER happen regardless of
  judgement: one ship per repo (67939ad live-pid lock), one gate per tree,
  nothing-lost, append-only audit. A handful of locks. NO new judgement
  branches in hooks from here on.
- HENRY gets every exception that has discretion:
  * a heavy op wants to start while another runs (wait? join? replace?)
  * background work orphaned/aborted by a daemon restart (re-run? obsolete?)
  * a gate/build is slow (starved by whom? kill? wait? tell the card?)
  * conflict unresolved after the 2 automatic tries (which side wins?)
  * deploy hook red after merge (retry? rollback? wake the owner?)
- WORKERS stay sandboxed; their one new affordance is already filed
  elsewhere: a one-line system snapshot at turn start (what runs, box load)
  so they can defer instead of colliding (load-aware-admission card).

## Mechanism (keep it thin)

1. Escalation queue: harness points that today hardcode-or-dead-end emit an
   ESCALATION event (kind, card, holder pids, log tail) instead of deciding.
   Append-only, visible in the app.
2. Henry consumes it with a SYSTEM SNAPSHOT tool (cards + statuses, running
   ships/gates with pids and ages, box load, locks with holders) and acts
   through the verbs he already has (steer, move_lane, update_track,
   dispatch_conflict_resolution, run/kill process) + notify owner as the
   last rung.
3. Henry's policy lives in his BRIEF (data, editable) - "prefer waiting over
   killing, never kill a build younger than X, wake the owner only if..." -
   NOT in daemon code. Changing behaviour = editing prose, not shipping
   Python. This is the mechanism-vs-policy line the plugin-kernel already
   drew for the app.
4. Bound Henry like the PM RESOLVE ladder: two decision attempts per
   escalation, then owner - and every decision writes an audit note on the
   affected card ("Henry: zweites Ship wartet auf pid 1234, joint danach").

## Verify

- Kill a daemon mid-build -> escalation appears -> Henry re-runs the ship ->
  APK lands with zero owner input.
- Fire two accepts back-to-back -> second deploy waits (code lock) AND the
  cards' chats say who holds and why (Henry note).
- Conflict past 2 auto-tries -> Henry picks a side with a reasoned note or
  asks the owner ONE concrete question, never a generic "resolve it".
