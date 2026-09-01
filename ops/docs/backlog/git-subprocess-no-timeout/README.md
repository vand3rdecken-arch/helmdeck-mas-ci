# Bare git subprocess calls have no timeout - a hung one pins a thread forever

**Filed 2026-09-01, from a Paseo 0.7.0 changelog parity check** (alongside
[[livemic-stop-drops-tail]], both found while checking HelmDeck against
Paseo's 0.7.0 fixes per `ops/docs/paseo-adoption-plan.md`). This one is small
and NOT urgent - noted so it doesn't get lost, not because anything is on
fire.

## The gap

Every `git` invocation in `spine/git/gitutil.py` (`_git`, `_git_try`,
`_branch_exists`, plus the fetch/import helpers further down the file) calls
`subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)`
with no `timeout=`. If a `git` process ever blocks waiting on input - an
interactive credential prompt, an SSH host-key confirmation, a signer prompt
if commit signing is ever turned on (see the adjacent, already-confirmed-safe
check that HelmDeck never forces `--no-gpg-sign`) - that call hangs
indefinitely.

## Why it's real but low-severity

HelmDeck's daemon already isolates this well: git work always runs on a
per-job background thread (`spine/ops/bgthread.spawn`), never the HTTP
request thread, so a hung git call can't take down the daemon or block other
cards. But it WOULD produce exactly the "card looks stuck, needs_you never
fires" symptom class the owner has hit before (see memory: "Stuck = usually
needs_you", the turn idle-watchdog work in Phase 1 of the adoption plan) -
except this path sits below any of that machinery, since Phase 1's
idle-TTL/interrupt/tree-kill hardening was built for the CLAUDE driver
process, not for bare git subprocess calls made by the orchestrator itself.

## Wanted

Add a bounded `timeout=` (e.g. 60-120s, matching the pattern already used for
the Claude driver's own timeouts) to the `subprocess.run` calls in
`spine/git/gitutil.py`, and decide what a timeout should surface as (a
`TimeoutExpired` -> the same escalation path a driver crash already uses,
per `henry_broker.py`, so the owner sees "git hung on X" rather than a
silently stuck card).

## Verify

- A git call given an artificially unreachable remote / a `GIT_ASKPASS` that
  never returns times out within the configured bound instead of hanging the
  worker thread forever, and the card surfaces a clear escalation instead of
  going silently stale.
