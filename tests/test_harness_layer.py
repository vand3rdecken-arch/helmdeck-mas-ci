# -*- coding: utf-8 -*-
"""The harness layer: briefs-as-data, the settings layer, and the loop state machine.

Three things are guarded here, each of which failed silently before it existed:

1. DRIFT. The briefs now live in harness/agents/*.md, but drivers.py and
   copilot.py still carry the same text as their built-in fallback (deliberately:
   a mangled file must degrade to today's behaviour, not to a lobotomised agent).
   Two copies of a prompt is exactly the duplication that let server.py's two
   hand-written loop maps drift apart. So instead of registering that as debt,
   the gate holds them equal.

2. THE FALLBACK. harness.py's one law is that it can never break a spawn. That is
   only true if it is true for a file that is missing, empty, malformed, or has
   garbage frontmatter - so each of those is fed to it here.

3. THE TWO LOOP FALSE POSITIVES. build_stale() nagged every quiet card to run a
   30-minute Android build it could not run, and the workorder ceremony was
   demanded of cards that arrive with a task and a gate already attached.

Self-sandboxing: temp dirs only, no daemon, no git, no network, no LLM. Nothing
here spawns an agent - the settings layer is checked as ARGV, because whether
the CLI honours those flags is a question for daemon/probe_harness_settings.py
(which measures it against the real binary), not for a unit test to pretend at.
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "daemon"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import harness

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# -- 1. the data and the built-in fallback must not drift --------------------
def test_no_drift():
    import drivers, copilot
    check(harness.brief("card-worker") == harness._resolve(
        harness._DEFAULT_CARD, harness._DEFAULTS["card-worker"][1]),
        "harness/agents/card-worker.md == the built-in card fallback")
    check(harness.brief("machine-worker") == harness._resolve(
        harness._DEFAULT_MACHINE, harness._DEFAULTS["machine-worker"][1]),
        "harness/agents/machine-worker.md == the built-in machine fallback")
    check(harness.brief("board-copilot", default=copilot.SYSTEM) == copilot.SYSTEM,
        "harness/agents/board-copilot.md == copilot.SYSTEM (the 10 KB role)")
    # the surfaces a track can resolve to
    check(drivers._agent_for({"machine": True}) == "machine-worker" and
          drivers._agent_for({}) == "card-worker", "a track resolves to its surface")


# -- 2. the wire protocol is spliced in, and stays owned by ask.py ------------
def test_ask_protocol():
    import ask
    card = harness.brief("card-worker")
    check(ask.BRIEF in card, "the card brief carries ask.BRIEF verbatim")
    check(harness.ASK_MARKER not in card, "the {{ask_protocol}} marker is consumed")
    check(ask.BRIEF not in harness.brief("board-copilot", default="x"),
          "the copilot does NOT get the ask protocol (it answers with an actions block)")
    # the protocol must come from code, so a reworded .md cannot break ask.parse()
    src = open(os.path.join(ROOT, "harness", "agents", "card-worker.md"),
               encoding="utf-8").read()
    check("helmdeck-ask" not in src,
          "the .md does not hardcode the protocol - ask.py owns it")


# -- 3. the settings layer, as argv ------------------------------------------
def test_cli_args():
    a = harness.cli_args("card-worker")
    check(a[:2] == ["--setting-sources", "project"],
          "a card drops the operator's ~/.claude but keeps the repo project layer")
    check("--settings" in a and a[a.index("--settings") + 1].endswith("card.json"),
          "a card gets harness/settings/card.json")
    c = harness.cli_args("board-copilot")
    check(c[:2] == ["--setting-sources", ""],
          "the copilot loads NO ambient layer (not even the repo Stop hook)")
    check("--settings" in c and c[c.index("--settings") + 1].endswith("copilot.json"),
          "the copilot gets its own settings file, not a cwd accident")
    for name in ("card", "copilot"):
        import json
        p = os.path.join(ROOT, "harness", "settings", "%s.json" % name)
        d = json.load(open(p, encoding="utf-8"))          # must be valid JSON
        blob = json.dumps(d)
        check("BEGIN PRIVATE KEY" not in blob and "sk-" not in blob,
              "%s.json carries no secret (it is tracked in git)" % name)


# -- 4. THE LAW: a broken harness file can never break a spawn ---------------
def test_never_breaks_a_spawn():
    tmp = tempfile.mkdtemp(prefix="hd-harness-")
    real_agents, real_settings = harness.AGENTS, harness.SETTINGS
    try:
        harness.AGENTS = os.path.join(tmp, "agents")
        harness.SETTINGS = os.path.join(tmp, "settings")
        os.makedirs(harness.AGENTS)
        os.makedirs(harness.SETTINGS)
        harness._cache.clear()

        # (a) nothing there at all
        check(harness._DEFAULT_CARD.split(".")[0] in harness.brief("card-worker"),
              "missing harness/ -> the built-in brief, unchanged")
        check(harness.cli_args("card-worker") == ["--setting-sources", "project"],
              "missing settings file -> no --settings flag, never a bad path")

        # (b) each way a file can be broken
        for label, body in (
                ("empty", ""),
                ("frontmatter only", "---\nname: card-worker\n---\n"),
                ("unterminated frontmatter", "---\nname: card-worker\nbody without end"),
                ("garbage yaml", "---\n\tname: [unclosed\n---\nreal body text here"),
                ("no frontmatter", "just a body, no frontmatter at all")):
            p = os.path.join(harness.AGENTS, "card-worker.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
            harness._cache.clear()
            got = harness.brief("card-worker")
            check(bool(got and got.strip()), "%s -> still a usable brief" % label)
            args = harness.cli_args("card-worker")
            check(isinstance(args, list), "%s -> cli_args still a list" % label)

        # (c) a settings file that is not JSON must not reach the CLI: the CLI
        #     ignores an invalid settings file SILENTLY, so passing it would
        #     look like isolation while providing none.
        with open(os.path.join(harness.SETTINGS, "card.json"), "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        harness._cache.clear()
        with open(os.path.join(harness.AGENTS, "card-worker.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: card-worker\nsettings: card\n---\nbody")
        check("--settings" not in harness.cli_args("card-worker"),
              "invalid settings JSON is dropped, not passed to the CLI")
        check(harness.errors(), "a broken file is REPORTED in errors(), not swallowed")
    finally:
        harness.AGENTS, harness.SETTINGS = real_agents, real_settings
        harness._cache.clear()
        harness._errors.clear()


# -- 5. the loop's two false positives ---------------------------------------
def test_loop_state():
    import loop_state

    # (a) BUILD only when the change could actually move the native fingerprint.
    #     A card worktree can never hold the APK (app/.gitignore ignores all of
    #     /android), so before this every quiet card was told to go build one.
    check(loop_state.build_stale(["daemon/server.py", "app/src/app/board.tsx"]) is False,
          "a pure JS/daemon change never nags for a native rebuild")
    check(loop_state.build_stale([]) is False, "no touched files -> nothing to rebuild")
    check(loop_state.touches_native(["app/app.json"]) is True,
          "app.json IS a native trigger (ship.sh fingerprints it)")
    check(loop_state.touches_native(["app/package.json"]) is True,
          "package.json too - its expo/react-native lines feed the fingerprint")

    # (b) card mode is DERIVED from the spawn env, and VERIFIED against this
    #     checkout so a stale inherited variable cannot switch the discipline off.
    old = os.environ.get("HELMDECK_WORKTREE")
    try:
        os.environ["HELMDECK_WORKTREE"] = ROOT
        check(loop_state.card_mode() is True, "HELMDECK_WORKTREE == this tree -> card mode")
        os.environ["HELMDECK_WORKTREE"] = os.path.join(ROOT, "nope", "elsewhere")
        check(loop_state.card_mode() is False,
              "a STALE HELMDECK_WORKTREE does not put the main repo in card mode")
        os.environ.pop("HELMDECK_WORKTREE", None)
        check(loop_state.card_mode() is False, "no env -> repo mode")

        # the machine exports the mode it is in, and only the states of that mode
        m = loop_state.machine()
        keys = [s["key"] for s in m["states"]]
        check(m["mode"] == "repo" and "ALIGN" in keys, "repo mode keeps the workorder ceremony")
        os.environ["HELMDECK_WORKTREE"] = ROOT
        m = loop_state.machine()
        keys = [s["key"] for s in m["states"]]
        check(m["mode"] == "card", "card mode is reported as data")
        check(not ({"ALIGN", "ANALYZE", "TEST", "BUILD"} & set(keys)),
              "a card is not asked to ALIGN/ANALYZE/TEST/BUILD - it has a task and a gate")
        check("EXECUTE" in keys and "CLEAN" in keys,
              "a card still owes red-checks and hygiene (the gate re-runs them)")
        check(all(e["from"] in keys and e["to"] in keys for e in m["edges"]),
              "no edge points at a state this mode does not have")
    finally:
        if old is None:
            os.environ.pop("HELMDECK_WORKTREE", None)
        else:
            os.environ["HELMDECK_WORKTREE"] = old


# -- 6. one definition, both endpoints ---------------------------------------
def test_one_definition():
    import sessions, server
    f = sessions.flow({"done": "Geliefert"})
    check([n["key"] for n in f["nodes"]] == list(sessions.LANES),
          "the lane graph covers exactly the real LANES tuple")
    check(f["nodes"][3]["label"] == "Geliefert", "policy.lane_labels renames a lane")
    check(all(n["kind"] in ("fixed", "policy") for n in f["nodes"]),
          "every node is tagged fixed|policy")
    check(all(n["settings"] for n in f["nodes"] if n["kind"] == "policy"),
          "every POLICY node names the settings key that governs it")

    rt = server._lane_flow({})
    check("lanes" in rt and "gate" in rt, "/loop/map keeps the wire shape the app reads")
    m = server._loop_machine()
    check(m["states"] and "current" in m, "/automation renders from the same machine")
    check([s["key"] for s in m["states"]] ==
          [s["key"] for s in __import__("loop_state").machine()["states"]],
          "the two endpoints cannot drift - they are one call")
    h = server._harness_state()
    check(not h["errors"], "the shipped harness/ files all load clean: %s" % h["errors"])


for fn in (test_no_drift, test_ask_protocol, test_cli_args,
           test_never_breaks_a_spawn, test_loop_state, test_one_definition):
    print(fn.__name__)
    fn()

print(("FAILED: %d" % len(_fails)) if _fails else "all harness-layer checks passed")
sys.exit(1 if _fails else 0)
