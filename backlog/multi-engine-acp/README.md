# Multi-engine: ACP driver — build cards ready to dispatch

**Filed 2026-08-24.** Analysis: `docs/multi-engine-support.md`. Build plan with
per-card scope + verify criteria: `docs/multi-engine-build-plan.md`. Read both;
every card additionally reads the real Paseo source (`~/Downloads/_paseo_src`)
at the file:line refs the plan names.

Five cards, ~12–16 days total:

| Card | What | Size | Status |
|---|---|---|---|
| 1 | Engine seam: CLAUDE constant dedup, parent-session env scrub (registry deferred — no 2nd engine to design it against yet) | M | ✅ SHIPPED 2026-08-24 |
| 2 | Event-time timeline store (pays the NO-MONKEY-PATCHES feed debt; worth it even engine-less) | L | ✅ SHIPPED 2026-08-24 |
| 3 | ACP transport + Stage-0 spike + brief-adherence probe (GO/NO-GO) | L | blocked on owner step below |
| 4 | Full feed + cancel parity | M–L | needs 3 + probe GO |
| 5 | Econ honesty ("n/a", never €0) + UI picker/badges | M | needs 4 |

See each card's section in `docs/multi-engine-build-plan.md` for what actually
landed vs. what was scoped, and how it was verified.

## The ONE owner step (before Card 3)

Install and authenticate the probe engine — a browser login no headless card
can do:

```
npm i -g @google/gemini-cli
gemini        # once, interactively: Google login, free tier, no card needed
```

Gemini CLI is the default probe target because it is the only candidate with a
real free tier (a second engine is otherwise a second bill: OpenCode needs
provider credentials, Codex an OpenAI login, Copilot a Copilot seat). Verified
2026-08-24: no candidate engine is currently installed on this box.

## Kill-switch

Card 3's probe report (`docs/acp-probe-report.md`) is the GO/NO-GO: if the
engine cannot be made to follow the `<helmdeck-ask>` / DELIVERED protocol
reliably, stop after Card 2 and revisit engine choice. Cards 1–2 are
independently valuable refactors either way.
