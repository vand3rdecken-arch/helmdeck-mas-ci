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

> `push_relay.sh` below installs **Caddy** and assumes an EMPTY box. Do not run
> it against this host - it would fight nginx for port 80. It stays here for a
> fresh VM.

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
bash deploy/push_relay.sh        # copies relay + units to the VM and starts everything
```

It installs Python + Caddy, drops `relay.py` in place, enables the systemd
service, and Caddy gets a Let's Encrypt certificate automatically. Verify:

```bash
curl https://relay.yourdomain.com/health     # {"ok": true, "rooms": 0}
```

**Finally, in HelmDeck:** Settings → *Mobile app - pair a phone* → enter the
relay URL → **Pair phone** → copy the pairing code → paste it in the app.
