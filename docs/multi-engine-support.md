# Multi-engine support — analysis + integration plan

How a SECOND agent runtime (OpenCode, Codex, Gemini CLI, …) docks as a card
driver next to `claude`. Analysis only — **no production code was written for
this document.** Effort estimates per building block are at the end.

This is the deferred **Phase 5** of `docs/paseo-adoption-plan.md`
("provider seam / capability flags, opaque IDs, forge registry — not scoped").
Phases 1–4 shipped; this is the piece that was left.

## Reference — MANDATORY

Every card derived from this plan MUST read the ACTUAL Paseo source, not this
summary: `C:\Users\Tien Duy Vo\Downloads\_paseo_src` (TypeScript monorepo,
`08c522c98`, paseo 0.2.0-beta.4). The same rule as the adoption plan — the
summary drifts, the source does not.

| What | Path (under `_paseo_src`) |
|---|---|
| **THE interface** (740 lines, the contract) | `packages/server/src/server/agent/agent-sdk-types.ts` |
| Registry, factories, derivation, wrappers | `packages/server/src/server/agent/provider-registry.ts` |
| Manifest (ids, labels, modes) | `packages/protocol/src/provider-manifest.ts` |
| Config schema (`agents.providers`) | `packages/protocol/src/provider-config.ts` |
| Binary + env resolution | `packages/server/src/server/agent/provider-launch-config.ts` |
| Shared turn runner | `packages/server/src/server/agent/providers/provider-runner.ts` |
| ACP base class (3486 lines) | `packages/server/src/server/agent/providers/acp-agent.ts` |
| Generic ACP adapter (237 lines) | `packages/server/src/server/agent/providers/generic-acp-agent.ts` |
| OpenCode adapter + helper server | `providers/opencode-agent.ts`, `providers/opencode/server-manager.ts` |
| Codex adapter | `providers/codex-app-server-agent.ts` |
| Docs | `docs/providers.md`, `docs/custom-providers.md`, `docs/agent-lifecycle.md`, `docs/opencode-global-event-baseline.md` |

External protocol reference: <https://agentclientprotocol.com/protocol/overview>.

---

## 1. Executive summary

**HelmDeck already has a driver abstraction. It is not the problem.**
`drivers.run(cfg, t, prompt) -> (session_id, reply, meta)` with
`cfg["type"] in {claude, http, cmd}` (`daemon/spine/agent/drivers.py:277-285`)
is a genuine seam, and `turnrunner._turn` (`daemon/cells/engineer/turnrunner.py:141`)
is its single call site for card and machine turns.

The problem is that **everything valuable lives on the claude side of the seam**,
and one whole subsystem bypasses the seam entirely:

1. The chat/transcript the owner reads is not produced by the driver. It is
   re-parsed off Claude Code's private `~/.claude/projects/<cwd>/<uuid>.jsonl`
   (`daemon/spine/agent/claude_sessions.py:11,139-143`). A second engine has no
   such file, so a second engine has **no card feed at all**.
2. `meta` is Claude's `result` event verbatim — `total_cost_usd`, `modelUsage`,
   `input_tokens`/`cache_creation_input_tokens`/… — and `econ.py` reads those
   key names directly (`daemon/spine/turn/econ.py:26-28,38-39`).
3. Seven further spawn sites (copilot ×3, PM, Henry broker, process designer,
   distiller) hand-roll a `claude` argv and never touch `drivers.run` at all.

**Good news, measured:** the gate is engine-neutral (git + shell only), the
`<helmdeck-ask>` question channel is engine-neutral (prose-taught, regex-parsed),
the background-task registry is engine-neutral at event time, and the app's
`TStep` transcript contract (`app/src/ui/card_transcript.tsx:24-42`) is already
provider-agnostic. There is even an unused client-side `Engine` plugin interface
waiting for a daemon counterpart (`app/src/kernel/keys.ts:17-25`).

**Recommendation:** add a generic **ACP** (Agent Client Protocol) driver, not an
OpenCode-specific one. See §6 — it is one adapter for ~30 engines, its process
model matches HelmDeck's per-card tree-kill isolation exactly, and its wire shape
is nearly isomorphic to the `claude --input-format stream-json` machinery
HelmDeck already runs. But it has one hard blocker (§6.3: ACP carries no system
prompt) and one hard prerequisite (§5, E3: an event-time timeline store).

---

## 2. What Paseo actually built

### 2.1 The interface

Two plain TypeScript interfaces in `agent-sdk-types.ts` — no Zod, no abstract
base, **no runtime conformance check**.

`AgentClient` (`agent-sdk-types.ts:685-740`) — the per-backend singleton.
**Required (6):** `provider`, `capabilities`, `createSession`, `resumeSession`,
`fetchCatalog`, `isAvailable`.
**Optional (11):** `resolveDefaultModeId`, `resolveCreateConfig`,
`isCreateConfigUnattended`, `listCommands`, `listFeatures`,
`listImportableSessions`, `importSession`, `getDiagnostic`,
`archiveNativeSession`, `unarchiveNativeSession`, `shutdown`.

`AgentSession` (`agent-sdk-types.ts:619-659`) — one live conversation.
**Required (17):** `provider`, `id`, `capabilities`, `run`, `startTurn`,
`subscribe`, `streamHistory`, `getRuntimeInfo`, `getAvailableModes`,
`getCurrentMode`, `setMode`, `getPendingPermissions`, `respondToPermission`,
`describePersistence`, `interrupt`, `close`.
**Optional (8):** `listCommands`, `setModel`, `setThinkingOption`, `setFeature`,
`revertConversation`, `revertFiles`, `revertBoth`, `tryHandleOutOfBand`.

`run()` is derivable from `startTurn` + `subscribe`; the shared helper
`runProviderTurn()` (`providers/provider-runner.ts:27-103`) does exactly that, so
adapters implement `run` as a one-line delegation. **HelmDeck's `run(cfg,t,prompt)`
is Paseo's `run()` — the same synchronous "give me the whole turn" shape.**

### 2.2 The real interop surface is the event union

Everything an adapter produces flows through a 14-arm discriminated union
(`agent-sdk-types.ts:379-435`), verbatim:

```ts
export type AgentStreamEvent =
  | { type: "thread_started"; sessionId: string; provider: AgentProvider }
  | { type: "turn_started"; provider: AgentProvider; turnId?: string }
  | { type: "turn_completed"; provider: AgentProvider; usage?: AgentUsage; turnId?: string }
  | { type: "usage_updated"; provider: AgentProvider; usage: AgentUsage; turnId?: string }
  | { type: "mode_changed"; ... }
  | { type: "model_changed"; ... }
  | { type: "thinking_option_changed"; ... }
  | { type: "turn_failed"; provider; error: string; code?; diagnostic?; turnId? }
  | { type: "turn_canceled"; provider; reason: string; turnId? }
  | { type: "timeline"; item: AgentTimelineItem; provider; turnId?; timestamp? }
  | { type: "permission_requested"; provider; request: AgentPermissionRequest; turnId? }
  | { type: "permission_resolved"; provider; requestId; resolution; turnId? }
  | { type: "attention_required"; provider; reason: "finished"|"error"|"permission"; timestamp }
  | { type: "provider_subagent"; provider; event: ProviderSubagentInputEvent };
```

`AgentTimelineItem` (`:370-377`) is `user_message | assistant_message | reasoning
| tool_call | todo | error | compaction`. Tool calls carry a 12-arm
`ToolCallDetail` union (`:228-325`: `shell`, `read`, `edit`, `write`, `search`,
`fetch`, `worktree_setup`, `sub_agent`, `plain_text`, `plan`, `unknown`) with an
explicit `unknown` fallback, and a 4-state status
`running | completed | failed | canceled`.

**HelmDeck's `TStep` (`app/src/ui/card_transcript.tsx:24-42`) is already a near-
subset of this**: kinds `text|thinking|tool|result|todos|plan|compaction|system|
note|turn|error`, statuses `running|completed|failed|canceled`. That was Phase 3
of the adoption plan — it landed, and it landed engine-neutral. The union above
is the shape a HelmDeck driver should emit.

### 2.3 Capability flags

```ts
export interface AgentCapabilityFlags {          // agent-sdk-types.ts:168-181
  [capability: string]: boolean | undefined;
  supportsStreaming: boolean;
  supportsSessionPersistence: boolean;
  supportsSessionListing?: boolean;
  supportsDynamicModes: boolean;
  supportsMcpServers: boolean;
  supportsNativePaseoTools?: boolean;
  supportsReasoningStream: boolean;
  supportsToolInvocations: boolean;
  supportsRewindConversation?: boolean;
  supportsRewindFiles?: boolean;
  supportsRewindBoth?: boolean;
}
```

Measured values per backend (`claude/agent.ts:274`, `codex-app-server-agent.ts:201`,
`opencode-agent.ts:88`, `acp-agent.ts:216`, `omp/agent.ts:119`, `pi/agent.ts:153`):

| flag | claude | codex | opencode | ACP dflt | omp | pi |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| supportsStreaming | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| supportsSessionPersistence | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| supportsDynamicModes | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| supportsMcpServers | ✅ | ✅ | ✅ | ✅* | ❌ | dynamic |
| supportsRewindConversation | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| supportsRewindFiles | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| supportsRewindBoth | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |

`supportsRewindFiles` is true for **claude only** (`claude/agent.ts:283`).
HelmDeck's rewind is git checkpoints (`turnrunner._turn_checkpoint:289-298`), so
HelmDeck is *better off here than Paseo* — its rewind is engine-independent by
construction.

Notably **only six non-test sites in the whole Paseo repo query a capability
flag** (`agent-manager.ts:819,4234`; `rewind/rewind.ts:18,24,30`;
`app/.../use-rewind-capabilities.ts`; `cli/.../inspect.ts:121`). The flags are
cheap to add and rarely branched on — a good sign for HelmDeck's own port.

### 2.4 Registration is a three-part split

1. **Manifest** (`protocol/provider-manifest.ts:190-251`) — six built-ins:
   `claude`, `codex`, `copilot`, `opencode`, `pi`, `omp`. Ids, labels, modes,
   UI metadata (`icon`, `colorTier`), one semantic bit `isUnattended`.
2. **Server factory table** (`provider-registry.ts:118-159`) — a flat
   `Record<string, (logger, runtimeSettings, options) => AgentClient>`.
3. **User config** (`$PASEO_HOME/config.json` → `agents.providers`,
   schema `protocol/provider-config.ts:46-111`) — `extends`, `label`, `command:
   string[]`, `env`, `params`, `models`, `additionalModels`, `disallowedTools`,
   `enabled`, `order`. Any key not in `BUILTIN_PROVIDER_IDS` must declare
   `extends`; `extends: "acp"` + a `command` yields a `GenericACPAgentClient`.

Selection at runtime is a plain map lookup plus an availability gate
(`agent-manager.ts:4250-4270`). There is no provider enum —
`AgentProviderSchema = z.string()` (`provider-manifest.ts:288`).

**HelmDeck's equivalent already exists and is simpler**: `settings.json`
→ `drivers.{name}.{type,...}` (`daemon/spine/storage/events.py:75-76`), with the
card's `driver` field naming one. HelmDeck needs (2) — a type→implementation
table richer than today's three-branch `if` — and capability flags. It does not
need Paseo's three-way split.

### 2.5 Four transport patterns, none one-shot

| Backend | Transport | Process model |
|---|---|---|
| opencode | HTTP + SSE against `opencode serve --port <ephemeral>` | **shared** ref-counted helper server, many sessions/process |
| codex | JSON-RPC over stdio (`codex app-server`) | one child per session |
| copilot / cursor / kiro / trae / gemini / custom | **ACP**: JSON-RPC over NDJSON stdio | one child per session |
| pi / omp | custom JSONL-RPC stdio (`pi --mode rpc`) | one child per session |

Every backend keeps a **live process across turns** — exactly HelmDeck's
`_ClaudeSession` model (`drivers.py:377-382`). Nobody re-spawns per turn.

---

## 3. Where HelmDeck actually breaks — the change surface

Swept across `daemon/`, `harness/`, `app/`, `tools/`.

### Tier 1 — blocking, must be abstracted

**(1) The transcript reader — the single biggest item.**
`claude_sessions.py` (~660 lines) + `claude_transcript_fmt.py` (190 lines) parse
Claude Code's private on-disk `.jsonl` at a hardcoded path:

- `claude_sessions.py:11` — `PROJECTS = os.path.join(HOME, ".claude", "projects")`
- `:139-143` — session-id → file via glob
- `:229` — the long-poll change token is *bytes of that file* + `live_partial.txt`
  + `actions.jsonl`
- `:479-656` — record schema: `isMeta`, `isSidechain`, `isCompactSummary`,
  `message.content[]` part types, plus envelope string-sniffing for
  `<task-notification>`, `<system-reminder>`, `<local-command…>`,
  `"[Request interrupted by user"` (`:585`), `"This session is being continued…"` (`:576`)
- `claude_transcript_fmt.py:47-93` — a Claude tool-name whitelist
  (`Read|NotebookRead`, `Edit|MultiEdit`, `Bash|PowerShell`, `Task|Agent`, …)

A second engine produces none of this. **Note this is also a standing violation of
this repo's own law** (`CLAUDE.md`, NO MONKEY PATCHES: "never reconstructed by
re-scanning artifacts"): the card feed is a heuristic reconstruction from another
program's private files. Multi-engine support and paying that debt are the same
piece of work.

**(2) Binary resolution — the same 5-line block copy-pasted six times.**
`drivers.py:54`, `copilot.py:14`, `sessions.py:17`, `processes.py:22`,
`probe_harness_settings.py:48`, `tests/probe_cli_askuser.py:25` — all
`CLAUDE = os.environ.get("HELMDECK_CLAUDE") or shutil.which("claude") or …`.
Plus an independent JavaScript reimplementation in `desktop/setup.js:110-167`
(`findClaude`/`realClaudeExe`/`resolveClaudeSpawn`), and a bare literal
`["claude", "-p", …]` in `daemon/spine/ops/distill.py:44`.

**(3) The argv vocabulary.** `drivers.build_argv` (`drivers.py:329-374`) and
`harness.cli_args` (`daemon/spine/registry/harness.py:286-300`) speak Claude CLI
flags: `--output-format stream-json`, `--input-format stream-json`,
`--include-partial-messages`, `--permission-mode`, `--append-system-prompt`,
`--allowedTools`, `--mcp-config`, `--setting-sources`, `--settings`, `--resume`,
`--fork-session`.

**(4) The `meta` contract.** `drivers.py:903-911` builds `meta` straight off the
`result` event; `econ.py:26-28,38-39` reads `input_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`;
`econ.py:52` sniffs `"[1m]"` in a `modelUsage` key to infer the context window;
`events.price_turn` substring-matches `claude-opus`/`claude-sonnet`/`claude-haiku`
against a price table (`events.py:24-26`). `turnrunner.resume_detached:302-319`
reads `meta["resume_echo"]`/`ctx_first`.

**(5) The interrupt control plane.** `drivers.cancel` (`drivers.py:72-82,495-542`)
speaks Claude's stream-json `control_request`/`control_response`. It has 12+
consumers through `turn_active`/`has_session`/`drop_session`
(`lifecycle.py`, `cardadmin.py`, `sessions.py`, `sessions_bg.py`, `henry_broker.py`).

### Tier 2 — needs a per-engine branch

6. The **seven non-driver spawn sites**: `copilot.py:152` (persistent),
   `copilot.py:850` (chat turn), `copilot.py:517` (compact/voice), `pm.py:222`,
   `henry_broker.py:78`, `processes.py:67`, `distill.py:44`. Only
   `drivers.py:473` is behind the seam.
7. `proctable._is_agent_pid` (`daemon/spine/agent/proctable.py:216`) —
   `any(n in img for n in ("claude","node","cmd"))`. A second engine's process
   image does not match ⇒ tree-kill and `reap_orphans` silently degrade and
   orphan trees leak.
8. Model manifest (`turnopts.CLAUDE_MODELS:22-33`), live discovery against
   `api.anthropic.com/v1/models` (`turnopts.py:93-110`), price table, `[1m]` sniff.
9. `daemon/spine/ops/usage.py` — entirely Anthropic OAuth
   (`api.anthropic.com/api/oauth/usage`, `~/.claude/.credentials.json`,
   windows `five_hour`/`seven_day`/`seven_day_opus`). This feeds the owner's
   plan-share economics (`events.plan_effective`, `pm_budget.py:193`,
   `pm.py:736`). See §7 — this is an owner decision, not a coding task.
10. `harness._claude_layers` (`harness.py:685-694`) and `_memory_isolation`
    (`:777-784`) — the spawn-preview provenance page.

### Tier 3 — cosmetic

11. Routes `/sessions/claude`, `/sessions/claude/adopt`
    (`routes_system.py:23-27`, `server.py:373`); client `claudeSessions`/
    `adoptClaude` (`app/src/data/client.ts:540-541`); `setup.claude`/
    `claudeVersion` (`desktop/setup.js:280`, `app/src/ui/onboard.tsx:83`).
12. ~12 daemon + ~6 app sites defaulting to the literal `"claude"` driver name.
13. Five `.replace("claude-", "")` label cleanups in the app.

### Already portable — zero work

- **Gate.** `lanemachine._gate` (`daemon/cells/engineer/lanemachine.py:162-261`)
  requires only: worktree exists, `.git` present, `git status --porcelain` clean,
  and `helmdeck.gate` exits 0. `tools/run_gate.py` is `py_compile` + an import
  check. **No engine coupling whatsoever.** A gate failure re-enters the turn
  loop as prompt text via `_pending_context` — also engine-neutral.
- **Ask protocol.** `daemon/spine/ops/ask.py` is prose-taught
  (`ask.BRIEF:62-82`) and regex-parsed
  (`_BLOCK = re.compile(r"<helmdeck-ask>\s*(.*?)\s*</helmdeck-ask>", re.S|re.I)`,
  `:58`). It never depended on `AskUserQuestion` interception — the file's own
  header records that this was measured to be unreachable on headless `claude -p`.
  Portable **provided the engine can receive a system prompt** — see §6.3.
- **Background-task registry.** `sessions.bg_upsert`/`reconcile_bg` are
  event-time and engine-neutral; only the fallback forensics path
  (`claude_sessions.background_state:341-457`) sniffs Claude tool names.
- **`TStep` UI contract** and the client-side `Engine` plugin interface
  (`app/src/kernel/keys.ts:17-25`, `app/src/plugins/engines/claude.ts`).
- **Rewind** — git checkpoints, not a provider capability.

---

## 4. The mechanics a second engine needs (from Paseo's measured behaviour)

### 4.1 Spawn

Paseo's single spawn primitive is `packages/server/src/utils/spawn.ts:54-82`.
Two things HelmDeck must copy:

**Parent-session env scrub** (`provider-launch-config.ts:203-211`):
```ts
// Env vars that indicate a running Claude Code session. If the daemon itself is
// launched from inside Claude Code (e.g. by a Paseo agent), these leak into
// child processes and cause "cannot be launched inside another session" errors.
const PARENT_SESSION_ENV_VARS = [
  "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "CLAUDE_AGENT_SDK_VERSION",
];
```
HelmDeck's `_CONTROL_ENV_KEYS` (`spawnenv.py:16-17`) strips
`HELMDECK_TLS_*`/`HELMDECK_CLAUDE`/`BASH_ENV` but **not** these. HelmDeck cards
are routinely spawned from inside a Claude Code session (direct/machine cards on
the live tree), so this is a live hazard the moment a second engine appears.

**Windows shim resolution.** Paseo hits HelmDeck's exact BatBadBut lesson from
the other side: `opencode/server-manager.ts:532-569` maps `opencode.cmd` →
`node_modules/opencode-ai/bin/opencode.exe` *specifically so tree-kill works*.
HelmDeck's `agentcli._real_claude_exe` already encodes this trap for claude
(`agentcli.py:18-45`) — it must become engine-parameterised, not re-derived.

### 4.2 Session resume — four different shapes

| Engine | Session id from | Resume |
|---|---|---|
| claude | `system/init` event | `--resume <uuid>` argv |
| opencode | `session.create` HTTP response | stateless — reattach id + cwd, **no flag** |
| codex | `thread/start` RPC response | `thread/resume` RPC, guarded by `thread/loaded/list` |
| ACP | `session/new` response | `session/load` (replays history), else `unstable_resumeSession`, else **throws** |
| pi/omp | a **file path** | `--session <path>` at spawn |

Paseo captures the handle at **turn finalize**, not at create
(`agent-manager.ts:2110-2117`) — the same discipline as HelmDeck's
`_finish_turn` guarded rotation (`turnrunner.py:348-379`). HelmDeck's
`AgentPersistenceHandle` equivalent is `t["session_id"]` + `t["session_chain"]`;
it needs a `nativeHandle`-shaped escape hatch (Paseo `agent-sdk-types.ts:183-189`)
because pi/omp-style engines key on a path, not a uuid.

A measured ACP trap worth copying verbatim (`acp-agent.ts` resume path):
> Some ACP providers (e.g. Devin CLI) require all three params (sessionId, cwd,
> mcpServers) to be present in `session/load` or `unstable_resumeSession` — even
> when mcpServers is an empty array — and return "Invalid params" if any are
> omitted.

### 4.3 Streaming and turn-end

The interesting difference: **where "the turn is over" comes from.**

- claude — the `result` event on stdout (HelmDeck `drivers.py:754-782`).
- ACP — the **`session/prompt` RPC response**, not a notification
  (`acp-agent.ts:2686-2712`): `stopReason` is `cancelled | end_turn | max_tokens
  | max_turn_requests | refusal`, and `response.usage` rides along. Cleaner than
  claude: no NULL-result guard needed, because the response is correlated to the
  request by JSON-RPC id.
- opencode — neither. `session.promptAsync` is fire-and-forget (the HTTP
  response only reports *dispatch* errors); terminal state arrives on the global
  SSE bus as `session.idle` / `session.error` / `session.status:idle`.
- codex — a `turn/completed` notification with `status: completed|failed|interrupted`.

ACP's `session/update` notification variants map onto HelmDeck's `TStep` kinds
almost 1:1 (`acp-agent.ts:2470-2535`): `agent_message_chunk` → `text`,
`agent_thought_chunk` → `thinking`, `tool_call` / `tool_call_update` → `tool`,
`plan` → `plan`, `current_mode_update` → mode, `available_commands_update` →
commands, `usage_update` → usage.

Two dedup lessons, both measured:
- OpenCode streams `message.part.delta` *and* later re-sends the full
  `message.part.updated`; Paseo registers `text:<partId>`/`reasoning:<partId>`
  keys on the delta and drops the later full part (`opencode-agent.ts:2489-2502`).
  HelmDeck's `_on_event` already does the moral equivalent for claude
  (`drivers.py:783-802`: clear `parts` when the full assistant message lands).
- Tool status vocabularies differ per engine and are normalised through a word
  list (`tool-call-mapper-utils.ts:14-39`): failed⊃`failure|error|errored|rejected|denied`,
  canceled⊃`cancelled|interrupted|aborted`, completed⊃`complete|done|success|succeeded`.

**Copy Paseo's tracing convention.** Every backend logs a
`provider.<name>.raw_event` / `provider.<name>.parsed_event` pair
(`opencode-agent.ts:1736-1751`, `acp-agent.ts:2116-2141`). Normalisation bugs are
otherwise undebuggable.

### 4.4 Cost — most engines do not report money

| Engine | Source | Cost in USD? |
|---|---|---|
| claude | `result.total_cost_usd` | ✅ |
| opencode | `step-finish` parts (`part.cost`) + `session.updated.info.cost` | ✅ |
| pi / omp | `get_session_stats` → `stats.cost` | ✅ |
| **codex** | `thread/tokenUsage/updated` | ❌ tokens only |
| **ACP** | `PromptResponse.usage` | ❌ tokens only |

Paseo's normalised shape (`agent-sdk-types.ts:205-212`) makes every field
optional:
```ts
export interface AgentUsage {
  inputTokens?; cachedInputTokens?; outputTokens?;
  totalCostUsd?; contextWindowMaxTokens?; contextWindowUsedTokens?;
}
```
**When a backend exposes no cost, Paseo omits the field. There is no estimator,
no price table, and no fabricated zero** (`agent-projections.ts:453` copies only
present keys). `contextWindowMaxTokens` for OpenCode comes from the *model
catalog*, not the stream (`opencode-agent.ts:3130-3131`).

HelmDeck cannot simply copy that: `events.price_turn` already falls back to a
price table, and the owner's economics are **plan-share percentages, not €**
(standing decree). See §7.

### 4.5 Interrupt / steer

Paseo's steer is HelmDeck's steer: `replaceAgentRun` = cancel-then-resend
(`agent-manager.ts:2136-2166`), which HelmDeck shipped as interrupt-and-replace.
Two measured refinements HelmDeck's ACP driver will need:

- **Force-synthesize the terminal event.** If the provider *acknowledges* the
  interrupt but the run does not settle within the timeout, Paseo dispatches a
  synthetic `turn_canceled` rather than hanging (`agent-manager.ts:2309-2397`).
  HelmDeck's `cancel()` escort already does the equivalent
  (`drivers.py:517-542`) — the pattern ports directly.
- **Orphaned tool calls must be closed.** On interrupt, synthesize `failed`/
  `canceled` for every still-running tool call
  (`opencode-agent.ts:3756-3782`), else the feed shows spinners forever.
- ACP interrupt (`acp-agent.ts:2021-2034`): resolve all pending permissions as
  `cancelled` **first**, then send `session/cancel`.

### 4.6 Permissions — how a headless engine is driven

HelmDeck runs headless, so every engine's approval prompt must be answered by
the harness, not a human:

- **claude** — `--permission-mode acceptEdits` at spawn (HelmDeck today).
- **codex** — structural: `approvalPolicy` + `sandbox` are passed at
  `thread/start`, so an unattended mode never generates a request at all.
- **opencode** — an `auto_accept` toggle; the adapter replies
  `permission.reply {requestID, directory, reply:"once"}` *before* the request
  is ever surfaced (`opencode-agent.ts:4323-4345`).
- **ACP** — the engine sends a `session/request_permission` **request** and
  blocks; the client picks one of the agent-supplied `options` by id
  (`acp-agent.ts:1980-2003`).

For HelmDeck the ACP shape is the nicest: it maps onto the existing `perm`
driver knob (`acceptEdits` → auto-select the permissive option;
a stricter mode → surface it as a typed `<helmdeck-ask>` question).

---

## 5. Integration plan — building blocks and effort

Effort is **working days for one worker card**, assuming the card reads the
Paseo source first. "Card" sizes: S ≤ 1d, M 1–2d, L 3–5d.

| # | Block | What | Size | Days |
|---|---|---|:--:|:--:|
| **E3** | **Event-time timeline store** | Driver folds normalised events into a persisted per-card timeline; `/transcript` reads THAT, not `~/.claude/**.jsonl`. Dual-write with the existing reader first, compare, then cut over. Pays the NO-MONKEY-PATCHES debt. **Hard prerequisite.** | **L** | **3–5** |
| E1 | Engine registry + capability flags | `drivers.run`'s 3-branch `if` → a type→implementation table; per-engine `capabilities` dict; card `driver` resolves through it. | S | 0.5–1 |
| E2 | Launch config | One `resolve_engine_exe(cfg)`; fold the 6 duplicated `CLAUDE` constants + the `desktop/setup.js` JS twin; parameterise `_real_claude_exe`; add Paseo's `PARENT_SESSION_ENV_VARS` scrub. | M | 1–1.5 |
| E4 | ACP transport | JSON-RPC 2.0 over NDJSON stdio: request/response correlation, notification dispatch, inbound server→client requests. HelmDeck's `_send_control`/`_control` (`drivers.py:549-574`) is 80% of this already. | M | 1.5–2 |
| E5 | ACP session lifecycle | `initialize` handshake, `session/new`, `session/load` + `unstable_resumeSession` fallback, `session/prompt` turn, `stopReason` → `meta`, `session/cancel`. | M | 1.5–2 |
| E6 | `session/update` → TStep mapping | 8 update variants + tool-status vocabulary normalisation + delta/full dedup + raw/parsed tracing. | M | 2 |
| E7 | Permissions | `session/request_permission` → auto-answer from the `perm` knob; strict mode → typed `<helmdeck-ask>`. | S–M | 1 |
| E8 | Econ generalisation | Engine-neutral `meta.usage` keys; `cost_usd` genuinely optional (no fabricated zero); per-engine price table; `usage.py` plan-share degrades to "n/a" without breaking `pm_budget`. | M | 1.5–2 |
| E9 | Brief delivery | Engines with no system-prompt channel (§6.3): prepend the brief on turn 1, re-assert after resume, **probe that it holds**. | S–M | 1 |
| E10 | Cancel / idle / turn_active parity | Per-engine interrupt semantics; stale-result suppression equivalent; keep `turn_active` a derived observation. | S–M | 1 |
| E14 | proctable image whitelist | Engine declares its process image names for `_is_agent_pid` / `reap_orphans`. | S | 0.5 |
| E12 | API + UI surface | `/sessions/claude` → `/sessions/<engine>`; driver picker shows engine + availability + capabilities; label cleanups; per-engine setup probe. | M | 1.5 |
| E11 | The 7 non-driver spawn sites | copilot ×3, PM, Henry, processes, distill. **Deliberately deferred** — keep them claude-only; they are HelmDeck's own governance surfaces, not card work. | M+ | (2+, deferred) |
| E13 | Gate | Verify only — measured engine-neutral. | — | 0 |

**Totals**

| Scope | Blocks | Days |
|---|---|:--:|
| **Stage 0 — spike** (prove one ACP engine answers a card; final reply only, no feed, no cost) | E1, E2, E4, E5(min), E9 | **3–4** |
| **Stage 1 — usable** (real card feed, cancel, permissions) | + E3, E6, E7, E10, E14 | **+8–11** |
| **Stage 2 — honest** (economics, UI, availability) | + E8, E12 | **+3–3.5** |
| **Full** | all but E11 | **~15–19** |

Stage 0 is worth calling out: at that level an ACP driver is **strictly better
than the `cmd` driver that already ships** (`drivers.py:989-996` — stateless, no
usage, no transcript), so it can land behind the existing degradation precedent
without touching E3.

**E3 is the fork in the road.** It is a prerequisite for anything the owner would
actually want to use, it is the largest block, and it is worth doing *even if
multi-engine is dropped*, because it closes a standing violation of this repo's
own NO-MONKEY-PATCHES law. Recommend filing it as its own card either way.

---

## 6. Recommendation: a generic ACP driver

### 6.1 Why ACP rather than an OpenCode-specific driver

The Agent Client Protocol is stdio JSON-RPC 2.0 with `initialize`, `session/new`,
`session/prompt`, `session/load`, `session/cancel`, a `session/update`
notification stream, and a client-side `session/request_permission`
(<https://agentclientprotocol.com/protocol/overview>).

1. **One adapter, ~30 engines.** OpenCode, Gemini CLI, GitHub Copilot CLI,
   Cursor, Goose, Cline, OpenHands, Qwen Code, Kimi CLI, Kiro, Mistral Vibe and
   others speak ACP natively; Codex CLI and Claude Code speak it through Zed's
   adapters (<https://agentclientprotocol.com/overview/agents>). Paseo proves the
   economics: `GenericACPAgentClient` is 237 lines, and the cursor/kiro/trae
   subclasses are ~45 lines each on top of the shared base.
2. **The process model matches HelmDeck exactly.** ACP is one child process per
   session, over pipes — which is what `_ClaudeSession` already is, and what
   HelmDeck's per-card tree-kill, PID table, orphan reaping and
   background-task-as-child-process registry all assume.
   **OpenCode's native transport does not**: it is a *shared, ref-counted*
   `opencode serve` process handling many sessions
   (`opencode/server-manager.ts:285-304`, `:182-213`). Tree-killing a card would
   kill other cards' sessions; `_bg_open` tasks would no longer be children of
   the card's tree; `_running_cards()`'s eviction guard (`drivers.py:141-158`)
   would be meaningless. Adopting OpenCode natively means rebuilding HelmDeck's
   isolation model. Reaching OpenCode *through ACP* avoids all of it.
3. **The wire shape is nearly isomorphic to what HelmDeck already runs.**
   `claude --input-format stream-json` is: persistent process, NDJSON on stdin,
   NDJSON on stdout, request/response correlated by `request_id`, streaming
   deltas, a terminal frame with usage. ACP is the same with a different
   vocabulary. `_send_control`/`_control` (`drivers.py:549-574`) is already a
   JSON-RPC-shaped correlator with an `Event` per request id.
4. **ACP's turn-end is better than claude's.** The terminal result is the
   `session/prompt` *response*, correlated by JSON-RPC id — which structurally
   cannot produce the NULL-result race that `drivers.py:754-771` exists to guard
   against.

### 6.2 What ACP costs you

- **Tokens only, no money** (`mapACPUsage`, `acp-agent.ts:556-566` maps
  `inputTokens`/`outputTokens`/`cachedReadTokens` and nothing else). E8 must
  handle "cost unknown" honestly rather than fabricating a zero.
- **Resume is optional in the protocol.** Paseo throws
  `` `${this.provider} does not support ACP session resume` `` when neither
  `session/load` nor `sessionCapabilities.resume` is advertised. A HelmDeck card
  on such an engine loses context between turns — that must be a capability flag
  surfaced on the card, not a silent degradation.
- **Mode/model switching is optional too** (`acp-agent.ts:1681,2462`), so the
  composer's model picker must be capability-gated.

### 6.3 The blocker: ACP carries no system prompt

**Measured, not assumed:** `grep -n "systemPrompt" acp-agent.ts` returns
**nothing**. `AgentSessionConfig.systemPrompt` exists in Paseo's neutral config
(`agent-sdk-types.ts`), but only two adapters consume it — claude
(`claude/agent.ts:2970,3029`, via the SDK's `systemPrompt` object) and OpenCode
(`opencode-agent.ts:3257-3273`, which passes `system:` on each prompt call).
**For ACP providers Paseo simply drops it.**

This matters more for HelmDeck than it does for Paseo, because HelmDeck's entire
governance layer rides on `--append-system-prompt`: the card/machine brief
(`harness/agents/*.md`), the `<helmdeck-ask>` wire protocol, and the
DELIVERED / "Ready for Review" convention that `outcomes.py` and
`_emit_delivered_parked` key off. An ACP worker that never receives the brief is
an agent HelmDeck cannot govern — it will not ask in protocol form, will not
know it must not merge, and will not signal completion.

**Workaround (E9), in order of preference:**
1. Per-engine config file where one exists (OpenCode `AGENTS.md`/agent config,
   Gemini `GEMINI.md`) — written into the worktree at card creation. Durable
   across turns, costs no tokens per turn, and is the engine's own idiom.
2. Prepend the brief to the **first** prompt of a session, and re-assert a short
   form after every resume/respawn. Costs tokens; reliability must be *measured*
   per engine, not assumed.
3. `AGENTS.md` in the worktree root — a growing cross-engine convention, and this
   repo already ships one.

This must be probed against a real engine before Stage 1 is scoped. It is the
single highest-risk unknown in the plan.

### 6.4 Traps to design around — from Paseo's own bugs

Paseo's provider seam has measured defects worth not reproducing:

- **Don't wrap clients to rewrite their id.** `GenericACPAgentClient` reports
  `provider: "acp"` rather than the user's id (`generic-acp-agent.ts:62-64`), and
  adapters *assert* their own id inbound (`claude/agent.ts:1600-1606`), so the
  registry must forge the id in both directions
  (`provider-registry.ts:255-288,350-384`). That two-way lie is load-bearing —
  and it silently drops four `AgentClient` methods (`listCommands`,
  `archiveNativeSession`, `unarchiveNativeSession`, `shutdown`) and the
  `persistSession` option for every derived provider. Consequence: OpenCode's
  `shutdown()` never runs for a custom profile ⇒ the helper server leaks past
  daemon shutdown. **Make the engine id data passed in, never a constant the
  implementation asserts.**
- **No vendor types in the neutral config.** `agent-sdk-types.ts:1` imports
  `Options` from `@anthropic-ai/claude-agent-sdk` into the provider-agnostic
  config, and `extra.claude`/`extra.codex` is a closed two-arm vendor union a
  third adapter cannot extend.
- **No id-sniffing inside the generic path.** `provider-registry.ts:668-687`
  hard-codes `if (providerId === "cursor"|"kiro"|"traecli")` *inside* the
  `extends: "acp"` branch — so naming your custom provider `cursor` silently
  gets you Cursor's transformers.
- **One source of truth for the built-in id list.** Paseo has two
  (`provider-manifest.ts:285` derived, `provider-config.ts:60` a literal) and
  they can diverge. `AgentCapabilityFlags` is likewise copy-pasted between server
  and protocol packages, and the protocol copy has **already** drifted (missing
  `supportsNativePaseoTools`).
- **No engine-string branches in the client.** `app/src/types/stream.ts:757-875`
  branches on `event.provider === "claude"` three times — the exact pattern
  Paseo's own `docs/coding-standards.md:69` forbids. HelmDeck's `TStep` contract
  is currently clean; keep it that way.
- **A typo'd capability is silently `undefined`.** The open index signature
  `[capability: string]: boolean | undefined` means `supportsRewindFile`
  type-checks and reads false. A Python dict has the same hazard — validate the
  key set.
- **Don't declare modes/models statically.** `provider-manifest.ts:21-23` carries
  a standing TODO admitting the static mode list is wrong, and the lists are
  duplicated between manifest and adapter. Also: **mode ids can be URIs** —
  Copilot's are `https://agentclientprotocol.com/protocol/session-modes#agent`.

### 6.5 What NOT to adopt

- **Paseo's three-way registration split.** HelmDeck's `settings.json` →
  `drivers.{name}` is already the right shape; it needs a richer type table and
  capability flags, not a manifest + factory + override-schema triangle.
- **Paseo's shared-helper-server pattern** (OpenCode) — see §6.1.2.
- **`fetchCatalog` / model+mode discovery machinery.** HelmDeck's model picker is
  a server-side whitelist by design (`turnopts.resolve_model:191-203`); a per-
  engine static list plus capability-gating is enough.
- **Rewind capability flags** — HelmDeck's rewind is git checkpoints.

---

## 7. Open decisions for the owner

These are policy, not engineering, and they gate the follow-up cards.

1. **Which path.** (a) Generic ACP driver as recommended; (b) one native engine
   (OpenCode HTTP+SSE — richer, but see §6.1.2); (c) Stage-0 spike only, decide
   later; (d) stay single-engine and take E3 alone as a debt-paying card.
2. **Economics.** HelmDeck's cost model is *plan-share percentage of the
   Anthropic subscription* (standing decree, `events.plan_effective`,
   `pm_budget.py`). Most non-Claude engines report **tokens only, no money**, and
   some run on a separate subscription or on BYOK. Options: (a) per-engine € price
   table (contradicts the plan-share decree); (b) show "cost unknown" and exclude
   those cards from PM budget maths; (c) a second plan-share window per engine.
   Paseo's answer is (b) — omit the field, never estimate.
3. **E3 scoping.** Own card now (recommended — it pays a law violation and
   unblocks everything), or bundled into the first engine card.
4. **Brief delivery (§6.3)** needs a real probe against a real engine before
   Stage 1 can be estimated with confidence. Which engine to probe against
   decides #1.

---

## 8. Verification notes

Claims in this document were read from source, not recalled:

- HelmDeck: `daemon/spine/agent/{drivers,agentcli,spawnenv,turnopts}.py`,
  `daemon/cells/engineer/turnrunner.py`, `daemon/spine/turn/econ.py`,
  `daemon/spine/ops/ask.py`, `daemon/spine/registry/harness.py`,
  `harness/schema/*.json`, `harness/settings/card.json`,
  `app/src/kernel/keys.ts`, `app/src/plugins/engines/claude.ts`.
- Paseo: `agent-sdk-types.ts` (capability flags and the event union were read
  verbatim at `:168-181` and `:379-435`), `provider-launch-config.ts`,
  `generic-acp-agent.ts`, plus targeted reads of `provider-registry.ts`,
  `acp-agent.ts`, `opencode-agent.ts`, `codex-app-server-agent.ts`,
  `opencode/server-manager.ts`.
- The absence of a system-prompt channel in ACP (§6.3) was verified by grep
  against `acp-agent.ts` — zero matches — and contrasted with
  `opencode-agent.ts:3257-3273`, which does pass `system:`.
- ACP method names and the engine support list are from the protocol's own site
  (linked in §6.1), not from memory.

**Not verified — deliberately left as measurement work for the first card:**
whether a given ACP engine honours a brief prepended to the first prompt (§6.3),
and how each engine behaves on Windows shim resolution (§4.1).
