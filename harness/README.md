# `harness/` - what the agents are told, as data

> This is the operator's tour of the directory. The developer's map - how a
> spawn resolves, the resolved argv and env, adding a policy knob, the measured
> per-surface skill sets, and the fixed/policy boundary - is [`HARNESS.md`](../HARNESS.md).

`ARCHITECTURE.md` says **the harness is code, policy is data**. The agent briefs
were the exception: what a card worker is told about itself lived as a 900-character
string constant in `daemon/drivers.py`, and the board copilot's 10 KB system prompt
lived in `daemon/copilot.py`. Both are policy. They are here now.

```
harness/
  agents/     one .md per surface - YAML frontmatter + the prompt as the body
  settings/   one .json per surface - a standard Claude Code settings file
  schema/     JSON Schemas for both, referenced by $schema in each file
```

Loaded by `daemon/harness.py`, which re-reads on mtime and **falls back to the
built-in default on any error**. Editing a file here can change what an agent is
told; it can never stop a card from spawning.

## What is data here, and what deliberately is not

| | where | why |
|---|---|---|
| the role brief (what a worker can/cannot do, how to hand off) | **data**, `agents/*.md` | policy - the owner may reword it |
| the `<helmdeck-ask>` wire protocol | **code**, `daemon/ask.py` | it is parsed by `ask.parse()`'s regex. Prompt and parser must ship together, or an innocent reword silently breaks every question button. `harness.py` splices it in at `{{ask_protocol}}` |
| the driver argv, auth, audit, gate, worktree isolation | **code** | fixed harness law (`CLAUDE.md`) |

## The settings layer

A card worker is `claude` running with the card's worktree as cwd, so until this
existed it silently loaded **the operator's personal `~/.claude/settings.json`** -
an `rtk hook claude` PreToolUse hook on every Bash call (296 observed failures
landing in card transcripts), a pinned `model: claude-fable-5[1m]` that overrode the
card's own model, ~150 `skillOverrides`, and personal plugins. A sandboxed worker
could neither use nor fix any of it.

Each agent file names its layer:

```yaml
settings: card          # -> harness/settings/card.json, passed as --settings
setting_sources: project # -> --setting-sources project
```

| surface | sources | effect |
|---|---|---|
| card / machine worker | `project` | operator's `~/.claude` **excluded**; the repo's own `.claude/settings.json` build-loop hooks (Stop / SessionStart / design PostToolUse) **kept**; `settings/card.json` added |
| board copilot | `""` | nothing ambient at all. Not even the project layer - the repo's Stop hook runs `loop_state --stop-hook`, which would block the copilot for a build-loop state it can neither cause nor fix |

## Two traps, both measured not assumed

`daemon/probe_harness_settings.py` is the throwaway that established all of this
against the real CLI (2.1.207). Re-run it after a CLI upgrade:

```
python daemon/probe_harness_settings.py            # full sweep
python daemon/probe_harness_settings.py --validate # just: are the shipped files accepted?
```

1. **`--settings` alone does not exclude anything.** It is purely additive. Only
   `--setting-sources` drops the user layer. (`CLAUDE_CONFIG_DIR` does redirect it,
   but the credentials live in that directory too, so the run exits 1 - wrong lever.)

2. **A settings file the CLI dislikes is discarded in SILENCE.** From `--help`:
   *"Settings files that fail validation are silently ignored in this mode."* So a
   bad key here does not raise - it just hands the agent an empty layer and nothing
   in the logs says so. That is why `--validate` exists and why it asserts a hook
   from the shipped file actually *fires*, rather than trusting the file parses.
