# Glasses reference — what the two real projects already paid for

**MANDATORY reading for every further card in the glasses process.** Same rule as
`docs/paseo-adoption-plan.md`: read the ACTUAL source before building. This
document is the map, not a substitute for it.

Two reference projects on this machine, both READ-ONLY for us — we adopt
decisions, we do not copy files:

| # | Path | What it is |
|---|---|---|
| 1 | `C:\Users\Tien Duy Vo\Downloads\glass-crud-harness` | The owner's earlier glasses project. Shipped companion APK, WhatsApp bridge/relay, Cloudflare worker, on-device probe results. **The experience.** |
| 2 | `C:\Users\Tien Duy Vo\Downloads\meta-wearables-webapp` | Meta's official Wearables Web App toolkit (`facebookincubator`, BSD-3). Skills, display guidelines, templates. **The platform rules.** |

Supporting source read for this document: the patched bridge fork at
`C:\Users\Tien Duy Vo\Downloads\whatsapp-claude-agent` (the daemon that actually
implements the channel decided on below).

Everything here is dated. The Meta preview moved twice in two months
(`glass-crud-harness/docs/android-dat-research.md:66`) — **recheck before
building**, don't trust this page as current on the platform side.

---

## 0. The one-screen summary

- **Voice output is SETTLED**: render speech server-side and deliver it over the
  WhatsApp channel. NOT per-device TTS. → §4.
- **The glasses webapp cannot capture and cannot run in the background.** Both
  verified, not assumed. → §3.
- **SDK access is much smaller than "partner approval"** — a GitHub PAT for the
  packages, plus Developer mode (and possibly a preview form). → §5.
- **HelmDeck's `glasses/` app is already ~80% conformant** with Meta's real
  display guidelines; four concrete deltas remain. → §6.
- The proven pairing/auth model is **valet tickets + device-code + anchor
  device** → §2 — but **do not reach for it without a second device to enroll**:
  it was adopted once for a companion app that was then scrapped. → §11.1.
- **GLASS MODE is the live direction**: the lens shows what is blocked and the
  owner *decides* on it by tapping options the worker offered. No companion app,
  no SDK, no PAT. → §11.

---

## 1. The architectural decision that matters most

> *"There is **no direct phone↔glasses link** — they meet at the worker."*
> — `glass-crud-harness/COMPANION.md:6-7`

glass-crud-harness never talks device-to-device. No BLE, no
`CompanionDeviceManager` (zero references in the entire repo), no adb, no LAN
discovery. One writer (the phone), one reader (the lens), one hub (a Cloudflare
Worker + D1 + Durable Objects).

**HelmDeck already has this shape** — the daemon is the hub, the phone and the
glasses are clients, the E2EE relay is the transport. Do not introduce a
device-to-device path. It was considered there and never built.

The second decision, from `AGENTS.md:263-270`, is the one that should gate every
future glasses card:

> **"does this app belong on the glasses at all?"** The glasses earn their place
> *only* when the **consuming** moment is hands-busy / eyes-up. […] Input still
> happens on the phone (you can't type on the glasses) — that's fine, because
> **authoring and consuming are different moments**.

For HelmDeck this is a clean fit and also a clean limit: *seeing that a card is
blocked* is eyes-up. *Steering and accepting* are authoring — they belong on the
phone.

⚠ **Refined 2026-08-16 by GLASS MODE (§11), and the distinction is the whole
point.** This section used to end "…*answering a question* is authoring, so
`/glance` being read-only is correct by this rule." That drew the line in the
wrong place. The rule the sources actually state is about *typing*: **"you can't
type on the glasses"** here, and §3.6's **"the webapp is output + SELECTION"**.
Picking one of six options a worker already wrote is selection, not authoring —
it needs no keyboard and no dictation, so it is squarely inside the law. Free
text would be authoring, which is exactly why `/glance/answer` refuses it and
leaves it to the phone. So `/glance` is no longer read-only, and that is not a
violation of this rule — it is the rule applied more precisely.

**And the precedent says HelmDeck is already past the point where that project
stopped.** glass-crud-harness designed exactly this surface — an "Agent Cockpit"
on the lens — and never finished it. `apps/cockpit/acceptance.md`: *"v1 shows
**hardcoded example tracks**"*, with `[ ] next: wire to the live worker/relay so
it reads the real agent state` still open. The glasses-native agent supervisor
was rendered and never connected to reality. HelmDeck's `/glance` is that
surface, wired to a real board, with the completeness now tested. Treat the
cockpit as the design study it is — and don't re-do the part that was already
finished here.

---

## 2. Adopt from glass-crud-harness

### 2.1 Valet tickets (auth) — the highest-value steal
`worker/schema.sql:15-38`, `worker/src/worker.js:59-122`.

> *"Accept the master secret OR a paired per-device ticket. Devices should carry
> tickets (revocable one by one); the master secret is for admin + pairing."*
> — `worker.js:379-381`

- `mintTicket()` generates 24 random bytes; **only `sha256hex(token)` is stored**;
  the token is returned exactly once.
- `authorize()` hashes the presented bearer, checks `revoked=0`, updates
  `last_seen` via `ctx.waitUntil` (off the response path).
- **Fail-safe worth copying verbatim** (`worker.js:106-107`): if the tickets
  table doesn't exist, only the master works — *"the kit degrades to the old
  single-secret behavior, never locks out."*

**Relevance to HelmDeck now:** `settings.glance_token` is today a single shared
secret with no revocation and no per-device identity — the same design this
project outgrew. When a second glasses/companion surface appears, go to tickets;
don't mint a second shared token.

### 2.2 Device-code pairing
`worker.js:50-122`, `app/index.html:450-459`.

- 6 chars from `ABCDEFGHJKMNPQRSTUVWXYZ23456789` — *"confusable chars (I/O/0/1/L)
  omitted"* (`worker.js:50-57`). The owner reads this off a lens.
- The un-credentialed surface gets `{code, claim}`; **only the claim's SHA-256 is
  stored**; it polls every 2 s.
- Approve is **master-only** (403 for tickets).
- Hand-over **deletes the pairing row — exactly once** (`worker.js:94-96`).
- **10-minute expiry**, enforced on both poll and approve.

HelmDeck's existing pairing (`relay.pair_pending`, `relay_client.PAIR_TTL`) is
the same idea; the confusable-free alphabet and the single-use hand-over are the
details worth importing.

### 2.3 The anchor-device model
`android/.../DevicesActivity.kt:16-24`:

> *"The companion is the ANCHOR: it already holds the master credential
> (encrypted prefs), so from here you enroll every OTHER surface WITHOUT typing
> the password again … Each enrolled surface holds its OWN revocable ticket."*

The password is typed **once, ever**. Every later surface (glasses, browser) is
enrolled from the anchor with one tap, and revoked the same way. This is the
model for "add the glasses to HelmDeck" — the paired phone enrolls them.

### 2.4 Backend-driven config + a generic command row
`Config.kt:11-38`, `CompanionService.kt:60-91`.

Every toggle, interval and collection name comes from a `_config` row; a `_cmd`
row carries one-shot commands and **is consumed after execution** so it can't
re-fire. `android/README.md:62-63`: *"sideload once. After that it's controlled
entirely from the backend."*

If HelmDeck ever ships a companion APK, build it this way — a native app you
must rebuild to retune is a native app you will stop retuning.

### 2.5 Transport discipline
- **WS push primary, poll as a slow safety-net only.** `app/index.html:532-535`:
  *"WS push is the live path; this interval is only the SLOW SAFETY-NET… Default
  60s (was 10s — that was near-polling). **Factory rule: never ship a fast
  poll — rely on WS.**"*
- Push payload is literally the string `"changed"`; the client re-pulls
  (`worker.js:539`). Cheap, idempotent, no ordering problem.
- **Bearer rides the WS subprotocol** — `Sec-WebSocket-Protocol: bearer.<token>` —
  *"browsers can't set headers on a WebSocket"* (`worker.js:319-320`).
- Capped exponential backoff 1 s … 30 s on both ends.
- Video: newest-frame-only, in memory, never persisted, plus a `watching` signal
  so the producer stops ~8 s after nobody looks (`MainActivity.kt:276`) — the
  single biggest battery lever.

The "never ship a fast poll" rule is the same conclusion HelmDeck's glasses app
reached independently (no idle timers; refresh on foreground + navigation).

### 2.6 Robustness idioms
- `safe {}` around **every** peripheral call (`CompanionService.kt:104`) —
  one bad sensor must never kill the service.
- `START_STICKY`, `BootReceiver` on `BOOT_COMPLETED` **and**
  `MY_PACKAGE_REPLACED`.
- **Atomic writes everywhere.** `AGENTS.md:413` hard rule: *"Write local files
  atomically (temp + `os.replace`)"*.

---

## 3. Traps already paid for — do not re-buy

### 3.1 Device / platform
| Trap | Evidence | Rule |
|---|---|---|
| **The webview denies all capture** | `apps/mic-test/verdict.md:14-16`, owner-read **on-device 2026-07-13**: *"the MRBD webview denies all capture — 'Mic no, Sprache-to-text no, Kamera no'."* Meta's own docs agree for the official web path (`android-dat-research.md:37-42`: *"explicitly no mic, no camera"*). | Never plan a webapp feature on mic, speech-to-text or camera. |
| **`speechSynthesis` is ABSENT — but audio playback WORKS** | `app/index.html:804-805`, confirmed **on-device 2026-07-16**: *"The MRBD webview has **NO speechSynthesis** … but it **DOES play audio** (podcasts work)."* Corroborated by `verdict.md:17-21` (*"Ton yes"* at 960×540). | The lens cannot synthesise speech. It **can** play an audio file you hand it. This is why §4 renders speech server-side. |
| **No German TTS voice on the device** | `apps/navigation/findings.md:3-16` (2026-07-16): a `de-DE` Web Speech attempt was silent — *"The glasses very likely have no German TTS voice installed"*. Switched to `en-US`. | Never depend on a device voice, least of all a German one. |
| **Raw `<video>` never reaches the lens** | `verdict.md:19-21` — hardware overlay not composited; *"aber ich sehe nix"*. Canvas-mirror workaround shipped and confirmed. | If you ever render video, mirror frames to a 2D canvas. |
| **Sensors** | `verdict.md:22-24`, on-device: compass YES, tilt YES, devicemotion YES, **GPS NO**, ambient light NO. | GPS on the lens needs the phone. |
| **HFP and A2DP are mutually exclusive** | `android-dat-research.md:24-26`: *"while the mic is on, ALL glasses audio output drops to telephone quality"*; mic is 8 kHz mono HFP only, *"no wideband path exists"*. | Listening degrades speaking. Decisive for §4. |
| **DAT sessions are fragile by design** | `android-dat-research.md:27-33`: three states, *"the API never tells you WHY a transition happened, you must not restart while PAUSED"*, and system gestures / other apps / Bluetooth loss / **hinge-close** kill sessions with no auto-restart. | Any DAT work needs defensive session management from day one. |
| **Known SDK crash** | `android-dat-research.md:31-33` — intermittent crash on rapid captures during >1-min streams. Workaround: recycle the session. | |
| **Mock Device Kit does not cover Display glasses** | `android-dat-research.md:50-53`. | Display UI cannot be tested without the real device. |

### 3.2 The one that decides the architecture
The web path has **no documented background execution, no notification API, no
wake**. Meta's toolkit contains zero references to any of them; the only
lifecycle guidance is "stop your timers when not visible". Treat backgrounded
behaviour as **unsupported-because-unspecified**, not as available.

Consequence: *the glasses webapp can never tell the owner anything he isn't
already looking at.* Any proactive alert must originate off-device. That is the
whole reason §4 exists.

### 3.3 WhatsApp channel traps (all already fixed in the fork)
| Trap | Evidence |
|---|---|
| **Unprompted sends silently reach nobody** — the big one | `docs/whatsapp-bridge.md:210-220`, verified **2026-07-13**. Replies target `message.from` (the real `…@lid` JID), but unprompted sends derived their target from the whitelist phone number → a `@s.whatsapp.net` JID that reaches nobody on a LID account. *"The daemon consumes the event file, logs 'sent', nothing lands."* Fixed by learning the owner's real JID from each inbound message and persisting it to `~/.whatsapp-claude-agent/owner.jid`. **That file exists on this box, dated Jul 13.** If unprompted sends go quiet, check it. |
| Sender identity is a LID, not a phone number | `docs/whatsapp-bridge.md:184-190` — whitelist BOTH, comma-separated. Silent block otherwise. |
| **Re-delivery loop costs real money** | `:203-206` — reconnect flaps make Baileys replay history, *"each replay runs a full paid Claude session (one replay re-ran a whole Playwright script)"*. Fixed by notify-filter + inbound dedup + read receipts. Side effect: senders see blue ticks. |
| Two listeners race | `whatsapp-relay/SKILL.md:42-44`, **verified incident 2026-07-10**: *"two listeners raced on replies and overwrote each other's outbox files."* Check the heartbeat before claiming the role. |
| Watchdog ≠ config reload | `:197-199` — the watchdog restarts the daemon only when it exits; edit the `.cmd`, you must close the window. |
| One instance only | `:200-201` — two connections on one auth state kick each other off WhatsApp. |
| Auto-spawning a successor session is **blocked by the safety classifier** | `whatsapp-relay/SKILL.md:153-161`, verified 2026-07-10. *"Do NOT retry the spawn or try to route around it."* Relay events are marked NOT USER INPUT and cannot clear the bar. |
| Windows spawn | `:191-193` extensionless exe copies do NOT spawn (ENOENT); `:180` npm's bun is a `.cmd` shim MCP can't spawn. (HelmDeck already knows this class — see the `cmd`-shim `--resume` incident.) |
| Default Python UA trips Cloudflare 1010 | `tools/assist_watch.py:14`. |

### 3.4 Android traps (only if a companion APK happens)
- **Typed foreground services (Android 14).** Commit `a722c49` shrank the FGS
  type set to stop a crash when mic/camera weren't granted; commit `2edb739`
  reversed it on the owner's instruction, and it is now permanently annotated
  (`AndroidManifest.xml:58-60`): the service keeps the **full FGS type set** —
  *"don't reduce it"*. Either grant everything before Start or declare narrowly —
  pick one and write it down.
- **Null-Looper kills location callbacks.** `LocationRelay.kt:41-43`: `start()`
  runs on `Dispatchers.IO` (Looper-less), so callbacks must be requested on the
  main looper or `onLocationResult` never fires.
- **`/api/ws` vs `/ws` misroute** returned 401 on the WS handshake and *"looked
  like"* a wrong password (commit `a722c49`). A handshake carries no
  Authorization header.
- **Blocked popups return `null`, they don't throw** (`CHANGELOG.md:119-121`) —
  `window.open` needs a `null` check, not a `try`.
- Background location must be requested **separately, after** fine location
  (`MainActivity.kt:135-137`).

### 3.5 Dead ends — do not repeat
- The **rich627 whatsapp-claude-channel plugin**: send worked, inbound never
  arrived across two runtimes and three re-pairings. *"Don't reinstall."*
  (`docs/whatsapp-bridge.md:178-180`)
- **Side-tap / media-button wake** — `TriggerReceiver.kt:14-16`: *"HONEST: this
  is the unofficial, fragile route. Meta can change the gesture→key mapping any
  release."* Scheduled last, best-effort, and there is no evidence in the repo
  that it was ever confirmed on-device.
- `GlassesDat.kt` is **mock-only dead code** still wired into the service, so
  `_cmd photo/say` silently do nothing. `CameraCapture.kt` is an empty stub.
  Health Connect is declared as a dependency with zero code references.
- **`COMPANION.md` and `android/README.md` are stale and contradict shipped
  code** (they still say the DAT camera is blocked; commit `41774b1` confirmed it
  works). **Trust the code, not the docs, in that repo.**

### 3.6 On-device UX laws — *"the simulator lies"*
`docs/glasses-ux-requirements.md`, nine rules, all learned **on-device
2026-07-14**. The ones that bind HelmDeck:

- **One card fills the lens; you flip between cards, you don't scroll a wall**
  (`:12-16`). HelmDeck's `/glance` list scrolls ~378px on a 9-card board — worth
  re-judging against this rule on the real device, not in a headless viewport.
- *"The waveguide makes black transparent — only bright pixels reach the eye …
  **never dark fills**"* (`:19-21`), and cards must be **`#0a0a0f`–`#1C1E21`, not
  pure black, or they vanish** (`:72-90`). HelmDeck already does this.
- *"**Input lives on the overlay, not the page.** The webapp is **output +
  selection**; never design a flow that needs dictation or a photo captured *in*
  the page."* (`:29-32`) — `/glance` being read-only is exactly right.
- **Stale page + fresh data = phantom UI** — *"the worst bug class we hit
  today"* (`:29-32`). The webview keeps running the HTML it loaded at open while
  only data refreshes, so old JS painted phantom badges over new rows
  (`apps/instructor/findings.md`, 2026-07-14). Fix shipped there: a BUILD stamp
  plus `version.json`, polled, **self-reloading at the next idle moment — never
  mid-detail, never mid-audio**. HelmDeck's glasses app has no version check and
  is now long-lived across foreground/background cycles; this is a real, cheap
  follow-up.
- *"Never a silent wait or a blank screen"* (`:34-38`).
- **Glance-safe in public** — *"a bystander sees/hears something harmless"*
  (`:41-43`). Same rule as §4.4, applied to the display.
- **Register `deviceorientation` at PAGE LOAD** — *"the MRBD webview only
  delivers to a listener present from the start; a lazily-added one stayed
  silent"* (commit `6d3fdb1`). Applies to any sensor HelmDeck ever uses.
- **Suggestions-first input** (house rule 2026-07-21, `AGENTS.md:311-314`):
  *"typing is the escape hatch, never the door."*

### 3.7 Process laws worth importing
These are about how the work is run, not the glasses, and HelmDeck already
follows most of them — the two it doesn't are worth adopting:

- **A reported bug hardens the REPO, not just the app** (`AGENTS.md:333-340`):
  write the regression test first and **confirm it FAILS on current code** —
  *"that proves the test catches the real bug"* — then fix. HelmDeck's gate
  already runs the suite; this is the missing discipline around it.
- **Self-fix budget** (`AGENTS.md:90-93`): iterate fix → re-run **up to ~3
  times** before involving the owner, then stop with a blocker report naming the
  one question that unblocks. *"Never end a turn with a silent failure, and never
  ask before you've spent your own attempts."*
- **Front-load approvals** (`:116-120`): every decision in one message at the
  start. *"Mid-loop questions are the anti-pattern."*
- *"Hotfixes take the same quick gate pass as releases, no exceptions"*
  (2026-07-14, after a feature was hot-shipped without re-running the evaluator).

---

## 4. SETTLED: voice output goes over the WhatsApp channel

**Owner decision. Not per-device TTS, not a platform speech API.**

### 4.1 Why this is right (the evidence, not the preference)
1. The glasses webapp **cannot originate an alert** — no background execution, no
   notification API (§3.2). Anything proactive must come from off-device.
2. **`speechSynthesis` does not exist on the device.** Not "undocumented" —
   *measured*: `app/index.html:804-805`, confirmed on-device **2026-07-16**.
   Meta's toolkit independently contains no speech API at all: a
   case-insensitive sweep of the entire `meta-wearables-webapp` repo for
   `speechSynthesis|SpeechRecognition|tts|utterance|new Audio|AudioContext|
   <audio|Notification.|showNotification|wakeLock` returns **zero matches**, and
   the `mrbd-web-app-capable` tag is identification-only. A `de-DE` Web Speech
   attempt was silent on the glasses (`apps/navigation/findings.md:3-16`).
   **Speech must be rendered off-device and handed over as an audio file.**
3. Device TTS would need the DAT mobile path, which drags in the fragile session
   lifecycle (§3.1) — and **turning the mic on collapses all glasses audio to
   telephone quality** (HFP/A2DP exclusion).
4. A WhatsApp voice note plays as **ordinary A2DP media audio from the phone**.
   No DAT session, no SDK, no session lifecycle, no HFP downgrade, and the
   Ray-Bans already announce and read WhatsApp today.

**Therefore the audio path is independent of Meta SDK access entirely.** The
native SDK stays relevant only for *display* integration.

### 4.2 The rendering half — `glass-crud-harness/tools/voice_note.py`
Read the file. The shape to mirror:

| Decision | Value | Why |
|---|---|---|
| Engine | `edge_tts` (Microsoft Neural Voices) | free, no API key, no account |
| Default voice | `en-US-AndrewMultilingualNeural` | *"The multilingual default handles mixed German/English naturally"* (`voice_note.py:11`) — HelmDeck's card titles are exactly that mix |
| Rate | `+8%` | `voice_note.py:31` |
| Transcode | `imageio_ffmpeg` → `libopus`, `-b:a 32k`, `-ac 1`, `-application voip` | *"WhatsApp voice notes are ogg/opus mono; 32k is plenty for speech"* (`:35`) |
| Output | `.ogg`, abs path printed on the last line | that path goes in the marker |

**HelmDeck feasibility, checked on this machine:**
- `imageio-ffmpeg` is **already** in `daemon/requirements.txt` and installed
  (0.6.0). Half the pipeline is a HelmDeck dependency today.
- `edge_tts` is **not installed** — it is the one new dependency.
- HelmDeck has **no TTS and no WhatsApp code at all** today. Green field.

### 4.3 The delivery half — `outbox/events/` ("speak first")
Protocol from `.claude/skills/whatsapp-relay/SKILL.md:31-38`, implementation
verified in the fork at `whatsapp-claude-agent/src/index.ts:245-320`:

> *"the daemon polls this dir every 2 s and sends each file's content to the
> owner as an UNPROMPTED WhatsApp message — no inbound message or reply slot
> needed."* (added **2026-07-11**)

Ground truth from the implementation:
- `EVENTS_POLL_MS = 2000` (`index.ts:251`).
- Files are `outbox/events/*.txt`, read **sorted** — prefix names (`001-…`) to
  control order.
- **Write atomically**: `.tmp` → rename. The daemon must never read a half-written
  file.
- **Consume-before-send**: the daemon `unlinkSync`s the file *before* sending —
  *"a send retry must not double-send"* (`index.ts:275`). So a failed send does
  **not** retry from the file; it lands in `outbox/events-failed/<name>` with the
  error appended. Success appends to `outbox/events-sent.log`.
- Targets are the learned `ownerJid` first, then the whitelist phone JID (§3.3).
- `[[img:path|caption]]` and `[[voice:path]]` markers work here too.

### 4.4 The register — this is a rule, not a style preference
`SKILL.md:91-101` (owner decision 2026-07-10) and `:106-112` (owner rule
2026-07-21):

- *"the owner is usually on voice-only glasses, often around other people; the
  register is a normal phone call."* Short plain sentences. **No lists, no
  numbered options, no emojis, no markdown.**
- **Glance-safe**: *"a bystander seeing the screen should read harmless small
  talk."*
- **One message per real transition, never a progress ticker** (`SKILL.md:38`).
- Long content (**> ~350 chars or > 4 sentences**) gets a voice note; keep the
  TEXT short (lead + essentials) and let the voice carry the detail.
- **Keep messages under ~900 characters** (`whatsapp-loop/SKILL.md:28`).
- **Never paste code** — *"WhatsApp has no code formatting and read-aloud would
  recite it"* (`whatsapp-loop/SKILL.md:22-27`). A gate report is exactly this
  hazard: send a one-line summary, not a stack trace. (glass-crud sends code as
  a snippet PNG; HelmDeck's equivalent is "the detail lives in the card".)
- *"First sentence = the decision needed, spoken-style — that's what the glasses
  read first."* (`whatsapp-loop/SKILL.md:21`)
- If HelmDeck ever accepts replies: only phrases **unambiguous in speech** count
  as confirmation. *"'Passt schon' is deliberately excluded — in German it
  usually means 'forget it'."* (`docs/whatsapp-bridge.md:166-168`)

### 4.5 What this means concretely for HelmDeck
The seam already exists and is already correctly gated:

```
sessions.owner_blockers()          # WHO is blocked (shipped this card)
        ↓
notify.card_event(track, reason)   # daemon/notify.py:162 - the ONE transition point
        ↓  should_push(): presence policy + dedup + NEVER_PUSH
        ├── push_fcm(...)                    # today: the phone
        └── voice event  (NEW)               # → outbox/events/NNN-<card>.txt
                render via the voice_note.py pattern → [[voice:<ogg>]]
```

Design notes that fall straight out of the sources:
- Reuse `should_push` — presence gating, dedup and `NEVER_PUSH` (background,
  error) are exactly right for a channel that interrupts a human by *speaking*.
  A voice ticker would be far worse than a push ticker.
- One event per transition, mapped from the `blocker()` reason vocabulary
  (`gate`/`conflict`/`failed`/`question`/`review`/`delivered`).
- Off by default, like `glance_token` and `relay.url`: empty config = channel OFF.
- Never put card *content* in the text half beyond a glance-safe lead — §4.4 is a
  privacy rule as much as a style one.

### 4.6 Honest gaps before this can be called proven
1. **No programmatic producer has ever existed.** Nothing in glass-crud-harness
   writes `outbox/events/` — the only producer was a human-driven Claude session
   following the skill. HelmDeck's daemon would be the **first automated
   writer**.
2. On this box `outbox/events/` is empty and there is **no `events-sent.log`**, so
   I can confirm the channel is *wired* and the JID fix landed, but I cannot
   evidence a delivered event from local logs. **Verify end-to-end delivery once**
   rather than inheriting it as proven.
3. The bridge is a **patched fork run from source with bun**, needing a second
   WhatsApp number, and `docs/whatsapp-bridge.md:15-17` is blunt about it:
   *"this is a tinkerer-grade setup, not a product."* Budget accordingly; the
   number alone can take 2–4 Werktage.
4. The bridge daemon must be running for any of this to land. HelmDeck already
   learned the equivalent lesson once (`desktop/tray.py` supervisor).
5. **The fork patch file is STALE.** `docs/whatsapp-bridge.fork.patch` is dated
   2026-07-10 and contains **neither** the `outbox/events/` speak-first feature
   (added 2026-07-11) **nor** the `[[voice:]]` marker (2026-07-21, commit
   `c88694e`). Re-applying it to a fresh clone yields a daemon **without the two
   features this whole decision rests on.** Diff against the live fork at
   `~/Downloads/whatsapp-claude-agent`, not against the patch.

### 4.7 The other voice path — for when the owner IS looking
Complementary, not competing. glass-crud also shipped an **in-app** voice path
for its navigation app, and it solves a different problem: speaking *while the
webapp is open*.

`worker/src/worker.js:194-208` — a same-origin `/api/tts?q=<text>&tl=en` proxy
returning mp3, because (verbatim):

> *"The MRBD webview can't do speechSynthesis, but plays audio; and
> translate_tts blocks browser cross-origin requests (Referer check) while a
> server fetch (no Referer) works — so we proxy it here, same-origin,
> edge-cached so a repeated line is instant. Short lines only."*

Three non-obvious details that cost time there:
- The route sits **before auth** — *"an `<audio>` can't send the bearer header"*
  (`worker.js:341-344`). Any HelmDeck equivalent has the same problem and must
  be solved by a URL-scoped token, not a header.
- **Audio must be unlocked inside a user gesture**: a `volume:0` play of a tiny
  clip during the open tap, so later non-gesture announcements are allowed
  (`app/index.html:809-813`).
- Cadence was tuned by complaint, twice: announce **once** per event, *"no
  periodic repeat — owner 2026-07-17 found re-saying every push too chatty"*,
  and delay the first announcement **~1.8 s** after open because an instant one
  *overlapped the app coming up* (`app/index.html:827-828`, `:965-971`).

For HelmDeck this is optional and clearly second: `/glance` is read when the
owner already chose to look, so text is usually enough. Reach for it only if a
glance screen needs to speak without a tap.

### 4.8 One caveat on edge-tts, from the same project
edge-tts is right for **utility speech** (a blocker summary) and was explicitly
rejected for **content**: `apps/daily-ritual/findings.md` (2026-07-09) records
*"'2 min of only robo voice' — System.Speech TTS too robotic"*, replaced with
real human LibriVox readings, and later *"Remove pre-seeded robotic/synthetic
voice, keep only real human readings"*. HelmDeck's use is squarely utility, so
this is a boundary marker, not a blocker: don't grow the voice channel into
something the owner is meant to enjoy listening to.

---

## 5. SDK access — smaller than feared, but the sources disagree

**Read this section carefully; two sources in the same repo do not say the same
thing, and the difference decides how much work the access step is.**

From `docs/android-dat-research.md` (deep-research run **2026-07-13/14**, 18
sources, 25 claims adversarially verified, 22 confirmed 3-0):

- **Package access is just a token.** DAT v0.8.0 (2026-06-25), Kotlin,
  distributed **via GitHub Packages — needs a GitHub PAT with `read:packages`**
  (`:17-19`). glass-crud-harness consumes it for real:
  `com.meta.wearable:mwdat-core:0.8.0` + `mwdat-camera:0.8.0`
  (`android/app/build.gradle.kts:48-49`), credentials from `GITHUB_ACTOR` /
  `GITHUB_TOKEN` so no token is committed.

**But** `android/README.md:13-18` says the glasses camera/mic *"need you
**accepted into Meta's developer preview (a form)**"* — a device-access
permission, distinct from package access. Both can be true: a PAT gets you the
artifact, a form gets the device to honour it. The repo also shows the cost of
that ambiguity — commit `8d6bea7` (2026-07-21) records a pure-Kotlin change that
**could not be built at all** because the DAT dependency lines demand a token at
*dependency-resolution* time: *"APK build blocked on the Meta DAT `read:packages`
token — pre-existing."*

**So the access check has two questions, not one:** (a) do we have a PAT that
resolves the packages, and (b) are we admitted to the device preview? Answer
both before estimating any companion work.
- **Developer mode runs unpublished apps on your own glasses with no review** —
  Meta AI app → Devices → **tap App version 5×** (`:44-46`). *"exactly the
  private-use case."*
- **No publishing during preview.** Sharing = password-protected URLs (web) or
  release channels ≤ 100 testers (mobile).
- **Germany is on the supported-country list** (`:47-49`).
- Nothing in Meta's own toolkit repo mentions a waitlist, partner programme or
  approval step at all — and it says *"No SDK required"* three times for the web
  path's sensor/storage APIs.

**So the SDK-access check is not "are we accepted?" but "do we have a PAT and is
Developer mode on?"** Recheck the version first — two releases in two months, and
the research itself says *"recheck before building"*.

What the SDK would buy that we cannot otherwise have: pushing text/images/lists/
buttons/video **to the lens** from a phone app, and the glasses **mic**. What it
does not need to buy: voice output (§4).

---

## 6. Meta toolkit — what is directly usable

The toolkit is **agent skills + guidelines**, not a runtime library. There is no
SDK, no build system, no tests and no lint config in it.

### 6.1 Install and caveats
`install-skills.sh claude` drops all 9 skills into **`./.claude/skills/`** and the
two reference docs into `./.claude/references/` — project-local, in the cwd. Two
traps:
- It **re-downloads from GitHub** even if you already cloned.
- Every SKILL.md's "Required reading" points at `${CLAUDE_PLUGIN_ROOT}/references/…`,
  which **does not resolve** under the project-local install. Only the
  marketplace/plugin install path resolves correctly.
- The repo's own `AGENTS.md` / `.github/copilot-instructions.md` are **stale
  flattened copies that contradict `plugins/`** (they lack the favicon/manifest
  step and get the passcode default backwards). **Trust `plugins/`.** The
  README's skill table is also wrong (lists `add-screen`/`add-button`/`add-sensors`,
  which don't exist).

### 6.2 The two files worth reading in full
- `plugins/meta-wearables-webapp/references/display-guidelines.md` (209 lines) —
  the real rules. See §6.4.
- `plugins/meta-wearables-webapp/references/performance-guidelines.md` (67 lines).

### 6.3 Highest-leverage single fact
The deep link that puts a webapp on the glasses
(`skills/test-on-device/SKILL.md:157`):

```
fb-viewapp://web_app_deep_link?appName=<name>&appUrl=<url-encoded https url>
```

Rendered as a QR and scanned **with the phone**. `skills/qr-code/scripts/qr_generator.py`
(879 lines, **stdlib-only**) generates it with no dependencies —
glass-crud-harness already uses exactly this (`tools/qr.py:32-35`), including the
good hygiene of masking the secret in console output and suppressing the ASCII QR
when a secret is present.

Requirements: a **public HTTPS URL** (`README.md:80`) and Developer mode. The
toolkit is emphatic that `python3 -m http.server` / localhost / LAN IP is **not**
the on-device path (`test-on-device/SKILL.md:69-70`) — fine for desktop smoke
tests only. If hosting on Vercel, the non-obvious step is disabling SSO
protection, *"glasses browser can't log in"* (`:138`).

### 6.4 Platform rules HelmDeck must hold to
| Rule | Cite |
|---|---|
| `<meta name="mrbd-web-app-capable" content="yes">` — keep `content="yes"` verbatim | `create-webapp/SKILL.md:82` |
| 600×600 **dp**. Additive waveguide: `#000000` = fully transparent, `#FFFFFF` = max brightness | DG:16-34 |
| `#000000` is correct for `body`/`html` but **never** for surfaces that must be visible — those need `#0a0a0f`–`#1C1E21` | DG:27-34 |
| Safe margin 8dp (24dp full-screen); header 24dp from top, 64dp tall; **button height 88dp fixed** | DG:65-84 |
| Type scale H1 28 / H2 22 / Body1 16 / Body2 14 / Meta1 12 / Meta2 10. **No font below 14dp for interactive elements; min tap target 88dp** | DG:86-97 |
| Contrast 4.5:1 body, 3:1 large. **Never use colour as the sole indicator** | DG:54-63 |
| Focus: **only the container scales** — `scale(calc(1 - 8/88))`, content stays 1x at opacity 0.8→1.0; on 475ms `cubic-bezier(0.6,0,0.4,1)`, off 625ms | DG:109-130 |
| **Scrims are required on any scrolling container** (SM 32 / MD 64 / LG 88dp gradients) | DG:142-163 |
| Toasts: 24dp from **top**, centred, max-width 536dp, radius 24, auto-dismiss 3.5s + 300ms/word, max 8s. *"Toasts are for feedback only."* | DG:176-186 |
| No external fonts, no icon fonts, no network-loaded SVG icon libraries; inline <2KB as data URIs | PG:24-28, DG:197-199 |
| Favicon **PNG only, no SVG**, larger than 52×52 (default 128×128), referenced from HTML *and* webmanifest | `create-webapp/SKILL.md:100-103` |
| <3s load on 4G, <500KB JS gzipped, 60fps, <128MB memory, **<10 network requests on load** | PG:5-13 |
| *"Avoid continuous `setInterval`/`requestAnimationFrame` loops. Start them on demand, stop them when not visible."* Prefer CSS transitions (GPU) | PG:15-22 |
| Interaction model: **no touchscreen, no mouse, no keyboard, no cursor** — focus jumps. Arrows/Enter/Escape. *"Keep navigation shallow — ideally 3 steps or fewer."* | DG:99-107 |

**Not documented anywhere**: any CSP, autoplay policy, service-worker
prohibition, or permitted-API allowlist. Service workers and WebSockets are
positively documented as available. Everything else is **unknown, not permitted** —
the authoritative list, if one exists, is behind
`https://wearables.developer.meta.com/llms.txt?full=true` (`tool-config.json:3`),
which is not vendored.

### 6.5 HelmDeck `glasses/` conformance — measured, not assumed
Already conformant: `mrbd-web-app-capable` present; 600×600 viewport; `body`
`#000` with `#1C1E21` surfaces; 8dp safe margin; header 24dp/64dp; system font
stack; H1 28px; three files and no dependencies (well under the request/JS
budget); no idle timers. It also ships a `prefers-reduced-motion` block, which
the toolkit doesn't even ask for.

Four real deltas:

| # | Delta | Where |
|---|---|---|
| 1 | **Tap targets below the 88dp minimum**: `.back-btn` 56px, `.field` 48px, `.list-item` ≈66px. Only `.nav-item` (88px) complies. | `glasses/styles.css:35,99,61` |
| 2 | **No scrim on the scrolling list** — and it genuinely scrolls (measured 378px of overflow on a 9-card board). | `.content`, `styles.css:39` |
| 3 | **Focus scales the wrong way and far too fast**: `scale(1.03)` up over 120ms, vs the spec's *shrink* to `calc(1 - 8/88)` over 475ms with content held at 1x. | `styles.css:118-122` |
| 4 | **No favicon and no `manifest.webmanifest`.** | `glasses/index.html` |

None of these is a correctness bug; all four are cheap. They are the natural
content of a follow-up card, and they should be judged on-device, not only in a
headless 600×600 viewport.

### 6.6 Worth lifting, file by file
- `skills/create-webapp/templates/styles.css:1-38` — CSS reset + `:root` token
  block + the exact system font stack. (Set `--bg-primary` to `#000000`.)
- `skills/create-webapp/templates/app.js:57-92` + `:290-330` — focus-nav helper
  with wrap-around, `scrollIntoView({block:'nearest'})`, and a keydown handler
  that correctly guards `INPUT`/`TEXTAREA`. The most reusable artifact in the repo.
- `display-guidelines.md:121-130` — the authoritative interaction-state snippet
  (the shipped template does *not* implement it).
- `display-guidelines.md:154-163` — scrim CSS (delta #2).
- `performance-guidelines.md:34-48` — 14-line cache-first service worker.
- `create-webapp/SKILL.md:128-139` — the webmanifest JSON (delta #4).
- `skills/qr-code/scripts/qr_generator.py` — stdlib-only QR (§6.3).

**Do not adopt**: the toolkit's `AGENTS.md`/copilot instructions (stale);
`examples/snake/styles.css`'s `--bg-primary: #0a0a0f` (violates the additive-display
rule); the template's `min-height: 44px` (violates the 88dp minimum). The
toolkit contradicts itself in those three places — the guidelines win.

---

## 7. What this means for the named follow-up steps

| Step | Verdict from the sources |
|---|---|
| **SDK access check** | Two questions, not one: (a) a GitHub PAT with `read:packages` that resolves `com.meta.wearable:mwdat-*` — without it the build fails at dependency resolution even for unrelated changes; (b) admission to Meta's developer preview for *device* access, which one source calls a form. Then Developer mode (tap App version 5×). Confirm the current DAT version first — v0.8.0 on 2026-06-25 and moving fast. Germany is supported. §5 |
| **Proactive notification** | Cannot come from the webapp — no background execution, no notification API (§3.2). It must originate in the daemon. The proven channel is `outbox/events/` (2 s poll, atomic write, consume-before-send), and the JID trap is the thing that will silently eat it. §4.3, §3.3 |
| **Voice reading** | SETTLED: server-side edge-tts → ogg/opus mono 32k → `[[voice:…]]` over WhatsApp. Not device TTS — the toolkit has none, and the SDK path would drag in the HFP audio downgrade. Independent of SDK access. §4 |
| **Companion app** | Only if something needs the glasses' *mic* or a *native lens push*. It is a sensing layer, never a renderer: *"the native app never draws a pixel on the glasses"* (`native-companion-plan.md:57`). If built: backend-driven config, `safe {}` everywhere, full FGS type set, and the Android-14 typed-FGS decision written down. §2.4, §3.4 |
| **Anything on the lens** | Gate it on `AGENTS.md:263-270` first: is the *consuming* moment hands-busy / eyes-up? If not, it is a phone feature. §1 |

---

## 8. Reading order for the next card

1. `glass-crud-harness/apps/mic-test/verdict.md` — 40 lines, the on-device truth.
2. `glass-crud-harness/docs/glasses-ux-requirements.md` — the nine on-device UX laws.
3. `glass-crud-harness/docs/android-dat-research.md` — 69 lines, the SDK reality.
4. `glass-crud-harness/.claude/skills/whatsapp-relay/SKILL.md` — the protocol.
5. `glass-crud-harness/tools/voice_note.py` — 60 lines, the whole voice recipe.
6. `whatsapp-claude-agent/src/index.ts:245-320` — how the daemon really consumes
   events. **Read the live fork, not `docs/whatsapp-bridge.fork.patch`** (§4.6.5).
7. `meta-wearables-webapp/plugins/meta-wearables-webapp/references/display-guidelines.md`.
8. `glass-crud-harness/docs/whatsapp-bridge.md` — the troubleshooting list *is*
   the trap register.

Then, and only then, write code.

---

## 9. Provenance

Written 2026-08-16 from a first-hand read of both projects plus the live bridge
fork. Where this document quotes, the quote is from the file cited; where it
states a HelmDeck fact (dependency present, seam location, CSS measurement), it
was checked in this worktree, not assumed.

Two honesty markers worth keeping in mind when reading:
- **glass-crud-harness's own docs are known-stale in places** — `COMPANION.md`
  and `android/README.md` contradict shipped code, and the fork patch predates
  the two features §4 depends on. When that repo's prose and its code disagree,
  **the code wins**.
- **Meta's platform side moves fast** — two SDK releases in two months, and the
  toolkit repo contradicts its own guidelines in three places. Re-verify §5 and
  §6 against the source before betting a card on them.

---

## 10. SDK access check — re-verified 2026-08-16, Go/No-Go for the companion-app step

§5 warned to recheck before building. This re-checks it against the live
`developer.meta.com/wearables` docs and the `facebook/meta-wearables-dat-android`
README (not the secondary sources §5 was built from), one month later.

### 10.1 Confirmed unchanged
- **The PAT is still the real gate on the artifact.** Straight from the SDK
  repo's own README: a GitHub PAT (classic) with `read:packages` is required to
  resolve `com.meta.wearable:mwdat-core` from GitHub Packages, supplied via
  `GITHUB_TOKEN` or `local.properties`. Anyone with a GitHub account can mint
  one — there is no separate approval step gating the token itself.
- **Developer Mode activation is unchanged**: Meta AI app → Settings → App Info
  → tap the App version number 5×.
- **Publishing is still fully closed in preview.** Meta's own wording:
  *"only select partners will be able to publish their integrations to the
  general public"* and *"Publishing will be available to limited audiences in
  the preview phase."* Their target is *"opening up publishing to general
  availability in 2026"* — no month or quarter given, so this is not close to
  lifting on any known date.
- Sharing during preview stays at web-app-via-URL or DAT-app-via-release-channel
  to testers inside your own org. No numeric tester cap could be re-confirmed
  from a live source this pass — treat the earlier "≤100 testers" figure as
  unverified, not re-stated as fact.

### 10.2 Changed since the 2026-07-13 research
- **DAT version moved 0.8.0 → 0.9.0.** Confirms the "moves fast" warning —
  anything actually built against it needs a fresh version pin.
- **No extra approval gate found beyond the PAT.** The old Android README's
  *"accepted into Meta's developer preview (a form)"* language does not
  reappear on the current live docs; account creation on the Developer Center
  now reads as being for updates/bug-reports/org-registration, not as an
  admission gate. This slightly de-risks access versus §5's two-question
  framing — though the account still has to exist first.
- Supported-country list wasn't itemized on the pages checked this pass;
  Germany's support still rests on the 2026-07-13 finding, not freshly
  re-confirmed today.

### 10.3 Go/No-Go — companion-app step (§7 row 4)
**No-Go, for now.**
1. Neither HelmDeck use case that would actually need the SDK — a native push
   to the lens, or the glasses' mic — has a live requirement today. Voice
   output is SETTLED without it (§4); `/glance` already covers the eyes-up case
   as a plain webapp (§1, §6.5), no SDK needed.
2. Publishing stays partner-only with no firm 2026 date. Even a built companion
   app could only ever run on the owner's own paired glasses (Developer Mode) —
   fine for personal use, but there's no path to anything beyond that this
   year.
3. Access itself is cheap exactly when it's needed (a Meta developer account +
   a GitHub PAT + one Developer Mode toggle, all self-serve) — no reason to
   front-load account setup for a feature with no driving use case yet.

**Decision:** leave SDK access unset up until a concrete feature demands the
mic or a native lens push. This card's output is the checklist below, ready to
execute in under an hour whenever that trigger appears — not a completed
account.

### 10.4 Account-setup checklist — status as of 2026-08-16
1. ~~Create/sign in to a Meta developer account~~ **Already done.** Turned out
   to predate this card entirely — see §10.5.
2. ~~Register the org on the Wearables Developer Center~~ **Already done** —
   org "Tien Duy Vo Team" exists (`devcenter/1317266500388880/`).
3. Generate a GitHub PAT (classic) with `read:packages`; store via
   `GITHUB_TOKEN` or `local.properties` — never commit it. **Still open** —
   not dispensed anywhere in the Dev Center UI; it's a GitHub-side token,
   unrelated to the Meta login.
4. On the owner's phone: Meta AI app → Settings → App Info → tap App version
   ×5 → confirm Developer Mode. **Not checked this pass.**
5. Re-check the DAT version pin before any build — confirmed **0.9.0**,
   tagged "2 weeks ago" (relative to 2026-08-16) on
   `github.com/facebook/meta-wearables-dat-ios`.

Step 3 is the only one that was never actually blocked on the owner's Meta
identity — a GitHub PAT needs only a GitHub account. It simply has no reason
to exist yet per the §10.3 No-Go.

### 10.5 Live walkthrough, 2026-08-16 — the account already existed
Driven live in the owner's persistent HelmDeck Chrome (CDP :9222,
`deploy/meta_wearables_guide.py`) with the owner completing the actual
work.meta.com login himself (email + whatever 2FA it asked — a Meta *Work*
account, not a plain Facebook login; the sign-in screen's own copy is "Use an
account given to you by your organization").

Findings, all read-only — nothing was configured or saved:
- The org and Dev Center account were **already registered**, dated before
  this card existed. Nobody re-ran the signup flow today; login alone landed
  straight on `Projects`.
- One project already exists: **"Claudia" ("AI everything app"), last edited
  2026-07-15** — a full month before the glasses-reference research started.
  **Its relationship to HelmDeck's glasses work is unknown — left untouched,
  not renamed, not repurposed, not deleted.** Don't assume it's HelmDeck's;
  don't assume it isn't.
- The project is a bare skeleton: iOS/Android **Team ID, Bundle ID and
  Universal Link are all empty**; **Camera access** permission is toggled on
  with rationale text *"generic access to build everything that needs cam
  access"*; **zero versions**, so `Distribute` refuses to let you create one
  until app details are filled in; `Required actions` shows none outstanding.
  Reads as: someone flipped the account on once, got as far as one permission
  toggle, and stopped — never carried to an actual build.
- **"Download SDK" in the Dev Center just links out to the public GitHub repo**
  (`github.com/facebook/meta-wearables-dat-ios`, unauthenticated view) — it is
  not a source of the PAT and doesn't hand out a token. Confirms §10.1/§10.2:
  the PAT is a GitHub-side artifact the Dev Center plays no part in issuing.

Net effect on §10.3: the Go/No-Go verdict is **unchanged** — this discovery
is about *existing, unfinished* access, not a new use case. It does mean step
3 (the PAT) is the only remaining item if a real trigger ever shows up;
account + org no longer need to be created.

Nothing here required a code change. The only files this card touched are
this doc and the co-pilot script (`deploy/meta_wearables_guide.py`) used to
drive the walkthrough.

---


## 11. GLASS MODE — the lens decides, and the companion app is scrapped

**Owner decision, 2026-08-16, superseding everything above about a companion:**
> *"Where did idea with ticket comes from .. scrap it. I need a glass system that
> only interact with board agent in glass mode. Should be conversation to
> understand where things are, plan and make decisions."*

### 11.1 Where the ticket idea came from, and why it is gone
From §2.1 of THIS document — *"when a second glasses/companion surface appears,
go to tickets; don't mint a second shared token."* That advice is sound for the
thing it was written about (a fleet of enrolled devices), and it was applied to
a native companion sensing app that the owner does not want. No companion app,
no fleet, no second surface ⇒ **no tickets**. `daemon/companion.py`, its tests
and its five routes were deleted in the same card that added them.

⚠ **§2.1's last paragraph is now stale as guidance.** Read it as history. If a
future card is tempted by it again, the question to ask first is not "which auth
model" but "is there actually a second device?" — here there was not.

### 11.2 What glass mode is
The lens talks to ONE thing: the board agent. Three moves, no more:

| | | |
|---|---|---|
| **Where things are** | `/glance` — every card blocked on the owner, worst news first | already existed |
| **Make decisions** | the worker's pending question, rendered as tappable options | **new** |
| **Plan** | the decision IS the plan step — the worker resumes with it | via the existing session |

The critical constraint, measured on-device and unchanged (§3.1/§3.2): the lens
has **no mic, no camera, no dictation, no keyboard**. So a "conversation" here
can only be *agent proposes → owner selects*. That is exactly the shape of the
ASK protocol HelmDeck already runs on every card (`daemon/ask.py`), which is why
glass mode needed no new conversation engine — only a way to see the question
and send back a pick.

### 11.3 How it is wired (and what was deliberately NOT built)
- `GET /glance` now carries `question` on any asking card: the prompt, the
  header, and the options, trimmed for the lens (`_glance_question`). Non-asking
  cards carry `question: null`.
- `POST /glance/answer` is the ONE write. It reuses `sessions.answer_question` —
  the same function the phone's `/tracks/<id>/answer` calls — so there is no
  second answering mechanism to drift out of sync. Verified: a lens pick writes
  the identical audit line, `FRAGE beantwortet: <header> -> <label>`.
- Four bounds, because `glance_token` is a single SHARED secret and this
  endpoint runs an agent turn:
  1. **off unless `settings.glance_decide` is true** — a second switch on
     purpose, so an existing read-only glance token does not silently become one
     that can move the board;
  2. **free text refused** — `ask.validate_answers` permits it (the phone's
     "Other" escape hatch), and glass mode explicitly rejects it: a shared token
     must never inject prose into a worker's next prompt. Verified with a
     literal injection attempt → 400;
  3. **`request_id` must match the card's current question** — a lens showing a
     stale screen cannot answer something the card moved past;
  4. it can only pick options **the worker itself wrote**.
- NOT built: no ticket registry, no companion APK, no device fleet, no DAT, no
  mic/camera. Glass mode needs **no GitHub PAT and no SDK** — it is a plain
  webapp against the daemon, which is why it works today.

### 11.4 Verified, not assumed
Against a live daemon on 3468 with a real question produced by the shipped
`ask.parse`, and the real UI driven by Playwright at the lens's 600×600:
- board + question render; the gate card correctly shows `question: null`;
- every bound rejects: bad token 403, `glance_decide` off 403, stale
  `request_id` 409, injection attempt 400, non-asking card 409;
- the glance token still 401s on `/tracks` and `/settings`;
- **the full loop**: D-pad to the 6th option → Enter → `Answered ✓` → question
  consumed → audit line written.

⚠ **The six-option layout, measured rather than guessed.** With the protocol's
maximum of 6 options the last one starts below the 600px fold. It is NOT
unreachable — this app is D-pad/EMG driven ("no touch", `app.js:3`) and focus
scrolls every option to `fullyVisible`, confirmed for all six. The residual risk
was only that the owner could not *know* a 6th choice existed, so the header now
states the option count. Do not "fix" this by clamping to 4 options — that would
silently drop a choice the worker offered.
