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
bash deploy/cloudflare_tunnel.sh            # quick tunnel: instant, URL changes on restart
bash deploy/cloudflare_tunnel.sh mydomain.com   # named tunnel: stable URL (domain on Cloudflare)
```

The script installs `cloudflared`, starts the tunnel to `localhost:8140`, and
prints the public HTTPS URL. Put that URL in the app's "daemon url" field.

Trade-off: the daemon is reachable on the internet, protected by HelmDeck auth
only. Harden it with Cloudflare Access (free) if you want a second door.

---

## LIVE DEPLOYMENT (what is actually running)

The relay is deployed on the Oracle Always Free VM and reachable at:

    https://141.144.227.105.sslip.io/health     -> {"ok": true, ...}

Layout on that box (Ubuntu 20.04, ARM, `ubuntu@141.144.227.105`,
key `~/.ssh/oracle_relay`):

| piece | where |
|---|---|
| relay code | `/opt/helmdeck-relay.py` |
| service | `helmdeck-relay.service`, bound to **127.0.0.1:6790** (not public) |
| TLS + proxy | **nginx** vhost `/etc/nginx/sites-available/helmdeck-relay` |
| certificate | Let's Encrypt via certbot, auto-renewing |
| nginx backup | `/home/ubuntu/nginx-backup-<ts>.tgz` |

That box previously served **stocknews-gpt.com**. It is now *deactivated, not
deleted*: `myproject.service` is stopped+disabled and its nginx site unlinked,
while `/home/ubuntu/flask_gpt`, the PostgreSQL data and
`/etc/nginx/sites-available/myproject` are untouched. To bring it back:

```bash
sudo ln -s /etc/nginx/sites-available/myproject /etc/nginx/sites-enabled/
sudo systemctl enable --now myproject && sudo nginx -t && sudo systemctl reload nginx
```

> `push_relay.sh` is the UPDATE script for this box: it ships `relay/relay.py`,
> the Expo APK + `/apk/version.json` (built by `tools/release.sh android`), and
> restarts the service. It does NOT touch nginx or TLS (the first-install
> version wrote a Caddyfile; that was removed exactly because it would fight
> nginx for :443). JS-only changes ride OTA instead: `deploy/push_update.sh`.

---

## LAN HTTPS — the daemon's own TLS listener (no tunnel, no VM)

For browsers/desktops on your own network (the phone should use Path A/B).
Mint a cert and restart the daemon:

```bash
py -3.12 tools/make_tls_cert.py        # writes daemon/certs/tls.crt + tls.key (git-ignored)
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

The relay (`relay/relay.py`) shuttles only ciphertext: it cannot read or forge
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
bash deploy/push_relay.sh        # ships relay.py (+ APK channel) and restarts the service
```

The script assumes the box was set up once (systemd unit + nginx/certbot or
equivalent TLS proxy, as on the live VM above); it only updates `relay.py`,
the `/apk/` update channel, and restarts `helmdeck-relay`. Verify:

```bash
curl https://relay.yourdomain.com/health     # {"ok": true, "rooms": 0}
```

**Finally, in HelmDeck:** Settings → *Mobile app - pair a phone* → enter the
relay URL → **Pair phone** → copy the pairing code → paste it in the app.
