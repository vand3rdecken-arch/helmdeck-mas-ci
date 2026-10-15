# -*- coding: utf-8 -*-
"""Reference-class forecast for Henry's time promises (owner 2026-10-15,
Flyvbjerg: the duration of a new job is the measured duration of similar past
jobs, not a gut feeling).

DATA MODEL: no new storage. Everything is DERIVED from what is already
recorded at event time:
  - agent / hands runs: `chat_runs` (descriptor `since` .. `updated`, kind)
  - cards: the append-only `events` log (lane->working, turn, answer, steer,
    autocontinue) + the card flags in `tracks` (machine / direct / fast_track)

PURE AGENT TIME. A card's clock runs from a START marker (dispatch to
`working`, an owner answer, a steer, a daemon autocontinue) to the next `turn`
event (the worker's turn ended). The gap from a turn end to the next start
marker is waiting - on the owner's answer or review - and is NOT counted. LIMIT
(measured, not hidden): a turn that was blocked INSIDE the worker on something
external (a login, a human at a console) still counts as agent time, because
the log has no event for it; and `direct_wait` tree-lock waits are inside the
segment. Both push P80 up, which is the safe direction for a promise.

Observability only (Paseo parity: a number the agent reads, no rule). The
brief tells Henry to quote it; what he promises stays his judgement.
"""
import json

DAYS = 30
MIN_N = 5          # below this a percentile is noise: say so instead of quoting it

# render order = how Henry thinks about work, cheapest first
CLASSES = ("agent", "hands", "direct_fast", "direct", "machine", "file_card")
_LABEL = {"agent": "agent", "hands": "hands", "direct_fast": "direct_task fast_track",
          "direct": "direct_task", "machine": "machine_task", "file_card": "file_card"}
_START = ("lane", "answer", "autocontinue", "touch")


def _pct(xs, p):
    """Nearest-rank percentile of a non-empty list."""
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(p * len(xs) + 0.5)) - 1))]


def _card_class(t):
    if t.get("machine") and not t.get("direct"):
        return "machine"
    if t.get("direct"):
        return "direct_fast" if t.get("fast_track") else "direct"
    return "file_card"


def _epoch(utc):
    import calendar
    import time
    try:
        return calendar.timegm(time.strptime(utc[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None


def samples(c=None, now=None, days=DAYS):
    """{class: [seconds, ...]} of pure agent runtime over the last `days`."""
    import time
    if c is None:
        from spine.storage import db
        c = db.conn()
    now = now or time.time()
    since = now - days * 86400
    out = {k: [] for k in CLASSES}
    for kind, s, u in c.execute(
            "SELECT json_extract(data,'$.kind'), json_extract(data,'$.since'), "
            "json_extract(data,'$.updated') FROM chat_runs WHERE status='completed'"):
        if kind in ("agent", "hands") and s and u and u >= since and u > s:
            out[kind].append(u - s)
    cards = {}
    for tid, d in c.execute("SELECT id, data FROM tracks"):
        try:
            t = json.loads(d)
        except ValueError:
            continue
        if not t.get("example"):
            cards[tid] = _card_class(t)
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))
    mark = None
    total, last_track = {}, None
    rows = c.execute(
        "SELECT track, kind, at_utc, json_extract(data,'$.to'), json_extract(data,'$.touch') "
        "FROM events WHERE kind IN ('lane','answer','autocontinue','touch','turn') "
        "AND track IS NOT NULL AND at_utc >= ? ORDER BY track, seq", (cutoff,))
    for track, kind, at, to, touch in rows:
        if track not in cards:
            continue
        t = _epoch(at)
        if t is None:
            continue
        if track != last_track:
            mark, last_track = None, track
        if kind == "turn":
            if mark is not None:
                total[track] = total.get(track, 0) + max(0, t - mark)
            mark = None
        elif kind == "lane":
            if to == "working":
                mark = t
        elif kind == "touch":
            if touch == "steer":
                mark = t
        elif mark is None:                     # answer / autocontinue restart the clock
            mark = t
    for track, secs in total.items():
        if secs > 0:
            out[cards[track]].append(secs)
    return out


def stats(c=None, now=None, days=DAYS):
    """{class: {n, p50, p80}} in seconds; p50/p80 None while n < MIN_N."""
    res = {}
    for k, xs in samples(c, now, days).items():
        ok = len(xs) >= MIN_N
        res[k] = {"n": len(xs), "p50": _pct(xs, .5) if ok else None, "p80": _pct(xs, .8) if ok else None}
    return res


def _min(s):
    m = s / 60.0
    return "%.0f" % m if m >= 10 else "%.1f" % m


def duration_line(c=None, now=None):
    """The one board_state line. '' when the log holds nothing at all."""
    st = stats(c, now)
    if not any(v["n"] for v in st.values()):
        return ""
    parts = []
    for k in CLASSES:
        v = st[k]
        if v["p50"] is None:
            parts.append("%s zu wenig Daten (n=%d)" % (_LABEL[k], v["n"]))
        else:
            parts.append("%s P50 %s / P80 %s min (n=%d)" % (_LABEL[k], _min(v["p50"]), _min(v["p80"]), v["n"]))
    return ("DAUER TYPISCH (letzte %d Tage, reine Agentenlaufzeit ohne Warten auf den Owner): %s"
            % (DAYS, ", ".join(parts)))
