# -*- coding: utf-8 -*-
"""Claude subscription usage: the 5-hour and weekly rate-limit windows, read from the
SAME source Paseo's usage tab uses - Anthropic's OAuth usage endpoint, authed with the
Claude Code login token in ~/.claude/.credentials.json.

The point isn't just to show a bar: it's PACING. A weekly window is a rolling 7 days, so
"40% used" only matters against how much of the week has elapsed. 40% by Wednesday with a
Saturday reset means the burn rate lands the account at ~114% before the window resets -
the PM flags that BEFORE the wall, not after. See pacing() and pm.py's usage check.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

OAUTH_BETA = "oauth-2025-04-20"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
SCOPE = "user:profile user:inference user:sessions:claude_code user:mcp_servers"
WEEK_SEC = 7 * 24 * 3600
RISK_MIN_AHEAD_PP = 5.0   # reset_risk needs this many pct-points over even pace

_cache = {"at": 0.0, "data": None}
CACHE_TTL = 300     # 5 min, like Paseo's staleTime - the windows move slowly


def _creds_path():
    home = os.environ.get("CLAUDE_HOME") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(home, ".credentials.json")


def _read_creds():
    try:
        with open(_creds_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_tokens(access, refresh):
    """Persist a refreshed token pair back where Claude Code (and we) read it."""
    p = _creds_path()
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        o = d.setdefault("claudeAiOauth", {})
        o["accessToken"] = access
        if refresh:
            o["refreshToken"] = refresh
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    except Exception:
        pass    # non-fatal: Claude Code refreshes on its own too


def _get_usage(token):
    """GET the usage windows. Returns dict, or 'NEEDS_AUTH' on 401/403, or raises."""
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "anthropic-beta": OAUTH_BETA,
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "NEEDS_AUTH"
        raise


def _refresh(refresh_token):
    body = json.dumps({
        "grant_type": "refresh_token", "refresh_token": refresh_token,
        "client_id": CLIENT_ID, "scope": SCOPE,
    }).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _tone(pct):
    if not isinstance(pct, (int, float)):
        return "default"
    if pct > 90:
        return "danger"
    if pct >= 70:
        return "warning"
    return "ok"


def _iso_to_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def pacing(used_pct, resets_at, window_sec=WEEK_SEC, now=None):
    """Burn-rate pacing for a rolling window. Even burn would put usedPct == elapsed%.
    Returns None if it can't be computed, else a dict with the projection + a flag."""
    reset_ts = _iso_to_ts(resets_at)
    if reset_ts is None or not isinstance(used_pct, (int, float)):
        return None
    now = now if now is not None else time.time()
    start = reset_ts - window_sec
    elapsed = max(0.0, min(1.0, (now - start) / window_sec))
    expected = elapsed * 100.0
    ahead = used_pct - expected            # >0 = burning faster than even pace
    proj = None                            # projected usedPct at reset if pace holds
    exhaust_ts = None                      # when usedPct would hit 100 at this pace
    if elapsed > 0.01 and used_pct > 0:
        rate = used_pct / elapsed          # pct per full window
        proj = min(999.0, rate)            # rate == projected end-of-window pct
        frac_100 = min(1.0, (100.0 / used_pct) * elapsed) if used_pct else 1.0
        exhaust_ts = start + frac_100 * window_sec
    hours_left = max(0.0, (reset_ts - now) / 3600.0)
    exhaust_before_reset = exhaust_ts is not None and exhaust_ts < reset_ts - 3600
    # reset_risk = the ONE claim "genuinely going to run out before the reset,
    # not just noise": proj >= 105% (the same buffer ahead_flag always had -
    # early in a window a handful of tokens can swing proj from 95% to 101%
    # on almost nothing) AND exhaust_before_reset. exhaust_before_reset ALONE
    # has no such buffer - measured 2026-09-14, 06:00 into a fresh window
    # (6% used, 6% elapsed): proj 100.7%, exhaust_before_reset True, but this
    # is noise, not a real trend, and used_pct is nowhere near 85 either.
    # Every "will you actually run out" claim (an owner ask, an "erschöpft"
    # escalation) must read THIS, never exhaust_before_reset by itself.
    # The 105% buffer is RELATIVE, so early in a window it is worth almost
    # nothing in absolute terms: proj = used/elapsed, and the API rounds
    # usedPct to whole percent. Measured 2026-09-14 08:46: 7% used at 6.4%
    # elapsed (0.6pp ahead, 157h left) -> proj 109%, reset_risk fired and
    # asked the owner to shelve work. Rounding alone swings proj by ~8% there.
    # So also demand a real ABSOLUTE lead over even pace (RISK_MIN_AHEAD_PP);
    # a genuine overrun clears it easily (e.g. 20% used at 6% elapsed).
    reset_risk = (proj is not None and proj >= 105.0 and exhaust_before_reset
                  and ahead >= RISK_MIN_AHEAD_PP)
    # Flag stays the separate, WEAKER "spend is hot" signal used for the
    # conservative-dispatch throttle (_quota_floor) - fires on reset_risk OR
    # merely used_pct >= 85 regardless of time left. Never read this as "will
    # run out before reset" - that claim is reset_risk, not flag.
    ahead_flag = reset_risk or used_pct >= 85.0
    return {
        "elapsed_pct": round(expected, 1),
        "ahead_pct": round(ahead, 1),
        "projected_pct": round(proj, 1) if proj is not None else None,
        "exhaust_at": datetime.fromtimestamp(exhaust_ts, timezone.utc).isoformat() if exhaust_ts else None,
        "reset_hours_left": round(hours_left, 1),
        "exhaust_before_reset": bool(exhaust_before_reset),
        "reset_risk": bool(reset_risk),
        "flag": bool(ahead_flag),
    }


def _plan(oauth):
    sub = oauth.get("subscriptionType")
    if not sub:
        return None
    label = sub[:1].upper() + sub[1:]
    tier = (oauth.get("rateLimitTier") or "").split("_")[-1]
    return "%s %s" % (label, tier) if tier else label


def login_method():
    """What the spawned claude CLI actually authenticates WITH - the signal the
    auto billing mode keys off (events.plan_effective). Paseo's usage tab keys
    off the same file: a stored Claude Code login means subscription quota.

    Precedence mirrors Claude Code's own: a stored OAuth login is used
    unconditionally, while an ANTHROPIC_API_KEY in the environment only bills
    once the owner has explicitly approved it in the CLI (customApiKeyResponses)
    - so the login wins whenever both exist. A login WITHOUT a subscriptionType
    is a Console (per-token) account, not a flat plan."""
    oauth = (_read_creds() or {}).get("claudeAiOauth") or {}
    if oauth.get("accessToken"):
        return {"method": "oauth",
                "subscription": oauth.get("subscriptionType") or None,
                "plan": _plan(oauth)}
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"method": "api_key", "subscription": None, "plan": None}
    return {"method": None, "subscription": None, "plan": None}


def snapshot(force=False):
    """The usage view: plan + windows (five_hour, weekly, weekly_opus) with tone and,
    for the weekly window, pacing. Cached; returns {'status': 'unavailable'} if there is
    no Claude login or the endpoint can't be reached."""
    if not force and _cache["data"] is not None and (time.time() - _cache["at"] < CACHE_TTL):
        return _cache["data"]
    creds = _read_creds()
    oauth = (creds or {}).get("claudeAiOauth") or {}
    token = oauth.get("accessToken")
    if not token:
        return {"status": "unavailable", "windows": [], "plan": None}
    try:
        resp = _get_usage(token)
        if resp == "NEEDS_AUTH" and oauth.get("refreshToken"):
            ref = _refresh(oauth["refreshToken"])
            if ref and ref.get("access_token"):
                _save_tokens(ref["access_token"], ref.get("refresh_token"))
                resp = _get_usage(ref["access_token"])
        if not isinstance(resp, dict):
            return {"status": "unavailable", "windows": [], "plan": _plan(oauth)}
    except Exception as e:
        return {"status": "error", "windows": [], "plan": _plan(oauth), "error": str(e)[:120]}

    windows = []
    specs = [("five_hour", "five_hour", "5-Stunden", WEEK_SEC),   # window_sec unused for 5h pacing
             ("seven_day", "weekly", "Woche", WEEK_SEC),
             ("seven_day_opus", "weekly_opus", "Woche · Opus", WEEK_SEC)]
    for key, wid, label, wsec in specs:
        w = resp.get(key)
        if not w:
            continue
        pct = w.get("utilization")
        entry = {
            "id": wid, "label": label,
            "usedPct": pct,
            "remainingPct": (max(0.0, 100.0 - pct) if isinstance(pct, (int, float)) else None),
            "resetsAt": w.get("resets_at"),
            "tone": _tone(pct),
        }
        if wid == "weekly":
            entry["pacing"] = pacing(pct, w.get("resets_at"), WEEK_SEC)
        windows.append(entry)

    out = {
        "status": "ok",
        "plan": _plan(oauth),
        "windows": windows,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }
    _cache["at"] = time.time()
    _cache["data"] = out
    return out


def cached(refresh=True):
    """The snapshot WITHOUT ever blocking on the network - for hot paths like
    events.metrics(), which the board polls every few seconds and which must not
    inherit a 15s HTTP timeout. Returns the cached snapshot (or None while the
    cache is still cold) and kicks a one-at-a-time background refresh when it is
    stale, so the cache warms itself even if nobody opens the usage panel."""
    data = _cache["data"]
    if refresh and (data is None or time.time() - _cache["at"] >= CACHE_TTL):
        _kick_refresh()
    return data


_refreshing = threading.Lock()
_last_try = [0.0]


def _kick_refresh():
    # back off on ATTEMPT, not on success: an unavailable endpoint (no Claude
    # login, offline) never fills the cache, and gating on _cache["at"] alone
    # would fire a fresh HTTP attempt on every single metrics poll.
    if time.time() - _last_try[0] < CACHE_TTL:
        return
    if not _refreshing.acquire(blocking=False):
        return                      # a refresh is already in flight
    _last_try[0] = time.time()
    def run():
        try:
            snapshot(force=True)
        except Exception:
            pass                    # cache simply stays cold; callers fall back
        finally:
            _refreshing.release()
    threading.Thread(target=run, daemon=True).start()


def weekly_pacing_flag():
    """The signal the PM acts on: the weekly window's pacing when it's ahead-of-pace,
    else None. Cheap (uses the cached snapshot)."""
    snap = snapshot()
    if snap.get("status") != "ok":
        return None
    for w in snap.get("windows", []):
        if w.get("id") == "weekly":
            p = w.get("pacing") or {}
            if p.get("flag"):
                return {"usedPct": w.get("usedPct"), "resetsAt": w.get("resetsAt"), **p}
            return None
    return None
