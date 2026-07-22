# SwarmDeck

**Work management where the workers are agents.** A merge of Jira (tickets,
boards, clients), n8n (processes that chain and auto-advance), and UiPath
(agents driving real software on real machines) — with Claude as the
workforce and a **flight recorder** as the trust layer: every agent action is
logged, screen-recorded, and auditable.

A client files a request in plain words. An agent proposes the step chain.
Humans adjust, accept, and do only the steps that need a human — everything
else dispatches itself, gets quality-gated, and lands as evidence-backed,
per-card-priced work.

## The surfaces

| Path | What it is |
|---|---|
| `daemon/` | **The brain + hands.** Python backend: board/orchestrator (cards = git branches with resumable Claude sessions), review gate, process chain, economics, auth, copilot, connectors, charter, checkpoints, recorder. API on `:8140` (plus a single-file fallback UI). |
| `web/` | **The UI.** Next.js + TS on the Plane design-token system with a liquid-glass pass. Board / List / Timeline / Processes / Dashboard / Recordings / History / Settings, copilot chat, ⌘K palette, client auras + spotlight, live thumbnails. Proxies `/backend/*` to the daemon. |
| `apk/` | Android hub (phone = auth/pairing/review per the APK rule). |
| `glasses/` | Meta Ray-Ban Display viewer (live glance feed). |
| `worker/` | Thin Cloudflare relay (rendezvous + newest frame). Never the brain. |
| `plane-selfhost/` | Optional real Plane instance + bridge (`daemon/plane_bridge.py`) as an alternative client frontend. Dormant; needs Docker/WSL. |

## Quick start

```bash
# backend (Python 3.12)
cd daemon && pip install -r requirements.txt
python swarm.py serve            # API on :8140

# frontend
cd web && npm install
npm run dev -- --port 3300       # the UI
```

First run shows a **create-owner** screen. Users, roles (owner / operator /
client), invite-code self-registration, and per-user device tokens live in
Settings.

## Core concepts

- **Card = branch = session.** Every request is a git branch in its own
  worktree, bound to a resumable Claude Code session. Lanes are workflow
  verbs: Backlog → Working (dispatches) → Review (**runs the quality gate**,
  bounces with a punch list) → Done (accepts + records economics). Cards are
  editable inline, archivable (reversible), deletable (owner; audit stays).
- **Processes (the n8n half).** Describe a client request; an agent proposes
  3–8 steps, each with an execution mode — do · prepare · cowork · teach ·
  human. Accepted steps become chained cards: agent steps auto-run when the
  previous step completes, human steps surface in the board's NEXT UP strip.
  The pipeline view shows where the chain is.
- **Drivers (the UiPath half).** Execution is pluggable per card: `claude`
  (code), `claude-desktop` (windows-mcp drives Windows/browser; every turn
  screen-recorded, live thumbnail on the card), `http` (any agent API),
  `cmd`. Driver commands are fixed harness — never chat-configurable.
- **Economics.** Humans are fixed capacity (touch units vs. daily budget);
  AI is variable cost (tokens × price table per turn). Dashboard: value
  delivered, margin, first-pass yield, automation rate, capacity gauge,
  gate-failure histogram — composition configurable, **measurement never
  stops**.
- **Copilot chat** (`k`, model picker haiku·sonnet·opus). Steers everything
  in natural language: cards, processes, workspace policy (per-role),
  imports, connector builds. Each user's chat is a persistent, resumable
  Claude session (`claude --resume <id>` works from a terminal).
- **Connectors — integrations built by chatting.** "Build an integration
  that pulls X" files a build card; an agent writes it, the gate checks it,
  your accept installs it — then it's a sidebar tab (run / schedule /
  rollback). Sandboxed, versioned, create-only toward the board.
- **Audit (History view).** Three layers: the git branch tree (the work,
  unfakeable), **system checkpoints** (every change to the software itself,
  actor-attributed, reversibly restorable), and the append-only event log.

## Safety model

See [ARCHITECTURE.md](ARCHITECTURE.md). In one line: **the harness is code,
policy is data, and everything buildable walks the gate.** The capability
charter (`GET /charter`) states what may be built here and is enforced at
commission, install, and run time.
