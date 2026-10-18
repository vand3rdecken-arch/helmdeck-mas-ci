//! The local server for the exported web app (surfaces/app/dist) - what `startWeb()` in
//! surfaces/desktop/main.js does for the Electron shell, with the same rules:
//!
//! * a missing path falls back to `index.html` (client-side routes of the SPA);
//! * the entry documents (`.html`, `.json`, no extension) are NEVER cached - the Electron
//!   shell once served a stale bundle for weeks because index.html was heuristically cached
//!   ("auf dem Desktop kommt nichts an"); hashed assets are immutable;
//! * `..` in a path is refused.
//!
//! Plain std sockets: one short-lived thread per connection, `Connection: close`. The only
//! client is the app's own window on loopback.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const UI_PORT: u16 = 3300;

/// Where the built web app is, first hit wins: `HELMDECK_APP_DIST`, `app-dist` next to the
/// exe (packaged), `surfaces/app/dist` of the checkout (walking up from the exe and the cwd),
/// the folder an installed Electron shell keeps and the OTA updater refreshes.
pub fn resolve_app_dist() -> Option<PathBuf> {
    let ok = |p: &Path| p.join("index.html").is_file();
    if let Ok(p) = std::env::var("HELMDECK_APP_DIST") {
        let p = PathBuf::from(p);
        if ok(&p) {
            return Some(p);
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(d) = exe.parent() {
            // next to the exe (Windows installs), or Contents/Resources of a macOS .app (exe in Contents/MacOS)
            for p in [d.join("app-dist"), d.join("..").join("Resources").join("app-dist")] {
                if ok(&p) {
                    return Some(p);
                }
            }
        }
    }
    let starts = [std::env::current_exe().ok(), std::env::current_dir().ok()];
    for start in starts.into_iter().flatten() {
        let mut cur: Option<&Path> = Some(start.as_path());
        while let Some(p) = cur {
            let cand = p.join("surfaces").join("app").join("dist");
            if ok(&cand) {
                return Some(cand);
            }
            cur = p.parent();
        }
    }
    let installed = PathBuf::from(r"C:\HelmDeck\resources\app-dist");
    ok(&installed).then_some(installed)
}

fn mime(ext: &str) -> &'static str {
    match ext {
        "html" => "text/html; charset=utf-8",
        "js" => "text/javascript",
        "css" => "text/css",
        "json" => "application/json",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "svg" => "image/svg+xml",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "ttf" => "font/ttf",
        "ico" => "image/x-icon",
        "map" => "application/json",
        _ => "application/octet-stream",
    }
}

fn percent_decode(s: &str) -> Option<String> {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' {
            let h = std::str::from_utf8(b.get(i + 1..i + 3)?).ok()?;
            out.push(u8::from_str_radix(h, 16).ok()?);
            i += 3;
        } else {
            out.push(b[i]);
            i += 1;
        }
    }
    String::from_utf8(out).ok()
}

pub struct Resp {
    pub status: u16,
    pub content_type: &'static str,
    pub cache: &'static str,
    pub body: Vec<u8>,
}

/// The whole routing rule, pure, so it is testable without a socket.
pub fn respond(dist: &Path, raw_target: &str) -> Resp {
    let path_only = raw_target.split(['?', '#']).next().unwrap_or("/");
    let Some(decoded) = percent_decode(path_only) else {
        return Resp { status: 400, content_type: "text/plain", cache: "no-store", body: b"bad request".to_vec() };
    };
    let mut file = dist.to_path_buf();
    for part in decoded.split(['/', '\\']) {
        match part {
            "" | "." => {}
            ".." => return Resp { status: 403, content_type: "text/plain", cache: "no-store", body: b"forbidden".to_vec() },
            p if p.contains('\0') || p.contains(':') => {
                return Resp { status: 403, content_type: "text/plain", cache: "no-store", body: b"forbidden".to_vec() }
            }
            p => file.push(p),
        }
    }
    if !file.is_file() {
        let idx = file.join("index.html");
        file = if idx.is_file() { idx } else { dist.join("index.html") }; // SPA fallback
    }
    let Ok(body) = std::fs::read(&file) else {
        return Resp { status: 404, content_type: "text/plain", cache: "no-store", body: b"not found".to_vec() };
    };
    let ext = file.extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase();
    let no_store = matches!(ext.as_str(), "html" | "json" | "");
    Resp {
        status: 200,
        content_type: mime(&ext),
        cache: if no_store { "no-store, must-revalidate" } else { "public, max-age=31536000, immutable" },
        body,
    }
}

fn handle(mut s: TcpStream, dist: &Path) {
    let _ = s.set_read_timeout(Some(Duration::from_secs(10)));
    let mut buf = Vec::new();
    let mut chunk = [0u8; 2048];
    while !buf.windows(4).any(|w| w == b"\r\n\r\n") && buf.len() < 16 * 1024 {
        match s.read(&mut chunk) {
            Ok(0) | Err(_) => break,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
        }
    }
    let head = String::from_utf8_lossy(&buf);
    let mut it = head.lines().next().unwrap_or("").split_whitespace();
    let (method, target) = (it.next().unwrap_or(""), it.next().unwrap_or("/"));
    let r = if method == "GET" || method == "HEAD" {
        respond(dist, target)
    } else {
        Resp { status: 405, content_type: "text/plain", cache: "no-store", body: b"method not allowed".to_vec() }
    };
    let reason = match r.status { 200 => "OK", 400 => "Bad Request", 403 => "Forbidden", 404 => "Not Found", _ => "Method Not Allowed" };
    let hdr = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nCache-Control: {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        r.status, reason, r.content_type, r.cache, r.body.len()
    );
    let _ = s.write_all(hdr.as_bytes());
    if method != "HEAD" {
        let _ = s.write_all(&r.body);
    }
}

/// True when something already answers on 127.0.0.1:port (another shell, or a browser-served UI).
pub fn already_serving(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&addr, Duration::from_millis(400)).is_ok()
}

/// Bind and serve in the background. Err when the port is taken or cannot be bound.
pub fn serve(dist: PathBuf, port: u16) -> std::io::Result<()> {
    let l = TcpListener::bind(SocketAddr::from(([127, 0, 0, 1], port)))?;
    std::thread::spawn(move || {
        for s in l.incoming().flatten() {
            let d = dist.clone();
            std::thread::spawn(move || handle(s, &d));
        }
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dist() -> PathBuf {
        let d = std::env::temp_dir().join(format!("hd-ui-{}-{:?}", std::process::id(), std::thread::current().id()).replace(['(', ')'], ""));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(d.join("_expo/static/js")).unwrap();
        std::fs::write(d.join("index.html"), "<html>SPA</html>").unwrap();
        std::fs::write(d.join("data.json"), "{\"a\":1}").unwrap();
        std::fs::write(d.join("_expo/static/js/app-abc123.js"), "console.log(1)").unwrap();
        std::fs::create_dir_all(d.join("settings")).unwrap();
        std::fs::write(d.join("settings/index.html"), "<html>SETTINGS</html>").unwrap();
        d
    }

    #[test]
    fn root_and_unknown_routes_fall_back_to_the_spa_shell() {
        let d = dist();
        let r = respond(&d, "/");
        assert_eq!((r.status, r.body.as_slice()), (200, b"<html>SPA</html>".as_slice()));
        let r = respond(&d, "/chat/some-card?x=1#frag");
        assert_eq!(r.body, b"<html>SPA</html>", "a client-side route gets index.html");
        let r = respond(&d, "/missing/app.js");
        assert_eq!(r.body, b"<html>SPA</html>", "same fallback as the Electron server, even for a missing asset");
        let r = respond(&d, "/settings");
        assert_eq!(r.body, b"<html>SETTINGS</html>", "a folder with its own index.html is served");
    }

    #[test]
    fn the_shell_is_never_cached_and_hashed_assets_always_are() {
        let d = dist();
        for p in ["/", "/index.html", "/data.json", "/anything"] {
            assert!(respond(&d, p).cache.starts_with("no-store"), "{p} must not be cached");
        }
        let r = respond(&d, "/_expo/static/js/app-abc123.js");
        assert_eq!((r.content_type, r.cache), ("text/javascript", "public, max-age=31536000, immutable"));
    }

    #[test]
    fn path_traversal_is_refused_in_every_spelling() {
        let d = dist();
        for p in ["/../secret", "/a/../../x", "/%2e%2e/secret", "/..%2fsecret", "/a%5c..%5c..%5cx", "/C:/Windows/win.ini", "/x%00y"] {
            assert_eq!(respond(&d, p).status, 403, "{p}");
        }
        assert_eq!(respond(&d, "/%zz").status, 400, "broken percent-encoding");
    }

    #[test]
    fn a_real_http_round_trip_over_a_socket() {
        let d = dist();
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        drop(l);
        serve(d, port).unwrap();
        assert!(already_serving(port));
        let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
        s.write_all(b"GET /data.json HTTP/1.1\r\nHost: localhost\r\n\r\n").unwrap();
        let mut out = String::new();
        s.read_to_string(&mut out).unwrap();
        assert!(out.starts_with("HTTP/1.1 200 OK"), "{out}");
        assert!(out.contains("Cache-Control: no-store"), "{out}");
        assert!(out.ends_with("{\"a\":1}"), "{out}");
        let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
        s.write_all(b"POST / HTTP/1.1\r\n\r\n").unwrap();
        let mut out = String::new();
        s.read_to_string(&mut out).unwrap();
        assert!(out.starts_with("HTTP/1.1 405"), "only GET and HEAD: {out}");
    }
}
