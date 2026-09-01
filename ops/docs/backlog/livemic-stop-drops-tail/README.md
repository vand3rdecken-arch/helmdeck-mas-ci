# Closing voice mode mid-sentence silently throws away the last thing you said

**Filed 2026-09-01, from a Paseo 0.7.0 changelog parity check.** Paseo shipped
two dictation fixes in 0.7.0 (#4065 "finalize recordings with abandoned
partials", #3968 "wait for in-flight dictation commits before finishing").
Checking HelmDeck's own live-mic pipeline (`ops/docs/paseo-adoption-plan.md`
precedent - always verify against real source, not just the changelog text)
found HelmDeck has the WORSE version of the same bug class: Paseo's partial
arrived late; HelmDeck's tail is never transcribed at all.

## The bug

`surfaces/app/modules/livemic/android/src/main/java/app/helmdeck/livemic/LiveMicModule.kt`:

- `stop()` (line 80-83) just sets `running = false` and returns immediately -
  synchronous, fire-and-forget, no wait for the capture thread.
- The capture loop's exit condition is checked at the TOP of each iteration
  (`while (running)`, line 280). If `running` flips to false while an
  utterance is mid-flight (`utterance != null`, i.e. the user was still
  talking), the loop breaks straight to cleanup (line 313-316) WITHOUT ever
  calling `finish()` (line 268). `finish()` is the only place that emits
  `onSegment` - so that in-progress utterance's audio is discarded, never
  base64'd, never sent to JS, never transcribed. Not late - lost.
- JS calls `mic.stop()` on every voice-mode close/teardown path
  (`surfaces/app/src/ui/voice_mode.tsx:463` unmount cleanup, `:508` the
  live-pipeline effect's cleanup) with no signal back for "was anything still
  being said" - `stop()` returns a plain `Boolean`, not a promise the JS side
  awaits before treating the session as finished.
- No serialization: `startCapture` (line 227-245) and `OnDestroy` (line
  215-219) touch the shared `@Volatile var running`/`var rec` with no lock or
  join. A quick stop -> start (e.g. re-entering voice mode fast, or the
  `tapOrb()` interrupt-and-restart path in voice_mode.tsx) can flip `running`
  back to true before the OLD pump thread's loop has observed it was false,
  resurrecting the old capture thread (it re-reads the now-true flag as
  license to keep going) alongside the new one - two `AudioRecord` pump
  threads briefly alive, each capable of emitting `onSegment` with an
  incomplete/overlapping utterance.

## Why this matters

The realistic trigger is completely ordinary: a user finishes their sentence
and taps to close voice mode (or the `should_listen` mute/restart cycle fires)
before the 700ms end-silence hangover (`END_SILENCE_FRAMES`) has elapsed. The
last clause of what they said just vanishes - no error, no transcript, no
sign anything was dropped. This is the project's own voice pipeline (see
memory: HelmDeck built VAD -> whisper live mode specifically to own this,
not delegate to the platform recognizer), so this is a correctness bug in
core functionality, not a third-party dependency issue.

## Wanted

1. `stop()` on the native side should drain, not just flag: if an utterance
   is in progress when `running` is cleared, call `finish(true)` (or an
   equivalent forced-finalize) before the loop exits, so a stop mid-sentence
   still emits whatever was captured so far as a segment.
2. Make `stop()` awaitable from JS (return a Promise that resolves once the
   pump thread has actually exited and any trailing segment has been sent)
   so `voice_mode.tsx`'s cleanup paths can `await` it instead of firing and
   forgetting - matches Paseo's #3968 fix shape (wait for the final buffer to
   cross the bridge before treating capture as stopped).
3. Serialize start/stop/destroy behind one owner (e.g. only the pump thread
   itself flips `rec`/`running` to their terminal values on exit, and
   `startCapture` refuses to start a new capture until the previous pump
   thread has confirmed exit) so a fast stop->start can't resurrect the old
   worker via the shared `running` flag.

## Verify

- Start voice mode, speak, tap-close mid-sentence (before 700ms of silence) -
  the segment for that utterance still arrives and gets transcribed.
- Rapid close/reopen of voice mode (or `tapOrb()`'s interrupt-and-restart) -
  only ever one live pump thread; no duplicate/overlapping `onSegment`
  events, no orphaned `AudioRecord`.
