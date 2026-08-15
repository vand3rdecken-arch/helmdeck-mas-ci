# HelmDeck landing site (M4 public-launch)

A single Cloudflare Worker that serves the whole public site — hero, live
download buttons for Windows/macOS/Android, and the waitlist (now scoped to
the not-yet-shipped **Watch & Glasses** line, since the app itself is
downloadable directly). Storage in Workers KV. No framework, no build step,
no tracking.

- **Live URL**: `https://helmdeck-waitlist.<account-subdomain>.workers.dev`
  (a custom domain can be attached later in the Cloudflare dashboard:
  Worker → Settings → Domains & Routes) — this is meant to become `helmdeck.de`.
- **Downloads**: the `/` route reads the latest GitHub release
  (`api.github.com/repos/Tienduyvo/helmdeck/releases/latest`) at request time
  and picks the Windows `.exe`, both macOS `.dmg`s and the Android `.apk` by
  content-type + filename, so the buttons never go stale when a new version
  ships. Result is cached in the `WAITLIST` KV for 1h (key `_cache:latest-release`)
  to stay well under GitHub's unauthenticated rate limit. If the fetch fails,
  every button falls back to the releases page itself instead of a dead link.
- **Storage**: KV namespace `WAITLIST` (id in `wrangler.jsonc`), key
  `email:<lowercased>`, value + metadata `{email, ts, lang, product}`.
  `product` is always `"wearables"` — the sole thing this waitlist now
  collects for. First signup wins; duplicates are acknowledged but never
  overwrite the original timestamp. No IP or user agent is stored.

## Owner: viewing the addresses

Two ways, pick either:

1. **CSV export** (Excel-ready, BOM + CRLF):
   `https://<worker-url>/export.csv?token=<EXPORT_TOKEN>`
   The token is a Worker secret (`npx wrangler secret put EXPORT_TOKEN`),
   never in git. Also accepted as `Authorization: Bearer <token>`.
2. **Cloudflare dashboard**: Workers & Pages → KV → `WAITLIST` → entries.

Delete a single address (GDPR request):
`npx wrangler kv key delete --namespace-id <id> "email:<address>"`
or via the dashboard.

## Deploy / update

```bash
cd deploy/waitlist
npx wrangler deploy                      # ship worker changes
npx wrangler secret put EXPORT_TOKEN     # (re)set the export token
```

## Behavior notes

- Email validation both client- and server-side (`EMAIL_RE`); the server is
  authoritative. Invalid input → inline error (no-JS fallback: redirect with
  `?err=1`).
- Bilingual DE/EN: German markup by default, client-side toggle (top right),
  choice persisted in localStorage, initial pick from `navigator.language`.
- Bot filter: invisible honeypot field (`company`). Filled → fake success,
  nothing stored. Upgrade path if spam ever appears: Cloudflare Turnstile.
- Works without JavaScript: plain form POST → 303 redirect back to `/` with
  the success/error state in query params, rendered server-side.
- Later Loops integration (if that card lands): push the CSV into a Loops
  segment, or extend `handleJoin` to also POST to the Loops API.
