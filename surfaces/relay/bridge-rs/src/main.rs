//! helmdeck-relay-bridge - the relay bridge's socket + worker pool in Rust (PROTOTYPE of
//! spine/comms/relay_client.py's `_ws_session` / `_loop`). One WebSocket to the room, a fixed
//! pool of workers serving phone frames against the local daemon, a protocol ping every 20 s
//! (no pong within 10 s -> reconnect), redial with backoff.
//!
//!   helmdeck-relay-bridge --relay https://relay.helmdeck.de --room R --sk <b64> --pubs <b64,b64> [--port 8140]
//!                         [--workers 24] [--run-for SECS]
//!
//! Not in the prototype (README): pairing/admission of NEW devices, pushing change events to the
//! phone, long-poll fallback.

use std::net::TcpStream;
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};

use helmdeck_relay_bridge as hb;
use serde_json::{json, Value};
use tungstenite::{stream::MaybeTlsStream, Error as WsError, Message};

const PING_EVERY: Duration = Duration::from_secs(20);
const PING_TIMEOUT: Duration = Duration::from_secs(10);
const STABLE: Duration = Duration::from_secs(60);

fn arg(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1).cloned())
}

fn log(msg: &str) {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    println!("{now} {msg}");
}

fn set_read_timeout(stream: &mut MaybeTlsStream<TcpStream>, d: Duration) {
    match stream {
        MaybeTlsStream::Plain(s) => {
            let _ = s.set_read_timeout(Some(d));
        }
        MaybeTlsStream::Rustls(s) => {
            let _ = s.sock.set_read_timeout(Some(d));
        }
        _ => {}
    }
}

/// One connected session. Returns when the socket is gone; the Err says why.
fn session(
    relay: &str,
    room: &str,
    ctx: &Arc<hb::Ctx>,
    frame_tx: &mpsc::Sender<Value>,
    out_rx: &mpsc::Receiver<hb::Reply>,
    stop_at: Option<Instant>,
) -> Result<(), String> {
    let url = hb::ws_url(relay, room).ok_or("relay URL must be http(s)://")?;
    let (mut ws, _resp) = tungstenite::connect(url.as_str()).map_err(|e| format!("connect: {e}"))?;
    set_read_timeout(ws.get_mut(), Duration::from_millis(100));
    log("bridge transport: websocket");
    let mut next_ping = Instant::now() + PING_EVERY;
    let mut ping_sent: Option<Instant> = None;
    loop {
        if stop_at.map(|t| Instant::now() >= t).unwrap_or(false) {
            let _ = ws.close(None);
            return Ok(());
        }
        // replies the workers finished since the last turn of the loop
        while let Ok(r) = out_rx.try_recv() {
            let msg = json!({"kind": "reply", "id": r.id, "cipher": r.cipher, "to": r.to}).to_string();
            if let Err(e) = ws.send(Message::text(msg)) {
                // the socket died mid-request: the HTTP push still lands on the same waiting id
                let relay = relay.to_string();
                let room = room.to_string();
                std::thread::spawn(move || {
                    hb::push_reply(&relay, &room, &r);
                });
                return Err(format!("send: {e}"));
            }
        }
        let now = Instant::now();
        if let Some(t) = ping_sent {
            if now.duration_since(t) > PING_TIMEOUT {
                return Err("keepalive ping timeout; no pong".into());
            }
        } else if now >= next_ping {
            ws.send(Message::Ping(Vec::new().into())).map_err(|e| format!("ping: {e}"))?;
            ping_sent = Some(now);
            next_ping = now + PING_EVERY;
        }
        match ws.read() {
            Ok(Message::Text(t)) => {
                let Ok(v) = serde_json::from_str::<Value>(t.as_str()) else { continue };
                match v.get("kind").and_then(|k| k.as_str()) {
                    Some("frame") => {
                        let _ = frame_tx.send(v);
                    }
                    Some("probe") => {
                        // the room asks "does anyone still read this socket?" - answer at once
                        ws.send(Message::text(json!({"kind": "alive"}).to_string()))
                            .map_err(|e| format!("alive: {e}"))?;
                    }
                    _ => {} // "client": events are not part of the prototype
                }
            }
            Ok(Message::Pong(_)) => ping_sent = None,
            Ok(Message::Close(f)) => return Err(format!("closed by the room: {f:?}")),
            Ok(_) => {}
            Err(WsError::Io(e)) if matches!(e.kind(), std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut) => {}
            Err(e) => return Err(format!("read: {e}")),
        }
        let _ = ctx; // the workers own the key; the socket loop never touches plaintext
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let (Some(relay), Some(room), Some(sk_b64)) = (arg(&args, "--relay"), arg(&args, "--room"), arg(&args, "--sk")) else {
        eprintln!("usage: helmdeck-relay-bridge --relay URL --room R --sk <b64> --pubs <b64,b64> [--port 8140] [--workers 24] [--run-for SECS]");
        std::process::exit(2);
    };
    let sk = match hb::secret_from_b64(&sk_b64) {
        Ok(k) => k,
        Err(e) => {
            eprintln!("bad --sk: {e}");
            std::process::exit(2);
        }
    };
    let pinned: Vec<String> = arg(&args, "--pubs")
        .unwrap_or_default()
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    let port: u16 = arg(&args, "--port").and_then(|p| p.parse().ok()).unwrap_or(8140);
    let workers: usize = arg(&args, "--workers").and_then(|p| p.parse().ok()).unwrap_or(24);
    let stop_at = arg(&args, "--run-for")
        .and_then(|s| s.parse::<u64>().ok())
        .map(|s| Instant::now() + Duration::from_secs(s));

    let ctx = Arc::new(hb::Ctx { sk, pinned, port });
    let (frame_tx, frame_rx) = mpsc::channel::<Value>();
    let (out_tx, out_rx) = mpsc::channel::<hb::Reply>();
    let frame_rx = Arc::new(Mutex::new(frame_rx));
    // a FIXED pool, never a thread per frame (the 2026-09-25 1,504-thread incident)
    for _ in 0..workers {
        let (rx, out, ctx) = (frame_rx.clone(), out_tx.clone(), ctx.clone());
        let (relay, room) = (relay.clone(), room.clone());
        std::thread::spawn(move || loop {
            let frame = match rx.lock().unwrap().recv() {
                Ok(f) => f,
                Err(_) => return,
            };
            if let Some(r) = hb::serve_frame(&frame, &ctx) {
                if r.cipher.len() <= hb::WS_MAX_REPLY {
                    let _ = out.send(r);
                } else {
                    hb::push_reply(&relay, &room, &r); // too big for one socket message
                }
            }
        });
    }

    let mut delay = Duration::from_secs(3);
    loop {
        let started = Instant::now();
        let r = session(&relay, &room, &ctx, &frame_tx, &out_rx, stop_at);
        if stop_at.map(|t| Instant::now() >= t).unwrap_or(false) {
            log("bridge stopped (--run-for)");
            return;
        }
        let up = started.elapsed();
        match r {
            Ok(()) => log("bridge socket closed cleanly - redialing"),
            Err(e) => log(&format!("bridge socket dropped after {}s ({e}) - redialing", up.as_secs())),
        }
        // an ESTABLISHED socket that drops redials at once; a failing dial backs off 3..60 s
        if up >= STABLE {
            delay = Duration::from_secs(3);
            std::thread::sleep(Duration::from_millis(500));
        } else {
            std::thread::sleep(delay);
            delay = (delay * 2).min(Duration::from_secs(60));
        }
    }
}
