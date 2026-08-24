# Fast-track toggle on a worktree card: convert to the live-tree rails

> **SHIPPED 2026-08-20** (owner-decreed direct fix - "might get stuck in gate
> again"): `sessions._convert_fast_track_live` + the `update_track` mid-turn
> guard, pinned by `daemon/test_fasttrack_convert.py` and the updated 6c case
> in `daemon/test_fast_track_direct.py`; debt note extended on
> `fast-track-no-gate`. Punch list below kept for the record; the one open
> item is the session-chain continuity measurement (last checkbox).

## The gap (measured 2026-08-20)

Flipping `fast_track` ON for a card that already started worktree-isolated
does NOT move it onto the no-gate Paseo rails. `cardadmin.update_track`
(cardadmin.py, `changed.get("fast_track") is True` branch) deliberately keeps
it isolated: the session transcript is cwd-keyed and the branch work hangs on
the worktree, so a live conversion would orphan both. The card then ships via
`_maybe_fast_track_ship` — which still runs the FULL gate.

Why this bit today: the card `req-worktree-base-sync` carried the fix for the
gate's own daemon-side bugs (zombie sweep killing live gates, gate-base-lag).
The buggy running daemon was the gatekeeper for the code that fixes it —
chicken-and-egg. Fast-track was supposed to be the escape hatch and wasn't;
the merge had to be done by hand outside the harness (ff to bce3f03).

## Wanted behavior

Owner semantics: flipping fast-track ON means "get this onto the live-tree,
no-gate, auto-deploy rails" — including for a card that started isolated.

Conversion is only safe when the turn is idle, so:

1. `fast_track: true` on a worktree card, turn idle (`turn_active` false):
   - land the worktree work onto base (autocommit; refuse on conflict
     markers, same data-hygiene line as `_maybe_fast_track_ship_direct`),
   - merge the card branch into the integration branch (this is the one
     deliberate gate-skip; it's what fast-track means — covered by the
     existing `fast-track-no-gate` debt entry, extend its note),
   - reclaim the worktree, repoint the card `direct=true, worktree=repo`,
   - drop the idle session (same move the driver-flip branch already does)
     so the next turn respawns cwd-keyed to the live tree.
2. Turn active: refuse the flip with a clear chat note ("wait for the turn
   to end"), do NOT queue a half-converted state.
3. Toggle OFF after conversion follows the existing direct→off branch
   (land uncommitted work now, stop deploying).

## Punch list

- [ ] `cardadmin.update_track`: replace the keep-isolated note with the
      conversion above (idle-only), reuse `_drivers.drop_session`.
- [ ] Conversion refuses while `turn_active` (invariant in update_track, not
      caller-dependent — same stance as the driver-flip guard).
- [ ] Extend `fast-track-no-gate` debt note in `spine/registry/debt.py`
      to cover the conversion merge.
- [ ] Tests: idle worktree card converts (branch merged, worktree reclaimed,
      direct set, session dropped); active turn refuses; conflict markers
      refuse; chat-only card (nothing to merge) converts cleanly.
- [ ] Session-transcript continuity: verify the respawned session still
      resumes the chat chain (session_chain) after the cwd move — measure,
      don't assume.
