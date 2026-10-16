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
    Update(String),
    Menu(MenuEvent),
    DoubleClick,
    Quit,
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
    let daemon_dir = hd::data_dir(&root);
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

    if !hd::single_instance(port) {
        std::process::exit(4); // another tray already supervises this daemon port
    }

    hd::log_line(&daemon_dir, &format!("tray start: root {}, port {port}{}", root.display(), if watch_only { ", watch-only" } else { "" }));
    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();

    // test/benchmark helper: leave through the SAME quit path as the menu
    if let Some(secs) = arg(&args, "--run-for").and_then(|s| s.parse::<u64>().ok()) {
        let p = proxy.clone();
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_secs(secs));
            let _ = p.send_event(UserEvent::Quit);
        });
    }

    // ---- supervisor thread: owns the child, beats every 4 s, takes commands
    let (tx, rx) = mpsc::channel::<Cmd>();
    let sup_proxy = event_loop.create_proxy();
    let sup_root = root.clone();
    let sup_dir = daemon_dir.clone();
    let exe_for_sup = exe.clone();
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
                let child = hd::spawn_daemon(&spawn_root, &py, port);
                if let Ok(c) = &child {
                    hd::log_line(&hd::data_dir(&spawn_root), &format!("daemon spawned, pid {}", c.id()));
                }
                child
            },
        );
        // the key-less relay bridge: runs exactly while relay.engine == "pipe" (read from the db each beat)
        let bridge_exe = hd::find_bridge(exe_for_sup.parent().unwrap_or(std::path::Path::new(".")), &sup_root);
        let bridge_dir = sup_dir.clone();
        let mut bridge = hd::BridgeKeeper::new(move || {
            let b = bridge_exe.clone().ok_or_else(|| std::io::Error::other("helmdeck-relay-bridge.exe not found"))?;
            let child = hd::spawn_bridge(&b, &bridge_dir);
            if let Ok(c) = &child {
                hd::log_line(&bridge_dir, &format!("relay bridge spawned, pid {}", c.id()));
            }
            child
        });
        let mut last: Option<Snapshot> = None;
        loop {
            let up = sv.tick();
            let row = hd::relay_row(&sup_dir);
            let bridge_state = if watch_only { hd::BridgeState::Off } else { bridge.tick(hd::relay_engine_is_pipe(row.as_deref())) };
            let mut relay = if up { hd::relay_status_from_json(row.as_deref()) } else { "Desktop aus".into() };
            match bridge_state {
                hd::BridgeState::Running(_) => relay.push_str(" · Brücke"),
                hd::BridgeState::Waiting => relay.push_str(" · Brücke wartet"),
                hd::BridgeState::Off => {}
            }
            let snap = Snapshot {
                daemon: up,
                relay,
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
                    bridge.stop(); // ...and only a bridge we started
                    return;
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
            }
        }
    });

    // ---- desktop-shell update thread: the shared Python engine, Paseo's cadence.
    // Not run in --watch-only (that mode must have no side effects) or --no-update.
    let (upd_tx, upd_rx) = mpsc::channel::<()>();
    let upd_thread = if watch_only || args.iter().any(|a| a == "--no-update") {
        None
    } else {
        let (u_root, u_data, u_proxy) = (root.clone(), daemon_dir.clone(), proxy.clone());
        Some(std::thread::spawn(move || {
            let Some(py) = hd::find_python_console() else {
                let _ = u_proxy.send_event(UserEvent::Update("aus (kein Python gefunden)".into()));
                return;
            };
            loop {
                let r = hd::run_update_once(&u_root, &py, &u_data);
                hd::log_line(&u_data, &format!("update: {}", r.text));
                let _ = u_proxy.send_event(UserEvent::Update(r.text.clone()));
                // the sender is dropped on quit: the wait ends at once
                if let Err(mpsc::RecvTimeoutError::Disconnected) = upd_rx.recv_timeout(hd::next_update_delay(&r)) {
                    return;
                }
            }
        }))
    };

    // ---- menu (items live on the main thread; updated from State events)
    let m_daemon = MenuItem::new("Daemon: …", false, None);
    let m_relay = MenuItem::new("Relay: …", false, None);
    let m_update = MenuItem::new("Update: prüft …", false, None);
    let m_open = MenuItem::new("Web-UI / Handy koppeln", true, None);
    let m_restart = MenuItem::new("Daemon neu starten", !watch_only, None);
    let m_auto = CheckMenuItem::new("Bei Anmeldung starten", true, hd::autostart_value().is_some(), None);
    let m_quit = MenuItem::new("Beenden", true, None);
    let menu = Menu::new();
    menu.append_items(&[
        &m_daemon,
        &m_relay,
        &m_update,
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
    let mut upd_tx = Some(upd_tx);
    let _upd_thread = upd_thread; // detached on quit: a running check must not hold the exit
    let p_quit = proxy.clone();
    let log_dir = daemon_dir.clone();
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
            Event::UserEvent(UserEvent::Update(text)) => {
                m_update.set_text(format!("Update: {text}"));
            }
            Event::UserEvent(UserEvent::Quit) => {
                hd::log_line(&log_dir, "tray quit");
                upd_tx.take(); // ends the update thread's wait
                if let Some(t) = tx.take() {
                    let _ = t.send(Cmd::Quit);
                }
                if let Some(h) = sup.take() {
                    let _ = h.join();
                }
                tray.take();
                *flow = ControlFlow::Exit;
            }
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
                    let _ = p_quit.send_event(UserEvent::Quit); // one quit path for menu and --run-for
                }
            }
            _ => {}
        }
    });
}
