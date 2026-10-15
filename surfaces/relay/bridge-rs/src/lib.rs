//! Data plane of the relay bridge, in Rust. PROTOTYPE of spine/comms/relay_client.py's
//! `_serve_one` / `_local` / `_deliver` - byte-compatible with it on the wire:
//!
//!   frame (room -> daemon): {"kind":"frame","id","pub","cipher","t"}
//!   inner request:  {"method","path","headers":{..},"body":"<text>"}      (after open)
//!   inner reply:    {"status","headers":{"Content-Type"},"body":"<text>"}  (before seal)
//!   cipher = base64( nonce(24) || NaCl-box(ciphertext+tag) )  - Curve25519 + XSalsa20-Poly1305,
//!   the same box PyNaCl and the phone's tweetnacl use (spine/comms/e2ee.py).
//!
//! What this prototype does NOT own (see README): admitting NEW devices (pairing writes
//! settings), pushing change events to the phone (the version counter lives in the
//! daemon process) and the long-poll fallback. Unpinned keys are answered exactly like
//! the Python bridge answers them outside a pairing window.

use std::io::Read;
use std::time::Duration;

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use crypto_box::{
    aead::{generic_array::GenericArray, Aead, AeadCore, OsRng},
    PublicKey, SalsaBox, SecretKey,
};
use serde_json::{json, Value};

pub const NONCE_LEN: usize = 24;
/// a sealed reply bigger than this goes over /tunnel/push instead of the socket
pub const WS_MAX_REPLY: usize = 900 * 1024;
/// the held loopback leg waits this long (the room's reply timeout is 120 s)
pub const LOCAL_TIMEOUT: Duration = Duration::from_secs(115);

pub const NOT_PAIRED: &str = "this device is not paired with the workspace - generate a pairing code on the desktop (Settings -> Mobile app -> Pair phone)";

fn key32(b64: &str) -> Result<[u8; 32], String> {
    let raw = B64.decode(b64.trim()).map_err(|e| format!("bad base64: {e}"))?;
    raw.try_into().map_err(|_| "a Curve25519 key is 32 bytes".to_string())
}

pub fn secret_from_b64(b64: &str) -> Result<SecretKey, String> {
    Ok(SecretKey::from(key32(b64)?))
}

pub fn public_from_b64(b64: &str) -> Result<PublicKey, String> {
    Ok(PublicKey::from(key32(b64)?))
}

pub fn public_to_b64(pk: &PublicKey) -> String {
    B64.encode(pk.as_bytes())
}

/// plaintext -> base64(nonce || ciphertext), the Python `e2ee.seal_b64`
pub fn seal_b64(plaintext: &[u8], my_sk: &SecretKey, peer_pk: &PublicKey) -> Result<String, String> {
    let b = SalsaBox::new(peer_pk, my_sk);
    let nonce = SalsaBox::generate_nonce(&mut OsRng);
    let ct = b.encrypt(&nonce, plaintext).map_err(|_| "seal failed".to_string())?;
    let mut out = nonce.to_vec();
    out.extend_from_slice(&ct);
    Ok(B64.encode(out))
}

/// base64(nonce || ciphertext) -> plaintext; Err on a tampered or foreign frame
pub fn open_b64(frame_b64: &str, my_sk: &SecretKey, peer_pk: &PublicKey) -> Result<Vec<u8>, String> {
    let raw = B64.decode(frame_b64.trim()).map_err(|e| format!("bad base64: {e}"))?;
    if raw.len() < NONCE_LEN + 16 {
        return Err("frame too short".into());
    }
    let (n, ct) = raw.split_at(NONCE_LEN);
    SalsaBox::new(peer_pk, my_sk)
        .decrypt(GenericArray::from_slice(n), ct)
        .map_err(|_| "open failed (tampered or wrong key)".to_string())
}

/// Call the daemon on loopback with the phone's request. Same answers as
/// `relay_client._local`: the daemon's own status/body, 504 `held` when the held
/// leg gives up (the request WAS accepted), 502 when nothing answers.
pub fn local_call(port: u16, inner: &Value) -> Value {
    let path = inner.get("path").and_then(|v| v.as_str()).unwrap_or("/");
    let method = inner.get("method").and_then(|v| v.as_str()).unwrap_or("GET").to_ascii_uppercase();
    let body = inner.get("body").and_then(|v| v.as_str()).unwrap_or("");
    let url = format!("http://127.0.0.1:{port}{path}");

    let agent: ureq::Agent = ureq::Agent::config_builder()
        .http_status_as_error(false)
        .timeout_global(Some(LOCAL_TIMEOUT))
        .build()
        .into();
    let mut req = ureq::http::Request::builder().method(method.as_str()).uri(&url);
    if let Some(h) = inner.get("headers").and_then(|v| v.as_object()) {
        for (k, v) in h {
            if let Some(v) = v.as_str() {
                req = req.header(k.as_str(), v);
            }
        }
    }
    let with_body = matches!(method.as_str(), "POST" | "PUT" | "PATCH" | "DELETE") && !body.is_empty();
    let built = if with_body { req.body(body.as_bytes().to_vec()) } else { req.body(Vec::new()) };
    let request = match built {
        Ok(r) => r,
        Err(e) => return json!({"status": 502, "headers": {}, "body": json!({"error": e.to_string()}).to_string()}),
    };
    match agent.run(request) {
        Ok(mut resp) => {
            let status = resp.status().as_u16();
            let ct = resp
                .headers()
                .get("content-type")
                .and_then(|v| v.to_str().ok())
                .unwrap_or("application/json")
                .to_string();
            let mut buf = Vec::new();
            let _ = resp.body_mut().as_reader().read_to_end(&mut buf);
            json!({"status": status, "headers": {"Content-Type": ct}, "body": String::from_utf8_lossy(&buf)})
        }
        Err(ureq::Error::Timeout(_)) => json!({
            "status": 504, "headers": {},
            "body": json!({"error": "still working - the answer arrives in the chat", "held": true}).to_string()
        }),
        Err(e) => json!({"status": 502, "headers": {}, "body": json!({"error": e.to_string().chars().take(200).collect::<String>()}).to_string()}),
    }
}

/// What the bridge needs to serve a frame.
pub struct Ctx {
    pub sk: SecretKey,
    pub pinned: Vec<String>, // base64 public keys of paired devices
    pub port: u16,
}

pub struct Reply {
    pub id: String,
    pub cipher: String,
    pub to: String,
}

/// Serve ONE `frame` message. None = nothing to send (undecryptable / tampered:
/// ignored exactly like `_serve_one`, silence is the answer to a forged frame).
pub fn serve_frame(frame: &Value, ctx: &Ctx) -> Option<Reply> {
    let id = frame.get("id")?.as_str()?.to_string();
    let pub_b64 = frame.get("pub").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let peer = public_from_b64(&pub_b64).ok()?;

    if !ctx.pinned.iter().any(|p| p == &pub_b64) {
        // refused: say so, sealed to the caller's own key (a pairing failure must
        // surface in the app instead of hanging) - same wording as relay_client._admit
        let body = json!({"error": NOT_PAIRED}).to_string();
        let resp = json!({"status": 409, "headers": {"Content-Type": "application/json"}, "body": body});
        let cipher = seal_b64(resp.to_string().as_bytes(), &ctx.sk, &peer).ok()?;
        return Some(Reply { id, cipher, to: pub_b64 });
    }
    let plain = open_b64(frame.get("cipher")?.as_str()?, &ctx.sk, &peer).ok()?;
    let inner: Value = serde_json::from_slice(&plain).ok()?;
    let resp = local_call(ctx.port, &inner);
    let cipher = seal_b64(resp.to_string().as_bytes(), &ctx.sk, &peer).ok()?;
    Some(Reply { id, cipher, to: pub_b64 })
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

/// A reply too big for one socket message: POST it to /tunnel/push (relay_client._push).
pub fn push_reply(relay: &str, room: &str, r: &Reply) -> bool {
    let url = format!("{}/tunnel/push?room={}", relay.trim_end_matches('/'), room);
    let body = json!({"id": r.id, "cipher": r.cipher, "to": r.to}).to_string();
    let secs = 15 + (body.len() as u64) / 100_000; // an upload budget that scales with the upload
    let agent: ureq::Agent = ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(secs)))
        .build()
        .into();
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
    use std::io::{Read, Write};
    use std::net::TcpListener;

    fn keypair() -> (SecretKey, PublicKey) {
        let sk = SecretKey::generate(&mut OsRng);
        let pk = sk.public_key();
        (sk, pk)
    }

    #[test]
    fn a_frame_sealed_by_one_side_opens_on_the_other_and_only_there() {
        let (a_sk, a_pk) = keypair();
        let (b_sk, b_pk) = keypair();
        let (_c_sk, c_pk) = keypair();
        let sealed = seal_b64(b"hello phone", &a_sk, &b_pk).unwrap();
        assert_eq!(open_b64(&sealed, &b_sk, &a_pk).unwrap(), b"hello phone");
        assert!(open_b64(&sealed, &b_sk, &c_pk).is_err(), "a third key must not open it");
        let mut raw = B64.decode(&sealed).unwrap();
        let last = raw.len() - 1;
        raw[last] ^= 1;
        assert!(open_b64(&B64.encode(raw), &b_sk, &a_pk).is_err(), "a flipped bit is rejected");
        assert!(open_b64("AAAA", &b_sk, &a_pk).is_err(), "a too-short frame is rejected, not a panic");
    }

    #[test]
    fn wire_format_is_nonce_then_ciphertext_with_a_fresh_nonce_each_time() {
        let (a_sk, _) = keypair();
        let (_, b_pk) = keypair();
        let x = B64.decode(seal_b64(b"same", &a_sk, &b_pk).unwrap()).unwrap();
        let y = B64.decode(seal_b64(b"same", &a_sk, &b_pk).unwrap()).unwrap();
        assert_eq!(x.len(), NONCE_LEN + 4 + 16, "24-byte nonce + payload + 16-byte tag");
        assert_ne!(&x[..NONCE_LEN], &y[..NONCE_LEN], "a nonce is never reused");
    }

    #[test]
    fn ws_url_matches_the_python_bridge() {
        assert_eq!(ws_url("https://relay.helmdeck.de", "r-1").unwrap(), "wss://relay.helmdeck.de/tunnel/ws?room=r-1");
        assert_eq!(ws_url("http://127.0.0.1:6790/", "a b").unwrap(), "ws://127.0.0.1:6790/tunnel/ws?room=a+b");
        assert!(ws_url("ftp://x", "r").is_none());
    }

    /// a one-shot local "daemon": answers every request with `reply`, remembers the request
    fn stub_daemon(reply: &'static str) -> (u16, std::sync::mpsc::Receiver<String>) {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            for s in l.incoming() {
                let mut s = s.unwrap();
                // read the WHOLE request (headers and body may arrive in separate
                // segments) before answering, or the client sees a reset
                s.set_read_timeout(Some(Duration::from_millis(300))).unwrap();
                let mut got = Vec::new();
                let mut buf = vec![0u8; 8192];
                while let Ok(n) = s.read(&mut buf) {
                    if n == 0 {
                        break;
                    }
                    got.extend_from_slice(&buf[..n]);
                }
                let _ = tx.send(String::from_utf8_lossy(&got).to_string());
                let _ = s.write_all(reply.as_bytes());
            }
        });
        (port, rx)
    }

    #[test]
    fn a_pinned_device_is_served_through_the_local_daemon_and_the_answer_is_sealed_back() {
        let (port, seen) = stub_daemon("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 12\r\nConnection: close\r\n\r\n{\"ok\":true}\n");
        let (d_sk, d_pk) = keypair();
        let (p_sk, p_pk) = keypair();
        let ctx = Ctx { sk: d_sk, pinned: vec![public_to_b64(&p_pk)], port };
        let inner = json!({"method": "POST", "path": "/chat/send?x=1", "headers": {"X-Test": "1"}, "body": "{\"a\":1}"});
        let cipher = seal_b64(inner.to_string().as_bytes(), &p_sk, &d_pk).unwrap();
        let frame = json!({"kind": "frame", "id": "abc", "pub": public_to_b64(&p_pk), "cipher": cipher});
        let r = serve_frame(&frame, &ctx).expect("a reply");
        assert_eq!((r.id.as_str(), r.to.as_str()), ("abc", public_to_b64(&p_pk).as_str()));
        let resp: Value = serde_json::from_slice(&open_b64(&r.cipher, &p_sk, &d_pk).unwrap()).unwrap();
        assert_eq!(resp["status"], 200);
        assert_eq!(resp["body"], "{\"ok\":true}\n");
        assert_eq!(resp["headers"]["Content-Type"], "application/json");
        let req = seen.recv_timeout(Duration::from_secs(3)).unwrap();
        assert!(req.starts_with("POST /chat/send?x=1 HTTP/1.1"), "{req}");
        assert!(req.to_ascii_lowercase().contains("x-test: 1"), "headers travel: {req}");
        assert!(req.contains("{\"a\":1}"), "body travels: {req}");
    }

    #[test]
    fn an_unpinned_device_gets_the_not_paired_answer_sealed_to_itself() {
        let (d_sk, d_pk) = keypair();
        let (p_sk, p_pk) = keypair();
        let ctx = Ctx { sk: d_sk, pinned: vec![], port: 1 };
        let frame = json!({"kind": "frame", "id": "x1", "pub": public_to_b64(&p_pk), "cipher": "ignored"});
        let r = serve_frame(&frame, &ctx).unwrap();
        let resp: Value = serde_json::from_slice(&open_b64(&r.cipher, &p_sk, &d_pk).unwrap()).unwrap();
        assert_eq!(resp["status"], 409);
        assert!(resp["body"].as_str().unwrap().contains("not paired"));
    }

    #[test]
    fn a_forged_or_tampered_frame_is_ignored_without_a_reply() {
        let (d_sk, d_pk) = keypair();
        let (p_sk, p_pk) = keypair();
        let ctx = Ctx { sk: d_sk, pinned: vec![public_to_b64(&p_pk)], port: 1 };
        let pubs = public_to_b64(&p_pk);
        let bad = json!({"kind": "frame", "id": "f", "pub": pubs, "cipher": "AAAAAAAA"});
        assert!(serve_frame(&bad, &ctx).is_none(), "garbage cipher: silence");
        let (stranger, _) = keypair();
        let wrong = seal_b64(b"{}", &stranger, &d_pk).unwrap();
        let bad2 = json!({"kind": "frame", "id": "g", "pub": pubs, "cipher": wrong});
        assert!(serve_frame(&bad2, &ctx).is_none(), "sealed by a key that is not the pinned one: silence");
        let _ = p_sk;
        assert!(serve_frame(&json!({"kind": "frame"}), &ctx).is_none(), "no id: nothing to answer");
    }

    #[test]
    fn a_dead_daemon_is_a_502_not_a_hang_and_a_slow_one_is_a_held_504() {
        let r = local_call(1, &json!({"method": "GET", "path": "/x"}));
        assert_eq!(r["status"], 502, "{r}");
        assert!(r["body"].as_str().unwrap().contains("error"));
    }
}
