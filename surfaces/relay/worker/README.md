# HelmDeck relay on Cloudflare Workers

The relay as a Worker + one Durable Object per room. Successor of
`surfaces/relay/relay.py` running on the owner's PC behind a cloudflared
tunnel (2026-09-08 fallback, debt 63). Why it moved (2026-09-22): relay.py
served OTA files from disk and an unauthenticated path bug let anyone read
files on the PC through `relay.helmdeck.de`. A Worker has no filesystem and
nothing on the PC listens publicly any more - the daemon only connects
outbound.

Same wire protocol, so phone, daemon and desktop OTA are untouched; only DNS
moves. Route list and behaviour: see the header of `src/index.js`.

## Publish (code + every OTA channel in one step)

```bash
bash ops/deploy/publish_relay_worker.sh            # from /c/opt/helmdeck-updates*
bash ops/deploy/publish_relay_worker.sh --dry-run  # stage public/ only
```

OTA bundles ship as static assets under `public/ota/<channel>/` with a
publish-time `_index.json` (sha256 per file, runtimeVersion, createdAt,
rollback). The worker computes nothing at request time. `push_update.sh`
still exports the bundle into `/c/opt/helmdeck-updates*`; this script is the
upload leg that replaced scp/ssh.

The sideload APK (~100 MB) exceeds the 25 MB static-asset limit and is a 302
to `APK_URL` (GitHub Releases). `/apk/version.json` stays a static asset.

## Verify

```bash
py -3.12 ops/tests/test_relay_worker_e2e.py https://helmdeck-relay.<sub>.workers.dev
```

Plays phone and daemon over plain HTTP against the deployed worker: routing,
timeouts (25 s pull, 120 s reply), limits (4 MB frame, 64 queued), static
pages, OTA path hygiene. workers.dev sits behind Cloudflare's browser
integrity check, which 403s the default `Python-urllib` agent (error 1010) -
the test sets its own User-Agent; the custom domain on the helmdeck.de zone
does not have that check (the daemon runs with the default agent today).

## Cutover to relay.helmdeck.de

1. Cloudflare dashboard, zone helmdeck.de, DNS: delete the `relay` record
   (CNAME to `<tunnel-id>.cfargotunnel.com`, proxied). wrangler cannot do it -
   its token only has zone read.
2. In `wrangler.jsonc` uncomment the `routes` block, then
   `bash ops/deploy/publish_relay_worker.sh` - wrangler creates the custom
   domain record itself.
3. Stop the local relay + tunnel: `surfaces/desktop/tray.py` supervises them
   only while `HELMDECK_LOCAL_RELAY=1`; the default is off since the worker
   went live. Remove `relay.helmdeck.de` from `~/.cloudflared/config.yml`.
4. `curl https://relay.helmdeck.de/health` must show `"edge": true`.

Rollback: re-add the tunnel DNS record, start `ops/deploy/relay_local.cmd`.
