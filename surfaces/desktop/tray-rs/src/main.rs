// GUI binary in release, console in debug so the CLI modes below can print.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! HelmDeck tray (Rust prototype of surfaces/desktop/tray.py).
//!
//!   helmdeck-tray [--root DIR] [--port N] [--watch-only]
//!   helmdeck-tray --once            print daemon/relay/autostart state as JSON, exit
//!   helmdeck-tray --dump-icon DIR   write icon-up.png / icon-down.png, exit
//!
//! --watch-only never spawns or stops a daemon: it can run beside the Python
//! tray (or any live daemon) and only shows what it sees. Autostart is never
//! touched at startup (unlike tray.py's repair) - only the menu item changes
//! it, because this is a prototype and must not replace the production Run
//! entry by merely being started.

use std::path::PathBuf;
use std::process::Command;
use std::sync::mpsc;
use std::time::Duration;

use helmdeck_tray as hd;
use tao::event::{Event, StartCause};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tray_icon::menu::{CheckMenuItem, Menu, MenuEvent, MenuItem, PredefinedMenuItem};
use tray_icon::{Icon, TrayIconBuilder, TrayIconEvent};

#[derive(Clone, PartialEq)]
struct Snapshot {
    daemon: bool,
    relay: String,
    ours: Option<u32>,
}

enum UserEvent {
    State(Snapshot),
    Menu(MenuEvent),
    DoubleClick,
}

enum Cmd {
    Restart,
    Quit,
}

fn arg(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1).cloned())
}

fn icon_for(ok: bool) -> Icon {
    let (rgba, w, h) = hd::icon_rgba(ok);
    Icon::from_rgba(rgba, w, h).expect("icon")
}

fn open_ui(port: u16) {
    use std::os::windows::process::CommandExt;
    let _ = Command::new("rundll32")
        .args(["url.dll,FileProtocolHandler", &format!("http://127.0.0.1:{port}/")])
        .creation_flags(hd::CREATE_NO_WINDOW)
        .spawn();
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let port: u16 = arg(&args, "--port").and_then(|p| p.parse().ok()).unwrap_or(hd::DEFAULT_PORT);
    let watch_only = args.iter().any(|a| a == "--watch-only");

    if let Some(dir) = arg(&args, "--dump-icon") {
        let dir = PathBuf::from(dir);
        std::fs::create_dir_all(&dir).expect("dir");
        hd::write_icon_png(&dir.join("icon-up.png"), true).expect("png");
        hd::write_icon_png(&dir.join("icon-down.png"), false).expect("png");
        println!("wrote {}", dir.display());
        return;
    }

    let root = hd::find_root(arg(&args, "--root").as_deref());
    let Some(root) = root else {
        eprintln!("helmdeck-tray: repo root not found (--root DIR or HELMDECK_ROOT)");
        std::process::exit(2);
    };
    let daemon_dir = root.join("daemon");
    let exe = std::env::current_exe().expect("exe");

    if args.iter().any(|a| a == "--once") {
        println!(
            "{}",
            serde_json::json!({
                "daemon": hd::health(port),
                "relay": hd::relay_status(&daemon_dir),
                "autostart": hd::autostart_value(),
                "root": root,
                "python": hd::find_python(),
            })
        );
        return;
    }

    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();

    // ---- supervisor thread: owns the child, beats every 4 s, takes commands
    let (tx, rx) = mpsc::channel::<Cmd>();
    let sup_proxy = event_loop.create_proxy();
    let sup_root = root.clone();
    let sup_dir = daemon_dir.clone();
    let sup = std::thread::spawn(move || {
        let python = hd::find_python();
        let spawn_root = sup_root.clone();
        let mut sv = hd::Supervisor::new(
            move || hd::health(port),
            move || {
                if watch_only {
                    return Err(std::io::Error::other("watch-only"));
                }
                let py = python.clone().ok_or_else(|| std::io::Error::other("no pythonw.exe"))?;
                hd::spawn_daemon(&spawn_root, &py, port)
            },
        );
        let mut last: Option<Snapshot> = None;
        loop {
            let up = sv.tick();
            let snap = Snapshot {
                daemon: up,
                relay: if up { hd::relay_status(&sup_dir) } else { "Desktop aus".into() },
                ours: sv.our_pid(),
            };
            if last.as_ref() != Some(&snap) {
                let _ = sup_proxy.send_event(UserEvent::State(snap.clone()));
                last = Some(snap);
            }
            match rx.recv_timeout(Duration::from_secs(4)) {
                Ok(Cmd::Restart) => {
                    if !watch_only {
                        sv.restart();
                    }
                }
                Ok(Cmd::Quit) | Err(mpsc::RecvTimeoutError::Disconnected) => {
                    if !watch_only {
                        sv.restart(); // stops only a daemon WE started
                    }
                    return;
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
            }
        }
    });

    // ---- menu (items live on the main thread; updated from State events)
    let m_daemon = MenuItem::new("Daemon: …", false, None);
    let m_relay = MenuItem::new("Relay: …", false, None);
    let m_open = MenuItem::new("Web-UI / Handy koppeln", true, None);
    let m_restart = MenuItem::new("Daemon neu starten", !watch_only, None);
    let m_auto = CheckMenuItem::new("Bei Anmeldung starten", true, hd::autostart_value().is_some(), None);
    let m_quit = MenuItem::new("Beenden", true, None);
    let menu = Menu::new();
    menu.append_items(&[
        &m_daemon,
        &m_relay,
        &PredefinedMenuItem::separator(),
        &m_open,
        &m_restart,
        &m_auto,
        &PredefinedMenuItem::separator(),
        &m_quit,
    ])
    .expect("menu");
    let (id_open, id_restart, id_auto, id_quit) =
        (m_open.id().clone(), m_restart.id().clone(), m_auto.id().clone(), m_quit.id().clone());

    let p1 = proxy.clone();
    MenuEvent::set_event_handler(Some(move |e| {
        let _ = p1.send_event(UserEvent::Menu(e));
    }));
    let p2 = proxy.clone();
    TrayIconEvent::set_event_handler(Some(move |e| {
        if matches!(e, TrayIconEvent::DoubleClick { .. }) {
            let _ = p2.send_event(UserEvent::DoubleClick);
        }
    }));

    let mut tray = None;
    let mut sup = Some(sup);
    let mut tx = Some(tx);
    let auto_cmd = hd::autostart_cmd(&exe, &root);

    event_loop.run(move |event, _, flow| {
        *flow = ControlFlow::Wait;
        match event {
            Event::NewEvents(StartCause::Init) => {
                tray = TrayIconBuilder::new()
                    .with_menu(Box::new(menu.clone()))
                    .with_tooltip("HelmDeck")
                    .with_icon(icon_for(false))
                    .build()
                    .ok();
            }
            Event::UserEvent(UserEvent::State(s)) => {
                m_daemon.set_text(format!("Daemon: {}", if s.daemon { "läuft ✓" } else { "aus ✕" }));
                m_relay.set_text(format!("Relay: {}", s.relay));
                if let Some(t) = tray.as_ref() {
                    let _ = t.set_icon(Some(icon_for(s.daemon)));
                    let _ = t.set_tooltip(Some(hd::tooltip(s.daemon, &s.relay)));
                }
            }
            Event::UserEvent(UserEvent::DoubleClick) => open_ui(port),
            Event::UserEvent(UserEvent::Menu(e)) => {
                if e.id == id_open {
                    open_ui(port);
                } else if e.id == id_restart {
                    if let Some(t) = tx.as_ref() {
                        let _ = t.send(Cmd::Restart);
                    }
                } else if e.id == id_auto {
                    let on = m_auto.is_checked();
                    if hd::set_autostart(on, &auto_cmd).is_err() {
                        m_auto.set_checked(!on); // the write failed: show the truth
                    }
                } else if e.id == id_quit {
                    if let Some(t) = tx.take() {
                        let _ = t.send(Cmd::Quit);
                    }
                    if let Some(h) = sup.take() {
                        let _ = h.join();
                    }
                    tray.take();
                    *flow = ControlFlow::Exit;
                }
            }
            _ => {}
        }
    });
}
