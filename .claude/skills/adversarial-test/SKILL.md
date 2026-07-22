---
name: adversarial-test
description: Use at TEST, after building a feature, to prove it holds up when used like an idiot. This is a PRINCIPLE applied per feature - you write the break-it cases for THE THING YOU JUST BUILT, then try them. It is NOT a generic suite that walks every view; a canned smoke that isn't about your feature proves nothing. Not for pure internal refactors with no user-facing surface.
---

"It renders" is not "it works." For every feature you ship, spend a few minutes
being the careless, confused, or hostile user of *that specific feature* - then
write down what you tried and whether it held.

## The principle

1. **Name the feature's surface.** What did this change let a user *do*? (submit a
   fork, edit a title, toggle a driver, open a dropdown.) That, not "the app," is
   what you test.
2. **Enumerate how a user breaks THIS surface.** Write the list fresh each time -
   the failure modes of a fork button are not the failure modes of a date field.
   Use the prompts below to generate them, don't run them as a fixed checklist.
3. **Try each. Record pass/fail in the workorder's `## Verified`.** A feature is
   verified only after you tried to break it and it held - not after one happy-path
   screenshot. Every UI bug shipped this session was a happy-path pass.

## Prompts for generating this feature's break-it list

Ask these *about the feature you built* and keep the ones that apply:

- **Empty / missing:** the field left blank, zero items, the object not yet
  created, not logged in. Does it validate or explode?
- **Too much / garbage:** 5000 chars, emoji, letters in a number field, a past
  date, a negative value, a name that's already taken.
- **Wrong order / repeat:** double-click submit, act before it loads, toggle
  on-off-on fast, open then navigate away then back - does state survive?
- **Wrong actor:** a client-role user hitting an owner-only control (must 403);
  a stale session; someone else's card id.
- **The invisible states screenshots miss** (this repo's repeat offender): open a
  `<select>` popup or date picker and check it follows the theme via *computed*
  `color-scheme` - not a screenshot. Check an overlay is opaque enough to read
  over a busy board (alpha, not eyeballing).
- **Does it actually persist / take effect?** Reload after the action - did it
  stick, and did the economics/audit trail update?

## Writing it down

The record IS the deliverable - a few lines in `## Verified` naming the feature and
each break attempt with its result. If a case needs to run again later, put a tiny
feature-specific check next to the feature (e.g. a Playwright snippet that opens
*this* control), not in one growing generic walk. One test, one feature.
