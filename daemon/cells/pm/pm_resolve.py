# -*- coding: utf-8 -*-
"""PM resilience ladder + burn guard - extracted from pm.py (god-file
breakup, see daemon/spine/registry/debt.py daemon-god-files).

RESOLVE: on ANY bounce the PM actively finds a path forward before it ever
bothers you: classify the blocker (dispatch failed / dirty shared checkout /
real merge conflict / gate red) -> delegate the matching fix -> RE-SUBMIT so
the gate, not a human, decides whether the card is unstuck -> if it bounces
AGAIN, retry once with a DIFFERENT approach -> only then escalate, and
always with a concrete unblock proposal attached (_unblock_proposal).

BURN GUARD: the driver folds the mechanical signal (N identical tool calls -
it alone sees the frames); the PM owns the JUDGEMENT (legit retry vs. real
loop, it knows the card + goal) and the owner is the LAST instance
(escalated to only if the PM's own correction doesn't take). Same shape as
resolve_card_now: classify -> correct -> re-check -> escalate, bounded by
_RESOLVE_MAX.

pm._pm()/pm._ask() are imported LAZILY (inside function bodies) rather than
at module level - pm.py imports THIS module at module level (to re-export
these names unchanged for existing callers), so a top-level import back
would cycle. pm_comm's _activity/_say (no dependency back into pm.py) import
cleanly at module level."""
import os
import threading

from daemon.spine.registry import i18n as _i18n
from daemon.cells.pm.pm_state import _loopstate, _save_loopstate, _today
from daemon.cells.pm.pm_comm import _activity, _say

_RESOLVE_MAX = 2            # delegation attempts per card per day before escalating
_resolving = set()          # card ids with a fix currently in flight (thread running)
_resolving_lock = threading.Lock()   # guards _resolving + loopstate writes from threads


def _bounce_kind(t):
    """Classify WHY a card bounced, from its persisted state:
      dispatch - never got a worktree (dispatch/start failed) -> retry the start
      dirty    - 'conflict' that is really git refusing to merge over an
                 uncommitted shared checkout -> park_and_retry_merge (resolve_blocker)
      conflict - real <<<<<<< markers -> the card's own worker resolves by editing
      gate     - gate red / error / zombie note -> steer the worker with the reason"""
    from daemon.cells.engineer import sessions
    wt = t.get("worktree")
    if not wt or not os.path.isdir(wt):
        return "dispatch"
    if sessions._is_dirty_block(t.get("merge_report") or ""):
        return "dirty"
    if t.get("merge_kind") == "conflict" and t.get("merge_report"):
        return "conflict"
    return "gate"


def _unblock_proposal(t):
    """The concrete next step attached to EVERY escalation - the owner never gets
    a bare 'it is stuck', always a decision they can take in one move."""
    kind = _bounce_kind(t)
    branch = t.get("branch") or t.get("id", "")
    if kind == "dispatch":
        err = ((t.get("last_reply") or "").split("\n")[0])[:160] or "Dispatch-Fehler"
        return ("Vorschlag: Repo/Setup pruefen (%s) und die Karte dann wieder auf "
                "'In Arbeit' ziehen - meine automatischen Neustarts haben es nicht behoben." % err)
    if kind == "dirty":
        return _i18n.t("unblock.dirty", branch=branch)
    if kind == "conflict":
        rep = ((t.get("merge_report") or "").split("\n")[0])[:160]
        return _i18n.t("unblock.conflict", branch=branch, detail=rep)
    reason = (" | ".join(p.split("\n")[0] for p in (t.get("gate_report") or []))
              or (t.get("last_error") or ""))[:200] or _i18n.t("unblock.reasonFallback")
    return _i18n.t("unblock.gate", reason=reason)


def _bump_attempt(tid):
    """Count a delegation attempt (thread-safe: resolve threads and the tick
    share the loopstate file). Returns the attempt number just started (1-based)."""
    with _resolving_lock:
        st = _loopstate()
        day = st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
        att = day.setdefault("resolve_attempts", {})
        att[tid] = att.get(tid, 0) + 1
        _save_loopstate(st)
        return att[tid]


def _give_up(tid):
    """Mark a card escalation-ready: attempts exhausted, _notify_deliveries now
    pings the owner ONCE - with the unblock proposal attached."""
    with _resolving_lock:
        st = _loopstate()
        day = st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
        if tid not in day.setdefault("resolved", []):
            day["resolved"].append(tid)
        _save_loopstate(st)


def _bounced_to_resolve(tracks, pm, day):
    """Bounced cards in ALLOWED repos the coordinator can still move forward:
    fewer than _RESOLVE_MAX attempts today, not given up on (day['resolved']),
    no fix currently in flight. Cards WITHOUT a worktree count too - a failed
    dispatch is retried, not silently abandoned."""
    allow = {os.path.normcase(r) for r in (pm.get("repos") or [])}
    given_up = set(day.get("resolved", []))
    attempts = day.get("resolve_attempts") or {}
    with _resolving_lock:
        busy = set(_resolving)
    return [t for t in tracks
            if t.get("status") == "bounced" and t["id"] not in given_up
            and t["id"] not in busy
            and attempts.get(t["id"], 0) < _RESOLVE_MAX
            and t.get("mode") not in ("human", "teach", "cowork")
            and not t.get("autopilot")   # autopilot drives its own cards (processes._autopilot)
            and (not allow or os.path.normcase(t.get("repo") or "") in allow)]


def _resolve_next(pm, st, day):
    """Kick ONE delegation attempt for the next bounced card, on its own thread
    (a fix can take minutes; the tick must not block). Attempts are counted in
    day['resolve_attempts']; after _RESOLVE_MAX failed attempts the card moves to
    day['resolved'] and _notify_deliveries escalates it WITH a proposal."""
    from daemon.cells.engineer import sessions
    todo = _bounced_to_resolve(sessions.list_tracks(), pm, day)
    if not todo:
        return
    t = todo[0]
    with _resolving_lock:
        if t["id"] in _resolving:
            return
        _resolving.add(t["id"])
    attempt = _bump_attempt(t["id"])
    threading.Thread(target=_resolve_card, args=(t["id"], attempt), daemon=True,
                     name="pm-resolve").start()


def mark_notified(tid):
    """Record that this card's escalation has already gone out, so the PM's own
    _notify_deliveries doesn't push it a SECOND time. The autopilot escalates
    its cards itself (it must work even with the PM loop switched off) and
    calls this so the owner still gets exactly one ping per stuck card."""
    with _resolving_lock:
        st = _loopstate()
        day = st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
        if tid not in day.setdefault("notified", []):
            day["notified"].append(tid)
            _save_loopstate(st)


_burn_lock = threading.Lock()
_burn_active = set()


def review_burn(tid):
    """Entry point (called by sessions.flag_burn). Judges on its OWN thread so the
    driver's event pump never blocks on a model call; one review per card at a
    time."""
    with _burn_lock:
        if tid in _burn_active:
            return
        _burn_active.add(tid)
    threading.Thread(target=_review_burn, args=(tid,), daemon=True, name="pm-burn").start()


def _burn_judge(b, t):
    """One model call: is the repetition a legit retry or a real loop? Returns
    {verdict: legit|loop, why, fix}. A judge failure defaults to 'loop' - the
    signal already crossed the threshold, and a wrong correction only costs a
    detour turn (interrupt-and-replace keeps the session)."""
    from daemon.cells.pm.pm import _ask
    prompt = (
        "Ein Worker-Agent hat denselben Tool-Aufruf %d Mal HINTEREINANDER gemacht:\n"
        "  Tool: %s\n  Input (gekuerzt): %s\n"
        "Aufgabe der Karte: %s\n\n"
        "Ist das ein LEGITIMER Retry (Warten/Polling mit Backoff, bewusste Wiederholung) "
        "oder ein sinnloser LOOP (immer derselbe fehlschlagende Schritt)?\n"
        "Antworte NUR als JSON: {\"verdict\":\"legit\"|\"loop\",\"why\":\"kurz\","
        "\"fix\":\"eine konkrete Kurskorrektur an den Worker, falls loop\"}"
        % (b.get("n", 0), b.get("name", ""), (b.get("sample") or "")[:200],
           (t.get("task") or "")[:200]))
    try:
        d = _ask(prompt)
        v = str(d.get("verdict", "")).lower()
        return {"verdict": "legit" if v == "legit" else "loop",
                "why": d.get("why", ""), "fix": d.get("fix", "")}
    except Exception:
        return {"verdict": "loop", "why": "Urteil fehlgeschlagen", "fix": ""}


def _push_burn(t, task, b):
    n, tool, corr = b.get("n", 0), b.get("name", ""), b.get("corrections", 0)
    try:
        from daemon.spine.comms import notify
        notify.push_fcm(_i18n.t("push.pmBurn"),
                        _i18n.t("push.pmBurnBody", task=task, n=n, tool=tool), t["id"])
    except Exception:
        pass
    _say(_i18n.t("pm.burnStuck", task=task, n=n, tool=tool, corr=corr))


def _review_burn(tid):
    from daemon.cells.engineer import sessions
    from daemon.cells.pm.pm import _pm
    try:
        t = sessions._find(sessions._load(), tid)
        b = (t or {}).get("burn")
        if not t or not b or t.get("status") != "running":
            return                              # turn already ended - nothing to correct
        task = (t.get("task") or "").replace("\n", " ")[:60]
        corrections = b.get("corrections", 0)
        if corrections >= _RESOLVE_MAX:         # corrected enough - hand it to the owner
            _activity("blocked", "Loop besteht trotz %d Korrekturen - eskaliere: %s"
                      % (corrections, task), card=tid)
            _push_burn(t, task, b)
            return
        verdict = _burn_judge(b, t)
        if verdict["verdict"] == "legit":
            _activity("resolve", "Wiederholung ist legitim (%s) - lasse laufen: %s"
                      % ((verdict.get("why") or "Backoff/Warten")[:60], task), card=tid)
            return
        if _pm().get("autonomy", "act") == "notify":   # advise-only: never touch the worker
            _activity("blocked", "Loop-Verdacht (%dx %s) - melde an Owner: %s"
                      % (b.get("n"), b.get("name"), task), card=tid)
            _push_burn(t, task, b)
            return
        fix = verdict.get("fix") or (
            "Du wiederholst denselben Schritt (%s) %dx mit gleichem Ergebnis. Brich diesen "
            "Ansatz ab, lies die letzte Fehlermeldung woertlich und mach den kleinsten ANDEREN "
            "Schritt, der die Ursache trifft." % (b.get("name"), b.get("n")))

        def _bump(tt):
            if tt.get("burn"):
                tt["burn"]["corrections"] = corrections + 1
        sessions._mutate(tid, _bump)
        _activity("resolve", "Loop erkannt - korrigiere Worker (Versuch %d): %s"
                  % (corrections + 1, task), card=tid)
        # steer-while-running = interrupt-and-replace: breaks the loop and
        # continues the SAME session with the correction (a36d962).
        sessions.steer(tid, fix, actor="pm", source="pm-burn")
    except Exception as e:
        _activity("resolve", "Burn-Review-Fehler: %s" % str(e)[:120], card=tid)
    finally:
        with _burn_lock:
            _burn_active.discard(tid)


def resolve_card_now(tid):
    """Run ONE rung of the resilience ladder for a SPECIFIC card, outside the
    proactive loop's gating (loop_enabled / window / idle / repo allowlist).
    The per-card autopilot (processes._autopilot) calls this so an opted-in
    card gets exactly the same classify -> delegate -> re-submit -> escalate
    treatment without waiting for the PM's idle window - ONE ladder, not two.
    Attempts share the PM's day budget (_RESOLVE_MAX), so a card can't be
    worked twice per day by two callers. Returns:
      "started"   - an attempt is now running on its own thread
      "busy"      - a fix for this card is already in flight
      "exhausted" - attempts used up; the caller escalates (_unblock_proposal)"""
    day = _loopstate().get(_today(), {})
    if tid in set(day.get("resolved", [])) \
       or (day.get("resolve_attempts") or {}).get(tid, 0) >= _RESOLVE_MAX:
        return "exhausted"
    with _resolving_lock:
        if tid in _resolving:
            return "busy"
        _resolving.add(tid)
    attempt = _bump_attempt(tid)
    threading.Thread(target=_resolve_card, args=(tid, attempt), daemon=True,
                     name="pm-resolve-auto").start()
    return "started"


def _resolve_card(tid, attempt):
    """One delegation attempt (runs on its own thread): pick the matching unblock
    path, then RE-SUBMIT to Review so the gate verdict decides whether the card
    is unstuck - the loop never waits for a human to press retry. A second
    attempt explicitly demands a DIFFERENT approach from the worker."""
    from daemon.cells.engineer import sessions
    note = ""
    try:
        t = sessions._find(sessions._load(), tid)
        if not t or t.get("status") != "bounced":
            return
        kind = _bounce_kind(t)
        task = (t.get("task") or "").replace("\n", " ")[:60]
        if attempt == 1 and kind != "dispatch":
            _say(_i18n.t("pm.onIt", task=task, kind=kind))
        if kind == "dispatch":
            _activity("resolve", "Dispatch schlug fehl - starte neu (Versuch %d): %s"
                      % (attempt, task), card=tid)
            sessions.move_lane(tid, "working", actor="pm")   # idempotent re-dispatch
        elif kind == "dirty":
            _activity("resolve", "Unsauberer Haupt-Checkout blockiert - parke + pruefe neu: "
                      + task, card=tid)
            note = sessions.park_and_retry_merge(tid, actor="pm")
        else:
            if kind == "conflict":
                _activity("resolve", "Merge-Konflikt an Worker delegiert (Versuch %d): %s"
                          % (attempt, task), card=tid)
                note = sessions.dispatch_conflict_resolution(tid, actor="pm", background=False)
                if "resolve_blocker" in note:
                    # mis-filed: the 'conflict' is really a dirty shared checkout -
                    # switch tools instead of stalling on the wrong one
                    _activity("resolve", "Kein Marker-Konflikt, sondern Checkout-Blocker - "
                              "wechsle auf park+retry: " + task, card=tid)
                    note = sessions.park_and_retry_merge(tid, actor="pm")
            else:   # gate red / error / zombie
                reason = (" | ".join(t.get("gate_report") or []) or t.get("last_error")
                          or "Review rot")[:500]
                if attempt <= 1:
                    instr = ("Die Karte ist beim Review gebounct. Grund: %s. Behebe die "
                             "Ursache im Code (nur editieren, kein git); das Neu-Einreichen "
                             "uebernehme ich." % reason)
                else:
                    instr = ("Zweiter Anlauf - der erste Fix hat den Bounce NICHT behoben. "
                             "Grund weiterhin: %s. Waehle einen ANDEREN Ansatz: hinterfrage "
                             "die Annahme hinter dem letzten Fix, lies die Fehlermeldung "
                             "woertlich und mach die kleinste Aenderung, die die Ursache "
                             "trifft (nur editieren, kein git)." % reason)
                _activity("resolve", "Fix an Worker delegiert (Versuch %d): %s"
                          % (attempt, task), card=tid)
                sessions.steer(tid, instr, actor="pm", source="pm-resolve")
            # delegate-then-verify: re-submit so the gate re-runs NOW; a green gate
            # parks the card on Review as 'submitted' for your accept (accept/merge
            # stay gated to you - the law), a red one bounces for the next rung.
            # Unconditional on status: 'already resolved, just re-submit' is a
            # real dispatch_conflict_resolution outcome that leaves it bounced.
            cur = sessions._find(sessions._load(), tid)
            if cur and cur.get("lane") in ("working", "review"):
                sessions.move_lane(tid, "review", actor="pm")
    except Exception as e:
        note = ("%s" % e)[:200]
    finally:
        with _resolving_lock:
            _resolving.discard(tid)
    t = sessions._find(sessions._load(), tid)
    task = ((t or {}).get("task") or "").replace("\n", " ")[:60]
    if t and t.get("status") != "bounced":
        _activity("resolve", "Wieder frei (Versuch %d): %s" % (attempt, task), card=tid)
        _say(_i18n.t("pm.freeAgain", task=task, note=(" - " + note[:200]) if note else "."))
    elif attempt >= _RESOLVE_MAX:
        _give_up(tid)
        _activity("blocked", "Haengt trotz %d Fix-Versuchen - eskaliere mit Vorschlag: %s"
                  % (attempt, task), card=tid)
        # the escalation itself (push + proposal) goes out via _notify_deliveries
    else:
        _activity("resolve", "Versuch %d hat nicht gereicht - naechster Anlauf mit anderem "
                  "Ansatz: %s" % (attempt, task), card=tid)
