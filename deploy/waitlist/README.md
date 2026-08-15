# HelmDeck landing site (M4 public-launch)

A single Cloudflare Worker that serves the whole public site — hero, live
download buttons for Windows/macOS/Android, the iOS TestFlight request, and
the waitlist (now scoped to the not-yet-shipped **Watch & Glasses** line,
since the app itself is downloadable directly). Storage in Workers KV. No
framework, no build step, no tracking.

- **Live URL**: `https://helmdeck.de` — the custom domain is already attached
  to this Worker (proof: `curl https://helmdeck.de/health` answers
  `{"ok":true,"service":"helmdeck-waitlist"}`). Use that health route, not the
  commit log, to check *which build* is actually live: a merged commit here is
  **not** deployed until someone runs `npx wrangler deploy` (see below).
- **Downloads**: the `/` route reads the latest GitHub release
  (`api.github.com/repos/Tienduyvo/helmdeck/releases/latest`) at request time
  and picks the Windows `.exe`, both macOS `.dmg`s and the Android `.apk` by
  content-type + filename, so the buttons never go stale when a new version
  ships. Result is cached in the `WAITLIST` KV for 1h (key `_cache:latest-release`)
  to stay well under GitHub's unauthenticated rate limit. If the fetch fails,
  every button falls back to the releases page itself instead of a dead link.
- **iOS has no download**: distribution is an *internal* TestFlight group
  (`docs/ios-requirements.md` fixes the scope), and internal testing has no
  public join URL — Apple invites by Apple-ID email. The card therefore links a
  `mailto:` that asks for the tester's Apple ID. If the owner ever switches to
  **external** TestFlight (needs Beta App Review), replace
  `TESTFLIGHT_REQUEST_URL` in `src/index.js` with the real
  `https://testflight.apple.com/join/<code>` link.
- **Domains — all 4 TLDs, with and without `www`** (Cloudflare account
  `0f5984a3acf38570ca44e7a62dc79434`). `helmdeck.de` is the canonical one and is
  a Workers Custom Domain on this worker; `.global` / `.info` / `.store` are
  brand-protection TLDs that 301 to it.

  | hostname | how it resolves |
  |---|---|
  | `helmdeck.de` | Custom Domain → this Worker |
  | `www.helmdeck.de` | A `192.0.2.1` proxied + redirect rule *"Umleitung von WWW zum Stammverzeichnis"* (`https://www.*` → `https://${1}`, 301) |
  | `helmdeck.global` / `.info` / `.store` | A `192.0.2.1` proxied + per-zone catch-all 301 → `https://helmdeck.de` |
  | `www.` of those three | A `192.0.2.1` proxied; the zone's existing catch-all rule already matches `www`, so **no second rule is needed** |

  ⚠ The `192.0.2.1` is TEST-NET-1 (never routable) and only exists so Cloudflare's
  edge has a proxied record to intercept — without *some* proxied record the
  hostname does not resolve at all and no redirect rule can ever fire. Keep the
  orange cloud ON; a grey-clouded (DNS-only) record would hand visitors a dead IP.

  ⚠ `wrangler` **cannot** manage any of this — its OAuth token is `zone (read)`
  only (`npx wrangler whoami`), so zone/DNS/redirect changes are dashboard-only
  (or need a separate API token with `Zone:DNS:Edit`). Do not waste time looking
  for a CLI path; there isn't one with the current credential.

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

⚠ **Merging is not shipping.** This Worker is outside the repo's card deploy
hook — nothing in the accept path runs `wrangler deploy`. Card
`proc-20260814-s7` merged the full landing page on 2026-08-15 and the site kept
serving the 2026-08-13 waitlist-only build for two days because that one command
never ran. Verify a deploy against the live origin, never against `git log`:

```bash
npx wrangler deployments list | tail -8            # newest deployment timestamp
curl -s https://helmdeck.de/ | grep -o '<title>[^<]*</title>'
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
