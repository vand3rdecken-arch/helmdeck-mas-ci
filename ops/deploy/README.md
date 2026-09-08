# Getting the phone connected (two paths)

The phone needs to reach your daemon over the internet. Pick ONE path.
Everything except the account sign-in is scripted here.

> The sign-up/sign-in itself has to be done by you in a browser: it means
> accepting the provider's terms and passing payment/identity checks. Those are
> personal and legally binding, and automating them also violates every
> provider's ToS (their anti-fraud systems ban bot signups).

---

## Path A — Cloudflare Tunnel (recommended: free, no credit card, no server)

No relay, no VM. `cloudflared` runs on THIS PC, dials out to Cloudflare, and
publishes the daemon under an HTTPS URL. The phone then talks to that URL
directly (HelmDeck's own login/device-token auth still applies).

**You (once):** create a free account at https://dash.cloudflare.com/sign-up

**Then run:**

```bash
bash ops/deploy/cloudflare_tunnel.sh                          # quick tunnel: instant, URL changes on restart
bash ops/deploy/cloudflare_tunnel.sh mydomain.com             # named tunnel: stable URL -> helmdeck.mydomain.com
bash ops/deploy/cloudflare_tunnel.sh mydomain.com sub.mydomain.com  # named tunnel: EXACT hostname (2nd arg overrides the helmdeck.* default)
```

The script installs `cloudflared`, starts the tunnel to `localhost:8140`, and
prints the public HTTPS URL. Put that URL in the app's "daemon url" field.

Trade-off: the daemon is reachable on the internet, protected by HelmDeck auth
only. Harden it with Cloudflare Access (free) if you want a second door.

---

## LIVE DEPLOYMENT (what is actually running)

**2026-09-08: trooper is down** (needs payment/access to reboot). `relay.helmdeck.de`
is served from a **local fallback on the owner's PC** instead:
`surfaces/relay/relay.py` runs directly from this repo
(`ops/deploy/relay_local.cmd`, HKCU `Run` autostart) and a `cloudflared` tunnel
named `helmdeck-relay` publishes it under the same DNS name - the phone/desktop
see no difference. `push_update.sh` and `push_relay.sh` both probe
`http://127.0.0.1:6790/health` first: if it answers, they publish straight into
the local `/opt/helmdeck-updates*` / `/opt/helmdeck-apk` dirs (Windows resolves
that to `C:\opt\...` - see the scripts' own comments) instead of SSH-ing to
`RELAY_HOST`, so a dead trooper no longer blocks a ship. The moment trooper (or
any VM at `RELAY_HOST`) is reachable again, this probe simply stops matching
and the section below applies unchanged - nothing to revert by hand. One gap
this fallback does NOT cover: a `relay.py` code change needs `relay_local.cmd`
restarted by hand (the running process doesn't hot-reload); the VM path always
restarted the service for you.

Everything below describes the **VM path**, still the setup `push_relay.sh`
drives whenever the local relay isn't answering:

    https://relay.helmdeck.de/health     -> {"ok": true, ...}

trooper sits behind its provider's own NAT/proxy - even ports it already
publishes itself (e.g. its LightRAG container) aren't reachable from the
open internet, and there's no dashboard access to request 80/443 forwarding.
So instead of nginx+certbot+public-bind, the relay is fronted by a
**Cloudflare Tunnel** (outbound-only from trooper, no inbound ports needed):

| piece | where |
|---|---|
| relay code | `/opt/helmdeck-relay.py` |
| service | `helmdeck-relay.service`, bound to **127.0.0.1:6790** (not public) |
| tunnel | `cloudflared` systemd service, config at `/etc/cloudflared/config.yml` |
| tunnel name/id | `helmdeck-relay` / `ee91e959-61a9-4856-a2f7-6a640c477485` |
| DNS | CNAME `relay.helmdeck.de` -> the tunnel (zone already on Cloudflare NS) |
| TLS | terminated by Cloudflare's edge - no certbot on the box at all |

> `push_relay.sh` is the UPDATE script for this box: it ships `surfaces/relay/relay.py`,
> the Expo APK + `/apk/version.json` (built by `ops/tools/release.sh android`),
> and restarts `helmdeck-relay.service`. It does NOT touch the tunnel/DNS -
> those were set up once (`cloudflared tunnel login` / `create` / `route dns`,
> then `cloudflared service install` pointed at `/etc/cloudflared/config.yml`).
> JS-only changes ride OTA instead: `ops/deploy/push_update.sh`.

The previous Oracle Always Free VM (`141.144.227.105`) is **retired** - it
needed payment to reboot and was abandoned. `ops/deploy/setup_relay_vm.sh`
(nginx+certbot+systemd, the old Path B recipe) is kept as a fallback if a
dedicated VM with a real public IP is ever wanted again, but is not what's
currently live.

---

## LAN HTTPS — the daemon's own TLS listener (no tunnel, no VM)

For browsers/desktops on your own network (the phone should use Path A/B).
Mint a cert and restart the daemon:

```bash
py -3.12 ops/tools/make_tls_cert.py        # writes daemon/certs/tls.crt + tls.key (git-ignored)
```

The daemon auto-detects the files and then serves **https on :8443**
(`HELMDECK_TLS_PORT` or `settings.tls.port` to change) while plain http
retreats to **loopback only** — local tooling (relay bridge, cloudflared,
Electron) keeps `http://localhost:8140`, but credentials and cookies never
cross the LAN unencrypted. Explicit paths beat auto-detection:
`HELMDECK_TLS_CERT`/`HELMDECK_TLS_KEY` (env) or `settings.tls {cert,key}`.

Self-signed = one browser trust warning per device (Android refuses outright).
For a cert every device trusts without warnings, use Tailscale:

```bash
tailscale up
tailscale cert <machine>.<tailnet>.ts.net    # real Let's Encrypt cert for your tailnet name
# point HELMDECK_TLS_CERT / HELMDECK_TLS_KEY at the two files it writes
```

Related enforcement: the daemon refuses to SAVE or PAIR a plain-`http://`
relay URL (non-loopback) — pairing links embed a live device token and must
never travel unencrypted.

---

## Path B — your own relay on a free VM (zero-knowledge, E2E encrypted)

The relay (`surfaces/relay/relay.py`) shuttles only ciphertext: it cannot read or forge
traffic (NaCl box, Curve25519 + XSalsa20-Poly1305 - Paseo's scheme). Use this
if you want the encrypted path, or to serve several users from one host.

**You (once):**
1. Sign up at https://signup.oraclecloud.com (Always Free tier; a card is
   required for identity, it is not charged for Always Free shapes).
2. Create an **Always Free VM** (Ampere/ARM or AMD micro), Ubuntu 22.04+.
3. Note its public IP, open ports 80 + 443 in the VCN security list.
4. Point a DNS A-record (`relay.yourdomain.com`) at that IP.
5. Put the IP/domain into `.env` (`RELAY_HOST`, `RELAY_DOMAIN`).

**Then run (from this repo):**

```bash
bash ops/deploy/push_relay.sh        # ships relay.py (+ APK channel) and restarts the service
```

The script assumes the box was set up once (systemd unit + nginx/certbot or
equivalent TLS proxy, as on the live VM above); it only updates `relay.py`,
the `/apk/` update channel, and restarts `helmdeck-relay`. Verify:

```bash
curl https://relay.yourdomain.com/health     # {"ok": true, "rooms": 0}
```

**Finally, in HelmDeck:** Settings → *Mobile app - pair a phone* → enter the
relay URL → **Pair phone** → copy the pairing code → paste it in the app.
