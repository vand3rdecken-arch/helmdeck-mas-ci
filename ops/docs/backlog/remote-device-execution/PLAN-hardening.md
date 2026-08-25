# Plan: harden remote device execution (pays debt `remote-worker-not-hardened`)

> **PHASES A, B, C SHIPPED 2026-08-25** (owner: "mache a,b und c"). Daemon
> side: `claimed_at` stamping + `sweep_stale_device_claims` (one-shot at
> boot next to `sweep_worktrees`, and a continuous poller via
> `sessions.start_engineer_lifecycle`), idempotent `submit_remote_result`
> (a lost-response retry no longer hits `_import_bundle`'s refuse-to-
> clobber as an error), a device-match check on submit (a device may only
> submit against a card bound to ITSELF), `reassign_remote_task` +
> `POST /devices/reassign` for owner/operator recovery. Worker side:
> `_api` gets bounded exponential backoff + jitter on transient failures
> (connection errors/5xx), never retries a 4xx, the main loop distinguishes
> "no work" from "daemon unreachable" pacing, and a KeyboardInterrupt exits
> with a clear message instead of a traceback. Also added, ahead of Phase D
> per owner request ("jeder pc kann eigenes claude haben, muss das
> unterscheiden können"): `spine.auth.devices.register`'s `billing_scope`
> field ("external" default / "shared"), so a device's own Claude
> account/subscription is never assumed to feed the workspace-global
> `ai_billing`/`plan_calibration` pool once Phase D's real usage capture
> exists - modeled now so that work has a field to key off instead of a
> schema migration later. All pinned: ops/tests/test_remote_device.py
> (grew from 27 to 57 assertions), new ops/tests/test_hd_worker.py (9
> assertions on `_api`'s retry/backoff behavior against a scripted fake
> transport, no real network/timing dependency).
>
> **NOT done in this round, explicitly deferred:** surfacing stuck/
> reassignable device cards in the board UI (Phase C's plan mentioned this;
> the API (`/devices/reassign`) and the daemon-side visibility (the
> `reclaimed` event + card note) exist, but no `surfaces/app` screen renders
> them yet - a frontend task, out of scope for this backend-only round).

The daemon side is proven (ops/tests/test_remote_device.py, 57 assertions).
Phases A-C are shipped (see above). This plan closes the gaps the debt
entry names, in PRIORITY order - each phase is independently shippable,
has its own test, and does not depend on the phase after it.

Ordering rationale: correctness before convenience. Phase A is a
data-integrity hole (a claimed card can wedge forever in `working` with no
worktree, invisible) and needs NO worker change - so it lands first. The
worker's own resilience (Phase B) and the owner's recovery controls (Phase
C) build on it. Packaging/driver-reuse (Phase D) is polish, last.

**Billing distinction (owner, 2026-08-25 chat: "jeder pc kann eigenes
claude haben, muss das unterscheiden können").** Each device may run its
OWN Claude account/subscription, not the daemon's - so its usage/cost must
never be folded into spine/storage/events.py's `ai_billing`/
`plan_calibration` pool (workspace-global, calibrated against ONE account's
quota - debt `ai-billing-workspace-global`/`plan-share-calibration`, both
already open). Today this is a non-issue by omission: submit_remote_result
never calls `_turn`, so a device card emits zero `turn` events and
contributes nothing (right by accident, not by design). Modeled explicitly
in Phase A below (`spine.auth.devices`'s `billing_scope` field) so Phase D's
eventual real usage capture has a place to plug into WITHOUT a schema
redesign, rather than deferring the whole distinction to Phase D.

---

## Phase A - daemon: stale claims can't wedge a card forever  [correctness]

**The hole.** `claim_remote_task` (cells/engineer/dispatch.py:443) moves a
card backlog -> working and records nothing about WHEN or that it is now
waiting on an off-box device. If that device then crashes / goes offline /
loops on a bad turn, the card sits in `working` with `worktree = ""`
forever - no local turn is running (nothing to sweep_zombies), no timeout,
no way back. Pure dead state.

**The fix, derived not assumed (no-monkey-patch law).**
1. `claim_remote_task` folds `claimed_at` (UTC) onto the card AT the claim
   event - the one owner of that fact, same shape as `_record_base_branch`
   / `drivers.turn_active`. `exec_site` already records WHICH device.
2. New `sweep_stale_device_claims()` (dispatch.py, next to the claim/submit
   pair). A claim is stale when BOTH signals agree - never a blind clock:
   - `claimed_at` older than `policy.device.claim_ttl_s` (default ~1800s), AND
   - the device's `last_seen` (spine.auth.devices, already touched on every
     queue poll) is older than a grace window (default ~180s).
   A device still long-polling (fresh last_seen) on a genuinely long turn is
   NOT reclaimed - only one that has actually gone quiet. A stale claim is
   returned to `backlog` (lane only - `exec_site` stays, so the SAME device
   re-claims it on reconnect; this is "allow re-claim", not "reassign", which
   keeps a card bound to one device and sidesteps every cross-device race).
   Emits `remote_device action=reclaimed`, logs on the card.
3. Wire it like the other backstops: one-shot at boot next to
   `sessions.sweep_worktrees()` (server.py:490), and on the engineer-cell
   continuous poller (sessions.start_engineer_lifecycle) so it keeps running.

**Submit correctness edges to close in the same phase** (both real, both in
`submit_remote_result`, dispatch.py:462):
- **Idempotent submit.** `_import_bundle` refuses to clobber an existing
  branch (gitutil.py, by design). If the worker's POST succeeds daemon-side
  but the response is lost to a network blip, the worker retries (Phase B)
  and the second import hits "branch already exists" -> today a hard 400.
  Fix: if the branch is already imported AND the card is already at
  review/done, treat the retry as success (return the current card state),
  don't error.
- **Device match.** Submit only checks `exec_site.startswith("local:")`, not
  that THIS device owns THIS card. Tighten to require the submitting
  device's id to equal the card's `exec_site` device - a device must not
  submit against a card bound to another device. (The route layer already
  resolves the device from the token; pass its id down and check.)

**Test** (extend test_remote_device.py or a new test_device_sweep.py):
claimed_at is stamped; a fresh-last_seen long claim is NOT reclaimed; a
stale claim (old claimed_at + stale last_seen) IS returned to backlog and
re-claimable by the same device; a double-submit is idempotent; a
wrong-device submit is refused.

---

## Phase B - worker: survive a flaky network  [resilience]

**The hole.** hd_worker.py's `_api` (ops/tools/hd_worker.py:32) raises on
any HTTP error and `main`'s loop just prints + sleeps 2s. A dropped
connection mid-poll, a daemon restart, or a lost submit response all
degrade badly (a lost submit = wasted turn, since the retry currently 400s
on the re-import - closed by Phase A's idempotency).

**The fix.**
1. `_api` gets bounded exponential backoff with jitter on connection errors
   and 5xx (retry), but NOT on 4xx (a real refusal - surface it). Cap the
   backoff; never spin hot.
2. The main loop distinguishes "no work" (sleep short) from "can't reach
   daemon" (backoff, keep trying, log once per state change not per attempt).
3. Submit is made idempotent on the worker side too: on a retry, if the
   daemon reports the branch already landed (Phase A response), treat as
   done and move on rather than looping.
4. A clean shutdown path (SIGINT) that finishes/returns the current claim
   rather than abandoning it mid-turn where possible.

**Test.** A fake daemon (stdlib http.server on a port, or monkeypatched
`_api`) that fails N times then succeeds - assert the worker retries with
backoff and eventually submits; assert a 4xx is NOT retried; assert a
lost-response submit is not double-counted.

---

## Phase C - owner: recover a card stuck on a dead device  [recovery]

**The hole.** Phase A returns a stale claim to backlog for the SAME device.
If that device is gone for good, the card is un-executable forever with no
owner escape hatch.

**The fix.** Two small owner/operator actions (route + a board control):
- `POST /devices/reassign {track, to_device}` - move a card's `exec_site`
  to a different registered device the actor owns (or clear it back to a
  normal local worktree card, `exec_site` removed, so it can be dispatched
  on the daemon itself). Guarded like every other structural card action
  via `auth.chat_admin_roles()` (owner/operator).
- Surface stuck device cards in the board / History so the owner SEES a
  card waiting on an offline device (the `reclaimed` event + a stale-claim
  flag on the card's presentation), rather than having to notice a silent
  `working` card.

**Test.** reassign moves exec_site and re-backlogs; clearing exec_site makes
it a normal dispatchable card; a client role is refused; a non-owned target
device is refused.

---

## Phase D - packaging + real driver reuse  [polish, lowest priority]

**The holes.** hd_worker.py shells out to `claude -p` directly instead of
reusing spine/agent/drivers.py's turn machinery (so a device turn gets no
usage/cost tracking and streams no transcript back to the board), and there
is no install/autostart story - it's a bare script run by hand.

**The fix (only if the feature sees real daily use - gate this phase on
that).**
1. The member's machine already has the repo (it's the clone the worker
   runs in), so the worker CAN `import spine.agent.drivers`. Extract the
   pure spawn-argv + stream-parse core of a turn into something callable
   without daemon-side trackstore/run_dir state, and have the worker use it
   - then a device turn reports the same usage/cost a local card does, and
   can stream its transcript back over the queue channel for the board to
   show live.
2. An install story: a small `pip`-installable entry point or a packaged
   launcher + an autostart registration (Windows scheduled task / service),
   with the daemon URL + device token from a config file instead of argv.

**Test.** A device turn's usage/cost lands on the card's turn events like a
local card's; the packaged entry point starts and claims one task.

---

## What stays out of scope (named so it's a decision)
- Streaming a device turn's LIVE transcript to the board mid-turn is folded
  into Phase D, not a separate promise - the queue channel is request/reply
  today; live streaming would need the relay long-poll shape, a bigger lift.
- Bundle size caps / large-binary handling (the debt entry's last bullet)
  stays a separate follow-up - it's a transport concern, orthogonal to the
  reliability work above.
