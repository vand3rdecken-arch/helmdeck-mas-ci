---
name: adversarial-test
description: Use when verifying a UI or behavioral change - test it like an idiot until it's bulletproof, instead of confirming it renders. Covers empty states, huge/garbage inputs, weird click orders, rapid toggles, missing data, wrong-then-right auth, overlay readability, layout overflow, and native-widget states (open dropdowns, date pickers) that screenshots can't see. Not for pure backend/logic (use unit tests).
---

Test the way a confused, hostile, or careless user does. "It renders" is not
"it works." The grumpy-tester stance: assume it's broken and try to prove it.

## Do these before saying "verified"

- **Run the smoke:** `py tools/adversarial_smoke.py` - it walks every view and
  does the dumb things automatically. Address anything it prints.
- **Empty states:** the view with zero cards / no data / not-logged-in. Does it
  crash or show a sensible empty state?
- **Garbage input:** paste 5000 chars into every text field; submit forms empty;
  put letters in number fields, past dates in due. Does it validate or explode?
- **Weird order:** open a card, then open chat, then switch view, then back -
  does state survive? Double-click, rapid open/close, Escape mid-action.
- **Auth edges:** wrong password (must block), a client-role user hitting an
  owner surface (must 403), a stale token.
- **The invisible states screenshots miss** (this repo's repeat offender):
  open a <select>'s popup and a date picker - do they follow the theme?
  (color-scheme). Verify with computed style, not a screenshot.
- **Overlay readability:** with a busy board behind, is the peek/modal/chat
  actually opaque enough to read? (alpha >= ~0.9 over content.)
- **Layout overflow:** does anything scroll sideways or clip at 1280px and at
  a narrow width?

## The rule

A change is "verified" only after you've *tried to break it* and it held -
not after it rendered once in a happy-path screenshot. Every bug shipped this
way was a happy-path pass. Judge, don't confirm.
