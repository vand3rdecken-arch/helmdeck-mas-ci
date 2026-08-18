# HelmDeck architecture

The organizing idea: **HelmDeck applies its own product philosophy to
itself.** A harness (the seeded, swappable-but-tracked world work executes
in) plus loops (the states work travels through). What makes the system
trustable is no longer "this part is unreachable" - it's that nothing
mutates untracked and every mutation is reversible; how work flows is data.

## The company model

| Company concept | HelmDeck primitive |
|---|---|
| Department / studio | a repo + its harness (rules, tools, gates) |
| Client engagement | a card (branch + worktree + resumable session) |
| The contract | the card's task + value + due |
| Employee / contractor | the driver's agent session |
| QA sign-off | the review gate (bounces with a punch list) |
| Audit file | events + git tree + screen recording |
| Capacity planning | touch units vs. daily budget, WIP limits |
| P&L | value − AI cost per card; margin, yield, automation rate |

Three nested loops:
1. **Lane loop** (ownership): Backlog → Working → Review → Done.
2. **Quality loop** (standards): define → build → **gate** → accept.
3. **Learning loop** (the institution): gate-failure histogram + capacity
   drains tell you which harness fix pays for itself next.

## Seeded vs. swappable (the full-dynamism decree, 2026-08-17)

This section used to read "Fixed - the harness (code, unreachable from chat/
config)". The owner decree superseded that: **nothing is structurally
unreachable.** Everything - engines, surfaces, tools, and governance itself
(auth, gate, audit, economics, worktree isolation) - is a swappable module.
The one invariant that replaced "fixed" is **trackability**: no module/state/
rule change may happen without an append-only, actor-attributed record, and
every swap must be reversible.

- **Seeded** (today's charter, loaded as the day-one default, not deleted):
  auth required; append-only audit; gate-before-review; measured economics;
  worktree isolation; WIP limit; `agentMaySwap=false` (an agent-initiated
  module swap needs a human confirm until this is seeded true).
- **Swappable, tracked** (a change here appends a `TrackEntry {op, pluginId,
  actor, replaced?, note}` to the append-only sink and returns a `rollback()`):
  engines (which agent backend runs a card), surfaces (which UI screens
  exist), the policy set above, and the charter/instruction text itself
  (CLAUDE.md is a seed module, not an out-of-band law - changing it is a
  tracked swap).
- **Human-only regardless of `agentMaySwap`**: the connector CAPABILITY
  SANDBOX (`daemon/charter.py`) - a security boundary that screens user-built
  code, kept deliberately distinct from the agent-instruction charter above.
  This is the one place "everything is swappable" still has a floor: an
  agent may propose, it may never unlock its own sandbox.

Two control planes carry this end to end:
- **App** (`app/src/kernel/`): a Cordis/DeepSeek-style plugin kernel - Kernel
  (service registry + event bus + reversible-effect loader), `Registry<T>`
  for many-contributor services (engines, surfaces), profiles (`store`/
  `owner`/`demo`/`headless-companion`, resolve+extends+patch+dumpConfig).
  `boot/policies.ts` + `boot/charter.ts` seed the defaults; `boot/hydrate.ts`
  swaps them to the daemon's canonical values at boot (a tracked swap, not a
  silent overwrite). The `/modules` surface renders the live journal + lets
  the user toggle policies via a tracked `/policy/swap`.
- **Daemon** (`daemon/policy.py` + `policy_seed.json`): the canonical seed
  both runtimes read. `policy.swap()` is the SOLE mutation path and mirrors
  every change into the append-only `events` sink. `GET /policy` / `POST
  /policy/swap` expose it; `POST /reconfig/track` mirrors app-side swaps into
  the same sink, so the journal spans both runtimes.

Every policy change ALSO creates a **checkpoint** (settings + connectors
snapshot, actor-attributed) with reversible restore - the older, narrower
mechanism the full-dynamism decree's `TrackEntry`/`rollback()` generalizes.
Checkpoints roll back the machine, never history - work data is immutable
record. See `daemon/debt.py` `full-dynamism-decree` for the parts of this
that are seeded-in-code but not yet daemon-enforced (gate/auth/economics
still hard-wire their own checks rather than reading the seeded `PolicySet`).

## The trust pipeline for buildable things

User-built artifacts (connectors today, templates next) never go from chat to
execution directly:

```
chat request ──► copilot checks the CHARTER ──► build card (agent writes code
in an isolated worktree) ──► review gate ──► human accept ──► install-time
static screening (charter.py) ──► versioned install (previous archived)
──► sandboxed runs (separate process, timeout, JSON-only, create-only)
```

Rollback exists at every level: connector versions, checkpoints, archive
instead of delete, and delete that can never touch events/recordings.

Generative UI follows the same split: **agents author data flows, the app
authors pixels.** A built connector auto-appears as a sidebar tab rendered by
a reviewed template; templates form a curated catalog, extended by template
request, never by generated frontend code.

## Runtime topology (today)

The single Expo app (`app/`) is the ONLY frontend - phone, web, and desktop
from one codebase (the old `web/` Next.js app and `apk/` Kotlin client are
archived; debt `expo-cutover-pipeline` is paid). It talks to the daemon
directly (or through the sealed relay when off the LAN):

```
app/ (Expo: phone + web :3300 + desktop) ──HTTP/SSE──► daemon (Python :8140)
```

The daemon is NOT a handful of god-files anymore. Debt `daemon-god-files`
tracks an ongoing strangler-pattern breakup: pure SERVICES were extracted
bottom-up first (so higher-level modules become thin dependents instead of
reaching into a monolith), then the HTTP surface itself was split into a
dispatch table. As of this writing:

```
server.py (H handler, ~478 lines, was 2109)
  do_GET/do_POST check a per-concern ROUTE-DISPATCH TABLE first, then fall
  through to whatever hasn't been converted yet - each conversion is
  behavior-preserving (route body moves verbatim; server.H is never touched
  except to add one dispatch-table line). Path-param routes (e.g.
  /connectors/<name>/rollback) keep their `parts[0]==.../parts[2]==...` guard
  inline in server.py - only the route BODY moved to the module.
  ├─ routes_auth.py        auth/state/setup/register/login/logout
  ├─ routes_policy.py      /policy, /policy/swap, /reconfig/track
  ├─ routes_settings.py    settings, nightshift, usage, automation
  ├─ routes_glance.py      the glasses surface (token-gated, first PREFIX route)
  ├─ routes_info.py        debt/charter/loop-map/models/harness (read-only)
  ├─ routes_pm.py          the proactive daily-loop's API surface
  ├─ routes_misc.py        /processes, /me
  ├─ routes_control.py     /control/state, teach/start, teach/stop, distill, demo
  ├─ routes_relay.py       /relay/pair, /relay/unpair
  ├─ routes_connectors.py  /connectors list, /connectors/<name>/rollback,run
  ├─ routes_checkpoints.py /checkpoints list, /checkpoints/<id>/diff,restore
  ├─ routes_projects.py    /projects CRUD
  ├─ routes_copilot.py     /chat, /chat/cancel, /chat/history, /chat/live
  ├─ routes_tracks.py      track CRUD/reads: /tracks list, new, reorder,
  │                        <id>/archive,fork,fork-chat,delete,update,rewind,
  │                        attach[+/remove],live,turns,history,transcript
  │                        [+/live],checkpoints,attachments,attachment/<name>
  ├─ routes_track_actions.py  the gate/dispatch-critical half of the tracks
  │                        cluster, kept ISOLATED for extra scrutiny (sits
  │                        directly on lanemachine.py's move_lane -> _gate ->
  │                        _merge_to_main, "the crown jewel"): GET /tracks/
  │                        <id>/stream (live transcript SSE), POST /tracks/
  │                        <id>/steer,answer,cancel,lane
  ├─ routes_runs.py        /runs list, /live.jpg, /runs/<id>/timeline,
  │                        playbook,video,videochunk (path-param sub-router,
  │                        guard stays inline in server.py)
  ├─ routes_system.py      /presence, /push/register, /sessions/claude,
  │                        /history, /harness[+/version/<kind>/<name>],
  │                        /debt/<id>/fix, /import/jira,url, /nightshift/plan,
  │                        the /processes/<id>/step path-param sub-router
  └─ glances.py / apimeta.py / startup.py   module-level helpers (pre-dispatch-table)

  The route-dispatch breakup is now essentially COMPLETE: every route group
  identified in the original 2109-line monolith has been extracted; what
  remains inline is only per-request auth/role branching and the handful of
  path-param guards the pattern itself calls for staying inline (see
  daemon/debt.py order 31).

sessions.py (the orchestrator, ~1050 lines, was 3927) sits on top of SERVICES:
  ├─ trackstore.py   the data layer: _load/_save/_mutate (THE one legal write path)
  ├─ locks.py        turn/desktop/direct locks + steer epoch
  ├─ gitutil.py       git/worktree primitives
  ├─ worktrees.py     reclaim + sweep (the isolation law's reclaim half)
  ├─ turnrunner.py + devport.py   turn execution (spawn, settle, finish)
  ├─ lanemachine.py  the lane/gate/merge state machine (move_lane, _gate, _merge_to_main)
  ├─ dispatch.py     new_track / machine-task / direct-task (dispatches through the services above)
  ├─ cardadmin.py    archive/update/fork/history/attachments
  ├─ lifecycle.py    present() (lifecycle is an OBSERVATION, never a stored
  │                  flag) + sweep_zombies + the reconciler
  ├─ econ.py, blockers.py, outcomes.py   turn economics, "what needs the
  │                  owner", outcome extraction
  └─ (steer, the bg-task cluster, and a few notice functions still live here
     - genuinely the orchestrator's own job, not trapped infrastructure)

drivers.py (~990 lines, was 1490, NO LONGER a god-file):
  ├─ agentcli.py   argv / MCP-config resolution
  ├─ proctable.py  PID/process table + reap_orphans (monkeypatched by tests -
  │                extracted with ZERO test changes since the patched fns'
  │                real callers stay in drivers.py)
  └─ spawnenv.py   the external env a spawned agent inherits

copilot.py (~1010 lines, was 1136): copilot_stats.py (PM-session economics),
  copilot_actions.py (reply/action parsing)
pm.py (~1940 lines, was 2192): pm_budget.py (budget/quota math + text),
  pm_state.py (presence + daily-loop-gate: touch()/loopstate/_board_idle)

Storage: db.py (SQLite, WAL) is the canonical store for tracks/projects/
processes/events/connector_state - each migrated ONCE from its old
flat-JSON-file form via an import-and-rename-to-*.imported step (originals
preserved, never deleted). settings.json and users.json remain flat JSON
(small, rarely-written config). checkpoints.py (directory-tree snapshots) and
voice.py (binary mp3 cache) were investigated for the same migration and
DECLINED on purpose (daemon/debt.py order 32): neither's storage is a JSON
blob keyed by id - a checkpoint IS a copied directory, a voice render IS an
audio file served by URL/bytes - so forcing them into db.py's `data TEXT` row
shape would trade a working mechanism for a worse one. connectors.py is a
mixed case: its `connectors/_state.json` (last-run timestamps) migrated into
db.py's `connector_state` table, but the connector CODE files themselves
(`connectors/<name>.py`, real importable modules run in a sandboxed
subprocess) correctly stay on disk. The extraction work surfaced a real trap
worth remembering: a module with its OWN hardcoded `ROOT`-based path
(events.py's `EV`, processes.py's old `STORE`, and - even where no db.py
migration applies - connectors.py's `CDIR`/`VDIR`, checkpoints.py's `CPDIR`,
voice.py's `CACHE`) silently bypasses db.py's sandboxing in tests unless the
test patches that global directly - grep for `os.path.join(ROOT,` before
trusting a new test's isolation.
```

Method for the ongoing daemon breakup (repeat, don't skip): before cutting
any line range, run a full dependency scan (module-DEFINEs vs external-refs,
filtering comment mentions from real calls) - a naive contiguous slice sweeps
in unrelated consts sitting nearby. Verify every extraction with: compile +
`orig.fn IS new_module.fn` identity + the full test suite + (for server.py)
a live-HTTP route smoke test + a checksum-exact check that no runtime data
file changed. See `daemon/debt.py` `daemon-god-files` (order 31) for the
full, current tally and the remaining scope.

## Where this goes (the product thesis)

Jira × UiPath × n8n with Claude as the workforce. The target shape is
**cloud control plane + local runners** (the UiPath orchestrator/robot or
GitHub Actions runner pattern): this daemon becomes the runner; the Expo app
becomes the seed of the multi-tenant plane (orgs, Postgres, SSE) - its
plugin kernel already models composition the way the runner protocol will
need it to. The strategic asset to extract on the way is the **runner
protocol**: claim card → execute turn → stream events + recording → gate
result. Everything in this repo already maps onto it.
