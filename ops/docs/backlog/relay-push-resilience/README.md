# Relay-Push-Resilience - truncated `/tunnel/push` bodies lose the daemon's reply

**Trigger (owner report + live forensics, 2026-09-11):** the relay console
showed two `JSONDecodeError: Unterminated string ... column 54` tracebacks
from `surfaces/relay/relay.py:552` and the owner read it as "relay died".
Verified state: the relay (PID 9904, up since the 09:31 login) never died -
`/health` 200 locally and via relay.helmdeck.de; the traceback is
socketserver's per-connection `handle_error`, reproduced on demand with a
POST that closes 500 bytes short (relay kept serving). Column 54 is exactly
where the `cipher` value starts, so every hit is a daemon->relay reply frame
whose body ended early.

**Three verified layers, top to bottom:**

1. **Transport: the daemon dials its OWN relay through Cloudflare.** Since
   the local fallback (memory `helmdeck-relay-local-fallback`, 2026-09-08)
   relay.py and the daemon share this PC, but `relay_client._cfg()`
   (`spine/comms/relay_client.py:60`, single caller: the bridge loop at
   `:199`) returns `settings.relay.url` = `https://relay.helmdeck.de` for
   pull AND push. Every leg goes PC -> edge -> cloudflared (PID 5932) ->
   127.0.0.1:6790 (that is why the traceback's peer is 127.0.0.1). The
   daemon's event log shows that leg being reset 8 times between 13:24 and
   16:18 today (`bridge unreachable ... WinError 10054` / read timeout /
   502, each followed by `reconnected after 1 attempt`). Those are the PULL
   side, which logs. A reset on the PUSH side is the truncated body. Second
   severing source: the singleton eviction (`spine/http/startup.py:144`,
   `taskkill /F /T`) at 16:27:19 kills any `_serve_one` thread mid-upload -
   covered by debt `workers-die-with-the-daemon`, NOT in scope here.
2. **Daemon: a failed push is silent and final.** `_serve_one`
   (`relay_client.py:125-167`) computes the reply, pushes once with
   `timeout=15`, and `except Exception: pass`. No event, no retry. The
   relay's waiting slot for that frame id stays open for REPLY_TIMEOUT
   (120s) - a retry a few seconds later WOULD still deliver - but nothing
   retries. Same shape for the 409 not-admitted push (`:143-147`).
3. **Relay: `/tunnel/push` decodes an unguarded body.** `_body()`
   (`relay.py:395`) trusts Content-Length; a short read returns the partial
   bytes and `json.loads` at `:552` raises. `/relay` already guards this
   (`:576-578`, "bad json"); `/tunnel/push` does not. Also `int()` on a
   non-numeric Content-Length would traceback the same way.

**What the phone sees per lost push:** the app's relay ladder
(`surfaces/app/src/data/client.ts:111-117`) aborts at 20s (normal) / 35s
(long-poll); `POST /chat` is unbounded and waits for the relay's 504 at
120s ("daemon offline or slow"). The daemon had the answer; the user sees a
dead desktop.

---

## Phase A - relay.py hardening (~1h; no daemon restart; relay restart = a 3s bridge blip)

1. **Guard the push body.** In `do_POST /tunnel/push` (`relay.py:548-560`):
   read the body first (same rule as `/relay`, comment at `:569`), then
   - if `len(raw) < declared Content-Length`: the peer hung up mid-body.
     Set `self.close_connection = True` (the keep-alive socket holds no
     usable next request) and `_send(400, {"error":"truncated body"})` -
     `_send` already swallows the reset if the peer is gone (c0992aa). One
     log line via a new `_note(msg)` (timestamped print; `log_message`
     stays muted): `push truncated room=<8 chars> got=<n> want=<m>`. No
     traceback.
   - `json.loads` in `try/except ValueError` -> 400 `{"error":"bad json"}`,
     keep-alive intact (body was fully consumed).
   - `_body()`: `int()` under `try` -> 0 on garbage (`:396`). A ValueError
     there is the same class of traceback.
   A client that vanished is not an error on our side, but it IS a counted,
   visible event - one line, not 25.
2. **Self-sandboxed test `ops/tests/test_relay_tunnel.py`** (pattern:
   `ops/tests/test_ota_relay.py:26-30` - import `relay`, ThreadingHTTPServer
   on port 0, no env, no live db). Cases: (a) full round trip `/relay` ->
   `/tunnel/pull` -> `/tunnel/push` returns the cipher to the waiting caller;
   (b) push with Content-Length 500 over actual bytes then close -> server
   still answers `/health`, and `sys.stderr` (swapped for a StringIO for the
   duration; `handle_error` resolves `sys.stderr` at call time) contains NO
   `Traceback`; (c) complete-but-malformed body -> 400 "bad json" and the
   SAME `http.client.HTTPConnection` then serves `/health` (keep-alive not
   poisoned); (d) push for an unknown id -> 200 ok (existing behaviour,
   pinned).

**Deliberate non-change:** no socket timeout on the handler class. A client
that stalls (not hangs up) mid-body holds one thread today; a
`H.timeout` would fix that but also closes cloudflared's pooled idle
connections, and a POST on a just-closed pooled connection is exactly the
failure class this card is closing. Separate card if the thread count ever
climbs (it is 3 after 7h today).

## Phase B - daemon push retry + visibility (~1.5h; needs daemon restart -> idle only)

3. **`_push(relay, room, payload) -> bool`** in `relay_client.py`, used by
   BOTH push sites (`:143-147`, `:161-167`). Up to 3 attempts, sleeps 1s
   then 3s between them. Retry ONLY on transport failures: `URLError`,
   `socket.timeout`, `ConnectionResetError`, `RemoteDisconnected`, and any
   HTTP status >= 500 (Cloudflare's own edge/tunnel errors are 502/504 AND
   520-530 - a 530 is what the edge returns while cloudflared is down).
   Never on 4xx from the relay (that is our bug, retrying hides it).
   Idempotent by construction: the relay keys pushes by frame id, a
   duplicate lands on an empty slot -> 200 ok (`relay.py:554-558`).
   Budget, stated honestly: a reset-class failure fails instantly, so the
   retry lands ~1s later, inside the app's 20s/35s ladder. A timeout-class
   failure burns 15s per attempt (worst case ~49s), which only still helps
   the unbounded `POST /chat` (120s relay slot) - for bounded requests the
   phone has already moved on and the late push lands on a dead slot,
   harmlessly. The 15s timeout stays: the observed failures are resets.
4. **Log like the pull loop.** `events.log("relay", ...)` on the FIRST
   failed push attempt and every 10th thereafter (module counter, same
   cadence as `_loop` at `:226-235` so the event stream reads uniformly),
   `push delivered after N retry(s)` on recovery (resets the counter), and
   `push lost frame=<8 chars> after 3 attempts: <err>` under the SAME
   first-then-every-10th cap - a total outage must not produce one event
   per frame. That lost line IS the phone's 504, now attributable.
5. **Unit test `ops/tests/test_relay_client_push.py`:** monkeypatch
   `relay_client.urllib.request.urlopen` with a fake raising `URLError`
   twice then returning 200 -> 3 calls, returns True, exactly ONE
   `events.log` call (patched at `relay_client` scope - NEVER patch
   `events.SET`/db, memory `helmdeck-config-consolidation` trap). Second
   case: HTTP 400 -> 1 call, False, no retry. Third: 3x URLError -> False,
   the `push lost` line once. Fourth: 30 consecutive lost frames -> 4 log
   calls total (1st, 10th, 20th, 30th), proving the cap. `time.sleep`
   patched to a no-op.

## Phase C - daemon dials the co-located relay over loopback (~2h; owner decision, explicit knob)

**The relay stays public.** relay.helmdeck.de, the tunnel, the pairing
link and the phone's path are untouched - the phone reaches the relay from
anywhere exactly as today. This phase changes ONE hop only: the daemon on
this PC talking to the relay.py that runs on this same PC. Today that hop
is `daemon -> Cloudflare edge -> cloudflared -> 127.0.0.1:6790` (both ends
on one box, yet every pull/push leaves it); afterwards it is
`daemon -> 127.0.0.1:6790`. Nothing that lives elsewhere is affected, and
the moment the relay moves back off-box the field is cleared and the daemon
dials the public URL again.

6. **New optional setting `relay.dial`** (daemon-only base URL for pull +
   push; empty = today's behaviour, dial `relay.url`). `_cfg()` returns
   `dial or url` as the first tuple element - it has exactly one caller
   (`:199`), so nothing else changes. `pairing_payload()` (`:247`) reads
   `settings.relay.url` directly and keeps doing so, so the phone's link
   and the QR never see the dial URL. Validation in `settings_post`
   (`routes_settings.py:169`): `dial` must pass `insecure_url()` (which
   already whitelists `localhost` / `::1` / `127.*`, `relay_client.py:46`)
   - so loopback http and any https pass, plain-http to a LAN host gets the
   existing 400 sentence. The bridge's own `insecure_url(relay)` warning at
   `:203` stays False for loopback, no new noise. An explicit owner-set
   value, not a locality guess - the relay is a separate process and the
   daemon must not infer where it lives (NO MONKEY PATCHES law).
7. **Settings UI, Mobile app screen:** one field "Daemon dial-out URL
   (optional)" with helper text "set to http://127.0.0.1:6790 while the
   relay runs on this PC; clear it when the relay moves back off-box".
   Startup line in the bridge: `events.log("relay", "bridge dials <url>")`
   once per daemon start, so a stale dial URL after the relay moves is
   visible in the first minute, not after an hour of 10054s. UI law:
   screenshot and JUDGE the field on phone width (label wrap, helper text
   contrast, keyboard type = url).
8. **Expected effect (measurable):** today's baseline is 8 pull-side resets
   in ~3h through the tunnel. After Phase C the daemon leg never leaves the
   loopback; the reset count for that leg should be 0 over the same window,
   and every relay round trip loses one edge hop (the "Verstaerker" noted in
   the chat-load-latency card).

## NOT in scope (verified reasons)

- Draining in-flight pushes on singleton eviction - debt
  `workers-die-with-the-daemon`, separate.
- Why the tunnel leg resets every 5-30 min (cloudflared edge re-registration
  vs. home uplink) - unknowable without cloudflared logs; Phase C removes
  the leg instead of diagnosing it. `logfile:` in
  `~/.cloudflared/config.yml` is worth adding for the phone leg anyway,
  independent of this card.
- Raising `timeout=15` on the push, any change to REPLY_TIMEOUT /
  PULL_TIMEOUT / the app ladder, a handler socket timeout (see Phase A).

## Verify (adversarial, per feature)

- **A:** run the truncated-POST probe from the forensics against the LIVE
  relay (`room=probe-analysis`): expect exactly one `push truncated` line
  in the relay console, no traceback, `/health` 200. Then a malformed body
  -> 400, and a `/health` on the same keep-alive socket -> 200.
- **B:** the unit tests above are the proof of the retry logic. Live
  evidence comes for free: today's tunnel leg fails ~3x/h, so within a few
  hours of the restart the event log must show `push delivered after N
  retry(s)` and/or `push lost` lines next to the existing pull-side
  `bridge unreachable` lines. Do NOT kill cloudflared to provoke it: that
  also cuts the phone's path, and restarting it via `relay_local.cmd`
  doubles the relay (trap below).
- **C:** set dial, restart daemon at idle, confirm `bridge dials
  http://127.0.0.1:6790` in events, pair state unchanged (phone still
  talks, QR payload still shows relay.helmdeck.de), then compare relay
  events over 3h to today's 8 resets. Time one `/tracks` round trip from
  the phone before/after (chat-load-latency Phase 0 method). Negative
  case: set dial to `http://192.168.0.5:6790` -> 400 with the https
  sentence.

## Rollout, rollback, traps

- Order: A first (relay-only, restart relay.py), then B + C in ONE daemon
  restart at idle (a restart kills live turns - memory
  `helmdeck-stuck-usually-needs-you`).
- **Restart only `python relay.py`, never re-run `relay_local.cmd`:** it
  also starts cloudflared, and a second connector joins the same tunnel
  and load-balances (memory `helmdeck-relay-local-fallback`).
- The relay is stateless; a restart costs the daemon one `bridge
  unreachable` + reconnect in 3s and the phone one aborted long-poll.
- Rollback: A and B are plain reverts. C rolls back by clearing the field
  (no restart needed - `_cfg()` is re-read every pull), and when the relay
  moves back off-box the `bridge dials` startup line plus the returning
  `bridge unreachable` events are the tell that the field was left set.
- No new debt if A-C ship whole. If C is deferred, nothing is registered
  either - an absent knob is today's behaviour, not a shortcut.
