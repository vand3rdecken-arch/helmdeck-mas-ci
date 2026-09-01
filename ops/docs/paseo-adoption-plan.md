# Paseo adoption plan

## Reference — MANDATORY
Every card in this plan MUST read the ACTUAL Paseo source, not just this summary:
`C:\Users\Tien Duy Vo\Downloads\_paseo_src` (TypeScript monorepo). Study the real
implementation and mirror its approach; do not reverse-engineer from the plan text
alone. Key files: `packages/server/src/server/agent/providers/claude/agent.ts`
(session/turn/interrupt/resume), `packages/server/src/server/agent/agent-manager.ts`
(attention/permission/idle), `packages/server/src/server/agent-attention-policy.ts`
(presence/notify), `packages/protocol/src/agent-attention-notification.ts`
(permission kind: tool|plan|question|mode), `packages/protocol/src/agent-types.ts`
(select/question types), `packages/protocol/src/messages.ts` (tool-call/turn model),
`packages/server/src/terminal/agent-hooks/*` (activity-state normalisation),
`packages/server/src/utils/{worktree,tree-kill,spawn}.ts`.


Derived from a deep analysis of the Paseo source (`~/Downloads/_paseo_src`,
2026-08-06). Filtered to what is worth it for HelmDeck (single-owner, claude-
focused, mobile + daemon). Each phase is a gated worker card: worktree -> checks
-> gate -> owner accept. Phase 5 (provider seam, opaque IDs, forge registry) is
deferred and NOT in scope here.

Guiding principle borrowed from Paseo: **bound the tool, not the turn; interrupt
cooperatively, never lose the session; notify only when the owner isn't already
looking.**

## Phase 0 - already shipped (baseline, 2026-08-06)
- Lossless resume (`_promote_live_session`) - sessions.py
- Bash tool timeout (`BASH_DEFAULT/MAX_TIMEOUT_MS`) - drivers.py `_env`
- "unterbrochen" label + abandoned-tool detection - claude_sessions.py, card_transcript.tsx
- Stop unfreezes zombies, single-instance lock - sessions.py, server.py
- Observability trio (elapsed clock / abandoned / waiting-for-you cue)

## Phase 1 - Runtime hardening (highest leverage)
Goal: no restart/timeout ever destroys a turn again; hung tools + interrupts are clean.
- 1.1 Idle-TTL sweeper (~2-5 min, 15s poll) replacing the single `wait(1800)`: evict
  runtime only, keep the session resumable; multi-condition guard (idle + no active
  turn + no tracked run + no pending permission + not protected). [drivers.py sweep_idle, server.py]
- 1.2 Cooperative interrupt instead of tree-kill: signal the claude stream, await ack
  ~2s, hard-kill only on hang - session survives for --resume. [drivers.py cancel, _run_turn_locked]
- 1.3 Stale-result suppression: after an interrupt, drop the late `result` frame so it
  can't falsely complete the next turn. [drivers.py pump]
- 1.4 Recognize `[Request interrupted by user for tool use]` and render it as a clean
  interrupted marker, not a prose bubble. [claude_sessions.py read_transcript]
- 1.5 Tree-kill escalation SIGTERM->grace->SIGKILL->confirm (reap MCP orphans). [drivers.py _tree_kill]
- 1.6 Stale-resume degradation: transcript JSONL gone -> fresh session with a visible
  notice, not a hard --resume failure. [drivers.py / claude_sessions.py]
Verify: throwaway card with a long sleep/adb -> idle-evict fires, session resumes;
Stop -> cooperative interrupt, context intact; restart mid-turn -> clean "unterbrochen" + resume.

## Phase 2 - Presence-aware notifications + question channel
Goal: no push when the owner is looking at the card; exactly one recipient; typed
approvals; AND the worker can ASK cleanly instead of parking with prose.

- 2.4 (PRIORITISED) Clean multiple-choice questions. Root cause: HelmDeck runs
  claude headless (`-p`, no canUseTool callback), so the worker can't answer
  AskUserQuestion interactively and falls back to prose + ends the turn (the
  "parks / waiting to be done" trap). Paseo intercepts it as
  permission_requested(kind:question) with options and routes the answer back via
  respondToPermission. Fix HelmDeck-fittingly: intercept AskUserQuestion in the
  worker's stream-json -> first-class "question" card state with real option
  BUTTONS -> owner's pick sent back as the next message so the turn CONTINUES with
  the choice. [claude_sessions.py, sessions.py, app card_transcript/composer]
- 2.5 Auto-continue on background completion: a turn that ends while a worker-
  launched background task is still running (and the worker is "waiting" on it)
  must trigger a follow-up turn when the task completes, not park the card in
  needs_you limbo. At minimum, distinguish the cue (waiting on a background task
  vs waiting on you). [drivers.py, sessions.py]
- 2.1 Client heartbeat: focusedCardId + appVisible + lastActivityAt (3-min freshness). [app heartbeat, server.py /presence]
- 2.2 3-tier notify policy: focused->silent, present->in-app, absent->push; "connected"
  != "present"; single push recipient. [notify.py, pm.py]
- 2.3 Edge-trigger on turn-end/error/permission; push dedup (permission first-only);
  errors never pushed. [notify.py, sessions.py]
- 2.4 Typed permission requests (tool|plan|question|mode) as first-class card state
  instead of chat prose. [sessions.py, app approve/deny UI]
Verify: emulator - card focused -> no push; app backgrounded -> push; two "devices" -> one pushes.

## Phase 3 - Transcript data model cleanup
Goal: a clean state model instead of the ad-hoc `abandoned` patch.
- 3.1 Tool-call = 4 states running|completed|failed|canceled (failed <=> error!=null);
  abandoned/interrupted -> canceled. [claude_sessions.py, card_transcript.tsx]
- 3.2 Split turn lifecycle from the step stream: turn_started/completed/failed/canceled
  + usage as their own events, not flat steps. [claude_sessions.py, transcript types]
- 3.3 compaction/error as first-class items (partly present). [card_transcript.tsx]
Verify: tsc + transcript renders all 4 tool states + turn failure with usage.

## Phase 4 - Worktree/env robustness
- 4.1 Worktree ownership keyed off the git-common-dir hash + ownership by path shape
  (cleanup survives a broken git state). [sessions.py worktree path + cleanup]
- 4.2 Per-card auto-allocated, persisted dev port (no port fights). [sessions.py]
- 4.3 Branch `--no-track` off resolved `origin/<base>` (reject HEAD/empty) + rebase-HEAD
  guard when reading current branch. [sessions.py]
- 4.4 Split env models + hydrate daemon PATH/JAVA_HOME at launch (setup steps run in a
  reproducible non-interactive shell). [drivers.py _env, surfaces/desktop/setup.js]

## Order & deferred
Recommended: P1 -> P2 -> (adopt protocol-discipline convention) -> P3 -> P4.
Deferred (Phase 5, not scoped): provider seam / capability flags, opaque IDs over
paths, forge registry, skills managed-dir. Not adopted: Paseo's PTY terminal
(HelmDeck correctly uses piped stream-json), unbounded agent concurrency.

Phase 5 is now ANALYSED (not built): see `ops/docs/multi-engine-support.md` for the
provider-seam comparison against the real Paseo source, the measured HelmDeck
change surface, and an ACP-driver integration plan with per-block effort
estimates.

## v0.7.0 changelog parity check (2026-09-01)

Paseo 0.7.0 shipped a batch of resilience/data-model fixes. Checked each
bug class against real HelmDeck source (not the changelog text alone) before
concluding anything:

- **CONFIRMED ABSENT** (HelmDeck already guards against these - no action):
  daemon crash on a dead child's stdin EPIPE (`drivers.py` write sites are
  already try/except-wrapped per-turn, per-card background threads only -
  `spine/ops/bgthread.spawn`); git subprocess spawns stalling the HTTP
  dispatcher (`ThreadingHTTPServer` + per-job threads, no shared lock); stale
  pending-question cards surviving an interrupt (`sessions.py` `steer()`/
  `answer()`/`cancel_turn()` all explicitly clear or claim `question`); a
  false "reopened" status on TodoWrite items (HelmDeck renders each
  `TodoWrite` call as an independent snapshot, no cross-call identity
  comparison exists to get this wrong); desktop update admission getting
  cleared by a later poll (no staged-rollout gate exists at all - see
  `native-updater.js`'s own comment on deliberately skipping that
  machinery); older desktop builds dropping newer settings.json fields on
  rewrite (`spine/storage/events.py` does a raw dict overlay, never a
  schema round-trip); commits forced to skip GPG signing (no call site in
  `gitutil.py`/`lanemachine.py`/`henry_broker.py` passes a signing override -
  git already applies the user's own config).
- **FOUND, filed to backlog**: [[livemic-stop-drops-tail]] (worse than
  Paseo's own #4065/#3968 dictation bugs - HelmDeck drops the tail entirely,
  Paseo's was merely late) and [[git-subprocess-no-timeout]] (small, low
  severity, noted so it isn't lost).

Method note for next time: `git log --all --oneline --grep="#<PR-number>"`
against a local Paseo clone finds the exact fix commit fast - much cheaper
than diffing the full history or guessing from changelog prose alone.
