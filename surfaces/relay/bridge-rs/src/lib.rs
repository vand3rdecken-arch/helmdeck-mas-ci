//! helmdeck-relay-bridge - the KEY-LESS half of the relay bridge.
//!
//! The bridge owns the one thing that must survive a daemon restart: the room WebSocket. It never
//! decrypts, never pins a device, never holds the room secret - frames go to the daemon exactly as
//! the room sent them, replies come back exactly as the daemon sealed them. All admission, pairing
//! and keys stay in `spine/comms/relay_client.py`.
//!
//! Two protected named pipes (owner-only DACL), newline-delimited JSON:
//!   `<name>.rx`  daemon -> bridge   hello {relay, room}, reply, event
//!   `<name>.tx`  bridge -> daemon   frame, client
//! (two pipes, because one synchronous handle serialises a blocked read against a write.)

use std::collections::VecDeque;
use std::sync::{Condvar, Mutex};
use std::time::{Duration, Instant};

use serde_json::json;

pub const HOLD_MAX: usize = 64; // frames kept while the daemon is away
pub const HOLD_FOR: Duration = Duration::from_secs(45); // ...and for how long (a restart is ~9 s)
pub const GRACE: Duration = Duration::from_secs(60); // keep the room socket this long without a daemon
pub const WS_MAX_REPLY: usize = 900 * 1024;

#[cfg(windows)]
pub mod pipe;

/// Full pipe paths `<name>.rx` / `<name>.tx` for a short name.
pub fn pipe_paths(name: &str) -> (String, String) {
    (format!("\\\\.\\pipe\\{name}.rx"), format!("\\\\.\\pipe\\{name}.tx"))
}

struct State {
    queue: VecDeque<(Instant, String)>,
    attached: bool,
    gen: u64,
    target: Option<(String, String)>, // (relay, room) from the daemon's last hello
    detached_at: Option<Instant>,
    ws_up: bool,
    grace: Duration,
}

/// Everything the threads share: the hold queue and who is attached.
pub struct Hub {
    st: Mutex<State>,
    cv: Condvar,
}

pub enum Pop {
    Line(String),
    Idle,
    Stale, // the daemon attached/detached since this pipe connection began: reconnect
}

impl Default for Hub {
    fn default() -> Self {
        Self::new()
    }
}

impl Hub {
    pub fn new() -> Hub {
        Hub {
            st: Mutex::new(State { queue: VecDeque::new(), attached: false, gen: 0, target: None, detached_at: None, ws_up: false, grace: GRACE }),
            cv: Condvar::new(),
        }
    }

    pub fn set_grace(&self, d: Duration) {
        self.st.lock().unwrap().grace = d;
    }

    pub fn attach(&self, relay: &str, room: &str) {
        let mut s = self.st.lock().unwrap();
        s.attached = true;
        s.gen += 1;
        s.target = Some((relay.to_string(), room.to_string()));
        s.detached_at = None;
        self.cv.notify_all();
    }

    pub fn detach(&self) {
        let mut s = self.st.lock().unwrap();
        if s.attached {
            s.attached = false;
            s.gen += 1;
            s.detached_at = Some(Instant::now());
        }
        self.cv.notify_all();
    }

    pub fn attached(&self) -> bool {
        self.st.lock().unwrap().attached
    }

    pub fn gen(&self) -> u64 {
        self.st.lock().unwrap().gen
    }

    pub fn target(&self) -> Option<(String, String)> {
        self.st.lock().unwrap().target.clone()
    }

    pub fn set_ws_up(&self, up: bool) {
        self.st.lock().unwrap().ws_up = up;
    }

    pub fn ws_up(&self) -> bool {
        self.st.lock().unwrap().ws_up
    }

    /// Where the room socket should point right now: while a daemon is attached, and for GRACE
    /// after it left (a restart). After that the socket closes so the worker answers phones with
    /// its own "no daemon connected" - the same thing a stopped daemon looks like today.
    pub fn dial_target(&self) -> Option<(String, String)> {
        let s = self.st.lock().unwrap();
        if s.attached || s.detached_at.map(|t| t.elapsed() < s.grace).unwrap_or(false) {
            s.target.clone()
        } else {
            None
        }
    }

    /// Queue one frame for the daemon. Returns how many old frames were dropped to stay bounded.
    pub fn push_frame(&self, line: String) -> usize {
        let mut s = self.st.lock().unwrap();
        let mut dropped = 0;
        while s.queue.len() >= HOLD_MAX {
            s.queue.pop_front();
            dropped += 1;
        }
        s.queue.push_back((Instant::now(), line));
        self.cv.notify_all();
        dropped
    }

    /// Put a line back at the front (the pipe write failed).
    pub fn requeue_front(&self, line: String) {
        let mut s = self.st.lock().unwrap();
        s.queue.push_front((Instant::now(), line));
        self.cv.notify_all();
    }

    /// Next frame for the daemon, only while it is attached and `my_gen` is still current.
    /// Frames older than HOLD_FOR are dropped (the phone's request has timed out by then).
    pub fn pop(&self, my_gen: u64, wait: Duration) -> (Pop, usize) {
        let mut s = self.st.lock().unwrap();
        let mut expired = 0;
        loop {
            if s.gen != my_gen {
                return (Pop::Stale, expired);
            }
            while s.queue.front().map(|(t, _)| t.elapsed() > HOLD_FOR).unwrap_or(false) {
                s.queue.pop_front();
                expired += 1;
            }
            if s.attached {
                if let Some((_, l)) = s.queue.pop_front() {
                    return (Pop::Line(l), expired);
                }
            }
            let (g, to) = self.cv.wait_timeout(s, wait).unwrap();
            s = g;
            if to.timed_out() {
                return (Pop::Idle, expired);
            }
        }
    }

    pub fn queued(&self) -> usize {
        self.st.lock().unwrap().queue.len()
    }
}

/// `wss://host/tunnel/ws?room=R` from the relay's https URL (relay_client._ws_url)
pub fn ws_url(relay: &str, room: &str) -> Option<String> {
    let base = if let Some(r) = relay.strip_prefix("https://") {
        format!("wss://{r}")
    } else if let Some(r) = relay.strip_prefix("http://") {
        format!("ws://{r}")
    } else {
        return None;
    };
    let mut u = url::Url::parse(&format!("{}/tunnel/ws", base.trim_end_matches('/'))).ok()?;
    u.query_pairs_mut().append_pair("room", room);
    Some(u.to_string())
}

/// A reply the socket could not carry: POST it to /tunnel/push (relay_client._push). The room
/// matches it to the waiting request by id, so a socket that died mid-request costs nothing.
pub fn push_reply(relay: &str, room: &str, id: &str, cipher: &str, to: &str) -> bool {
    let url = format!("{}/tunnel/push?room={}", relay.trim_end_matches('/'), room);
    let body = json!({"id": id, "cipher": cipher, "to": to}).to_string();
    let secs = 15 + (body.len() as u64) / 100_000; // an upload budget that scales with the upload
    let agent: ureq::Agent = ureq::Agent::config_builder().timeout_global(Some(Duration::from_secs(secs))).build().into();
    for _ in 0..3 {
        match agent.post(&url).header("Content-Type", "application/json").send(body.as_bytes()) {
            Ok(_) => return true,
            Err(ureq::Error::StatusCode(c)) if c < 500 => return false, // our bug, never retried
            Err(_) => std::thread::sleep(Duration::from_millis(500)),
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ws_url_maps_schemes() {
        assert_eq!(ws_url("https://r.example/", "abc").unwrap(), "wss://r.example/tunnel/ws?room=abc");
        assert_eq!(ws_url("http://127.0.0.1:6790", "x y").unwrap(), "ws://127.0.0.1:6790/tunnel/ws?room=x+y");
        assert!(ws_url("ftp://nope", "r").is_none());
    }

    #[test]
    fn frames_wait_for_the_daemon_and_arrive_in_order() {
        let h = Hub::new();
        h.push_frame("a".into());
        h.push_frame("b".into());
        let g = h.gen();
        assert!(matches!(h.pop(g, Duration::from_millis(10)).0, Pop::Idle)); // nobody attached: held
        h.attach("https://r", "room");
        let g = h.gen();
        assert!(matches!(h.pop(g, Duration::from_millis(10)).0, Pop::Line(l) if l == "a"));
        assert!(matches!(h.pop(g, Duration::from_millis(10)).0, Pop::Line(l) if l == "b"));
        assert!(matches!(h.pop(g, Duration::from_millis(10)).0, Pop::Idle));
    }

    #[test]
    fn a_stale_connection_is_told_to_reconnect() {
        let h = Hub::new();
        h.attach("https://r", "room");
        let g = h.gen();
        h.detach();
        assert!(matches!(h.pop(g, Duration::from_millis(10)).0, Pop::Stale));
        h.attach("https://r", "room");
        assert!(matches!(h.pop(g, Duration::from_millis(10)).0, Pop::Stale)); // old generation
    }

    #[test]
    fn the_hold_queue_is_bounded() {
        let h = Hub::new();
        for i in 0..(HOLD_MAX + 5) {
            h.push_frame(format!("f{i}"));
        }
        assert_eq!(h.queued(), HOLD_MAX);
        h.attach("u", "r");
        let g = h.gen();
        // the OLDEST were dropped
        assert!(matches!(h.pop(g, Duration::from_millis(10)).0, Pop::Line(l) if l == "f5"));
    }

    #[test]
    fn the_room_socket_outlives_a_restart_but_not_forever() {
        let h = Hub::new();
        assert!(h.dial_target().is_none()); // never had a daemon: do not dial
        h.attach("https://r", "room");
        assert_eq!(h.dial_target().unwrap().1, "room");
        h.detach();
        assert_eq!(h.dial_target().unwrap().1, "room"); // inside the grace window
        h.st.lock().unwrap().detached_at = Some(Instant::now() - GRACE - Duration::from_secs(1));
        assert!(h.dial_target().is_none()); // gone for good: close, let the worker say "no daemon"
    }
}
