# -*- coding: utf-8 -*-
"""Teach mode: record the OWNER doing a task once. Screen video (wincap) + input events
(pynput) + foreground-window changes — the demonstration an agent learns a playbook from.

Click coordinates alone don't teach much; the foreground-window title at each moment is
what gives the distiller context ('clicked in "Checkout – Edge"'). Keystrokes are batched
into readable chunks and Ctrl+Esc ends the session (chosen because it never collides with
normal app shortcuts)."""
import ctypes, threading, time
from pynput import mouse, keyboard
import wincap
from actionlog import ActionLog
from runs import new_run, finish_run

def _fg_window():
    try:
        h = ctypes.windll.user32.GetForegroundWindow()
        n = ctypes.windll.user32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(h, buf, n + 1)
        return buf.value or "(desktop)"
    except Exception:
        return "?"

def record_demo(title):
    rid, run_dir = new_run("teach", title)
    log = ActionLog(run_dir)
    log.log("note", "TEACH demo started: " + title)
    cap = wincap.start(run_dir)
    stop_evt = threading.Event()
    state = {"win": "", "buf": "", "ctrl": False}

    def flush_typing():
        if state["buf"]:
            log.log("type", state["buf"], window=state["win"])
            state["buf"] = ""

    def on_click(x, y, button, pressed):
        if not pressed:
            return
        flush_typing()
        w = _fg_window()
        state["win"] = w
        log.log("click", 'in "%s"' % w, x=x, y=y, button=str(button))

    def on_scroll(x, y, dx, dy):
        pass  # scroll spam adds nothing to a playbook

    def on_press(key):
        w = _fg_window()
        if w != state["win"]:
            flush_typing()
            state["win"] = w
            log.log("focus", w)
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            state["ctrl"] = True
        elif key == keyboard.Key.esc and state["ctrl"]:
            stop_evt.set()
            return False
        elif hasattr(key, "char") and key.char:
            state["buf"] += key.char
        else:
            flush_typing()
            name = getattr(key, "name", str(key))
            if name not in ("ctrl_l", "ctrl_r", "shift", "shift_r", "alt_l", "alt_gr"):
                log.log("key", name, window=w)

    def on_release(key):
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            state["ctrl"] = False

    ml = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
    kl = keyboard.Listener(on_press=on_press, on_release=on_release)
    ml.start(); kl.start()
    print("RECORDING '%s' — do the task now. Ctrl+Esc to stop." % title)
    stop_evt.wait()
    flush_typing()
    ml.stop()
    log.log("note", "TEACH demo ended")
    wincap.stop(cap)
    finish_run(run_dir, "done")
    print("saved:", run_dir)
    return rid, run_dir
