// GUI subsystem in release: the tray starts this without a console; output goes to the log it redirects.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! helmdeck-relay-bridge (key-less). See lib.rs for the protocol.
//!
//!   helmdeck-relay-bridge [--pipe NAME] [--run-for SECS] [--grace SECS]
//!
//! It dials nothing until a daemon says hello over the pipe (relay URL + room), keeps the room
//! socket across a daemon restart (GRACE), holds phone frames meanwhile (HOLD_MAX / HOLD_FOR), and
//! answers the room's liveness probe itself. It holds no key: frames are opaque lines to it.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::sync::{mpsc, Arc};
use std::time::{Duration, Instant};

use helmdeck_relay_bridge as hb;
use serde_json::{json, Value};
use tungstenite::{stream::MaybeTlsStream, Error as WsError, Message};

const PING_EVERY: Duration = Duration::from_secs(20);
const PING_TIMEOUT: Duration = Duration::from_secs(10);
const STABLE: Duration = Duration::from_secs(60);
const MAX_LINE: usize = 4 * 1024 * 1024;

fn arg(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1).cloned())
}

fn log(msg: &str) {
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    println!("{now} {msg}");
    let _ = std::io::stdout().flush();
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

/// A reply the socket could not carry goes to /tunnel/push - on its own thread, never blocking a loop.
fn push_async(relay: String, room: String, line: String) {
    std::thread::spawn(move || {
        let Ok(v) = serde_json::from_str::<Value>(&line) else { return };
        if v.get("kind").and_then(|k| k.as_str()) != Some("reply") {
            return;
        }
        let s = |k: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
        hb::push_reply(&relay, &room, &s("id"), &s("cipher"), &s("to"));
    });
}

/// One connected session. Returns when the socket is gone or the target changed.
fn session(hub: &Arc<hb::Hub>, relay: &str, room: &str, out_rx: &mpsc::Receiver<String>, stop_at: Option<Instant>) -> Result<(), String> {
    let url = hb::ws_url(relay, room).ok_or("relay URL must be http(s)://")?;
    let (mut ws, _resp) = tungstenite::connect(url.as_str()).map_err(|e| format!("connect: {e}"))?;
    set_read_timeout(ws.get_mut(), Duration::from_millis(100));
    while out_rx.try_recv().is_ok() {} // anything from a previous socket is stale
    hub.set_ws_up(true);
    log("bridge transport: websocket");
    let mut next_ping = Instant::now() + PING_EVERY;
    let mut ping_sent: Option<Instant> = None;
    let result = (|| loop {
        if stop_at.map(|t| Instant::now() >= t).unwrap_or(false) {
            return Ok(());
        }
        if hub.dial_target().as_ref().map(|(r, m)| (r.as_str(), m.as_str())) != Some((relay, room)) {
            return Ok(()); // the daemon is gone for good (or points elsewhere): close the socket
        }
        // lines the daemon sent since the last turn (replies, events)
        while let Ok(line) = out_rx.try_recv() {
            if let Err(e) = ws.send(Message::text(line.clone())) {
                push_async(relay.to_string(), room.to_string(), line); // same waiting id in the room
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
                        let dropped = hub.push_frame(t.as_str().to_string());
                        if dropped > 0 {
                            log(&format!("hold queue full: dropped {dropped} oldest frame(s)"));
                        }
                    }
                    Some("client") => {
                        if hub.attached() {
                            hub.push_frame(t.as_str().to_string());
                        }
                    }
                    Some("probe") => {
                        // "does anyone still read this socket?" - the bridge does, always
                        ws.send(Message::text(json!({"kind": "alive"}).to_string())).map_err(|e| format!("alive: {e}"))?;
                    }
                    _ => {}
                }
            }
            Ok(Message::Pong(_)) => ping_sent = None,
            Ok(Message::Close(f)) => return Err(format!("closed by the room: {f:?}")),
            Ok(_) => {}
            Err(WsError::Io(e)) if matches!(e.kind(), std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut) => {}
            Err(e) => return Err(format!("read: {e}")),
        }
    })();
    hub.set_ws_up(false);
    // replies that raced the close still reach the phone over HTTP
    while let Ok(line) = out_rx.try_recv() {
        push_async(relay.to_string(), room.to_string(), line);
    }
    let _ = ws.close(None);
    result
}

#[cfg(windows)]
fn main() {
    use helmdeck_relay_bridge::pipe::Pipe;

    let args: Vec<String> = std::env::args().skip(1).collect();
    let name = arg(&args, "--pipe").unwrap_or_else(|| format!("helmdeck-relay-{}", std::env::var("USERNAME").unwrap_or_default().to_lowercase()));
    let stop_at = arg(&args, "--run-for").and_then(|s| s.parse::<u64>().ok()).map(|s| Instant::now() + Duration::from_secs(s));
    let (rx_path, tx_path) = hb::pipe_paths(&name);
    // First-instance + owner-only DACL: a second bridge, or something squatting on the name, fails here.
    let rx_pipe = match Pipe::create(&rx_path, true) {
        Ok(p) => Arc::new(p),
        Err(e) => {
            log(&format!("cannot create {rx_path}: {e} (another bridge running?)"));
            std::process::exit(3);
        }
    };
    let tx_pipe = match Pipe::create(&tx_path, false) {
        Ok(p) => Arc::new(p),
        Err(e) => {
            log(&format!("cannot create {tx_path}: {e}"));
            std::process::exit(3);
        }
    };
    log(&format!("bridge up, pipe {name}"));

    let hub = Arc::new(hb::Hub::new());
    if let Some(g) = arg(&args, "--grace").and_then(|s| s.parse::<u64>().ok()) {
        hub.set_grace(Duration::from_secs(g)); // tests only; the default is lib::GRACE
    }
    let (out_tx, out_rx) = mpsc::channel::<String>();

    // daemon -> bridge: hello, then replies and events
    {
        let (hub, pipe, out_tx) = (hub.clone(), rx_pipe.clone(), out_tx);
        std::thread::spawn(move || loop {
            if pipe.connect().is_err() {
                std::thread::sleep(Duration::from_millis(200));
                continue;
            }
            let mut rd = BufReader::new(&*pipe);
            let mut line = String::new();
            let mut hello = false;
            loop {
                line.clear();
                match rd.by_ref().take(MAX_LINE as u64).read_line(&mut line) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => {}
                }
                if !line.ends_with('\n') {
                    log("daemon line too long or cut - dropping the pipe");
                    break;
                }
                let Ok(v) = serde_json::from_str::<Value>(line.trim_end()) else { continue };
                let s = |k: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
                match v.get("kind").and_then(|k| k.as_str()) {
                    Some("hello") => {
                        hub.attach(&s("relay"), &s("room"));
                        hello = true;
                        log(&format!("daemon attached ({} frame(s) waiting)", hub.queued()));
                    }
                    Some("reply") | Some("event") if hello => {
                        let l = line.trim_end().to_string();
                        if hub.ws_up() {
                            let _ = out_tx.send(l);
                        } else if let Some((relay, room)) = hub.target() {
                            push_async(relay, room, l); // no socket right now: HTTP still lands on the waiting id
                        }
                    }
                    _ => {}
                }
            }
            drop(rd);
            hub.detach();
            pipe.disconnect();
            log("daemon detached");
        });
    }

    // bridge -> daemon: frames, held while nobody is attached
    {
        let (hub, pipe) = (hub.clone(), tx_pipe.clone());
        std::thread::spawn(move || loop {
            if pipe.connect().is_err() {
                std::thread::sleep(Duration::from_millis(200));
                continue;
            }
            let my_gen = hub.gen();
            let mut w = &*pipe;
            loop {
                let (p, expired) = hub.pop(my_gen, Duration::from_secs(1));
                if expired > 0 {
                    log(&format!("{expired} held frame(s) expired before the daemon came back"));
                }
                match p {
                    hb::Pop::Line(l) => {
                        let ok = w.write_all(l.as_bytes()).and_then(|_| w.write_all(b"\n"));
                        if ok.is_err() {
                            hub.requeue_front(l);
                            break;
                        }
                    }
                    hb::Pop::Idle => {}
                    hb::Pop::Stale => break,
                }
            }
            pipe.disconnect();
        });
    }

    let mut delay = Duration::from_secs(3);
    loop {
        if stop_at.map(|t| Instant::now() >= t).unwrap_or(false) {
            log("bridge stopped (--run-for)");
            return;
        }
        let Some((relay, room)) = hub.dial_target() else {
            std::thread::sleep(Duration::from_millis(200));
            continue;
        };
        let started = Instant::now();
        let r = session(&hub, &relay, &room, &out_rx, stop_at);
        let up = started.elapsed();
        match r {
            Ok(()) => log("bridge socket closed"),
            Err(e) => log(&format!("bridge socket dropped after {}s ({e}) - redialing", up.as_secs())),
        }
        // an ESTABLISHED socket that drops redials at once; a failing dial backs off 3..60 s
        if up >= STABLE {
            delay = Duration::from_secs(3);
            std::thread::sleep(Duration::from_millis(500));
        } else if hub.dial_target().is_some() {
            std::thread::sleep(delay);
            delay = (delay * 2).min(Duration::from_secs(60));
        }
    }
}

#[cfg(not(windows))]
fn main() {
    eprintln!("helmdeck-relay-bridge: named-pipe transport is Windows-only for now");
    std::process::exit(2);
}
