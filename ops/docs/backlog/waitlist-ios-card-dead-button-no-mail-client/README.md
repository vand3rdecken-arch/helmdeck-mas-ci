# helmdeck.de iOS download card: primary button does nothing without a mail client

**Filed 2026-09-02 from card `20260901-202935-machine`** (build-verification
card that grew unrelated scope after the owner asked "have you tested the
links on helmdeck.de"). Split off so the fix gets a clean, small-context
worker instead of riding along in a card that had already delivered its
actual job (build check + upload, already committed/pushed).

## What's broken

`ops/deploy/waitlist/src/index.js` renders the iOS download card
(`dlIosRequestBtn`, ~line 378) as a plain `mailto:` link
(`TESTFLIGHT_REQUEST_URL`, line 63). On a device/browser with no configured
mail client (very common on desktop browsers, and on phones where Mail was
never set up), clicking the primary blue button **does visibly nothing** -
no error, no fallback, the tab just sits there. From the visitor's
perspective the CTA is dead.

The second button (`dlIosAppBtn`, line 379, `TESTFLIGHT_APP_URL`) is fine as
designed - it correctly opens the generic TestFlight app page, which is the
right target for a closed-group internal beta.

## Why it's mailto in the first place (don't "fix" this part)

Read the comment at `index.js:25-31` and `:57-62` first - this is a
deliberate decision, not an oversight: iOS ships as an **internal**
TestFlight group (ASC app 6801637667, capped at 100 testers,
`ops/docs/ios-requirements.md`). Internal testing has no public join URL by
Apple design; a self-service link needs external testing + Beta App Review,
which the owner ruled out of scope. So asking for the tester's Apple ID by
mail is the correct mechanism - the bug is only that `mailto:` has no
fallback when there's no mail client wired to the browser.

## Fix shape

Give the button a fallback path when `mailto:` silently no-ops - e.g. show
the target address/subject as copyable text next to (or inside a toast
triggered by) the button, or detect click-with-no-navigation and swap to a
"copy request email" affordance. Keep the existing i18n keys
(`dlIosRequestBtn`, `dlIosNote`) working in both `de`/`en` blocks
(~line 454-456 and ~486-488).

## Verify

Manual - `mailto:` fallback behavior can't be asserted from a headless
fetch. Open the deployed card in a browser with no default mail handler
(or an incognito window) and confirm the button now gives the visitor an
actionable next step instead of nothing.
