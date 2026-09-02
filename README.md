# HelmDeck

**A task board where the tickets get done.** AI agents run on your own Windows PC and work through your Kanban board. Your phone is the cockpit: create tasks with photos and attachments, watch the agent work live, answer its questions in chat, approve or reject results. A PM agent keeps tasks, budgets and timelines on track.

Never sit in front of a PC again unless you want to.

## Privacy

The app talks only to **your own machine**, over LAN or a zero-knowledge relay. Everything, push notifications included, is end-to-end encrypted (Curve25519 / XSalsa20-Poly1305).

- No account
- No ads
- No analytics
- Your data never touches our servers, because there are none

[Privacy policy](https://relay.helmdeck.de/privacy)

## Downloads

Grab both parts from the [**Releases**](../../releases) page:

| File | What it is |
|---|---|
| `HelmDeck-Setup-*-x64.exe` | Windows desktop app (the daemon your agents run on) |
| `HelmDeck-*-arm64.dmg` / `HelmDeck-*-x64.dmg` | macOS desktop app (signed & notarized) |
| `HelmDeck-*.apk` | Android app, direct APK (or install it from [Google Play](https://play.google.com/store/apps/details?id=app.helmdeck)) |

### Android

Preferred: install [**HelmDeck on Google Play**](https://play.google.com/store/apps/details?id=app.helmdeck) – it's publicly available and updates itself. The APK here is for sideloading if you'd rather not use Play.

**No Windows PC?** Open the app unpaired and tap **"Try it without your own computer"**. You get a fully interactive sample board: move cards, steer agents, file requests. Nothing leaves your device.

### Windows

1. Download and run `HelmDeck-Setup-*-x64.exe`
2. **SmartScreen note:** the installer is not code-signed yet, so Windows will warn you. Click *More info → Run anyway*. Verify your download against the SHA-256 checksums attached to the release if you want to be sure.
3. Start HelmDeck, go to *Settings → Mobile app → Pair phone*, scan the QR with the Android app. Takes about 2 minutes.

### macOS

1. Download `HelmDeck-*-arm64.dmg` (Apple Silicon) or `HelmDeck-*-x64.dmg` (Intel), open it, and drag HelmDeck to Applications.
2. Signed with a Developer ID certificate and notarized by Apple, so it opens with no Gatekeeper warning.
3. Start HelmDeck, go to *Settings → Mobile app → Pair phone*, scan the QR with the Android app. Updates apply automatically in the background.

## Feedback

The closed test is over – HelmDeck is live on Google Play:
https://play.google.com/store/apps/details?id=app.helmdeck

Feedback is very welcome, here in the issues or as a Play review.

## Development

The source lives in this repo. Start with [`ARCHITECTURE.md`](ARCHITECTURE.md)
(the harness is code, policy is data), [`HARNESS.md`](HARNESS.md) (where that
code/data line actually falls: how a spawn resolves, how to add a policy knob)
and [`DEPLOY.md`](DEPLOY.md) (how a change reaches a phone, a desktop or a Mac).
CI builds the macOS app on a macOS runner — `.github/workflows/desktop-mac.yml`.
