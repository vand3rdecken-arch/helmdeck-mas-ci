# -*- coding: utf-8 -*-
"""Teach mode: record the OWNER doing a task once. Screen video (wincap) + input events
(pynput) + foreground-window changes - the demonstration an agent learns a playbook from.

Click coordinates alone don't teach much; the foreground-window title at each moment is
what gives the distiller context ('clicked in "Checkout – Edge"'). Keystrokes are batched
into readable chunks. Two ways to stop: Ctrl+Esc at the keyboard, or TeachSession.stop()
(the phone's stop button via the control API - same capabilities on mobile)."""
import ctypes, threading
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

class TeachSession:
    """One demo recording. start() arms capture+hooks; stop() finalizes (idempotent)."""

    def __init__(self, title):
        self.title = title
        self.rid, self.run_dir = new_run("teach", title)
        self.log = ActionLog(self.run_dir)
        self.stopped = threading.Event()
        self._state = {"win": "", "buf": "", "ctrl": False}
        self._cap = None
        self._ml = None
        self._kl = None

    def start(self):
        self.log.log("note", "TEACH demo started: " + self.title)
        self._cap = wincap.start(self.run_dir)
        st = self._state

        def flush_typing():
            if st["buf"]:
                self.log.log("type", st["buf"], window=st["win"])
                st["buf"] = ""
        self._flush = flush_typing

        def on_click(x, y, button, pressed):
            if not pressed:
                return
            flush_typing()
            w = _fg_window()
            st["win"] = w
            self.log.log("click", 'in "%s"' % w, x=x, y=y, button=str(button))

        def on_press(key):
            w = _fg_window()
            if w != st["win"]:
                flush_typing()
                st["win"] = w
                self.log.log("focus", w)
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                st["ctrl"] = True
            elif key == keyboard.Key.esc and st["ctrl"]:
                threading.Thread(target=self.stop, daemon=True).start()
                return False
            elif hasattr(key, "char") and key.char:
                st["buf"] += key.char
            else:
                flush_typing()
                name = getattr(key, "name", str(key))
                if name not in ("ctrl_l", "ctrl_r", "shift", "shift_r", "alt_l", "alt_gr"):
                    self.log.log("key", name, window=w)

        def on_release(key):
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                st["ctrl"] = False

        self._ml = mouse.Listener(on_click=on_click)
        self._kl = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._ml.start()
        self._kl.start()
        return self

    def stop(self):
        if self.stopped.is_set():
            return self.rid
        self.stopped.set()
        try: self._flush()
        except Exception: pass
        for l in (self._ml, self._kl):
            try:
                if l: l.stop()
            except Exception: pass
        self.log.log("note", "TEACH demo ended")
        if self._cap:
            wincap.stop(self._cap)
        finish_run(self.run_dir, "done")
        return self.rid

def record_demo(title):
    """CLI path: record until Ctrl+Esc."""
    s = TeachSession(title).start()
    print("RECORDING '%s' - do the task now. Ctrl+Esc to stop." % title)
    s.stopped.wait()
    print("saved:", s.run_dir)
    return s.rid, s.run_dir
