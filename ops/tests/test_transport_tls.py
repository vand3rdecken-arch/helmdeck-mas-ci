# -*- coding: utf-8 -*-
"""Self-sandboxing checks for the [single-secret-transport] payment: the
insecure_url truth table, the pairing/settings https guards, and the TLS
config resolution. Run:  py -3.12 ops/tests/test_transport_tls.py
(Redirects settings AND the db to a temp dir. Settings live in the db since
the config consolidation - patching events.SET alone stopped sandboxing
anything, and a 2026-09-03 run of exactly that stale sandbox wrote this
test's relay/tls values into the LIVE workspace_config until the relay
block was restored from its .imported archive. Both db.ROOT and db.DBPATH
must be patched - see test_hook_idle.py's preamble for the ROOT half.)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def main():
    from spine.storage import db, events
    from spine.comms import relay_client as rc

    # sandbox: settings (db-backed) live in a temp dir for this test's duration
    tmp = tempfile.mkdtemp(prefix="helmdeck-tls-test-")
    old_conn = getattr(db._local, "c", None)
    if old_conn is not None:
        old_conn.close()
        db._local.c = None
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "helmdeck.db")
    events.SET = os.path.join(tmp, "settings.json")
    db.init()
    assert db.DBPATH.startswith(tmp), "REFUSING TO RUN: db not sandboxed"

    cases = [
        ("http://192.168.178.22:8140", True),
        ("http://1.2.3.4", True),
        ("http://relay.example.com", True),
        ("https://relay.example.com", False),
        ("http://localhost:6790", False),
        ("http://127.0.0.1:6790", False),
        ("http://127.5.5.5:6790", False),
        ("http://[::1]:6790", False),
        ("", False),
    ]
    for url, want in cases:
        got = rc.insecure_url(url)
        assert got == want, (url, got, want)
    print("insecure_url: %d cases OK" % len(cases))

    events.save_settings({"relay": {"url": "http://192.168.178.22:6790"}})
    try:
        rc.pairing_payload()
        raise SystemExit("FAIL: pairing_payload accepted a plain-http relay url")
    except ValueError as e:
        print("pairing_payload refuses http url OK: %s..." % str(e)[:50])
    # refusal must not have opened the pairing window
    assert not (events.settings().get("relay") or {}).get("pair_pending")
    print("refusal left no pairing window open OK")

    events.save_settings({"relay": {"url": "https://relay.example.com"}})
    pay = rc.pairing_payload()
    assert pay.get("room") and pay.get("daemon_pub")
    assert pay["url"].startswith("https://")
    print("pairing_payload with https url OK (room + pub minted)")

    from spine.http import server
    os.environ.pop("HELMDECK_TLS_CERT", None)
    os.environ.pop("HELMDECK_TLS_KEY", None)
    os.environ["HELMDECK_TLS_PORT"] = "9999"
    events.save_settings({"tls": {"cert": "", "key": ""}})
    cert, key, tls_port = server._tls_config()
    # auto-detect depends on whether daemon/certs exists on this machine
    auto = os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "certs", "tls.crt"))
    assert (cert is not None) == auto and tls_port == 9999
    os.environ["HELMDECK_TLS_CERT"] = "X:/nope.crt"
    os.environ["HELMDECK_TLS_KEY"] = "X:/nope.key"
    cert, key, tls_port = server._tls_config()
    assert cert == "X:/nope.crt" and key == "X:/nope.key"
    os.environ.pop("HELMDECK_TLS_CERT")
    os.environ.pop("HELMDECK_TLS_KEY")
    os.environ.pop("HELMDECK_TLS_PORT")
    print("_tls_config precedence OK (env > settings > auto-detect, port env)")

    print("ALL OK")


if __name__ == "__main__":
    main()
