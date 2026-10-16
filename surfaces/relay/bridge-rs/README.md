# helmdeck-relay-bridge (key-less, switchable)

The process that holds the phone's room WebSocket so it survives a daemon restart. It is OFF by
default (`relay.engine = "inproc"`: the daemon dials the room itself, as always). Turn it on with
`py -3.12 ops/tools/relay_engine.py pipe`, back with `... inproc`.

    phone <-> Cloudflare worker <-> [bridge: ONE WebSocket, ping, redial, hold queue]
                                         <-> two owner-only named pipes <->
                                    daemon (relay_client._pipe_session -> _serve_one / _admit / events)

## What it is NOT (the point of the redesign)

The first prototype (2026-10-15) decrypted frames itself, so it needed the room secret key, its
own copy of the pinned device list, and a way to admit new devices - three security seams, and no
measurable gain over the Python bridge (see git history of this README). This version has none of
them: **the bridge holds no key and decides nothing.** Frames go to the daemon exactly as the room
sent them, replies and events come back exactly as the daemon sealed them. Admission, pairing, the
secret key, the "frame waited" / "daemon took" logs and the event publisher stay in
`spine/comms/relay_client.py`, byte for byte. `Cargo.toml` has no crypto crate to prove it.

## Wire (newline-delimited JSON, the same objects the WebSocket carries)

| pipe | direction | messages |
|---|---|---|
| `\\.\pipe\helmdeck-relay-<user>.rx` | daemon -> bridge | `hello {relay, room}`, `reply {id, cipher, to}`, `event {to, cipher}` |
| `\\.\pipe\helmdeck-relay-<user>.tx` | bridge -> daemon | `frame {id, pub, cipher, t}`, `client {pub}` |

Two pipes because one synchronous handle serialises a blocked read against a write. The daemon
opens `.rx`, says hello (relay URL + room), then opens `.tx`. Replies over 900 KB go over
`/tunnel/push` straight from the daemon (`_deliver`), as in the inproc engine.

## Behaviour

- Dials NOTHING until a daemon says hello; one socket per room (the daemon never dials in this mode).
- A daemon restart: the bridge keeps the socket, holds up to 64 frames for up to 45 s, delivers them
  in order when the daemon is back. The room's liveness probe is answered by the bridge itself.
- A daemon that stays away for more than 60 s (GRACE): the bridge closes the room socket, so the worker
  answers phones with its own 503 - what a stopped daemon looks like today. A returning daemon is
  served again at once.
- A reply that finds the socket gone is pushed over `/tunnel/push` (same waiting id).
- Redial: an established socket redials at once, a failing dial backs off 3..60 s.

## Security

Both pipes are created with an explicit protected DACL naming only the current user's SID
(`D:P(A;;GA;;;<sid>)`; Windows' default would give Everyone read), `PIPE_REJECT_REMOTE_CLIENTS`, and
`FILE_FLAG_FIRST_PIPE_INSTANCE` - a second bridge, or something squatting on the name, exits with code 3.
`ops/tests/test_relay_bridge_rs_e2e.py` reads the DACL back from the kernel.

## Run / verify

    cargo build --release
    cargo test                                          # 7: hold queue, order, bounds, grace, stale client, DACL, squatter
    py -3.12 ops/tests/test_relay_bridge_rs_e2e.py      # REAL worker, throw-away room, REAL Python daemon half as a killable subprocess
    py -3.12 ops/tools/relay_engine.py status|pipe|inproc

The e2e proves: GET/POST/1.3 MB reply/404, an unpinned key refused BY THE DAEMON and served once the
daemon opens its pairing window, a forged frame answered with silence, a joining phone announced and
sent its event, a daemon KILLED mid-flight (the request is held and answered when the next daemon
attaches, 3.6 s), the grace window, and 8 phones x 20 requests.

The tray (`surfaces/desktop/tray-rs`, `BridgeKeeper`) starts and stops the bridge while the db row says
`pipe` (checked every 4 s) and logs to `daemon/relay-bridge.log`. The Python tray does not supervise it:
`relay_engine.py` refuses `pipe` without the Rust tray.

## Known limits (debt `relay-pipe-no-longpoll-fallback`)

No long-poll fallback (a worker without `/tunnel/ws` needs `inproc`); frames held longer than 45 s are
dropped and the phone times out by itself; Windows only (the pipe layer).
