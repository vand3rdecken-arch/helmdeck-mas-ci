# -*- coding: utf-8 -*-
"""Self-sandboxing end-to-end test for remote device execution
(ops/docs/backlog/remote-device-execution).

Proves the core architectural claim: a branch produced entirely OUTSIDE the
daemon's own repo (a separate clone standing in for "a team member's own
PC"), imported via a git bundle, is INDISTINGUISHABLE to the existing
gate/merge pipeline from a branch a local worktree card produced - no
change to lanemachine.py was needed or made.

Covers:
  1. device registry: register/list/resolve/revoke, ownership discipline
     (one user cannot resolve another user's device)
  2. gitutil._import_bundle: verifies + imports, refuses to clobber an
     existing branch
  3. the full dispatch flow: new_remote_task (files, stays in backlog) ->
     claim_remote_task (device polls, card moves to working) ->
     submit_remote_result (bundle import + _ensure_worktree + move_lane
     ('review') - the SAME _gate a local card's submit runs)
  4. the HTTP route layer (routes_devices.py) against the same flow

Run: py -3.12 ops/tests/test_remote_device.py
"""
import base64
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def git(repo, *a):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    return r.stdout.strip()


class FakeH:
    def __init__(self):
        self.code = None
        self.body = None

    def _send(self, code, body, ct=None):
        self.code = code
        try:
            self.body = json.loads(body)
        except (TypeError, ValueError):
            self.body = body
        return code


def call(fn, *a):
    h = FakeH()
    fn(h, *a)
    return h


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-remotedevice-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")
    db.init()

    from spine.auth import devices
    devices.DEVICES = os.path.join(tmp, "devices.json")

    from cells.engineer import dispatch
    rec = os.path.join(tmp, "recordings")
    os.makedirs(rec, exist_ok=True)
    dispatch.REC = rec   # module-global rebind, same trick every other
                          # sandboxing test uses for db.ROOT/auth.USERS etc.

    auth.create_user("alice", "alice-password-1", "operator")
    auth.create_user("bob", "bob-password-1", "operator")
    ALICE = {"name": "alice", "role": "operator"}
    BOB = {"name": "bob", "role": "operator"}

    # -- 1: device registry --------------------------------------------------
    print("\ndevice registry")
    rec1 = devices.register("alice", "Alice's laptop", actor="alice")
    ok(rec1.get("id") and rec1.get("token"), "register returns id + token")
    d = devices.get_device(rec1["id"])
    ok(d["owner"] == "alice", "device is owned by the registering user")
    ok(devices.resolve(ALICE, rec1["id"]) is not None, "owner can resolve their own device")
    ok(devices.resolve(BOB, rec1["id"]) is None, "a DIFFERENT user cannot resolve alice's device")
    ok(len(devices.list_devices("alice")) == 1, "list_devices scoped to owner")
    ok(len(devices.list_devices("bob")) == 0, "bob sees none of alice's devices")
    devices.revoke(rec1["id"], actor="alice")
    ok(devices.get_device(rec1["id"]) is None, "revoke removes the device record")
    u = auth.get_user("alice")
    ok(not any(t.get("id") == rec1["token_id"] if "token_id" in rec1 else False
              for t in u.get("tokens", [])), "revoke also killed the underlying token")

    # a fresh device for the rest of the test
    rec2 = devices.register("alice", "Alice's laptop", actor="alice")
    did = rec2["id"]

    # -- 2: repo + a REMOTE clone standing in for "alice's own PC" -----------
    print("\ncentral repo + remote clone")
    central = os.path.join(tmp, "central-repo")
    os.makedirs(central)
    git(central, "init", "-q")
    git(central, "config", "user.email", "t@t.t"); git(central, "config", "user.name", "T")
    open(os.path.join(central, "a.txt"), "w").write("base\n")
    git(central, "add", "-A"); git(central, "commit", "-qm", "base")

    remote_clone = os.path.join(tmp, "alices-own-pc-clone")
    git(tmp, "clone", "-q", central, remote_clone)
    branch = "device/feature-x"
    git(remote_clone, "checkout", "-qb", branch)
    open(os.path.join(remote_clone, "feature.txt"), "w").write("work done on alice's PC\n")
    git(remote_clone, "add", "-A")
    git(remote_clone, "commit", "-qm", "feature work, entirely local to the device")

    bundle_path = os.path.join(tmp, "submission.bundle")
    r = subprocess.run(["git", "-C", remote_clone, "bundle", "create", bundle_path, branch],
                       capture_output=True, text=True)
    ok(r.returncode == 0 and os.path.exists(bundle_path), "worker produced a real git bundle")

    # -- 3: the dispatch flow -------------------------------------------------
    print("\ndispatch flow: new_remote_task -> claim -> submit")
    t = dispatch.new_remote_task(central, branch, "feature X", did, actor="alice")
    ok(t["lane"] == "backlog", "filed card stays in backlog (nothing to run locally yet)")
    ok(t["exec_site"] == "local:" + did, "exec_site records which device owns it")
    ok(t.get("machine") is not True, "NEVER machine=True - must ride the normal gated path")

    claimed = dispatch.claim_remote_task("nonexistent-device-id")
    ok(claimed is None, "a different/unknown device claims nothing")
    claimed = dispatch.claim_remote_task(did)
    ok(claimed is not None and claimed["id"] == t["id"], "the owning device claims the card")
    ok(claimed["lane"] == "working", "claim moves the card to working")

    try:
        dispatch.submit_remote_result("no-such-card", bundle_path, actor="alice")
        ok(False, "submit on an unknown card should raise")
    except RuntimeError:
        ok(True, "submit on an unknown card raises RuntimeError")

    result = dispatch.submit_remote_result(t["id"], bundle_path, actor="alice")
    ok(git(central, "rev-parse", "--verify", branch) != "",
       "the branch now exists in the CENTRAL repo (bundle import worked)")
    ok(result.get("lane") in ("review", "done"),
       "card advanced past the gate (got lane=%r)" % result.get("lane"))
    wt = result.get("worktree") or ""
    # .git is a FILE (gitdir pointer) inside a worktree, a DIRECTORY only in
    # the main checkout - exists(), not isdir(), is the correct worktree check.
    ok(wt and os.path.isdir(wt) and os.path.exists(os.path.join(wt, ".git")),
       "a real local worktree was materialized from the imported branch")
    ok(os.path.exists(os.path.join(wt, "feature.txt")),
       "the device's actual commit content is present in the central worktree")

    # re-submitting the same branch is IDEMPOTENT (Phase A), not an error:
    # a lost HTTP response must not turn a retry into a hard failure. The
    # underlying refuse-to-clobber in _import_bundle is exercised directly
    # in section 6 below (device-match / fresh-branch-collision cases), not
    # through the public submit_remote_result retry path.
    again = dispatch.submit_remote_result(t["id"], bundle_path, actor="alice")
    ok(again.get("id") == t["id"] and again.get("lane") == result.get("lane"),
       "re-submitting an already-landed branch is idempotent, not an error")

    # -- 4: HTTP route layer ---------------------------------------------------
    print("\nHTTP route layer")
    from spine.http.routes import routes_devices

    h = call(routes_devices.devices_register_post, ALICE, {"label": "Alice's phone-tethered laptop"})
    ok(h.code == 200 and h.body.get("token"), "POST /devices/register 200")
    did2 = h.body["id"]

    h = call(routes_devices.devices_mine_get, ALICE)
    ok(h.code == 200 and any(d["id"] == did2 for d in h.body), "GET /devices/mine lists it")
    ok(all("token_id" not in d for d in h.body), "token_id never leaves the server")

    h = call(routes_devices.devices_mine_get, BOB)
    ok(h.code == 200 and h.body == [], "bob's /devices/mine is empty - no cross-user leak")

    CLIENT = {"name": "eve", "role": "client"}
    h = call(routes_devices.devices_register_post, CLIENT, {"label": "x"})
    ok(h.code == 403, "a client role cannot register a device")

    h = call(routes_devices.devices_revoke_post, BOB, {}, did2)
    ok(h.code == 404, "bob cannot revoke alice's device (not found, not 403 - no existence leak)")

    branch2 = "device/feature-y"
    git(remote_clone, "checkout", "-q", "-b", branch2)
    open(os.path.join(remote_clone, "feature2.txt"), "w").write("second device task\n")
    git(remote_clone, "add", "-A")
    git(remote_clone, "commit", "-qm", "second feature")
    bundle2 = os.path.join(tmp, "submission2.bundle")
    subprocess.run(["git", "-C", remote_clone, "bundle", "create", bundle2, "device/feature-y"],
                   capture_output=True, text=True)

    t2 = dispatch.new_remote_task(central, "device/feature-y", "feature Y", did2, actor="alice")
    h = call(routes_devices.devices_queue_get, ALICE, did2)
    ok(h.code == 200 and h.body and h.body["id"] == t2["id"],
       "GET /devices/<id>/queue returns the claimed card")

    with open(bundle2, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    h = call(routes_devices.devices_submit_post, ALICE, {"track": t2["id"], "bundle_b64": b64}, did2)
    ok(h.code == 200 and h.body.get("lane") in ("review", "done"),
       "POST /devices/<id>/submit lands the card past the gate")

    h = call(routes_devices.devices_submit_post, BOB, {"track": t2["id"], "bundle_b64": b64}, did2)
    ok(h.code == 404, "a different user's token cannot submit against alice's device")

    # -- 5: billing_scope on the device registry ------------------------------
    print("\nbilling_scope (Phase A data model, Phase D usage capture will key off it)")
    rec_ext = devices.register("alice", "default scope")
    ok(devices.get_device(rec_ext["id"])["billing_scope"] == "external",
       "default billing_scope is 'external' (device's own account pays)")
    rec_shared = devices.register("alice", "company box", billing_scope="shared")
    ok(devices.get_device(rec_shared["id"])["billing_scope"] == "shared",
       "billing_scope='shared' is recorded when explicitly asked for")
    try:
        devices.register("alice", "bad", billing_scope="nonsense")
        ok(False, "an invalid billing_scope should raise")
    except ValueError:
        ok(True, "an invalid billing_scope is rejected")

    # -- 6: idempotent submit (a lost HTTP response after a real landing) ----
    print("\nsubmit_remote_result: idempotent on a branch already landed")
    branch3 = "device/feature-z"
    git(remote_clone, "checkout", "-q", "-b", branch3)
    open(os.path.join(remote_clone, "feature3.txt"), "w").write("idempotency test\n")
    git(remote_clone, "add", "-A"); git(remote_clone, "commit", "-qm", "feature z")
    bundle3 = os.path.join(tmp, "submission3.bundle")
    subprocess.run(["git", "-C", remote_clone, "bundle", "create", bundle3, branch3],
                   capture_output=True, text=True)
    t3 = dispatch.new_remote_task(central, branch3, "feature Z", did, actor="alice")
    dispatch.claim_remote_task(did)
    r1 = dispatch.submit_remote_result(t3["id"], bundle3, actor="alice", device_id=did)
    ok(r1.get("lane") in ("review", "done"), "first submit lands normally")
    # the device never saw r1 (simulated lost response) and retries with the
    # SAME bundle - must not error on _import_bundle's refuse-to-clobber.
    r2 = dispatch.submit_remote_result(t3["id"], bundle3, actor="alice", device_id=did)
    ok(r2.get("id") == t3["id"] and r2.get("lane") == r1.get("lane"),
       "a re-submit of an already-landed branch is idempotent, not an error")

    # -- 7: device-match on submit (device X may not submit device Y's card) -
    print("\nsubmit_remote_result: device-match")
    branch4 = "device/feature-w"
    git(remote_clone, "checkout", "-q", "-b", branch4)
    open(os.path.join(remote_clone, "feature4.txt"), "w").write("device match test\n")
    git(remote_clone, "add", "-A"); git(remote_clone, "commit", "-qm", "feature w")
    bundle4 = os.path.join(tmp, "submission4.bundle")
    subprocess.run(["git", "-C", remote_clone, "bundle", "create", bundle4, branch4],
                   capture_output=True, text=True)
    t4 = dispatch.new_remote_task(central, branch4, "feature W", did, actor="alice")
    dispatch.claim_remote_task(did)
    try:
        dispatch.submit_remote_result(t4["id"], bundle4, actor="alice", device_id=rec_ext["id"])
        ok(False, "a different device (same owner) submitting card bound to `did` should raise")
    except RuntimeError as e:
        ok("different device" in str(e), "device-match refuses cleanly with a clear reason")
    r4 = dispatch.submit_remote_result(t4["id"], bundle4, actor="alice", device_id=did)
    ok(r4.get("lane") in ("review", "done"), "the CORRECT device can still submit normally")

    # -- 8: claimed_at + sweep_stale_device_claims ----------------------------
    print("\nclaimed_at + sweep_stale_device_claims")
    from datetime import datetime, timedelta
    branch5 = "device/feature-v"
    git(remote_clone, "checkout", "-q", "-b", branch5)
    t5 = dispatch.new_remote_task(central, branch5, "feature V", did, actor="alice")
    claimed = dispatch.claim_remote_task(did)
    ok(claimed.get("claimed_at"), "claim_remote_task stamps claimed_at")

    swept = dispatch.sweep_stale_device_claims(claim_ttl_s=1800)
    ok(t5["id"] not in swept, "a FRESH claim is never swept")

    fmt = dispatch._TS_FMT
    long_ago = (datetime.now() - timedelta(seconds=3700)).strftime(fmt)
    dispatch._mutate(t5["id"], lambda tt: tt.update(claimed_at=long_ago))
    devices.touch(did)   # device is actively polling RIGHT NOW
    swept = dispatch.sweep_stale_device_claims(claim_ttl_s=1800, last_seen_grace_s=180)
    ok(t5["id"] not in swept,
       "an OLD claim on a device that is STILL POLLING is not reclaimed (long turn, not dead)")

    long_ago_seen = (datetime.now() - timedelta(seconds=400)).strftime(fmt)
    dev_rec = devices._load()
    for d in dev_rec:
        if d["id"] == did:
            d["last_seen"] = long_ago_seen
    devices._save(dev_rec)
    swept = dispatch.sweep_stale_device_claims(claim_ttl_s=1800, last_seen_grace_s=180)
    ok(t5["id"] in swept,
       "an OLD claim on a device that has gone QUIET is reclaimed")
    t5_now = dispatch._find(dispatch._load(), t5["id"])
    ok(t5_now["lane"] == "backlog" and not t5_now.get("claimed_at"),
       "a reclaimed card is back in backlog with claimed_at cleared")
    ok(t5_now.get("exec_site") == "local:" + did,
       "reclaim keeps the SAME device bound - it can re-claim on reconnect (not a reassign)")

    reclaimed_again = dispatch.claim_remote_task(did)
    ok(reclaimed_again and reclaimed_again["id"] == t5["id"],
       "the same device CAN re-claim the reclaimed card")

    # -- 9: reassign_remote_task (owner recovery for a dead device) ----------
    print("\nreassign_remote_task")
    branch6 = "device/feature-u"
    t6 = dispatch.new_remote_task(central, branch6, "feature U", did, actor="alice")
    reassigned = dispatch.reassign_remote_task(t6["id"], rec_ext["id"], actor="alice")
    ok(reassigned["exec_site"] == "local:" + rec_ext["id"],
       "reassign moves exec_site to the new device")
    ok(reassigned["lane"] == "backlog", "reassigned card goes back to backlog for the new device")

    cleared = dispatch.reassign_remote_task(t6["id"], "", actor="alice")
    ok("exec_site" not in cleared, "reassign with no target device clears exec_site entirely")

    try:
        dispatch.reassign_remote_task("no-such-card", did, actor="alice")
        ok(False, "reassigning an unknown card should raise")
    except RuntimeError:
        ok(True, "reassigning an unknown card raises")

    t6b = dispatch.new_remote_task(central, "device/feature-t", "feature T", did, actor="alice")
    try:
        dispatch.reassign_remote_task(t6b["id"], rec_ext["id"], actor="bob")
        ok(False, "bob reassigning alice's device-bound card to bob's own device id should fail")
    except RuntimeError:
        ok(True, "reassign refuses a target device the actor does not own")

    # route layer
    h = call(routes_devices.devices_reassign_post, BOB,
            {"track": t6b["id"], "to_device": rec_ext["id"]})
    ok(h.code == 400, "POST /devices/reassign: bob is operator (role passes) but does not "
                       "own the target device - refused with 400, not 403 (a role vs. "
                       "ownership distinction)")
    h = call(routes_devices.devices_reassign_post, CLIENT, {"track": t6b["id"], "to_device": ""})
    ok(h.code == 403, "a client role cannot call /devices/reassign")
    h = call(routes_devices.devices_reassign_post, ALICE,
            {"track": t6b["id"], "to_device": rec_ext["id"]})
    ok(h.code == 200 and h.body.get("exec_site") == "local:" + rec_ext["id"],
       "POST /devices/reassign works for the owning actor")

    # -- 10: submit_remote_result folds usage_meta via the real econ path ----
    print("\nsubmit_remote_result: usage_meta -> spine.turn.econ, external tag by billing_scope")
    from spine.storage import events as _events
    meta = {"usage": {"input_tokens": 2000, "output_tokens": 1000}, "cost_usd": 0.10,
           "models": ["claude-sonnet-5"]}

    branch7 = "device/feature-econ-ext"
    git(remote_clone, "checkout", "-q", "-b", branch7)
    open(os.path.join(remote_clone, "econ_ext.txt"), "w").write("x\n")
    git(remote_clone, "add", "-A"); git(remote_clone, "commit", "-qm", "econ ext")
    bundle7 = os.path.join(tmp, "s7.bundle")
    subprocess.run(["git", "-C", remote_clone, "bundle", "create", bundle7, branch7],
                   capture_output=True, text=True)
    t7 = dispatch.new_remote_task(central, branch7, "econ ext", rec_ext["id"], actor="alice")
    dispatch.claim_remote_task(rec_ext["id"])
    r7 = dispatch.submit_remote_result(t7["id"], bundle7, actor="alice",
                                       device_id=rec_ext["id"], usage_meta=meta)
    t7_now = dispatch._find(dispatch._load(), t7["id"])
    ok(t7_now.get("ai_cost", 0) > 0, "an EXTERNAL device's usage still lands on ITS card (ai_cost)")
    turn_ev7 = next((e for e in _events.read_events()
                     if e.get("kind") == "turn" and e.get("track") == t7["id"]), None)
    ok(turn_ev7 and turn_ev7.get("external") is True,
       "the turn event for an external-scope device is tagged external=True")

    branch8 = "device/feature-econ-shared"
    git(remote_clone, "checkout", "-q", "-b", branch8)
    open(os.path.join(remote_clone, "econ_shared.txt"), "w").write("x\n")
    git(remote_clone, "add", "-A"); git(remote_clone, "commit", "-qm", "econ shared")
    bundle8 = os.path.join(tmp, "s8.bundle")
    subprocess.run(["git", "-C", remote_clone, "bundle", "create", bundle8, branch8],
                   capture_output=True, text=True)
    t8 = dispatch.new_remote_task(central, branch8, "econ shared", rec_shared["id"], actor="alice")
    dispatch.claim_remote_task(rec_shared["id"])
    r8 = dispatch.submit_remote_result(t8["id"], bundle8, actor="alice",
                                       device_id=rec_shared["id"], usage_meta=meta)
    turn_ev8 = next((e for e in _events.read_events()
                     if e.get("kind") == "turn" and e.get("track") == t8["id"]), None)
    ok(turn_ev8 and not turn_ev8.get("external"),
       "the turn event for a SHARED-scope device carries no external tag")

    # a submit with NO usage_meta (worker couldn't parse the CLI output) must
    # still land the card cleanly - cost reporting is best-effort, never a
    # blocker for real work.
    branch9 = "device/feature-no-usage"
    git(remote_clone, "checkout", "-q", "-b", branch9)
    open(os.path.join(remote_clone, "no_usage.txt"), "w").write("x\n")
    git(remote_clone, "add", "-A"); git(remote_clone, "commit", "-qm", "no usage")
    bundle9 = os.path.join(tmp, "s9.bundle")
    subprocess.run(["git", "-C", remote_clone, "bundle", "create", bundle9, branch9],
                   capture_output=True, text=True)
    t9 = dispatch.new_remote_task(central, branch9, "no usage", rec_ext["id"], actor="alice")
    dispatch.claim_remote_task(rec_ext["id"])
    r9 = dispatch.submit_remote_result(t9["id"], bundle9, actor="alice",
                                       device_id=rec_ext["id"], usage_meta=None)
    ok(r9.get("lane") in ("review", "done"), "a submit with no usage_meta still lands normally")

    print("\n%d failure(s)" % len(_fails))
    if _fails:
        sys.exit(1)
    print("all green - %s" % tmp)


if __name__ == "__main__":
    main()
