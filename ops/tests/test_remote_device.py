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

    # re-submitting the same branch must not silently clobber
    try:
        dispatch.submit_remote_result(t["id"], bundle_path, actor="alice")
        ok(False, "re-submitting an already-imported branch should raise")
    except RuntimeError as e:
        ok("already exists" in str(e), "refuses to re-import/clobber the branch")

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

    print("\n%d failure(s)" % len(_fails))
    if _fails:
        sys.exit(1)
    print("all green - %s" % tmp)


if __name__ == "__main__":
    main()
