# -*- coding: utf-8 -*-
"""THE ALWAYS-ON READER of Henry's warm chat process (Paseo parity: the
provider's stdout is pumped for the life of the process, never only while a
turn is open).

MEASURED 2026-09-16 19:05 (probe: `claude -p --output-format stream-json
--verbose` + an Agent with run_in_background): the CLI writes EVERY
sub-agent event to stdout - `assistant`/`user` frames with
parent_tool_use_id set, `system/task_progress`, and at the end
`system/task_notification` followed by a turn the CLI runs ON ITS OWN
(second init + Henry's reaction + a result frame). Until now stdout was read
only inside a turn (chat pump, keepalive ping, _control). Between turns the
pipe filled, the child BLOCKED on write, and Henry's Explore agent advanced
exactly one step per keepalive ping: its transcript timestamps (18:51:35,
18:55:40, 18:59:42, 19:03:48) are the ping times. "Nur kurze Anweisung und
er arbeitet 20 Minuten" - it worked 4 minutes per step, and the CLI's own
follow-up turn streamed into a pipe nobody read, to be taken by the next
ping as ITS result.

So: one reader thread per process. While a consumer is attached (a turn, a
ping, a control round-trip) the lines go to the consumer's queue - the wire
order and the consumer's code are unchanged. While NOBODY is attached the
lines go to the idle handler (copilot._idle_frame): fold the background
registry, notice the CLI's own between-turns turn, and hand the cue to the
auto-continue. The child never blocks again."""
import queue
import threading


class Port:
    def __init__(self, p, on_idle):
        self.p = p
        self.q = queue.Queue()
        self.active = False          # a consumer is attached (set BEFORE its stdin write)
        self.eof = False
        self.on_idle = on_idle
        threading.Thread(target=self._reader, daemon=True, name="henry-port-%s" % getattr(p, "pid", "?")).start()

    def _reader(self):
        try:
            for line in self.p.stdout:
                if self.active:
                    self.q.put(line)
                else:
                    try:
                        self.on_idle(line)
                    except Exception:                    # noqa: BLE001
                        pass                             # idle folding is best-effort, never the reader
        except Exception:                                # noqa: BLE001
            pass
        self.eof = True
        self.q.put(None)

    def begin(self):
        """Attach a consumer. Call BEFORE writing the request to stdin, or the
        first reply frames race into the idle handler."""
        self.active = True

    def lines(self):
        """The consumer's line iterator - ends on EOF (sticky) and detaches
        when the caller stops iterating (break -> generator close)."""
        self.active = True
        try:
            while True:
                line = self.q.get()
                if line is None:
                    self.q.put(None)                     # EOF stays visible to the next consumer
                    return
                yield line
        finally:
            self.active = False


def attach(p, on_idle):
    """Give `p` an always-on reader; idempotent."""
    if getattr(p, "_hd_port", None) is None:
        p._hd_port = Port(p, on_idle)
    return p._hd_port


def begin(p):
    port = getattr(p, "_hd_port", None)
    if port is not None:
        port.begin()


def lines(p):
    """Line iterator for whoever consumes `p`'s stdout: the port's queue when
    one is attached, the raw pipe otherwise (one-shot processes, test fakes)."""
    port = getattr(p, "_hd_port", None)
    if port is None:
        return iter(p.stdout)
    return port.lines()
