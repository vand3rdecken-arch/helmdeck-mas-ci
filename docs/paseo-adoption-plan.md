# Paseo adoption plan

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

## Phase 2 - Presence-aware notifications
Goal: no push when the owner is looking at the card; exactly one recipient; typed approvals.
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
  reproducible non-interactive shell). [drivers.py _env, desktop/setup.js]

## Order & deferred
Recommended: P1 -> P2 -> (adopt protocol-discipline convention) -> P3 -> P4.
Deferred (Phase 5, not scoped): provider seam / capability flags, opaque IDs over
paths, forge registry, skills managed-dir. Not adopted: Paseo's PTY terminal
(HelmDeck correctly uses piped stream-json), unbounded agent concurrency.
