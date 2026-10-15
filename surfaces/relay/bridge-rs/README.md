# helmdeck-relay-bridge (Rust prototype, NOT wired in)

The data plane of the relay bridge in Rust: one WebSocket to the room, a fixed pool of 24
workers that decrypt a phone frame, call the local daemon on loopback and send the sealed answer
back, a protocol ping every 20 s (no pong in 10 s -> redial), backoff redial, replies over 900 KB
through `/tunnel/push`. Wire-compatible with `spine/comms/relay_client.py` and the phone
(Curve25519 + XSalsa20-Poly1305, `nonce(24) || ciphertext`, same JSON inner request/reply).

    cargo build --release
    helmdeck-relay-bridge --relay https://relay.helmdeck.de --room R --sk <b64> --pubs <b64,b64> [--port 8140] [--workers 24] [--run-for SECS]
    cargo test                                          # 7 tests: crypto, wire format, serving, refusal, forgery, dead daemon
    py -3.12 ops/tests/test_relay_bridge_rs_e2e.py      # against the REAL worker, throw-away room, PyNaCl phone
    py -3.12 ops/tools/bench_relay_bridge.py 40 8       # A/B against the Python bridge

## Proven

- byte-compatible with the Python side and the real worker (end to end, PyNaCl phone): GET, POST
  with a unicode body and headers, a 1.3 MB reply via push, the daemon's own error status, an
  unpinned key answered "not paired" sealed to itself, a forged frame answered with silence and the
  bridge still serving, 8 phones x 20 requests at once.

## Measured (2026-10-15, real worker, each bridge in its own process, 8 phones x 40 requests)

| | Python bridge | Rust bridge |
|---|---|---|
| latency p50 | 145 / 156 ms | 183 / 162 ms |
| latency p95 | 236 / 259 ms | 284 / 254 ms |
| CPU per 1,000 requests | 2.5 / 2.1 s | 2.6 / 1.6 s |
| private memory (own process) | 31 MB | 5 MB |
| threads | 15 | 28 |

Latency and CPU are a wash: the internet round trip to the worker (~130 ms) dominates. The memory
figure is for a bridge in its OWN process; the Python bridge in production lives inside the daemon
and costs it a few MB and threads, so the real saving is single-digit MB. One request per run hit a
connection reset after ~19 s on BOTH bridges (the phone-side HTTPS client / the line), not a bridge
fault.

## Not in the prototype - the three seams a production switch needs

1. **Admitting NEW devices.** Pairing pins a key by writing `settings.relay` inside an open pairing
   window. The bridge only serves keys passed in `--pubs`. A production bridge needs the daemon to own
   admission and answer a narrow question ("may this key be served, and pin it if the window is open?")
   - NOT as a normal HTTP route: the bridge forwards arbitrary paths from decrypted frames to
   `127.0.0.1:8140`, so any route on that port is reachable by a paired phone.
2. **Pushing change events to the phone.** The daemon's change counter lives in the daemon process
   (`db.wait_any`). The bridge needs a signal channel that is not a phone-reachable route.
3. **The daemon's relay secret key.** Today it sits in `workspace_config.relay`; reading it from a
   second process is what the tray already does for the pairing status, but a bridge that holds the key
   widens who can read it.

Also missing: the long-poll fallback when the worker has no `/tunnel/ws`, the per-frame
"waited Ns in the relay queue" log, the "daemon took Ns" log.

## Recommendation

Do not switch the production bridge to this on the numbers above: there is no latency, CPU or
meaningful memory gain, and the three seams are security-sensitive design work. The one thing a
separate bridge process WOULD buy is that the phone's socket survives a daemon restart (the room would
keep its daemon socket and answer "daemon starting" instead of dropping). That is a product question,
not a performance one - decide it before building the seams.
