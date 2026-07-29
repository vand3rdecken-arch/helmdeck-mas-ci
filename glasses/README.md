# SwarmDeck Glance — Meta Ray-Ban Display webapp

A glanceable ops view for the Meta Ray-Ban Display glasses (600×600 additive
waveguide, D-pad / EMG input). Shows what needs you, capacity, and SoW margin —
read straight from the SwarmDeck daemon.

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
- **The data** → your **SwarmDeck daemon** (`daemon/`, port 8140), hosted by you
  — the same box you already run it on, reachable over LAN or Tailscale
  (e.g. `https://<host>.ts.net:8140`). The webapp calls its read-only
  `GET /glance?token=…` endpoint (CORS-enabled, token-gated).

## Connect it

1. In SwarmDeck **Settings**, set a **glance token** (`settings.glance_token`)
   — any random string. Empty = the `/glance` endpoint stays **off**.
2. Open this webapp; on first run it shows the **Connect** screen. Enter:
   - **Daemon URL** — where your daemon is reachable (must be **HTTPS** for the
     glasses; a Tailscale/reverse-proxy TLS endpoint in front of :8140).
   - **Glance token** — the value from step 1.
3. Save. The home screen loads live data. Config is stored in `localStorage`.

The token grants **read-only** access to a compact glance (needs-you list +
capacity + SoW margin). It never carries write access and is independent of the
session-cookie auth used by the desktop UI.

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
