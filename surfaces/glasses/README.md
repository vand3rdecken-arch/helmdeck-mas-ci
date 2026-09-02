# HelmDeck Glance — Meta Ray-Ban Display webapp

> **Before changing anything here, read `ops/docs/glasses-reference.md`** (in the
> repo root, plain reference — `ops/docs/` is stripped from the published mirror, so
> a link would 404 there). It is the mandatory reference distilled from the
> owner's earlier glasses project and Meta's official toolkit: the real display
> guidelines, the traps already paid for on-device, and the settled voice-output
> architecture.

A glanceable ops view for the Meta Ray-Ban Display glasses (600×600 additive
waveguide, D-pad / EMG input). Shows what needs you, capacity, and SoW margin —
read straight from the HelmDeck daemon.

```
surfaces/glasses/
  index.html   # screens: home · needs-you · card · decide · talk · SoW · connect
  styles.css   # additive dark theme (black = transparent), focus states
  app.js       # /glance fetch, the conversation stream, D-pad nav, localStorage config
```

## The conversation, and the listening indicator

The `talk` screen is the lens's window onto **one** Henry conversation — the same
`copilot.chat` session the phone and the watch read, never a lens-local copy. It
is shaped like the Wear OS watch's `HenryScreen`: the whole exchange is visible,
and the owner's own words appear the moment they are sent rather than only after
the answer arrives.

The lens's own problem is that **it has no microphone**. The mic is opened by
`GlassVoiceService` on the phone (the glasses mic over Bluetooth HFP, or the
phone's own), which posts the recognised words to `/glance/talk`. Before this
screen existed, that loop ran entirely past the display: nothing on the lens said
anything was listening, and the transcript was never shown — so a misheard
sentence could not be caught before it was sent in the owner's name.

So the daemon publishes the state of the turn and the lens renders it:

| state | who observes it | on the lens |
|---|---|---|
| `listening` | the process holding the mic, via `POST /glance/state` | pulsing dot + **Listening** + which mic |
| `heard` / `thinking` | the daemon, as `/glance/talk` arrives and runs | the pending line, then **Henry is thinking** |
| `answered` | the daemon, when the turn returns | the reply and its tappable options |
| `failed` | the daemon, when the model call raises | **No answer - ask again**, never a silent wait |

`answered` is deliberately not called "speaking": whether the clip reached the
owner's ear is something the daemon never learns, so it reports what it saw.

Reads go over `GET /glance/chat`, a **hanging GET** (~20s) that returns the moment
the transcript or the turn moves — one open request, never a fast poll. The
options travel with the turn state rather than with the `/glance/talk` response,
because on a spoken turn that response goes to the *phone* and the lens would
otherwise have nothing to tap.

Two switches, both pre-existing: `glance_token` turns the surface on,
`glance_talk` turns the conversation (and therefore the indicator) on.

Built with Meta's **Wearables Web App toolkit** (`meta-wearables-webapp`) — the
Ray-Ban Display renders standard HTML/CSS/JS, so this is a normal webapp under
the platform's constraints (600×600 viewport, `mrbd-web-app-capable`, dark
additive surfaces, focus-based navigation, no touch).

## Who hosts what

- **The webapp (these 3 files)** → hosted by **you**, on any public HTTPS
  origin. You do **not** run a server on the glasses, and Meta does **not** host
  it for you. Two paths, and they are for different purposes:
  - *Throwaway testing* → the toolkit's `/test-on-device` skill uploads the
    files and hands back a temporary HTTPS URL. Fine for a look; it is not an
    install.
  - *Permanent* → put the files on an origin you control, then in the **Meta AI
    app → Developer Mode → App Connections → Web Apps → Add a Web App**,
    register that one URL. It stays. No review, no Developer Center, no partner
    programme — those gate the public STORE LISTING, which is a different thing
    (see `ops/docs/glasses-reference.md` §11.9). `ops/tools/qr.py` in the owner's
    glass-crud-harness turns the URL into a QR so the phone adds it in one tap.

  Register **one** URL and keep it: new screens ship by redeploying the origin,
  never by re-registering on the glasses.
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

The payload carries `ts` (epoch seconds) — when it was true. The webapp refreshes
on the events that mean you are actually looking (coming back to the foreground,
opening the needs list) **and** on a bounded 60s poll while the page is visible —
started on foreground, stopped the instant it hides, never a fast poll (battery,
per the platform guidance). The poll exists so a new blocker lands proactively:
each refresh diffs `needs_you` against the ids it already knew about, and a
freshly-appeared card lights a badge on "Needs you" (clears when you open the
list) plus a short glance-safe banner — a count only, never a task name, so a
bystander glancing at the lens learns nothing. The same count is also spoken
(the lens has no `speechSynthesis` but plays audio, same mechanism as the
board-agent replies below), with **Voice on/off** and **Repeat** controls on
the Needs screen — mute for a meeting, repeat when the browser blocked the
unprompted playback or you just missed it. The home screen prints the age
next to the count, and a failed fetch keeps the last data but drops the
connection dot to red rather than implying it is current. A stale "all clear" is
the one thing this display must never show.

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
