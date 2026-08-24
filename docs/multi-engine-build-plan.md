# Multi-engine build plan — full Paseo-equivalent breadth, card by card

Executes the recommendation of `docs/multi-engine-support.md` (read that FIRST —
it carries the analysis, the change surface, and the trap register). Same shape
as `docs/paseo-adoption-plan.md`: each phase is a gated worker card
(worktree → checks → gate → owner accept), each with a Verify line that is a
MEASUREMENT, not a rendering check.

## Reference — MANDATORY

Every card MUST read the ACTUAL Paseo source, not the analysis summary:
`C:\Users\Tien Duy Vo\Downloads\_paseo_src`. Per-card key files are named in
each card below. The ACP wire protocol is specified at
<https://agentclientprotocol.com/protocol/overview> — read the spec pages for
the exact methods a card touches, not a blog summary.

## Corrections from the review of the analysis (2026-08-24)

Two facts the analysis under-weighted, both verified on this box:

1. **No second engine is installed.** `where opencode gemini codex copilot`
   finds nothing; npm global list has none. Card 3 therefore has an
   install-and-authenticate prerequisite that is OWNER work (a login flow in a
   browser cannot be done by a headless card).
2. **A second engine is a second bill.** The analysis treated economics as a
   reporting problem (tokens vs €). Operationally it is first an *account*
   problem: OpenCode needs provider credentials, Codex needs an OpenAI login,
   Copilot CLI needs a Copilot seat. **Gemini CLI is the one candidate with a
   real free tier** (Google login, no card), speaks ACP natively
   (`gemini --acp`; Paseo launches it as `npx -y @google/gemini-cli --acp`,
   `packages/app/src/data/acp-provider-catalog.ts:182-189`), and is therefore
   the default probe target below.

Everything else in the analysis survived review: every file:line citation that
was spot-checked resolved (proctable:216, price table, gate neutrality,
`stream.ts` claude branches, the §6.3 systemPrompt grep, the capability tables,
the event union), and the spawn-site inventory matches an independent grep.

## Defaults chosen (owner can override by rejecting the card)

These were the open decisions in `multi-engine-support.md` §7; building means
picking, so the plan picks and says so:

- **Path (REVISED 2026-08-24 — owner decision):** full Paseo-equivalent
  breadth, not ACP alone. Generic ACP stays the DEFAULT (§6 of the analysis,
  Cards 3–4 below) for the ~30 engines it reaches natively; NATIVE adapters
  are added on top for the three Paseo treats specially — Codex, OpenCode
  (via Paseo's own dedicated-server acquisition mode, not its shared
  default — see analysis §6.6.2), and Pi/OMP. See analysis §6.6 for the full
  reasoning and per-engine mechanics; Cards 6–9 below are the resulting work.
- **Probe engine**: Gemini CLI, free tier — the only zero-billing candidate,
  used to validate the ACP path (Card 3). Codex/OpenCode/Pi/OMP each need
  their OWN owner step (account/login) before their native-adapter card —
  named in each card below.
- **Economics**: Paseo's model — when an engine reports no cost, the card shows
  "n/a", never a fabricated 0; plan-share math simply excludes those cards.
  OpenCode and Pi/OMP DO report real cost natively (analysis §6.6.4) — Card 9
  wires that in once Card 5's generic econ-honesty scaffolding exists.
- **E3 (timeline store)**: its own card, dual-write with comparison before
  cutover. It pays the NO-MONKEY-PATCHES debt and is worth accepting even if
  the owner stops after it.

## Guiding principles (from the trap register, §6.4 of the analysis)

- Engine id is DATA passed in, never a constant an implementation asserts.
- No vendor types/branches in neutral code; `TStep` stays engine-blind.
- No id-sniffing in generic paths; one source of truth for the engine list
  (settings.json `drivers`, as today).
- A typo'd capability key must FAIL, not read as false — validate the key set.
- Every normalisation layer logs raw_event/parsed_event pairs.

---

## Card 1 — Engine seam (E1 + E2 + E14) — SHIPPED 2026-08-24

Pure refactor; behaviour with claude must be bit-identical.

**Landed narrower than scoped below, deliberately**: `daemon/spine/agent/
engines.py` (a full capability-flag registry) was NOT built - no second engine
is installed on this box, so there was nothing to validate a capability
abstraction against, and building one anyway would have been exactly the
speculative scaffolding this repo's own law forbids. What shipped: the CLAUDE
constant dedup (`agentcli.py` is now the single source, all 6 call sites
updated) and the parent-session env scrub (`spawnenv.py` - a real, live hazard
today, not a multi-engine-only concern). The registry itself is still Card 3's
job, once there is a real second engine to design it against.

- `daemon/spine/agent/engines.py` (new): the engine registry —
  `{name: {run_fn, capabilities, resolve_exe, process_images}}`. `drivers.run`
  dispatches through it; today's `claude`/`http`/`cmd` branches become entries.
  Capabilities (validated key set): `supports_resume`, `supports_streaming`,
  `supports_system_prompt`, `reports_cost`, `supports_mcp`.
- `agentcli.py`: `_real_claude_exe` → parameterised shim resolution
  (npm-.cmd → real exe is a per-engine map, the BatBadBut lesson generalised).
  Fold the six duplicated `CLAUDE = …` constants onto one import
  (`drivers.py:54`, `copilot.py:14`, `sessions.py:17`, `processes.py:22`,
  `probe_harness_settings.py:48`, `tests/probe_cli_askuser.py:25`).
  `desktop/setup.js`'s JS twin stays for Card 5.
- `spawnenv.py`: add Paseo's parent-session scrub — `CLAUDECODE`,
  `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_SSE_PORT`, `CLAUDE_AGENT_SDK_VERSION`
  (`provider-launch-config.ts:203-211`). This is a live hazard TODAY for
  direct/machine cards spawned from inside a Claude session.
- `proctable.py`: `_is_agent_pid` image list comes from the registry
  (default unchanged: `claude|node|cmd`).

Paseo reading: `provider-registry.ts:118-159` (factory table),
`provider-launch-config.ts` (whole file).

**Verify**: gate green; full `daemon/test_*.py`; `/harness` spawn-preview argv
byte-identical before/after; one live throwaway card turn on the running
daemon behaves identically. Size **M (1.5–2d)**.

## Card 2 — Event-time timeline store (E3) — SHIPPED 2026-08-24

The card feed becomes first-class state the DRIVER writes, instead of a
re-parse of Claude Code's private `~/.claude/projects/**.jsonl`. Pays
`daemon/spine/registry/debt.py`'s `card-feed-is-claude-private-jsonl` entry
(now `status: paid` — read it for the full account).

- `daemon/spine/agent/timeline_store.py` (new): append-only JSONL,
  `{"_id": step_id, **patch}` per line, `read()` folds every line sharing an
  `_id` via `dict.update` in file order — a running tool receiving its result
  is a PATCH line, not a rewrite, so it stays genuinely append-only.
- `_ClaudeSession._fold_timeline` (`drivers.py`) folds every stream event at
  the moment each block completes — same discipline as `_scan_bg`
  (`drivers.py:634-680`), called from the exact same `if typ in
  ("assistant","user")` gate.
- `claude_sessions.read_transcript_store`/`transcript_store_version` are the
  new primary readers; `/transcript`, `/transcript/live` and the SSE tick
  (`routes_tracks.py`, `routes_track_actions.py`) all cut over. The old
  `.jsonl` reader is kept for exactly what the plan called for: pre-cutover
  `session_chain` history (adopted/rotated-away foreign sessions) and the
  in-progress `live_partial.txt` streaming block (the store only ever holds
  COMPLETED blocks).
- Verified with `tools/compare_timeline.py` (new) against real dispatched
  turns on a throwaway daemon (port 3915, isolated worktree data, a scratch
  repo under a real Windows path — `/tmp/...` silently fails since the daemon
  is a native Windows process) before cutover, per the plan's own discipline.

**Two real bugs found and fixed during verification, not assumed away:**
1. The human's own steer text NEVER arrives on the output stream — Claude
   Code does not echo stdin back; `type:"user"` frames are only `tool_result`
   echoes. Fixed by folding at the point the driver WRITES the prompt
   (`_run_turn_locked`), where it's known with certainty. HelmDeck's own
   harness-injected prompts (ask-repair) are re-attributed to a system note
   there too, exactly like the old reader.
2. A message's LIVE `usage.output_tokens` can read far below its own settled
   value in the persisted file — measured: `2` live vs. `152` in the file,
   same `message.id`, no later live frame ever corrects it. Documented as a
   permanent, harmless approximation: `ctx` (input + cache), the only usage
   field `econ.py`'s context meter reads, is proven identical live vs. file.
   `compare_timeline.py` excludes `tokOut` from its usage comparison for this
   reason, with the measurement in the code comment.

**Not done**: no app screenshot — zero frontend code changed (the `TStep`
wire contract is byte-identical, verified directly against the JSON) and
`app/node_modules` isn't set up in this worktree. Recommend the owner spot-
check a real card's feed once after accepting.

**Verify**: side-by-side diff EMPTY on real turns covering text, thinking,
tools (all 4 states), todos, usage, a `<helmdeck-ask>` question, a cancel —
DONE, all categories PASS (unit tests with synthetic events for the full
matrix; 5 real dispatched-and-cancelled turns on a live throwaway daemon for
end-to-end confirmation, including through the actual `/transcript` HTTP
route post-cutover). Size **L (3–5d)**.

## Card 3 — ACP transport + Stage-0 spike + the E9 probe (E4 + E5 + E9)

**Owner prerequisite (the one human step): install + authenticate Gemini CLI**
— `npm i -g @google/gemini-cli`, run `gemini` once interactively, complete the
Google login. Everything after is card work.

- `daemon/spine/agent/acp.py`: NDJSON JSON-RPC 2.0 client over Popen pipes.
  Reuse the `_ClaudeSession` skeleton: pump thread, `_send_control`-style
  request/response correlation (`drivers.py:549-574` is already 80% of it),
  tree-kill teardown, PID registration.
  Methods: `initialize` handshake → `session/new {cwd, mcpServers: []}` →
  `session/prompt` (turn = the RPC *response*; `stopReason` →
  `meta.subtype`/`is_error`/`canceled`) → `session/cancel`.
  Trap (measured by Paseo): some agents hard-require `sessionId` + `cwd` +
  `mcpServers` on `session/load` even when empty — never omit them.
- Inbound `session/request_permission`: auto-pick the most permissive offered
  option when `perm` is `acceptEdits`-class (Stage 0 scope; typed-ask routing
  is Card 4's).
- Stage-0 reply: accumulate `agent_message_chunk` text; full TStep mapping is
  Card 4. `meta`: tokens from `PromptResponse.usage` if present,
  `cost_usd=None`, `models=["gemini-acp"]`.
- Resume: `session/load` if advertised, else `supports_resume=false` and the
  card carries a visible "kein Sitzungsgedächtnis" badge — a flag, never a
  silent degradation.
- **The E9 probe is this card's second deliverable** — the GO/NO-GO gate:
  measure brief adherence three ways (`GEMINI.md`/`AGENTS.md` context file in
  the worktree; first-prompt prepend; both) × three behaviours (emits
  `<helmdeck-ask>` in protocol form when blocked? emits DELIVERED/Ready for
  Review? respects the no-merge boundary?). Written up as
  `docs/acp-probe-report.md` with transcripts.

Paseo reading: `acp-agent.ts:1003-1081` (spawn+init), `:1379-1446` (session),
`:2686-2712` (stopReason), `:2021-2034` (interrupt), `:2085-2113` (permission).

**Verify**: a real backlog card dispatched with driver `gemini-acp` produces a
committed worktree change and a coherent reply; Stop mid-turn works; daemon
kill mid-turn leaves no orphan gemini process after `reap_orphans`; probe
report exists with a clear GO/NO-GO. Size **L (3–4d)**.

## Card 4 — Full feed + cancel parity (E6 + E10) — needs Cards 2 + 3, and a GO from the probe

- `session/update` → TStep: all 8 variants (`agent_message_chunk`,
  `agent_thought_chunk`, `tool_call`, `tool_call_update`, `plan`,
  `current_mode_update`, `available_commands_update`, `usage_update`), tool
  status through the vocabulary normaliser
  (`tool-call-mapper-utils.ts:14-39`), delta/full dedup, raw/parsed trace
  pairs on every event.
- Interrupt parity: resolve pending permissions as cancelled → `session/cancel`
  → synthesise `canceled` TSteps for still-running tools → force-synthesise the
  terminal event on ack-without-settle (the existing escort pattern,
  `drivers.py:517-542`, generalised).
- `turn_active`/`has_session` stay derived observations — identical semantics
  so all 12+ consumers are untouched.
- Burn-watch reads ACP `tool_call` events (name + input hash, as today).

**Verify**: feed shows streaming text, 4-state tool steps, cancel marker, todos;
steer-while-running interrupts and continues on the same session; burn flag
fires on a forced loop. Size **M–L (2–3d)**.

## Card 5 — Econ honesty + UI surface (E8 + E12)

- `econ.py`: engine-neutral usage-key mapping; `cost_usd=None` renders as
  "Kosten: n/a (Engine meldet keine)" — never €0.00; `price_turn` takes
  optional per-engine table entries; `plan_effective`/`pm_budget` exclude
  n/a-cost cards from plan-share math (turns still counted).
- Routes: `/sessions/<engine>` (keep `/sessions/claude` as alias); New-Request
  driver picker lists engines from settings with an availability probe
  (exe resolvable?) and capability badges; `desktop/setup.js` probes
  per-engine; the five `.replace("claude-","")` label sites generalised.

**Verify**: `npx tsc --noEmit`; emulator screenshots of picker + cost display
+ resume badge, JUDGED (readability, centering, collisions — the owner reviews
UI hard). Size **M (2d)**.

## Card 6 — Codex native adapter (N1, analysis §6.6.1)

**Owner prerequisite**: an OpenAI account with Codex CLI access —
`npm i -g @openai/codex` (or the current install path), run once
interactively to complete login. Own step, separate from Card 3's Gemini
login.

- `daemon/spine/agent/codex.py`: JSON-RPC 2.0 over stdio, newline-delimited.
  Spawn `codex app-server` (`+ --enable goals` if `codex --version` clears
  `CODEX_GOALS_MIN_VERSION`); no cwd at spawn, it's a `thread/start` param.
  Handshake: `initialize` request → `initialized` notify with
  `CODEX_NON_ORIGINATING_APP_SERVER_CLIENT_INFO` (Codex keys "who is the
  model-request originator" off the client name — do not invent one).
  Session: `thread/start` → thread id; resume is `thread/resume` GUARDED by
  `thread/loaded/list` (only resume a thread that's actually loaded).
  Turn-end: `turn/completed` NOTIFICATION, `status: completed|failed|
  interrupted` → `meta.subtype`/`is_error`/`canceled`. Interrupt:
  `turn/interrupt {threadId, turnId}` — CANNOT interrupt before `turn/started`
  names the turn id, so a Stop pressed in that narrow window must queue, not
  error.
- Permissions are STRUCTURAL, not per-prompt: `approvalPolicy` + `sandbox` at
  `thread/start`, chosen from HelmDeck's `perm` knob (`acceptEdits`-class →
  the least-restrictive Codex preset). If Codex nonetheless sends an inbound
  `item/commandExecution/requestApproval` (a mode gap, not expected in
  unattended mode), auto-`accept` it rather than hanging the turn.
- `meta`: tokens only (`toAgentUsage`, no cost field) — same "n/a" handling
  Card 5 already built for ACP engines.

Paseo reading: `codex-app-server-agent.ts:3226-3247` (spawn+handshake),
`:4506-4543` (thread/start), `:3564-3602` (resume guard), `:5297-5333`
(turn-end mapping), `:4253-4268` (interrupt), `:3472-3491` (approval
handlers).

**Verify**: a real card on driver `codex-native` writes a file and reports
back; the SAME card's second turn resumes context (ask about what it just
wrote); Stop mid-tool-call cleanly interrupts; no process leak after daemon
kill (same orphan-reap check as Card 3). Size **M (2–2.5d)**.

## Card 7 — OpenCode native adapter, dedicated-server mode (N2, analysis §6.6.2)

**Owner prerequisite**: OpenCode installed + a model provider configured
(`npm i -g opencode-ai`, then `opencode auth login` or equivalent for
whichever model backend the owner wants OpenCode driving — OpenCode itself
is free/open-source, the COST is whatever provider it's pointed at).

**The one thing this card must get right**: Paseo's DEFAULT OpenCode
transport shares one `opencode serve` process across many sessions — that
breaks HelmDeck's per-card tree-kill isolation (analysis §6.1 point 2). This
card uses Paseo's OWN `acquireDedicated(env)` mode instead — one PRIVATE
`opencode serve --port <ephemeral>` per card, spawned and owned by that
card's session object exactly like `_ClaudeSession.proc`. Do not build the
shared-pool version; there is no HelmDeck use case that needs it, and it is
the one thing analysis §6.5 explicitly says not to adopt.

- `daemon/spine/agent/opencode.py`: allocate an ephemeral port (`net`
  bind-to-0 trick or equivalent), spawn `opencode serve --port <p>` with cwd
  set to a NEUTRAL home dir (not the card's worktree — launching from the
  worktree makes OpenCode index it as the default workspace; the actual
  workspace is passed as `directory` on every HTTP call instead). Wait for
  `"listening on"` on stdout, 30s cap, keep first 8KiB of stdout+stderr for
  the failure message.
  PID-register it exactly like a claude child so `reap_orphans`/tree-kill
  see it; owner tag `{provider:"opencode", kind:"dedicated-server"}` in the
  process table (distinct from Paseo's `"helper-server"` tag — this one is
  NOT shared, don't let it get swept by shared-server logic that doesn't
  exist here anyway, but keep the tag honest for future debugging).
- Session: `POST /session {directory}` → session id (stored as the card's
  `session_id`, same field every other driver uses). Resume is stateless —
  no flag, just reattach id + cwd to a (new, since dedicated) server
  instance; the OLD server is gone once its card's daemon session ends, so a
  resume after an idle-eviction respawns BOTH a fresh server AND reattaches
  the existing OpenCode session id to it (measured-safe per Paseo: session
  identity lives in OpenCode's own storage, not in the server process).
- Streaming: ONE SSE connection per card to `/global/event` (simpler than
  Paseo's multi-tenant demux since this server serves exactly one card).
  Turn-end: `session.idle` on the bus, NOT the HTTP response (`session.
  promptAsync` is fire-and-forget). Dedup delta vs. full text parts by
  `partID` (analysis §4.3). Cancel: local abort → `session.abort` capped at
  2s → before the NEXT turn, poll `session.status` until idle (measured:
  OpenCode 1.14.42+ blocks abort until the running tool actually stops).
- Permissions: `permission.asked` event → `auto_accept` toggle answers it
  BEFORE it's ever surfaced, for `acceptEdits`-class `perm`.
- `meta`: REAL cost this time — `part.cost` accumulated per session, cross-
  checked against `session.updated.info.cost`.

Paseo reading: `opencode/server-manager.ts` (whole file — spawn, port alloc,
`acquireDedicated`, PID registration), `opencode-agent.ts:1302-1388`
(session create/resume), `:3485-3536` (SSE consume + EOF-during-turn
handling), `:2489-2502` (delta/full dedup), `:3009-3110` (interrupt +
pending-abort-before-next-turn), `:4323-4345` (auto-approve), `:808-858`
(cost accumulation).

**Verify**: a real card on driver `opencode-native` produces a per-card
`opencode serve` process (confirm via PID table — NOT a shared one across
two simultaneously-dispatched OpenCode cards); killing one card's session
does NOT affect a second concurrent OpenCode card's session (the isolation
property this whole card exists to prove); cost shows a real number, not
"n/a". Size **M–L (2.5–3d)**.

## Card 8 — OMP native adapter (N3, analysis §6.6.3) — SHIPPED 2026-08-24 (omp only, Pi deferred)

**Landed via an unplanned owner step — no new login needed at all.** `omp.exe`
was already installed on this box (`%LOCALAPPDATA%\omp\omp.exe`, prior owner
use), and `omp --help` shows `ANTHROPIC_OAUTH_TOKEN` takes precedence over
`ANTHROPIC_API_KEY` — proven live: feeding it the SAME OAuth token
`~/.claude/.credentials.json` already holds (the exact read `turnopts.
_oauth_token()` already does) let it drive real turns on the owner's
existing Claude subscription with zero new account. This made omp the ONE
native engine actually buildable-and-verifiable end-to-end in this session -
Codex/OpenCode/Pi still need their own owner step (Cards 6/7, and the Pi half
of this one, remain unshipped).

**The wire protocol in this card's original scope text (below the line) was
WRONG in one specific and important way** - kept here, struck through, as a
record of what "measure, don't assume" actually caught: reusing Paseo's own
TS types (`pi/rpc-types.ts`) as ground truth got the REQUEST shape right
(`{"type":"prompt","message":str}`, matching `PiAgentRunRequest`) but nothing
in that source told a reader that ONE submitted prompt can produce MULTIPLE
internal `turn_start`/`turn_end` pairs when tool calls are involved - proven
live 2026-08-24: a two-tool prompt emitted two `turn_end` events, the FIRST
carrying the model's own "I'll do X now" narration text, not the answer. An
early version of this driver returned that narration as the reply. Fixed by
treating `agent_end` (fires exactly once, for both normal completion AND
after `abort`) as the true completion signal instead - a pinned regression
test (`tests/test_omp_driver.py`, "MULTI-TURN tool loop") reproduces the
exact failure this caused.

**What shipped** (`daemon/spine/agent/omp_driver.py`, new; `drivers.py`
`run()` dispatch + `cancel`/`has_session`/`turn_active`/`drop_session` now
check omp's registry too; `proctable._is_agent_pid` knows the `omp` image):
- Transport: JSONL-RPC over stdio, one persistent `omp --mode rpc-ui`
  process per card (same isolation shape as `_ClaudeSession` - no shared-
  server conflict, unlike OpenCode's default mode).
- Session identity: a FILE PATH derived from `run_dir`
  (`<run_dir>/omp_session`) - proven live: the SAME path across two SEPARATE
  process spawns correctly recalled prior-turn context. No field to keep in
  sync on the track; resume is automatic.
- Brief delivery: native `--append-system-prompt` - no ACP-style blocker at
  all (§6.3 does not apply to this engine).
- Cost: REAL `usage.cost.total` in USD per message, accumulated onto the
  turn's `cost_usd` - proven live ($0.11-0.15 per real dispatched turn,
  correctly landing in the track's `ai_cost` and flowing through the SAME
  `econ._record_econ` path claude uses, no new econ code needed).
- Cancel: `{"type":"abort"}`; a cancelled tool call's own `tool_execution_end`
  reports `isError:true` with `"[Command cancelled]"` - mapped to the 4-state
  model's `canceled` (not `failed`), matching the claude driver's own
  interrupt-sentinel rule, only caught by testing a REAL cancel against the
  real daemon (a synthetic-only test pass would have missed this, since
  nothing in the request/response shapes hints that a cancelled tool call
  even reports `isError`).

**Verified**: `tests/test_omp_driver.py` (27 checks, synthetic frames built
from real captured JSON - see the module docstring's "measured live" notes)
+ real dispatches on the live throwaway daemon: a two-tool turn (write+ls,
correct final reply, real cost), an explicit-model dispatch (confirms the
auto-model-routing gap below), a steer/resume (turn 2 correctly recalled
turn 1's file content), a real mid-turn Stop/cancel (tool step lands
`canceled`, track `last_reply` reads "(turn cancelled by you)" - the SAME
sentinel claude's driver uses) - through the ACTUAL `/tracks/.../transcript`
HTTP route post-Card-2-cutover, not just the store directly.

**One real gap found and registered, not silently shipped**: HelmDeck's
`policy.auto` model routing (`turnopts.resolve_model`) only knows
claude-shaped model ids and hands them to whatever driver is active
unchanged - measured live, an auto-routed omp card got the literal string
`"claude-sonnet-5"` fed to `--model`, which omp's OWN fuzzy-matcher happened
to resolve correctly (the turn worked, cost more than an explicit `haiku`
dispatch would have). Filed as `daemon/spine/registry/debt.py`'s
`auto-model-routing-is-claude-ids-only` (open) - the workaround (an explicit
`model` on card creation bypasses the auto-resolve branch entirely) is
proven, the real fix is out of this card's scope.

**Not built this session**: the Pi half (single-vendor CLI, not installed on
this box, no owner-account shortcut like omp's existing OAuth reuse) -
`daemon/spine/agent/omp_driver.py` is OMP-specific by name and by a few
omp-only details (its tool-name vocabulary, its exact usage/cost field
names); a Pi adapter would very likely reuse most of the JSONL-RPC/session-
path/agent_end structure but needs its OWN live protocol measurement before
being assumed identical - `pi/rpc-types.ts` and `omp`'s measured behavior are
close cousins, not proven identical.

<details>
<summary>Original scope text (kept for the record; superseded above)</summary>

Lowest priority of the three — single-vendor CLIs, not a widely-adopted
engine. Build only if the owner specifically wants Pi or OMP; otherwise
defer indefinitely without blocking anything else (Cards 6/7/9 don't depend
on it).

- `daemon/spine/agent/pirpc.py`: JSONL-RPC over stdio, `pi --mode rpc` /
  `omp --mode rpc-ui`. Session identity is a FILE PATH, not a uuid —
  `--session <path>` at spawn (`--no-session` for ephemeral) — the one engine
  where resume is baked into argv instead of a protocol call.
  Cost: `get_session_stats` RPC → `stats.cost`; version-compat fallback to
  `get_state.contextUsage` if the stats RPC doesn't exist on the installed
  version.

Paseo reading: `jsonl-rpc-process.ts` (whole file), `pi/runtime.ts:110-138`
(argv construction), `pi/cli-runtime.ts:143-145,171-201` (abort, stats
fallback).

**Verify**: same shape as Cards 6/7 — real card, real turn, resume works,
cost is real. Size **S–M (1.5–2d)**.
</details>

## Card 9 — Wire native engines' real cost into econ honesty (N4)

Small top-up, needs Card 5's generic scaffolding (`cost_usd=None` → "n/a")
PLUS whichever of Cards 6–8 shipped. Codex stays "n/a" forever (tokens
only, native or not) — this card is specifically for OpenCode/Pi/OMP's real
`cost_usd`, which Card 5's scaffolding already has a slot for but nothing
populates yet outside `claude`.

- `econ.py`/`price_turn`: accept a driver-reported `cost_usd` from
  OpenCode/Pi/OMP's `meta` the same way it already does for claude (no new
  code path — Card 5 built this generically; confirm it actually fires for
  a non-claude `cost_usd` and isn't accidentally gated on `driver=="claude"`
  anywhere).
- `pm_budget.py`/`plan_effective`: these cards should COUNT toward plan-share
  economics now (they have real €), not be excluded the way tokens-only
  engines are — confirm the exclusion logic keys off `cost_usd is None`,
  not off `driver != "claude"`.

**Verify**: a real OpenCode-native turn's cost appears in `/tracks/<id>/turns`
and in PM budget totals, not as "n/a" and not silently dropped. Size **S (1d)**.

---

## Order, totals, deferrals

```
Card 1 ✅ ──→ Card 3 ──→ Card 4 ──→ Card 5 ──┬──→ Card 6 (Codex)    ──┐
Card 2 ✅ ──┬───────────↗                    ├──→ Card 7 (OpenCode) ──┼──→ Card 9
            └──→ Card 8 ✅ (omp; Pi deferred, no owner step needed) ──┘
```

Card 8 shipped directly off Cards 1+2 - it did NOT need Card 5's queue, it
just also happens to satisfy Card 9's "needs 5 + whichever of 6-8 shipped"
once Card 5 itself lands.

Cards 1, 2 and 8 (omp half) SHIPPED 2026-08-24 (see each card's section
above for what landed and how it was verified) — Card 8 shipped OUT OF the
originally-planned order because omp turned out to need no new owner step at
all (reused the daemon's existing Claude OAuth token), while Card 3's Gemini
prerequisite and Cards 6/7's own account steps were still open. Card 3 is
next, blocked only on the owner's one prerequisite (Gemini CLI install +
login — not doable from a headless card). Cards 6/7 each have their OWN
separate owner prerequisite and are independently orderable once Card 5
lands — build Codex first (biggest ecosystem after Gemini), OpenCode second
(real cost reporting is the biggest win). Pi (the other half of Card 8)
has no owner-account shortcut the way omp did and stays deferred.

**Total ~22–27.5 days across 9 cards, ~6–9 done** (full Paseo-equivalent
breadth — analysis §6.6.4 has the per-native-adapter breakdown). The ACP-only
subset (Cards 1–5) is **~12–16 days, ~4–7 done** and is a complete, coherent
stopping point on its own — reaches ~30 engines, just without Codex/OpenCode/
Pi's native depth (omp's IS done, out of order). After Card 3 the owner has a
working second engine at `cmd`-driver-plus quality and a measured answer to
the §6.3 brief question; after Card 4 it is daily-usable; Card 5 makes it
honest; Cards 6/7/9 bring the rest to full Paseo-equivalent breadth.

**Deferred, deliberately**: E11 (copilot/PM/Henry/processes/distill stay
claude-only — they are HelmDeck's governance organs, not card work);
OpenCode's SHARED-BY-DEFAULT transport (Card 7 uses the dedicated mode
instead — see that card and analysis §6.6.2); the Pi half of Card 8 (no
owner-account shortcut, no live protocol measurement yet — see that card's
"not built this session" note).

**Kill-switches**: if the Card-3 probe returns NO-GO on brief adherence (the
engine cannot be made to follow the ask/DELIVERED protocol reliably), stop
after Card 2 — which is worth having regardless — and revisit engine choice.
Each of Cards 6/7 is independently droppable without affecting the other or
Card 9's applicability to whichever DID ship (omp already qualifies for
Card 9 today).
