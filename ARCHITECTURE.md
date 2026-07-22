# SwarmDeck architecture

The organizing idea: **SwarmDeck applies its own product philosophy to
itself.** A harness (the fixed world work executes in) plus loops (the states
work travels through). What makes the system trustable is code; how work
flows is data.

## The company model

| Company concept | SwarmDeck primitive |
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

## Fixed vs. flexible

**Fixed — the harness (code, unreachable from chat/config):**
- auth, users, roles, sessions, device tokens
- the audit trail: append-only events, non-optional recording, git history
- gate-before-review; measured economics (display is configurable,
  measurement is not)
- worktree isolation; chain ordering (step N+1 only after N)
- driver commands (what executes on the machine)
- the capability charter core

**Flexible — policy (data in `settings.json`, editable in Settings or via
copilot, per `policy.chat_configure_roles`):**
- lane labels; automation (`auto_dispatch_modes`, `auto_accept_green`,
  priority self-dispatch); capacity, tariffs, value, prices, currency
- dashboard composition; appearance/backdrop; registration; Jira connection;
  connector schedules; additive `house_rules`

Every policy change creates a **checkpoint** (settings + connectors snapshot,
actor-attributed) with reversible restore. Checkpoints roll back the machine,
never history — work data is immutable record.

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

```
web (Next.js :3300) ──proxy /backend/*──► daemon (Python :8140)
                                            ├─ sessions.py   cards/branches/worktrees, gate, edits
                                            ├─ processes.py  step chains + auto-advance poller
                                            ├─ drivers.py    claude / claude-desktop / http / cmd
                                            ├─ copilot.py    chat -> JSON actions (per-user Claude session)
                                            ├─ connectors.py sandboxed user-built importers + scheduler
                                            ├─ charter.py    capability screening
                                            ├─ events.py     settings + append-only event log + metrics
                                            ├─ checkpoints.py config snapshots + restore
                                            ├─ auth.py       PBKDF2 users, cookie sessions, device tokens
                                            └─ wincap/actionlog/teach  flight recorder
apk / glasses / worker: companion surfaces per the APK rule (thin, never the brain)
```

Storage is JSON files (tracks/events/users/settings) — right for a
single-tenant daemon; the known upgrade path is per-track turn locks →
SQLite → SSE push, none of which changes anything above the storage layer.

## Where this goes (the product thesis)

Jira × UiPath × n8n with Claude as the workforce. The target shape is
**cloud control plane + local runners** (the UiPath orchestrator/robot or
GitHub Actions runner pattern): this daemon becomes the runner; the Next app
becomes the seed of the multi-tenant plane (orgs, Postgres, SSE). The
strategic asset to extract on the way is the **runner protocol**: claim card
→ execute turn → stream events + recording → gate result. Everything in this
repo already maps onto it.
