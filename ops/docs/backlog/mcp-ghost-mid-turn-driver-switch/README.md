# windows-mcp ghost survives a mid-conversation driver switch

**Anlass (2026-09-16, direct-task card, marketing prep task):** card was
dispatched as a machine/direct task; ToolSearch found no `mcp__windows-mcp__*`
tool at any point, needed for a Product Hunt image upload (the bounded
`mcp__helmdeck-browser__*` verbs have no file-upload capability and hang on
"Paste a URL"). Owner said "Du laeufst jetzt mit dem claude-desktop Driver"
mid-conversation and asked to re-check via ToolSearch - still nothing, tried
both keyword queries and exact guessed names
(`mcp__windows-mcp__Click-Tool` etc.).

## What's confirmed NOT broken

- `claude mcp list` (CLI-level, this machine): `windows-mcp: uvx windows-mcp
  serve --transport stdio - Connected`.
- `~/.claude.json` user-scope `mcpServers.windows-mcp` is present and correct
  (`{"type":"stdio","command":"uvx","args":["windows-mcp","serve",
  "--transport","stdio"],"env":{"MCP_TIMEOUT":"60000"}}`) - exactly what
  `spine/agent/agentcli.py::_user_mcp_servers()` reads.
- The bridge mechanism itself (`agentcli._mcp_config_arg`, `drivers.py:597`,
  fixed 9cb229d per [[helmdeck-cards-mcp-ghost]]) is sound in principle: IF a
  turn's `cfg["allowed_tools"]` contains `mcp__windows-mcp__*` at spawn time,
  it resolves the server from `_user_mcp_servers()` and adds it via
  `--mcp-config`, independent of `--setting-sources project`.
- `new_machine_task` (`cells/engineer/cards/dispatch.py:440-459`) already
  defaults machine tasks to `driver="claude-desktop"` and force-corrects any
  driver whose `allowed_tools` lacks the windows-mcp grant - so a FRESH
  machine-task dispatch should already carry the right grant from turn 1.

## Root-cause hypothesis (not yet proven against the DB)

`-p --input-format stream-json` keeps ONE long-lived CLI process for the
current turn; `_mcp_config_arg` only runs when `drivers.py` builds a NEW
spawn's argv (`build_argv`, called once per turn/resume). A driver value
changed on the card's stored `cfg` mid-conversation cannot retroactively
change the argv of the process that is already running - the next argv
rebuild only happens on the NEXT turn spawn (`--resume <session_id>` with
freshly-built `--allowedTools`/`--mcp-config` flags). Because this
conversation stayed inside one continuous turn across the whole ask/answer
exchange with the owner, "switching the driver" changed the stored cfg but
never triggered a new `build_argv` call, so the running process kept its
original (pre-switch) argv with no windows-mcp registration - textbook ghost,
just at turn-boundary granularity instead of the card-boundary granularity
[[helmdeck-cards-mcp-ghost]] already fixed.

Not yet verified: whether `cfg["driver"]` actually persisted to `claude-desktop`
for this track in `helmdeck.db` at all (didn't check - db is off-limits for a
direct/machine card to touch per CLAUDE.md secrets rule, needs an owner-side
or Henry-side read).

## Suggested fix / verification (for Henry or the owner to dispatch)

1. Confirm via the daemon (not this card) whether the track's `cfg["driver"]`
   really flipped to `claude-desktop` for this session.
2. If yes: reproduce with a genuinely NEW turn (fresh `move_lane`/steer call
   that causes a new `build_argv`) after a driver switch, and confirm
   ToolSearch finds windows-mcp THEN. If it does, the fix is documentation/UX
   only - a driver switch note should say "takes effect on the next turn,
   not the current one," and the harness could proactively end the current
   turn (or warn) when a driver change lands mid-turn instead of silently
   no-op'ing until the next spawn.
3. If a fresh-turn spawn still doesn't surface windows-mcp even with a
   confirmed `claude-desktop` cfg, the bug is elsewhere in `build_argv`/
   `_mcp_config_arg` for the direct/machine path specifically and needs a
   repro test under `ops/tests/` (root-cause-not-workaround: a test that runs
   the real dispatch path, per [[feedback-root-cause-not-workaround]]).

## Why this matters beyond one card

Henry's own "hands" sub-agent already uses windows-mcp/browser reliably
per [[helmdeck-henry-three-tiers]] (fresh spawn each time, no mid-conversation
driver flip) - that path is unaffected and is the reliable way to get actual
mouse/keyboard/file-dialog control done today. The gap is specific to
mid-session driver switches on an already-running machine/direct card turn.

**done_when:**
- Repro test in `ops/tests/` that starts a card turn with driver=claude,
  flips its cfg to claude-desktop mid-turn, asserts the CURRENT spawn's argv
  is unaffected (documents the boundary) and the NEXT spawn's argv DOES
  contain `--mcp-config` with windows-mcp.
- Either a warning surfaced to the operator on a mid-turn driver switch
  ("takes effect next turn"), or the switch is made to end the current turn
  cleanly so the next one picks it up immediately.
