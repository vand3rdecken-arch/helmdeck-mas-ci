# HelmDeck Glance — Meta Ray-Ban Display webapp

> **Before changing anything here, read `docs/glasses-reference.md`** (in the
> repo root, plain reference — `docs/` is stripped from the published mirror, so
> a link would 404 there). It is the mandatory reference distilled from the
> owner's earlier glasses project and Meta's official toolkit: the real display
> guidelines, the traps already paid for on-device, and the settled voice-output
> architecture.

A glanceable ops view for the Meta Ray-Ban Display glasses (600×600 additive
waveguide, D-pad / EMG input). Shows what needs you, capacity, and SoW margin —
read straight from the HelmDeck daemon.

```
glasses/
  index.html   # screens: home · needs-you · card · SoW · connect
  styles.css   # additive dark theme (black = transparent), focus states
  app.js       # /glance fetch, D-pad nav, localStorage config
```

Built with Meta's **Wearables Web App toolkit** (`meta-wearables-webapp`) — the
Ray-Ban Display renders standard HTML/CSS/JS, so this is a normal webapp under
the platform's constraints (600×600 viewport, `mrbd-web-app-capable`, dark
additive surfaces, focus-based navigation, no touch).

## Who hosts what

- **The webapp (these 3 files)** → hosted by **Meta's HTTPS preview** for
  on-device testing. In Claude Code with the toolkit plugin installed, run the
  `/test-on-device` skill; it uploads the files and gives an HTTPS URL the
  glasses open. (For a permanent install you publish through the Wearables
  Developer Center.) You do **not** run a server on the glasses.
- **The data** → your **HelmDeck daemon** (`daemon/`, port 8140), hosted by you
  — the same box you already run it on, reachable over LAN or Tailscale
  (e.g. `https://<host>.ts.net:8140`). The webapp calls its read-only
  `GET /glance?token=…` endpoint (CORS-enabled, token-gated).

## Connect it

1. In HelmDeck **Settings**, set a **glance token** (`settings.glance_token`)
   — any random string. Empty = the `/glance` endpoint stays **off**.
2. Open this webapp; on first run it shows the **Connect** screen. Enter:
   - **Daemon URL** — where your daemon is reachable (must be **HTTPS** for the
     glasses; a Tailscale/reverse-proxy TLS endpoint in front of :8140).
   - **Glance token** — the value from step 1.
3. Save. The home screen loads live data. Config is stored in `localStorage`.

The token grants **read-only** access to a compact glance (blocked-on-you list +
capacity + SoW margin). It never carries write access and is independent of the
session-cookie auth used by the desktop UI.

## What "needs you" means here

`needs_you` is **every card blocked on the human**, not just the parked ones —
the daemon derives it in exactly one place (`sessions.owner_blockers`), which is
also what the board and the PM narrative read. Each entry carries a `reason` and
a one-line `detail`, and the list arrives sorted worst-news-first:

| `reason` | the card is… |
|---|---|
| `gate` | held on Review by a **red quality gate** |
| `conflict` | held on Review by an **open merge conflict** |
| `failed` | a dead dispatch, a swept turn, or bounced back by you |
| `question` | **asking you** something and parked on the answer |
| `review` | gate green, **resting on Review** for your accept |
| `delivered` | finished, handed back for your accept |

A card waiting on its own **background task** is deliberately absent — that one
is the machine's move, not yours.

Cards whose turn **died** are included. Lifecycle is derived from the runtime's
own signals, so a card stuck behind a dead process appears the moment it is
read, rather than whenever the reconciler next sweeps.

`yours` is a **second, separate** list: un-started cards in a mode the machine
never dispatches (`human`, `teach`, `cowork`) — work only you can begin. It has
its own count (`econ.yours`) and never merges into `needs_you`, so a backlog
cannot bury a red gate. An ordinary `do` card in the backlog is on neither list:
the PM will get to it, so it is queued, not blocked.

## Staleness

The payload carries `ts` (epoch seconds) — when it was true. The webapp runs **no
idle timers** (battery, per the platform guidance), so it refreshes on the events
that mean you are actually looking: coming back to the foreground, and opening
the needs list. The home screen prints the age next to the count, and a failed
fetch keeps the last data but drops the connection dot to red rather than
implying it is current. A stale "all clear" is the one thing this display must
never show.

## Desktop smoke test

```
# terminal 1 — daemon
cd daemon && py -3.12 swarm.py serve
# terminal 2 — serve the webapp
cd glasses && py -3.12 -m http.server 8155
```

Open `http://localhost:8155` at a 600×600 viewport, enter
`http://localhost:8140` + your token on the Connect screen. (Local HTTP is fine
for desktop; the glasses themselves require HTTPS.)

Navigation: **Arrow keys** move focus, **Enter** selects, **Esc** goes back —
these map to the EMG band / captouch D-pad on the glasses.
