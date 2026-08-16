# -*- coding: utf-8 -*-
"""The companion registry, attacked where a shallow test would agree with a bug.

Three questions decide whether this layer is real, and none of them is answered
by "the call returned without raising":

1. IS THE TICKET ACTUALLY A SECRET? Storing a credential is easy to get subtly
   wrong - the token ends up in the file next to its hash, or revocation checks
   the wrong field. So the store is read back as TEXT and the raw token must not
   appear anywhere in it, and every rejection path (revoked, wrong scope,
   garbage, empty) is asserted separately rather than as one truthy check.

2. IS A COMMAND CONSUMED ON PROOF, OR ON READ? This is the load-bearing one and
   the repo's NO-MONKEY-PATCHES law in miniature. Consuming on read looks
   identical in the happy path and silently drops a command whenever a device
   dies between fetch and execution. So the test explicitly fetches TWICE
   without acking and demands the command BOTH times, then acks and demands it
   is gone. A consume-on-read implementation passes every other test in this
   file and fails exactly this one.

3. DOES THE FAIL-SAFE HOLD? A corrupt store must degrade to "nobody enrolled"
   and never raise into the daemon - the owner's own auth does not live here, so
   a crash would be a lockout with extra steps.

Self-sandboxing: companion.STORE is redirected to a temp file for every test and
restored in a finally, so the real daemon/companion.json is never touched. No
daemon, no network, no git.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import companion


class Base(unittest.TestCase):
    def setUp(self):
        self._real = companion.STORE
        self._dir = tempfile.mkdtemp(prefix="hd-companion-")
        companion.STORE = os.path.join(self._dir, "companion.json")

    def tearDown(self):
        companion.STORE = self._real


class TestTickets(Base):
    def test_token_is_returned_once_and_never_stored(self):
        out = companion.mint_ticket("phone")
        token = out["token"]
        self.assertTrue(token.startswith("hdc_"))

        # the raw token must not survive anywhere in the store
        with open(companion.STORE, encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn(token, raw)
        self.assertIn("hash", raw)

        # and it is never handed back by any read path
        self.assertNotIn("hash", out["device"])
        for dev in companion.list_devices():
            self.assertNotIn("hash", dev)

    def test_authorize_accepts_the_real_token_only(self):
        token = companion.mint_ticket("phone")["token"]
        self.assertIsNotNone(companion.authorize(token))

        for bad in ("", None, "hdc_wrong", token + "x", token[:-1]):
            self.assertIsNone(companion.authorize(bad), "accepted %r" % (bad,))

    def test_revoke_kills_one_device_and_leaves_the_others(self):
        a = companion.mint_ticket("phone")
        b = companion.mint_ticket("tablet")

        companion.revoke(a["device"]["id"])
        self.assertIsNone(companion.authorize(a["token"]))
        self.assertIsNotNone(companion.authorize(b["token"]),
                             "revoking one ticket must not disturb another")

        # revoking twice is a no-op, not a crash
        self.assertIsNone(companion.revoke(a["device"]["id"]))

    def test_scopes_are_enforced_not_decorative(self):
        token = companion.mint_ticket("mic-only", scopes=("observe",))["token"]
        self.assertIsNotNone(companion.authorize(token, scope="observe"))
        self.assertIsNone(companion.authorize(token, scope="command"))
        self.assertIsNone(companion.authorize(token, scope="config"))

    def test_unknown_scope_is_refused_at_mint(self):
        with self.assertRaises(ValueError):
            companion.mint_ticket("bad", scopes=("observe", "root"))

    def test_last_seen_is_an_observation(self):
        token = companion.mint_ticket("phone")["token"]
        self.assertIsNone(companion.list_devices()[0]["last_seen"])
        companion.authorize(token)
        self.assertIsNotNone(companion.list_devices()[0]["last_seen"])


class TestFailSafe(Base):
    def test_corrupt_store_degrades_to_empty_and_never_raises(self):
        with open(companion.STORE, "w", encoding="utf-8") as f:
            f.write("{not json at all")
        self.assertEqual(companion.list_devices(), [])
        self.assertIsNone(companion.authorize("hdc_anything"))
        self.assertEqual(companion.config()["poll_seconds"], 60)

    def test_missing_store_is_not_an_error(self):
        self.assertFalse(os.path.exists(companion.STORE))
        self.assertEqual(companion.list_devices(), [])
        self.assertIsNone(companion.authorize("hdc_anything"))

    def test_wrong_shape_store_degrades(self):
        with open(companion.STORE, "w", encoding="utf-8") as f:
            f.write('["a list, not an object"]')
        self.assertEqual(companion.list_devices(), [])


class TestConfig(Base):
    def test_defaults_never_ship_a_fast_poll(self):
        # the reference project shipped 10s, called it near-polling, and wrote
        # the rule down. Guard it so nobody "optimises" it back.
        self.assertGreaterEqual(companion.config()["poll_seconds"], 60)

    def test_every_sensing_capability_defaults_off(self):
        cfg = companion.config()
        for k in ("mic_enabled", "camera_enabled", "notifications_enabled"):
            self.assertFalse(cfg[k], "%s must default OFF" % k)

    def test_override_merges_over_defaults(self):
        companion.save_config({"mic_enabled": True})
        cfg = companion.config()
        self.assertTrue(cfg["mic_enabled"])
        self.assertEqual(cfg["poll_seconds"], 60)   # untouched key survives


class TestCommandsConsumedOnProof(Base):
    def setUp(self):
        Base.setUp(self)
        self.dev = companion.mint_ticket("phone")["device"]["id"]

    def test_pending_does_not_consume(self):
        """THE test. A fetch is not proof of execution."""
        cmd = companion.queue_command("capture_photo")

        first = companion.pending(self.dev)
        self.assertEqual([c["id"] for c in first], [cmd["id"]])

        second = companion.pending(self.dev)
        self.assertEqual([c["id"] for c in second], [cmd["id"]],
                         "a command vanished on READ - a device that died "
                         "between fetch and execution would lose it silently")

    def test_ack_is_what_consumes(self):
        cmd = companion.queue_command("capture_photo")
        companion.pending(self.dev)
        companion.ack(cmd["id"], self.dev, ok=True, result={"file": "x.jpg"})
        self.assertEqual(companion.pending(self.dev), [])

    def test_ack_is_idempotent(self):
        cmd = companion.queue_command("capture_photo")
        companion.pending(self.dev)
        first = companion.ack(cmd["id"], self.dev, ok=True)
        again = companion.ack(cmd["id"], self.dev, ok=False)
        self.assertEqual(first["state"], "done")
        self.assertEqual(again["state"], "done",
                         "a retried ack must not flip a settled command")

    def test_failure_is_recorded_as_failure_not_success(self):
        cmd = companion.queue_command("capture_photo")
        companion.pending(self.dev)
        out = companion.ack(cmd["id"], self.dev, ok=False, result={"err": "denied"})
        self.assertEqual(out["state"], "failed")
        self.assertEqual(out["result"], {"err": "denied"})

    def test_ack_of_unknown_command_is_none(self):
        self.assertIsNone(companion.ack("cmd_nope", self.dev))

    def test_redelivery_is_capped(self):
        companion.queue_command("capture_photo")
        for _ in range(companion.MAX_ATTEMPTS):
            self.assertEqual(len(companion.pending(self.dev)), 1)
        self.assertEqual(companion.pending(self.dev), [],
                         "a command that keeps killing its device must stop "
                         "being redelivered")

    def test_expiry_is_derived_from_the_clock_not_a_sweeper(self):
        cmd = companion.queue_command("capture_photo")
        d = companion._load()
        d["commands"][0]["created"] -= (companion.COMMAND_TTL + 1)
        companion._save(d)

        self.assertEqual(companion.pending(self.dev), [])
        states = {c["id"]: c["state"] for c in companion.list_commands(True)}
        self.assertEqual(states[cmd["id"]], "expired")

    def test_command_targeted_at_one_device_is_not_offered_to_another(self):
        other = companion.mint_ticket("tablet")["device"]["id"]
        companion.queue_command("capture_photo", device_id=other)
        self.assertEqual(companion.pending(self.dev), [])
        self.assertEqual(len(companion.pending(other)), 1)

    def test_empty_kind_is_refused(self):
        with self.assertRaises(ValueError):
            companion.queue_command("   ")

    def test_sweep_keeps_live_commands(self):
        live = companion.queue_command("capture_photo")
        done = companion.queue_command("say_hello")
        companion.pending(self.dev)
        companion.ack(done["id"], self.dev)

        companion.sweep(max_settled=10)
        ids = [c["id"] for c in companion.list_commands()]
        self.assertIn(live["id"], ids)


class TestConcurrency(Base):
    """Regression: the store is read-modify-written from a ThreadingHTTPServer.

    This is not a hypothetical. Before the lock, 8 threads queueing 40 commands
    landed 5 of them, and on Windows 7 of the 8 threads died outright with
    PermissionError because every writer used the same `.tmp` path and collided
    inside os.replace. "A device polls while the owner queues a command" is the
    feature's ordinary case, so this had to be a fix, not a debt entry.
    """

    def test_concurrent_writers_lose_nothing(self):
        import threading
        errs = []

        def queue(n):
            try:
                for i in range(5):
                    companion.queue_command("cmd_%d_%d" % (n, i))
            except Exception as e:          # a crashed writer is the other half
                errs.append(e)              # of the bug, not just a lost row

        ts = [threading.Thread(target=queue, args=(n,)) for n in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

        self.assertEqual(errs, [], "a concurrent writer raised")
        self.assertEqual(len(companion.list_commands()), 40, "lost updates")

    def test_concurrent_acks_settle_each_command_once(self):
        import threading
        dev = companion.mint_ticket("phone")["device"]["id"]
        cmds = [companion.queue_command("k%d" % i) for i in range(20)]
        companion.pending(dev)

        def ack(c):
            companion.ack(c["id"], dev, ok=True)

        ts = [threading.Thread(target=ack, args=(c,)) for c in cmds]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

        states = [c["state"] for c in companion.list_commands(include_settled=True)]
        self.assertEqual(states.count("done"), 20)
        self.assertEqual(companion.pending(dev), [])

    def test_no_temp_files_are_left_behind(self):
        companion.mint_ticket("phone")
        junk = [f for f in os.listdir(os.path.dirname(companion.STORE))
                if f.endswith(".tmp")]
        self.assertEqual(junk, [], "a temp file survived a write")


class TestObservations(Base):
    def test_newest_value_per_key(self):
        companion.record("dev_1", "battery", 90)
        companion.record("dev_1", "battery", 80)
        self.assertEqual(companion.observations()["battery"]["value"], 80)

    def test_oversize_observation_is_refused(self):
        with self.assertRaises(ValueError):
            companion.record("dev_1", "blob", "x" * (companion.MAX_OBSERVATION_BYTES + 1))

    def test_key_is_required(self):
        with self.assertRaises(ValueError):
            companion.record("dev_1", "", 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
