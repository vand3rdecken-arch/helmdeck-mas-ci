# -*- coding: utf-8 -*-
"""The desktop LEASE: the cursor is taken per windows-mcp control call by the
card's own guard hook, not per turn (2026-09-22).

Live failure this pays for (2026-09-19, 12 desktop_wait events in one
morning): every machine card is forced onto claude-desktop, so the old
per-turn lock made an hour-long Node/Haiku script card - which never clicked -
hold the cursor for its whole turn. Three sibling cards, one hands run and
the card's OWN re-dispatch queued behind it and bounced after 960s each.
Henry fanned out; the harness serialized him back to one.

Pins, against the REAL hook (ops/tools/card_tool_guard.py run as the CLI
runs it, stdin payload, env) and the real lease module, sandboxed through
HELMDECK_DESKTOP_LEASE:
  1. classify: only windows-mcp CONTROL tools take the lease; Screenshot/
     Snapshot/Scrape/DisplayInventory/Wait and non-desktop tools never do
  2. card A's Click takes the lease; card B's Click within the hold-over is
     DENIED (bounded wait, then a retry hint naming the holder) - and B's
     Screenshot is still allowed
  3. A's PostToolUse keeps A the owner (hold-over), A's next Click renews
  4. release(A) - the turn-end owner - frees it: B's Click is allowed at once
  5. an idle holder past the grace is reclaimed; a wedged holder (busy, no
     PostToolUse) is reclaimed only after the busy TTL
  6. a lease older than its own grace does not block release/status logic
Run: py -3.12 ops/tests/test_desktop_lease.py
"""
import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-lease-")
LEASE = os.path.join(SANDBOX, "desktop.lease")
os.environ["HELMDECK_DESKTOP_LEASE"] = LEASE
GUARD = os.path.join(ROOT, "ops", "tools", "card_tool_guard.py")

from spine.git import desktop_lease as dl


def check(ok, desc):
    assert ok, desc
    print("  ok: " + desc)


def hook(card, tool, event="PreToolUse", wait_s=1):
    env = dict(os.environ, HELMDECK_CARD=card, HELMDECK_DESKTOP_WAIT_S=str(wait_s),
               HELMDECK_DESKTOP_LEASE=LEASE)
    env.pop("HELMDECK_WORKTREE", None)
    payload = {"hook_event_name": event, "tool_name": tool, "tool_input": {}}
    p = subprocess.run([sys.executable, GUARD], input=json.dumps(payload), capture_output=True,
                       text=True, env=env, cwd=SANDBOX, timeout=60)
    assert p.returncode == 0, "hook exit %s: %s" % (p.returncode, p.stderr[-400:])
    out = p.stdout.strip()
    if not out:
        return "allow", ""
    d = json.loads(out)["hookSpecificOutput"]
    return d["permissionDecision"], d.get("permissionDecisionReason", "")


print("1) classify")
check(dl.is_control_tool("mcp__windows-mcp__Click"), "Click is control")
check(dl.is_control_tool("mcp__windows-mcp__Type"), "Type is control")
check(dl.is_control_tool("mcp__windows-mcp__SomethingNew"), "unknown windows-mcp tool is control (fail-safe)")
for ro in ("Screenshot", "Snapshot", "Scrape", "DisplayInventory", "Wait"):
    check(not dl.is_control_tool("mcp__windows-mcp__" + ro), ro + " is read-only")
check(not dl.is_control_tool("Bash"), "Bash is not desktop")
check(not dl.is_control_tool("mcp__helmdeck-browser__click"), "the headless browser is not the cursor")

print("\n2) A holds, B is denied within the hold-over, B may still look")
check(dl.status() == {}, "desktop free at start")
check(hook("A", "mcp__windows-mcp__Click")[0] == "allow", "A's Click takes the lease")
st = dl.status()
check(st.get("owner") == "A" and st.get("busy") is True, "status: A, busy (%r)" % st)
t0 = time.time()
dec, why = hook("B", "mcp__windows-mcp__Click", wait_s=1)
check(dec == "deny", "B's Click is denied while A holds")
check(time.time() - t0 >= 1.0, "...after the bounded wait (%.1fs)" % (time.time() - t0))
check("A" in why and "Desktop belegt" in why and "erneut" in why, "deny names the holder and says retry (%r)" % why[:90])
check(hook("B", "mcp__windows-mcp__Screenshot")[0] == "allow", "B's Screenshot needs no lease")
check(hook("B", "Bash")[0] == "allow", "B's Bash is not the guard's desktop business")

print("\n3) PostToolUse keeps the owner, next call renews")
check(hook("A", "mcp__windows-mcp__Click", event="PostToolUse")[0] == "allow", "A's PostToolUse passes")
st = dl.status()
check(st.get("owner") == "A" and st.get("busy") is False, "status: A idle in hold-over (%r)" % st)
check(hook("B", "mcp__windows-mcp__Type", wait_s=0)[0] == "deny", "B still denied inside A's hold-over")
check(hook("A", "mcp__windows-mcp__Type")[0] == "allow", "A's next control call renews at once")
check(dl.status().get("busy") is True, "...and is busy again")

print("\n4) turn end releases")
check(dl.release("B") is False, "B cannot release A's lease")
check(dl.release("A") is True, "A's turn end releases")
check(dl.status() == {}, "desktop free")
check(hook("B", "mcp__windows-mcp__Click", wait_s=0)[0] == "allow", "B's Click allowed immediately")
check(dl.release("B") is True, "cleanup")

print("\n5) expiry: idle grace vs busy TTL")
ok, _ = dl.acquire("C", tool="mcp__windows-mcp__Click", grace=0.5, busy_ttl=1.5)
check(ok, "C holds (busy)")
time.sleep(0.7)
check(hook("D", "mcp__windows-mcp__Click", wait_s=0)[0] == "deny", "busy holder past the idle grace is NOT reclaimed")
time.sleep(1.0)
check(hook("D", "mcp__windows-mcp__Click", wait_s=0)[0] == "allow", "...but past the busy TTL it is")
check(dl.status().get("owner") == "D", "D owns it now")
dl.release("D")
ok, _ = dl.acquire("E", tool="mcp__windows-mcp__Click", grace=0.5, busy_ttl=5)
dl.touch("E", busy=False)
time.sleep(0.7)
check(hook("F", "mcp__windows-mcp__Click", wait_s=0)[0] == "allow", "idle holder past the grace is reclaimed")
check(dl.status().get("owner") == "F", "F owns it now")
dl.release("F")

print("\n6) a bounded wait that ends inside the window gets the lease")
ok, _ = dl.acquire("G", tool="mcp__windows-mcp__Click", grace=0.8, busy_ttl=5)
dl.touch("G", busy=False)
t0 = time.time()
dec, _ = hook("H", "mcp__windows-mcp__Click", wait_s=5)
check(dec == "allow" and 0.5 <= time.time() - t0 < 5, "H waited for G's grace, then took it (%.1fs)" % (time.time() - t0))
dl.release("H")

print("\nPASS test_desktop_lease")
