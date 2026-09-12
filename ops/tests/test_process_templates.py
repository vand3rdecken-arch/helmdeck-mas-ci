# -*- coding: utf-8 -*-
"""Process TEMPLATES vs process RUNS (process/config split, owner decree
2026-09-03: "das ist auch config, wie trennen" - a process row mixed its
reusable step SHAPE with per-run fields in one blob, so the shape never
accumulated anywhere an owner could export it).

Pins:
  1. a template's steps are a CLOSED shape - runtime fields never survive
     save_template, however they arrive (fresh dict, or lifted off a real
     run's steps via template_from_process)
  2. creating a process from a template is deterministic (no LLM call) and
     the run's steps carry no template-only leftovers, just runtime state
  3. an explicit tid UPSERTS (create OR overwrite) - the shape a harness
     import needs to replay a template at its original id
  4. deleting a template is real, and returns False for an unknown id
  5. GET /harness/export includes process_templates; POST /harness/import
     replays a template through save_template, never a raw db write

Self-sandboxing: db.ROOT/db.DBPATH + events.EV/SET redirected to a temp dir,
same preamble as test_processes_db_migration.py.

Run: py -3.12 ops/tests/test_process_templates.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-tmpltest-")
    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    db.init(role="tool")
    assert db.DBPATH.startswith(tmp), "REFUSING TO RUN: db not sandboxed"

    from cells.engineer.chains import processes

    # 1. closed shape: runtime fields never survive save_template.
    dirty_steps = [{"title": "Vorlage entwerfen", "desc": "aus Muster", "mode": "do",
                    "days": 2, "done": True, "lane": "done", "track": "t-123",
                    "state": "done", "ready": False, "auto_dispatched": True}]
    doc = processes.save_template("Vertrag Q3", "Standard-Vertragsprozess", dirty_steps,
                                  actor="owner")
    tid = doc["id"]
    check(set(doc["steps"][0].keys()) == {"title", "desc", "mode", "days"},
          "save_template strips every runtime field (got %r)" % sorted(doc["steps"][0].keys()))
    check(doc["steps"][0]["title"] == "Vorlage entwerfen", "the real content survives")
    check(tid == "vertrag-q3", "id auto-slugified from the name (got %r)" % tid)

    listed = processes.list_templates()
    check(tid in listed and listed[tid]["name"] == "Vertrag Q3",
          "list_templates surfaces the saved template")

    # 2. deterministic creation from a template - no LLM call, no proposer thread.
    p = processes.create("Kunde Meier Q3", actor="owner", template_id=tid)
    check(p["status"] == "ready", "a template-sourced process is ready immediately")
    check(p["template_id"] == tid, "the run remembers which template it came from")
    check(len(p["steps"]) == 1 and p["steps"][0]["title"] == "Vorlage entwerfen",
          "the run's steps come from the template")
    check(set(p["steps"][0].keys()) >= {"status", "track", "due"},
          "the run's steps carry RUNTIME fields the template itself never has")

    unknown = None
    try:
        processes.create("x", actor="owner", template_id="does-not-exist")
    except RuntimeError as e:
        unknown = e
    check(unknown is not None, "an unknown template_id refuses, not silently empty-steps")

    # 3. explicit tid UPSERTS - the shape a harness import needs.
    processes.save_template("Vertrag Q3 v2", "updated", dirty_steps, tid=tid, actor="owner")
    check(processes.get_template(tid)["name"] == "Vertrag Q3 v2",
          "an explicit tid overwrites the existing template")
    processes.save_template("Fresh at a chosen id", "x", dirty_steps,
                            tid="brand-new-id", actor="owner")
    check(processes.get_template("brand-new-id") is not None,
          "an explicit tid also creates fresh when nothing existed there yet "
          "(the shape harness-import needs: replay at the original id either way)")

    # 4. template_from_process strips a real run down to its shape.
    run_doc = processes.template_from_process(p["id"], name="From a real run", actor="owner")
    check(set(run_doc["steps"][0].keys()) == {"title", "desc", "mode", "days"},
          "template_from_process strips the run's own runtime fields too")

    # 5. deletion.
    check(processes.delete_template("brand-new-id", actor="owner") is True,
          "deleting an existing template succeeds")
    check(processes.delete_template("brand-new-id", actor="owner") is False,
          "deleting an already-gone template returns False, not an exception")

    # 6. export/import round trip through the real HTTP handlers (owner-only,
    # replay-through-writers contract already proven for the other planes).
    from spine.http.routes import routes_settings

    class FakeConn:
        def __init__(self):
            self.sent = None
        def _send(self, code, body):
            self.sent = (code, body)
            return self.sent
    import json as _json

    class FakeSelf(FakeConn):
        path = "/harness/export"

    owner = {"name": "owner", "role": "owner"}
    exp_self = FakeSelf()
    routes_settings.harness_export_get(exp_self, owner)
    code, body = exp_self.sent
    check(code == 200, "GET /harness/export succeeds")
    exported = _json.loads(body)
    check(tid in (exported.get("process_templates") or {}),
          "the export includes process_templates (got keys %r)" %
          sorted((exported.get("process_templates") or {}).keys()))

    # wipe and re-import from the export - never a raw db write.
    processes.delete_template(tid, actor="owner")
    check(processes.get_template(tid) is None, "template wiped before import")
    imp_self = FakeConn()
    routes_settings.harness_import_post(imp_self, owner, {"process_templates": exported["process_templates"]})
    code2, body2 = imp_self.sent
    check(code2 == 200, "POST /harness/import succeeds")
    result = _json.loads(body2)["result"]
    check(result.get("template:" + tid) == "ok", "import reports the template row ok")
    restored = processes.get_template(tid)
    check(restored is not None and restored["name"] == "Vertrag Q3 v2",
          "the template is back, byte-identical in content")

    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        sys.exit(1)
    print("process-templates: all pinned - PASS")


if __name__ == "__main__":
    main()
