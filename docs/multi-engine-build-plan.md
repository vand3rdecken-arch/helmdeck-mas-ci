# Multi-engine build plan — ACP driver, card by card

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

- **Path**: generic ACP driver (§6 recommendation). Not OpenCode-native.
- **Probe engine**: Gemini CLI, free tier — the only zero-billing candidate.
- **Economics**: Paseo's model — when an engine reports no cost, the card shows
  "n/a", never a fabricated 0; plan-share math simply excludes those cards.
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

---

## Order, totals, deferrals

```
Card 1 ✅ ──→ Card 3 ──→ Card 4 ──→ Card 5
Card 2 ✅ ──────────────↗
```

Cards 1 and 2 SHIPPED 2026-08-24 (see each card's section above for what
landed and how it was verified). Card 3 is next, blocked only on the owner's
one prerequisite (Gemini CLI install + login — not doable from a headless
card). Total **~12–16 days** across 5 cards, ~4–7 done. After Card 3 the
owner has a working second engine at `cmd`-driver-plus quality and a measured
answer to the §6.3 brief question; after Card 4 it is daily-usable; Card 5
makes it honest.

**Deferred, deliberately**: E11 (copilot/PM/Henry/processes/distill stay
claude-only — they are HelmDeck's governance organs, not card work); OpenCode's
native HTTP+SSE transport (breaks per-card tree-kill isolation, §6.1.2);
model-catalog discovery (`fetchCatalog` machinery — HelmDeck's picker is a
whitelist by design).

**Kill-switch**: if the Card-3 probe returns NO-GO on brief adherence (the
engine cannot be made to follow the ask/DELIVERED protocol reliably), stop
after Card 2 — which is worth having regardless — and revisit engine choice.
