# HARNESS.md - the agent harness, for developers

`ARCHITECTURE.md` states the rule this whole directory exists to serve: **the
harness is code, policy is data.** This document is the developer's map of where
that line actually falls, how a spawn resolves across it, and what you have to
touch to move something from one side to the other.

Read `ARCHITECTURE.md` for the *why* and `CLAUDE.md` for the Laws. This file is
the *how*. `harness/README.md` is the short operator-facing version of the same
material; when the two disagree, the code wins and both are wrong.

---

## 1. What `harness/` contains

```
harness/
  agents/     one .md per surface - YAML frontmatter + the prompt as the body
    card-worker.md      an agent working ONE card in an isolated git worktree
    machine-worker.md   a task on the owner's own PC (no worktree, no branch)
    board-copilot.md    the board copilot / PM surface (~10 KB of board vocabulary)
  settings/   one .json per surface - a standard Claude Code settings file
    card.json           used by BOTH worker surfaces
    copilot.json        the copilot's own layer
  schema/     JSON Schema for each of the two file kinds, referenced by $schema
    agent.schema.json      validates the FRONTMATTER (the body is free prose)
    settings.schema.json   validates the settings layer
  .versions/  every write archives the bytes it replaced (git-ignored)
```

Loaded by `daemon/harness.py`. The agent-file convention (frontmatter + body) is
Claude Code's own, deliberately, so these files need no translation layer.

### The one law of the loader

> **`daemon/harness.py` can never break a spawn.**

A card is the owner's work in flight; a typo in a markdown file must not be able
to strand it. So every function on the read path is **total** - it returns the
built-in default instead of raising - and the built-in defaults in
`daemon/harness.py:50-98` are the exact text that used to be hardcoded in
`drivers.py` / `copilot.py`. Deleting `harness/` entirely degrades to precisely
the pre-harness behaviour.

Failures are not swallowed, though. They accumulate in `harness.errors()`, which
`/loop/map` and `/harness` surface, so a broken file is *visible* rather than
mysteriously ineffective. That split - **silent fallback, loud reporting** - is
the design, and `daemon/test_harness.py` pins both halves.

The write path is the deliberate **mirror**: `write_agent()` / `write_settings()`
*must* raise on a rejected edit, and must leave the file byte-identical when they
do. A rejection that returned quietly would leave the owner believing a brief is
live when it is not.

### What is deliberately NOT data

| | where | why |
|---|---|---|
| the role brief (what a worker can/cannot do, how to hand off) | **data**, `harness/agents/*.md` | policy - the owner may reword it |
| the `<helmdeck-ask>` wire protocol | **code**, `daemon/ask.py` | it is parsed by `ask.parse()`'s regex. Prompt and parser must ship together, or an innocent reword silently breaks every question button the owner taps. `harness.py` splices it in at the `{{ask_protocol}}` marker |
| the driver argv, auth, audit, gate, worktree isolation | **code** | fixed harness law - see §5 |

---

## 2. How a brief resolves and spawns

### The resolution chain

```
harness/agents/<name>.md
   │  _agent_file()      re-read when (mtime, size) changes - size is in there
   │                     because mtime granularity is ~1s on some filesystems
   │  _parse_agent()     frontmatter via PyYAML when importable, else the flat
   │                     `key: value` subset in _mini_yaml() - the loader must
   │                     have NO import that can fail
   │  frontmatter merged OVER the built-in defaults, so a file that forgot its
   │  frontmatter still gets its surface's normal wiring
   │  _resolve()         splices ask.BRIEF at {{ask_protocol}} (or appends it)
   ▼
harness.brief(name)  ->  the string handed to --append-system-prompt
```

Every step falls back rather than raising (`daemon/harness.py:209`).

### Which surface a spawn is

There are exactly three, declared once in `harness.SURFACES`
(`daemon/harness.py:315`):

| key | agent file | builder | cwd |
|---|---|---|---|
| `card` | `card-worker` | `drivers.build_argv` | the card's worktree |
| `machine` | `machine-worker` | `drivers.build_argv` | the task's working folder |
| `pm` | `board-copilot` | `copilot.build_argv` | repo root |

- **card vs machine** is decided by `drivers._agent_for(t)`: `machine-worker` when
  the track carries `machine: True`, else `card-worker`. That flag is stamped in
  exactly one place, `sessions.new_machine_task()`.
- **pm** is never resolved from a track - `copilot.py` names `"board-copilot"`
  directly. It has no card and no worktree.

### The resolved argv

`drivers.build_argv(agent, cfg, brief, session_id=None, adopted_source=None, exe=None)`
(`daemon/drivers.py:677`) is **THE** assembly point for a card or machine spawn:

```
claude -p
  --output-format stream-json  --input-format stream-json
  --include-partial-messages   --verbose
  --permission-mode <cfg.perm | acceptEdits>
  --append-system-prompt <brief>
  <<< harness.cli_args(agent) >>>        # --setting-sources … [--settings …]
  [--model <cfg.model>]                  # only if the card picked one
  [--allowedTools <pat>]…                # one pair per pattern
  [--resume <session-id>]                # only from the second turn
  [--fork-session]                       # only if adopted_source == session_id
```

`copilot.build_argv(cli_model, sid, system)` (`daemon/copilot.py:832`) returns
`(argv, role_in_turn)` and its flag order genuinely differs - `--model` /
`--resume` come *before* the system prompt and the settings layer goes last.

**These two functions are the only places an argv is assembled, and that is
load-bearing.** `/harness`'s spawn preview *calls* them rather than re-listing
the flags; a preview that re-listed them would be a heuristic reconstruction that
drifts the first time a flag moves and then lies confidently about a command it
no longer describes. `CLAUDE.md` forbids exactly that. If you add a flag, add it
in the builder and the preview follows for free.

### Two traps that cost real time

1. **Never spawn a `.cmd` shim with quoted arguments.** `drivers._cmd_line()`
   rewrites `argv[0]` from `claude.cmd` to the real `bin\claude.exe` before
   `Popen`, because routing a `.cmd` through `cmd.exe` mangles quoted args
   (BatBadBut / CVE-2024-24576). That is what once **ate the trailing
   `--resume`**, so every worker silently started with a fresh mind. Check
   `drivers.argv_form_safe()` before putting anything large or quote-heavy on a
   command line - it is why `copilot.build_argv` returns `role_in_turn`.
2. **The preview shows the *exec* form, not just the logical argv**
   (`preview()["exec"]`), precisely because that rewrite is the most consequential
   thing about how the process starts.

### The resolved env

`drivers._card_env(t)` (`daemon/drivers.py:489`) is the per-card overlay, and it
is short on purpose:

| var | when | why |
|---|---|---|
| `HELMDECK_WORKTREE` | worktree set | `loop_state.card_mode()` derives the card discipline from it |
| `HELMDECK_DEV_PORT` | dev_port set | bind THIS, not the project default, so parallel cards never fight over a port |
| `HELMDECK_BRANCH` | card only | a machine task has no branch |

Deliberately **not** exported: the source checkout path. That is where the
secrets live that the worktree was isolated away from.

`drivers._env(cfg, card)` then layers: `os.environ` → strip
`_CONTROL_ENV_KEYS` (`HELMDECK_TLS_*`, `HELMDECK_CLAUDE`, `BASH_ENV` - supervision
config, plus a file that could rewrite the env behind our back in every shell) →
`BASH_DEFAULT_TIMEOUT_MS` / `BASH_MAX_TIMEOUT_MS` (bound the **tool**, not the
turn) → the card overlay → the driver's declared `env` from `settings.json`, with
`PATH+` prepending rather than replacing.

---

## 3. Adding a declarative policy knob

Policy knobs live in **one** table: `server._config_schema(s)`, served by
`GET /automation`. The app renders each control generically and writes it back
with `saveSettings(nest(path, value))`, so a new knob is one entry here rather
than hand-wiring in two screens.

One entry:

```python
{"group": "policy",                      # "policy" | "night" - which panel
 "path": "policy.auto_accept_green",     # dotted, two levels
 "control": "toggle",                    # toggle|multi|single|text|number|labels
 "labelKey": "cfg.autoAccept",           # i18n key, never a literal
 "value": bool(pol.get("auto_accept_green")),   # read at request time
 # "options": [...]      for multi / single
 # "keys":    [...]      for labels
 # "placeholder": "..."  for text
}
```

**To add one, edit exactly these:**

1. `daemon/events.py` `DEFAULTS` (the `policy` block) - so `events.settings()`
   always resolves it. The `or`-fallback you write into the schema entry is a
   *display* default and is not the same thing.
2. `server._config_schema()` - one entry.
3. `app/src/i18n/dict/screens.ts` - the `cfg.*` label, **both** languages.
4. The consumer that actually reads it (usually `daemon/processes.py`).
5. *Optional:* if a graph node should link to the knob, add the dotted path to
   that node's `settings: [...]` in `sessions.LANE_FLOW` or
   `loop_state.LOOP_STATES`.

Nothing else. Do **not** add a control to a screen - **unless** you need a
control type that does not exist yet, in which case add the branch to the app's
`Control` component *and* the name to `server.CONTROLS` in the same commit.

The gate holds you to all of it (`tests/test_harness_layer.py`
`test_policy_knob_contract`): every `control` the daemon emits must exist both in
the app's `Ctl` union and as a real branch in `Control`; every `labelKey` must
have a two-language dict entry; every path must be exactly two levels, because
the app's `nest()` splits on one dot. None of those is a type error on either
side - a knob with an unhandled control renders as **nothing**, silently, on an
owner-only screen.

Two things worth knowing before you add one:

- **The schema table itself is not validated anywhere.** Enforcement is on the
  write side: `POST /settings` is owner-only, and the chat path
  (`copilot.ALLOWED_CONFIG`) whitelists **top-level keys only** - so any
  `policy.*` sub-key is reachable from chat once `policy` is listed. If your knob
  must not be chat-editable, it does not belong under `policy`.
- **Every policy change checkpoints.** `events.save_settings()` snapshots first
  when the patch touches `SIGNIFICANT_SETTINGS`.

---

## 4. Skills discovery and `skillOverrides`, per surface

**HelmDeck ships no skill-handling code.** There is no `--skill` flag, no
allow/deny list, no filtering anywhere in `daemon/`. Which skills a surface sees
is entirely a consequence of `--setting-sources`, and that is the point: skills
are the CLI's mechanism, and the harness's job is to choose the right layer set,
not to reimplement discovery.

The only functional skill reference in the repo is `tools/loop_state.py`, which
appends a *prompt* nudge to apply `.claude/skills/impeccable` when a change
touches `app/src/**.tsx` - a string, not a flag.

### Why this needed measuring rather than reasoning

`skillOverrides` is a **settings key**. `~/.claude/skills/` is a **directory**.
Those are two different mechanisms, and only the first is obviously governed by
`--setting-sources`. Reasoning from the flag's semantics gives you a plausible
answer; it does not give you the right one.

So it is measured. `python daemon/probe_harness_settings.py --skills` spawns each
shipped surface and reads the `init` event, which carries `skills`, `plugins` and
`memory_paths` *before any model inference* - deterministic, one cheap turn. The
env is scrubbed of `CLAUDE*` first, because the probe is usually launched from
inside a Claude Code session and measuring inherited config while inheriting the
measurer's own config gives you a reading about the probe.

### Measured, CLI 2.1.207, 2026-08-16

| surface | `--setting-sources` | skills | delta |
|---|---|---|---|
| *(no flags - the pre-harness card)* | *inherits everything* | 19 | - |
| card / machine | `project` | **18** | −`generate-image` |
| board copilot | `""` | **16** | −`adversarial-test`, −`impeccable` |

The two deltas are the whole story, and each isolates one layer:

1. **Project-layer skill discovery follows `--setting-sources`.** The copilot
   loses exactly `adversarial-test` and `impeccable` and nothing else - that
   difference *is* `.claude/skills/`.
2. **User-layer skill discovery follows it too.** A card loses exactly
   `generate-image`, which is a *directory* (`~/.claude/skills/generate-image`),
   not a settings key and not a plugin (`enabledPlugins` is empty). So the flag
   governs skill **directories**, not just the `skillOverrides` key - which was
   the open question, and is why this was measured instead of reasoned.

**Do not oversell that second one.** The operator has **149 user skill
directories and 148 `skillOverrides: "off"`** - he had already disabled all but
one himself, so dropping his layer visibly costs a card exactly one skill. The
isolation was never really about skills. What that layer actually carried, and
what a sandboxed worker could neither use nor fix, was a
`model: claude-fable-5[1m]` pin that silently overrode the card's own model and
an `rtk hook claude` PreToolUse hook on every Bash call - 296 observed failures
landing in card transcripts. Those are the reason `--setting-sources` is set;
the skill delta is a side effect worth knowing about, not the motivation.

### The two traps, also measured

`daemon/probe_harness_settings.py` is a permanent regression check, not a
throwaway. **Re-run it after a CLI upgrade** - a silently-changed flag would not
error, it would quietly hand every card back the operator's config.

1. **`--settings` alone excludes nothing.** It is purely additive. Only
   `--setting-sources` drops the user layer. (`CLAUDE_CONFIG_DIR` does redirect
   it, but the credentials live in that directory too, so the run exits 1 - wrong
   lever.) *Corollary: the presence of a `--settings` flag is not evidence of
   isolation. Only `--setting-sources` is.*
2. **A settings file the CLI dislikes is discarded in SILENCE.** From `--help`:
   *"Settings files that fail validation are silently ignored in this mode."* A
   bad key does not raise - it hands the agent an empty layer with nothing in the
   logs. That is why `harness.settings_file()` JSON-validates before returning a
   path, why `write_settings()` schema-checks before writing, and why
   `probe --validate` asserts a hook from each shipped file actually **fires**
   rather than trusting that the file parses.

### Fixed gap: auto-memory is shared, and now read-only

Measured with the env scrubbed: **every surface resolves `memory_paths.auto` to
the operator's personal `~/.claude/projects/<main-repo-slug>/memory/`** - and the
slug is the *main repo's* path, not the worktree's. So every card, every machine
task, the copilot and the owner's own desktop sessions share one directory
outside the worktree, and `--setting-sources` does not move it.

`harness/` had closed the **settings** half of the personal-layer leak. This half
was not noticed at first, because nothing rendered it. When it surfaced, the
first instinct was reasonable and worth checking rather than assuming: *isn't
that directory tracked by git, so what's the issue with a card writing to it?*
It is not. `git -C ~/.claude status` and the same command against the memory
directory both say `not a git repository` - there is no `.git` anywhere under
`~/.claude`, so a card's write there had no revert path. Measured against the
real spawn (`drivers.build_argv` + the shipped `card.json`, a stream-json turn on
stdin exactly like `_ClaudeSession.run_turn` sends): the Write tool created a
file in that directory with no permission prompt, under `--permission-mode
acceptEdits`.

**Fixed** by denying the write, not by relocating the directory:
`harness/settings/card.json` and `copilot.json` now carry
`Write(~/.claude/projects/**)` and `Edit(~/.claude/projects/**)` in
`permissions.deny` - the identical Read/Write/Edit tool-pattern mechanism that
already protects `daemon/settings.json` two lines above it. `Read` stays open, so
a card still benefits from accumulated notes; only the write is closed. Measured
both ways before shipping: the real spawn wrote the file with the deny absent,
and got a permission error with it present, for both the Write tool (new file)
and the Edit tool (existing one - Edit is a distinct tool and needed its own
line).

`harness.preview()` now reports this per surface (`out["memory"]`), read out of
the **real settings file at preview time** rather than asserted - so an edit that
removes the deny line shows up in `/harness` the same way a disappearing hook
does. Deliberately *not* shown: the literal value of `memory_paths.auto`. The CLI
derives that slug from a project identity that measurably is not just "this
cwd" - every card worktree probed resolved to the *same* directory despite
different cwds - and reconstructing that derivation here to render it live would
be exactly the guess `CLAUDE.md`'s NO MONKEY PATCHES rule forbids. What the
provenance view states is only what is honestly derivable from the file: does
this surface's actual deny list cover it, right now.

Debt entry `card-shares-the-operators-auto-memory` in `daemon/debt.py`: **paid**.

**The other half is versioning, not blocking.** The deny stops a card's write
from being adopted as context before anyone notices; it gives no recoverability,
and never covered the operator's own interactive sessions - now the only writers.
That half is a `Stop` hook that keeps every project's memory directory in local
git: see §6.

---

## 5. The fixed / policy boundary

### The two sides

**Fixed - the harness.** Code, unreachable from chat or config
(`ARCHITECTURE.md` "Fixed vs. flexible", `CLAUDE.md` "Laws"):

| law | enforced in |
|---|---|
| auth, users, roles, sessions, device tokens | `daemon/auth.py`; the `H.OPEN` public-path list and the role gates in `daemon/server.py` |
| append-only audit / events | `events.emit()` - append + write-through, no delete path |
| gate-before-review | `sessions.move_lane()` → `sessions._gate()`; red keeps the card on Review |
| measured economics | `daemon/usage.py` - *display* is configurable, *measurement* is not |
| worktree isolation | `git worktree add` in `daemon/sessions.py`; the agent's cwd is that worktree |
| chain ordering (step N+1 only after N) | `processes.sync()` |
| driver commands | `drivers.build_argv` / `copilot.build_argv`; `drivers` is not in `copilot.ALLOWED_CONFIG`, so chat can never reach it |
| the charter core | `daemon/charter.py` - `CHARTER` + the `FORBIDDEN` list + `screen_source()` |

**Policy - data** in `settings.json`, editable in Settings or via the copilot per
`policy.chat_configure_roles` (`ARCHITECTURE.md` "Flexible - policy"): lane labels; automation;
capacity, tariffs, value, prices, currency; dashboard composition; appearance;
registration; Jira; connector schedules; additive `house_rules`.

The gate is **run by the daemon, not by the card's agent** - that is what makes
it a law rather than a convention. The harness has full command access, so tests
run even when the agent's permission mode gates commands.

### The boundary is exported, not described

`sessions.flow()` and `loop_state.machine()` tag **every** node `kind: "fixed" |
"policy"`, and every policy node names the `settings` key that governs it, so the
UI can link a node straight to its knob. Fixed nodes additionally carry a
`source` of the form `"tools/loop_state.py:<line>"`, **read out of the source
file at call time** by `_decl_lines()` - never written down, because a
hand-maintained line number is wrong the first time anyone inserts a line above
it, and a citation that rots is worse than none: it sends the reader to the wrong
place with confidence.

That is the difference between claiming "structure is code" and showing it.

(This document is not exempt. The `EXECUTE` state moved from line 472 to 487
while this file was being written, because a fix three sections down inserted a
function above it - so the *illustrative* citation above deliberately carries no
number. Where a line is quoted below, it points at a declaration stable enough to
be worth the risk; `grep` for the symbol if it has moved.)

### Where the copies are, and what holds them together

The machine had already drifted once. `/loop/map` and `/automation` each carried
a hand-typed copy of the build loop; `/loop/map` had silently lost `BUILD`
entirely, and `/automation` still described `BUILD` as rebuilding
"Installer / APK / glasses" long after `ARTIFACT_SRC` was cut to the signed APK
alone. Both now render `loop_state.machine()` and `sessions.flow()`.

There is one more copy, and it is not in Python: **`app/src/data/client.ts`
declares the wire shape the UI reads.** `tsc` never sees the daemon and the gate
never saw the TypeScript, so a renamed field left both sides self-consistent and
the UI rendering `undefined`. `tests/test_harness_layer.py` now parses those
interfaces and diffs them against real exported objects in **both** directions:

- a required TS field missing from the export → the UI silently renders nothing;
- an exported field the TS does not declare → the machine grew and the view was
  not told.

Undeclared exports need an entry in `DELIBERATE_EXTRAS` **with a reason**, so
adding a field forces a conscious choice rather than a silent one.

### If you touch any of this

- **Never weaken a fixed law.** They are listed in `CLAUDE.md`; the daemon serves
  its own citation table at `GET /loop/map` under `laws`, each with the module
  that enforces it.
- **A new load-bearing shortcut goes in `daemon/debt.py` in the same commit.**
  Paying it: file the fix card, flip `status` to `paid`, keep it listed.
- **NO MONKEY PATCHES** (`CLAUDE.md`, "NO MONKEY PATCHES"). Load-bearing state is *derived* and
  *verified* from the runtime's own signals, folded in at event time, mutated at
  exactly one owner. A heuristic reconstruction that ships anyway is a shortcut →
  register it.

  The most recent worked example lives in `loop_state.build_stale()`: it had two
  signals for "is the APK stale" - a fingerprint derived from the real native
  inputs, and a `git status`-derived guess about which files changed. Ordering
  the *guess* first let its blind spot (all of `app/android/` is git-ignored)
  veto the authoritative answer. The fix was not a wider heuristic; it was
  asking the derived signal first and letting the guess gate only the branches
  where no derived answer exists.

---

## 6. Memory is versioned by a Stop hook

The permission deny above stops a *card* writing to the shared memory directory.
It does nothing for the operator's own interactive sessions, which write there
constantly and are the only writers left - and the directory still had no
history of its own. `tools/memory_autocommit.py` closes that:

| | |
|---|---|
| canonical | `tools/memory_autocommit.py` (versioned, gated by `tests/test_memory_autocommit.py`) |
| deployed | `~/.claude/hooks/memory_autocommit.py` |
| wired as | a **`Stop`** hook in `~/.claude/settings.json` |
| installer | `py -3.12 tools/install_memory_hook.py` (`--check` for drift, `--uninstall`) |

It sweeps **every** `~/.claude/projects/*/memory/`, `git init`s any that holds
notes but has no repo, and commits whatever changed - so a project created next
month is covered with no action taken. Commits record the `session_id` from the
hook's stdin payload, which is what makes a later revert decidable ("was this me,
or a turn I never read?").

Two files because a script living only in `~/.claude/hooks/` would itself be
untracked and unreviewable - fixing untracked state with an untracked script.
`--check` keeps the two byte-identical.

**Its one law is `daemon/harness.py`'s law:** it can never break a turn. A `Stop`
hook that exits 2 **blocks** the turn, so that exit code is unreachable from
`main()` - every git call is timeout-bounded, every failure becomes a log line,
and the worst outcome is "this turn was not snapshotted", which the next turn
fixes. It never configures a remote and never pushes; these are private notes.
It also leaves alone any memory directory that is already inside somebody else's
repo, rather than nesting a second one inside it.

`Stop` rather than `SessionEnd` because `SessionEnd` is missed exactly when it
matters most - a crashed process. The cost is that it runs constantly, so the
no-op path is one `git status --porcelain` per directory.

This hook lives in the **personal** layer, so cards and the copilot never load
it (§4). That is correct: they cannot write memory at all, so they have nothing
to commit.

### The trap: settings apply at SESSION START

Measured the hard way while verifying the deny. A running session holds the
settings file contents it was spawned with - editing
`harness/settings/card.json` does **not** change the permissions of a card
that is already mid-flight, only of the next spawn. Symptom: a Bash write that
*should* be denied succeeds, and you conclude the deny is broken when it is
merely younger than the process. Confirmed against a fresh spawn across five
write vectors (`Write`, `Edit`, `>`, `>>`, `tee`, `python -c`) - all blocked;
the same commands from the older session went through. The `install_memory_hook`
output says "Active from the NEXT session" for the same reason.

---

## 7. Run / verify

```bash
python daemon/harness.py                        # what each surface resolved to
python daemon/harness.py --preview              # full argv + provenance, as JSON
python daemon/probe_harness_settings.py         # full sweep vs the real CLI (~20s)
python daemon/probe_harness_settings.py --validate   # are the SHIPPED files accepted?
python daemon/probe_harness_settings.py --skills     # per-surface skills + memory paths

py -3.12 daemon/test_harness.py                 # loader, write path, isolation
py -3.12 tests/test_harness_layer.py            # no-drift, the loop, the app contract
py -3.12 tests/test_memory_autocommit.py        # the Stop hook, incl. its never-wedge law
py -3.12 tools/run_gate.py                      # everything the gate runs

py -3.12 tools/install_memory_hook.py --check   # is the deployed hook current?
py -3.12 tools/memory_autocommit.py --dry-run -v  # what would it commit right now?
```

The `test_*` files are unit tests and never spawn an agent - the settings layer is
checked **as argv and env**, because whether the CLI *honours* those flags is a
question for the probe, which measures it against the real binary. Asserting flag
semantics in a unit test would be pretending, and this is the one layer that
cannot afford to be confidently wrong about the thing it exists to guarantee.
