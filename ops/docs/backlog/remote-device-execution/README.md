# Remote device execution: a team's own PCs as workers, gate stays central

Owner framing (2026-08-25 chat): a project team should be able to work with
HelmDeck in a MIXED topology - one central daemon reachable by every device
for board/chat/steer, AND multiple team members' OWN PCs actually EXECUTING
cards in their own dev environment (their own Android SDK, their own
toolchain), not the daemon's. On a member's own machine they may do
anything - "nur mergen nicht" (just not merge). Landing on main stays a
strictly central, gated act.

## The governing principle

Split EXECUTION (where a card's `claude` turns actually run - can be
anywhere) from GOVERNANCE (card state, audit, the gate, the merge, GxP
signatures - always the one central daemon). The boundary between them is
physical: a git branch. A device produces commits on a branch in ITS OWN
clone; the branch reaching the central daemon's repo is the only thing that
crosses the boundary, and from that point on the EXISTING, unmodified
lanemachine.py pipeline (`_gate` -> `_merge_to_main` -> `gxp.accept_block_
reason`) treats it exactly like a normal worktree card's branch. Verified
(lanemachine.py:162-196): `_gate` only ever needs `t["repo"]` + `t["worktree"]`
to be a real local checkout - it does not care how the branch got there.

## Prerequisite finding (2026-08-25 probe): the gate is not a universal
chokepoint today, and that is fine, AS LONG AS remote-device cards never
touch the paths that legitimately bypass it

Audited every path that can write to `main`. `_merge_to_main`
(lanemachine.py:263) IS the sole merge chokepoint for the normal
card/Henry-`move`/PM-accept path. But three OWNER-ONLY convenience paths
bypass it BY DESIGN, each already registered as open debt:
  - fast-track direct-ship (dispatch.py:194-210, debt `fast-track-no-gate`)
  - `new_direct_task`/machine cards (dispatch.py:334, debt
    `direct-build-no-gate`)
  - Henry's `did` verb (henry_broker.py:64-71, debt `henry-direct-hands`)
No git-level protection exists either (no pre-receive/pre-push hook) - the
gate is a pure application convention. This is acceptable for a
single-owner-on-their-own-machine shortcut; it would NOT be acceptable for
a team member's device. **Hard constraint for everything below: a
device-dispatched card is ALWAYS a normal worktree+branch card
(`machine`/`direct`/`fast_track` never set on it).** It goes through the
exact same gate a local card does - no new bypass is introduced.

## Design

### Identity: reuse auth.py's device tokens, add a thin device-metadata layer
A device does not need a new identity system. `auth.issue_token(name, label,
actor)` already mints a bearer credential that `auth.resolve(token=...)`
turns back into `{"name", "role"}` - a device's calls are already
authenticated AS the user who registered it, for free. New:
`daemon/devices.json` (git-ignored runtime data, same tier as users.json):
`{id, owner (username), label, token_id, created, last_seen}` - maps a
token to "this is Alice's laptop", nothing more. Registration is
owner/operator only (`devices_register_post`); a client can never own a
device, and `devices_queue_get`/`devices_submit_post` re-check the role at
USE time too, not just at registration, so a user later demoted to client
loses device access immediately rather than on next re-auth.

### Dispatch: `new_remote_task(repo, branch, task, device_id, actor, ...)`
Files a normal card (worktree card shape, NOT machine=True) via `new_track`
but never calls `_ensure_worktree`/`move_lane` - it stays in `backlog` with
`exec_site = "local:<device_id>"` recorded on it; there is nothing to check
out locally yet. `claim_remote_task(device_id)` (called from the queue
poll) moves the oldest matching backlog card straight to `working` without
touching `_start_inner` - the device is now the one doing the work.

### Pull, not push: the device long-polls, mirroring relay_client.py
The device is behind NAT/a firewall with no inbound port, same constraint
the phone-relay pairing already solved. Shipped endpoints (client blocked
by server.py's existing do_POST blanket gate for POST; the two GET/POST
handlers below also re-check role themselves, see above):
  - `GET /devices/<id>/queue` (long-poll, ~20s, same shape as
    tracks_transcript_live_get) - claims the daemon's own queue for that
    device; not a new relay hop.
  - `POST /devices/<id>/submit` `{track, bundle_b64}` - the device uploads a
    `git bundle` of its finished branch (base64 in JSON, same encoding
    routes_runs.py's videochunk already uses for the relay's text-frame
    constraint). The daemon does `spine.git.gitutil._import_bundle` (fetch
    into `t["repo"]`, verify first, refuse to clobber an existing branch of
    the same name), then the SAME `_ensure_worktree` a local card uses -
    `t["worktree"]` now points at a real local checkout - then
    `move_lane(tid, "review", actor)` UNMODIFIED. From here the card is
    gated exactly like one worked locally.

### The worker process itself
`ops/tools/hd_worker.py` (sketch, see below): long-polls
`GET /devices/<id>/queue`, on a claimed task branches its LOCAL clone,
shells out to `claude -p --permission-mode acceptEdits` directly in that
clone (full local capability - no HELMDECK_WORKTREE guard, this IS the
member's own trusted machine, per the owner's own framing that sandboxing
your own PC is theater), commits, bundles, `POST`s to
`/devices/<id>/submit`.

## Shipped this round (2026-08-25) - all proven in
`ops/tests/test_remote_device.py` (27 assertions, incl. the HTTP route
layer) against REAL git repos/bundles/subprocesses, not mocks
- `spine/auth/devices.py`: device registry (register/list/revoke/resolve/
  touch), layered on existing auth.py tokens.
- `spine/http/routes/routes_devices.py` + `spine/http/server.py` wiring:
  register/mine/revoke/queue/submit endpoints.
- `cells/engineer/dispatch.py`: `new_remote_task`/`claim_remote_task`/
  `submit_remote_result`, explicitly excluded from the machine/direct/
  fast-track bypass paths (see constraint above) - verified by an explicit
  assertion in the test.
- `spine/git/gitutil.py`: `_import_bundle` (verify, refuse-to-clobber,
  fetch a bundle into `repo`) - proven end to end against
  `_gate`/`_merge_to_main` unmodified.
- `ops/tools/hd_worker.py`: reference worker implementation (see debt
  `remote-worker-not-hardened` for what it deliberately skips).

## Explicitly NOT done this round (follow-up, named so it stays a decision -
registered as debt `remote-worker-not-hardened`, spine/registry/debt.py)
- `ops/tools/hd_worker.py` is a design sketch, not a hardened long-running
  service (no retry/offline/reconnect handling, no packaging/install story,
  shells out to `claude` directly instead of reusing
  spine/agent/drivers.py's turn machinery).
- No UI for registering/naming a device from the app.
- Device revocation does not yet kill an in-flight task (the device's
  token stops working on its NEXT call, mid-turn work is not interrupted).
- Bundle upload has no size cap / large-binary handling beyond what the
  relay's existing chunking pattern implies.
- `awaiting_device`/claimed-but-abandoned cards have no timeout or
  reassignment - a device that goes offline mid-task leaves its card
  stuck in `working` with no local worktree.
