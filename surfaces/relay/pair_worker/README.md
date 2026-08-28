# HelmDeck Pair worker — the public door to GET /relay/pair/claim

> Read `ops/docs/backlog/wear-os-integration/README.md` §4.11–§4.13 first. It
> records why this exists: a raw `cloudflare_tunnel.sh` origin answers
> **everything** on the daemon, including `/auth/login`, to anyone who finds
> the hostname — fine for a phone that dials in over the sealed E2EE relay,
> not fine for the ONE thing a keyboard-less, camera-less device (a Wear OS
> watch) needs to reach before it has any credentials at all.

This is the second thing in HelmDeck that puts a door to the owner's daemon
on the open internet (the first is `surfaces/glasses/worker`) — same
discipline, narrower door.

## The security model

**The Worker proxies ONE path and nothing else, ever.**

| Path | Method |
|---|---|
| `GET /relay/pair/claim` | the single-use, 15-minute-TTL device-code claim (`spine/comms/relay_client.py`'s `claim_code()`) |

Deliberately **not** `/relay/pair/code` (the code-minting route) — that one
is session-authenticated, and this Worker strips `Cookie`/`Authorization` on
the way up exactly like the glance worker does, so forwarding it would only
ever 401. It stays on the daemon, reached over the sealed relay by an
already-paired phone, never over this Worker.

`ops/tests/test_pair_worker.py` executes the real routing function under
plain node, including traversal/prefix-confusion cases and a check that the
*sibling* authenticated route is refused — mirrors
`ops/tests/test_glance_worker.py`'s own discipline.

## Setup (once)

```bash
# 1. a Worker at the edge cannot see localhost:8140 - route a DEDICATED
#    origin hostname to the tunnel (NOT the same hostname this Worker will
#    eventually own - see the "pair.helmdeck.de" note below):
bash ops/deploy/cloudflare_tunnel.sh helmdeck.de daemon-origin.helmdeck.de

# 2. tell the Worker where that is (a SECRET - a door to the flat)
cd surfaces/relay/pair_worker && npx wrangler secret put DAEMON_URL
#   -> https://daemon-origin.helmdeck.de

# 3. ship
bash ops/deploy/push_pair_worker.sh
```

**`pair.helmdeck.de` as this Worker's own Custom Domain is the intended end
state, not yet live.** It still CNAMEs to the OLD raw tunnel origin this
Worker exists to replace, and Cloudflare refuses to attach a Custom Domain to
a hostname with an existing external DNS record (error `100117`) — neither
`cloudflared` (no route-delete subcommand) nor this repo's `wrangler` token
(scoped `zone:read`, not `zone:write`) can remove that record. One manual,
one-time step: Cloudflare dashboard → `helmdeck.de` → DNS → delete the `pair`
CNAME → re-run `push_pair_worker.sh`. Until then, use the Worker's own
`workers.dev` address (kept alive on purpose in `wrangler.jsonc` for exactly
this reason) — `surfaces/app/plugins/wear/PairingScreen.kt`'s
`DEFAULT_CLAIM_BASE_URL` points there today.

## Layout

```
surfaces/relay/pair_worker/
  wrangler.jsonc   # name, the pending pair.helmdeck.de custom-domain route, workers_dev
  src/index.js     # allowlist proxy - no static assets, no webapp
  src/routes.js    # the one-entry PROXY_ROUTES allowlist
```

No `public/` directory — unlike the glance worker, this one has no webapp to
host, only the one API route.

## Local check

```bash
curl https://helmdeck-pair.<your-subdomain>.workers.dev/health
# {"ok":true,"service":"helmdeck-pair","daemon":true|false}
```

`daemon` reports whether `DAEMON_URL` is set — not whether the tunnel is
currently *running*. A tunnel that's down still answers with a real 502 from
Cloudflare's edge, which is the honest failure mode, not a silent one.
