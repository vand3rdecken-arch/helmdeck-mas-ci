# -*- coding: utf-8 -*-
"""The harness layer: briefs-as-data, the settings layer, and the loop state machine.

Three things are guarded here, each of which failed silently before it existed:

1. DRIFT. The briefs now live in ops/harness/agents/*.md, but drivers.py and
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
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))

from spine.registry import harness

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# -- 1. the data and the built-in fallback must not drift --------------------
def test_no_drift():
    from spine.agent import drivers
    from cells.copilot import copilot
    check(harness.brief("card-worker") == harness._resolve(
        harness._DEFAULT_CARD, harness._DEFAULTS["card-worker"][1]),
        "ops/harness/agents/card-worker.md == the built-in card fallback")
    check(harness.brief("machine-worker") == harness._resolve(
        harness._DEFAULT_MACHINE, harness._DEFAULTS["machine-worker"][1]),
        "ops/harness/agents/machine-worker.md == the built-in machine fallback")
    henry = harness.brief("board-copilot")
    check(len(henry) > 10000 and "degraded mode" not in henry,
        "board-copilot.md resolves as THE role (policy is data, no code copy)")
    # the surfaces a track can resolve to
    check(drivers._agent_for({"machine": True}) == "machine-worker" and
          drivers._agent_for({}) == "card-worker", "a track resolves to its surface")


# -- 2. the wire protocol is spliced in, and stays owned by ask.py ------------
def test_ask_protocol():
    from spine.ops import ask
    card = harness.brief("card-worker")
    check(ask.BRIEF in card, "the card brief carries ask.BRIEF verbatim")
    check(harness.ASK_MARKER not in card, "the {{ask_protocol}} marker is consumed")
    check(ask.BRIEF not in harness.brief("board-copilot", default="x"),
          "the copilot does NOT get the ask protocol (it answers with an actions block)")
    # the protocol must come from code, so a reworded .md cannot break ask.parse()
    src = open(os.path.join(ROOT, "ops", "harness", "agents", "card-worker.md"),
               encoding="utf-8").read()
    check("helmdeck-ask" not in src,
          "the .md does not hardcode the protocol - ask.py owns it")


# -- 3. the settings layer, as argv ------------------------------------------
def test_cli_args():
    a = harness.cli_args("card-worker")
    check(a[:2] == ["--setting-sources", "project"],
          "a card drops the operator's ~/.claude but keeps the repo project layer")
    check("--settings" in a and a[a.index("--settings") + 1].endswith("card.json"),
          "a card gets ops/harness/settings/card.json")
    c = harness.cli_args("board-copilot")
    check(c[:2] == ["--setting-sources", ""],
          "the copilot loads NO ambient layer (not even the repo Stop hook)")
    check("--settings" in c and c[c.index("--settings") + 1].endswith("copilot.json"),
          "the copilot gets its own settings file, not a cwd accident")
    for name in ("card", "copilot"):
        import json
        p = os.path.join(ROOT, "ops", "harness", "settings", "%s.json" % name)
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
              "missing ops/harness/ -> the built-in brief, unchanged")
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
    #
    #     STUBBED, not ambient: build_stale() consults a REAL marker
    #     (ops/deploy/.native_fp) and a REAL fingerprint (git-bash hashing the
    #     actual native sources) when either is available - and this repo's
    #     own dev checkout (unlike a fresh card worktree, which never ships
    #     natively) genuinely HAS shipped from here before. Found live: this
    #     exact pair of checks passed in every card's isolated gate (a fresh
    #     worktree has no marker, so the degraded/heuristic path always
    #     answered) and only failed on the owner's real box, where a stale-
    #     but-real marker made the AUTHORITATIVE path answer instead - correctly,
    #     but not what these two lines are trying to pin. Stub both signals to
    #     "" so the assertion is about the DEGRADED-path guess (what a fresh
    #     card worktree actually sees) on every machine, not about whether
    #     THIS checkout's native fingerprint happens to be stale right now.
    _fp, _mk = loop_state._native_fp, loop_state._ship_marker
    try:
        loop_state._native_fp = lambda: ""
        loop_state._ship_marker = lambda: ""
        check(loop_state.build_stale(["daemon/server.py", "surfaces/app/src/app/board.tsx"]) is False,
              "a pure JS/daemon change never nags for a native rebuild")
        check(loop_state.build_stale([]) is False, "no touched files -> nothing to rebuild")

        # (a2) WHICH SIGNAL ANSWERS. There are two, and they are not equal: the
        #      fingerprint is derived from the real native inputs, `touched` is
        #      reconstructed from `git status` and cannot see surfaces/app/android/ at all.
        #      Ordering the heuristic first let that blind spot VETO the
        #      authoritative check (debt: build-stale-tracked-sources-only). Both
        #      directions are pinned here, with both signals stubbed so the check is
        #      deterministic on a box with no git-bash and no APK.
        loop_state._native_fp = lambda: "AAA"
        loop_state._ship_marker = lambda: "BBB"
        check(loop_state.build_stale([]) is True,
              "FALSE NEGATIVE CLOSED: fingerprint moved -> stale even though the "
              "change is invisible to git (an edit under the ignored surfaces/app/android/)")
        loop_state._ship_marker = lambda: "AAA"
        check(loop_state.build_stale(["app/app.json"]) is False,
              "fingerprint matches the ship marker -> NOT stale, even though a "
              "native trigger path was touched (the OTA version-bump case)")
        loop_state._ship_marker = lambda: ""          # never shipped from here
        check(loop_state.build_stale(["daemon/server.py"]) is False,
              "FALSE POSITIVE STILL FIXED: no marker (a card worktree) -> degrade "
              "to the guess, and a non-native change stays silent")
        check(loop_state.build_stale([]) is False,
              "no marker and nothing touched -> nothing to say")
    finally:
        loop_state._native_fp, loop_state._ship_marker = _fp, _mk
    check(loop_state.touches_native(["app/app.json"]) is True,
          "app.json IS a native trigger (ship.sh fingerprints it)")
    check(loop_state.touches_native(["surfaces/app/package.json"]) is True,
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
    from cells.engineer import sessions
    from spine.http import server
    from spine.http.routes import routes_info
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
    h = routes_info._harness_state()
    check(not h["errors"], "the shipped ops/harness/ files all load clean: %s" % h["errors"])


# -- 7. the export vs the APP'S DECLARED VIEW OF IT --------------------------
# The state machine is single-sourced inside the daemon (test 6), but the app is
# the OTHER copy of it: surfaces/app/src/data/client.ts declares the wire shape the UI
# reads, and nothing connected the two. Adding a column to LOOP_STATES, renaming
# `setting_sources`, or dropping a field from preview() would leave the daemon
# self-consistent and the UI reading `undefined` - typecheck-clean on both sides,
# because tsc never sees the Python and the gate never saw the TypeScript.
#
# So: parse the declared interfaces and diff them against real exported objects.
# Both directions matter and they catch different mistakes.
#   required TS field missing from the export -> the UI silently renders nothing
#   exported field the TS does not declare    -> the machine grew and the view
#                                                was not told; the field is dead
#                                                weight until someone notices
# The second direction needs an escape hatch or it fails on payload that is
# deliberately internal, so DELIBERATE_EXTRAS lists those WITH a reason. Adding
# a field now forces a conscious choice - declare it, or say why it stays
# internal - which is the whole point.
CLIENT_TS = os.path.join(ROOT, "surfaces", "app", "src", "data", "client.ts")
# types.ts is read TOO, not instead: the app splits its wire types across both
# files (client.ts holds the ones declared next to the call that returns them,
# types.ts the shared ones like Me/Profile), and an interface is checkable
# wherever it is declared. Concatenating them is safe because the parser looks
# up interfaces BY NAME and the two files may not declare the same name twice -
# tsc would already reject that.
TYPES_TS = os.path.join(ROOT, "surfaces", "app", "src", "data", "types.ts")

DELIBERATE_EXTRAS = {
    # (interface, field): why the app does not declare it
    ("LoopNode", "default_label"):
        "the pre-rename label; the UI reads `label`, which flow() has already "
        "resolved through policy.lane_labels",
    ("HarnessLayer", "abs"):
        "the absolute path, used by preview()'s own hook scan; the UI shows "
        "`path`, the shortened honest form (~/... inside the home dir)",
}


def _ts_interfaces():
    """{name: {field: required_bool}} from client.ts + types.ts.

    A deliberately small parser: strip comments, find `export interface X`, walk
    to the matching brace tracking depth, and take `name:` / `name?:` at depth 1
    only - so a nested object type (preview's `brief: {...}`) contributes its own
    key and not its children's. It follows `extends`. Anything it cannot parse
    shows up as an empty field set, which the caller reports rather than skips."""
    import re
    src = "\n".join(open(p, encoding="utf-8").read() for p in (CLIENT_TS, TYPES_TS))
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)

    def body_and_bases(name):
        m = re.search(r"export interface %s\b([^{]*)\{" % re.escape(name), src)
        if not m:
            return None, []
        ext = re.findall(r"extends\s+([\w,\s]+)", m.group(1))
        bases = [b.strip() for b in (ext[0].split(",") if ext else []) if b.strip()]
        i, depth, out = m.end(), 1, []
        while i < len(src) and depth:
            c = src[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if not depth:
                    break
            if depth == 1:
                out.append(c)
            i += 1
        return "".join(out), bases

    cache = {}

    def fields(name, seen=None):
        if name in cache:
            return cache[name]
        seen = seen or set()
        if name in seen:
            return {}
        seen.add(name)
        body, bases = body_and_bases(name)
        if body is None:
            return {}
        out = {}
        for b in bases:
            out.update(fields(b, seen))
        for fm in re.finditer(r"(?:^|[;\n])\s*(\w+)(\??)\s*:", body):
            out[fm.group(1)] = (fm.group(2) != "?")
        cache[name] = out
        return out

    return fields


def test_export_matches_the_app_contract():
    from spine.registry import harness
    from cells.engineer import sessions
    import loop_state
    from spine.storage import boards, userconfig
    fields = _ts_interfaces()
    # default_record(), not ensure_default(): this test runs against the LIVE
    # daemon root, so it reads the shape the seed would write without writing
    # anything. Same function the daemon seeds from, so it cannot drift.
    _board = boards.default_record()
    check(os.path.exists(CLIENT_TS), "surfaces/app/src/data/client.ts is where we think it is")
    check(os.path.exists(TYPES_TS), "surfaces/app/src/data/types.ts is where we think it is")

    old = os.environ.pop("HELMDECK_WORKTREE", None)
    try:
        m = loop_state.machine()          # repo mode: the widest state set
        f = sessions.flow({})
        prev = [harness.preview(s["key"]) for s in harness.SURFACES]
        desc = harness.describe()
        # (interface, [objects it describes]) - every ELEMENT is checked, not a
        # sample: only one loop edge carries `modes`, and checking edges[0] would
        # have missed it.
        contract = [
            ("LoopState", m["states"]),
            ("LoopEdge", list(m["edges"]) + list(f["edges"])),
            ("LoopNode", f["nodes"]),
            ("HarnessAgent", desc["agents"]),
            ("HarnessSurface", harness.SURFACES),
            ("HarnessPreview", prev),
            ("HarnessLayer", [l for p in prev for l in p["layers"]]),
            ("HarnessHook", [h for p in prev for h in p["hooks"]]),
            ("HarnessAgentDoc", [harness.agent_doc(s["agent"]) for s in harness.SURFACES]),
            ("HarnessSettingsDoc", [harness.settings_doc(k) for k in harness.settings_keys()]),
            # accounts-boards-prd phase 1. THE drift this catches: the profile
            # whitelist is a closed set in spine/storage/userconfig.py and a
            # mirrored interface in the app, and the two are edited by
            # different hands months apart. A key added server-side but not
            # declared here is a value the daemon happily stores and the app
            # can never read; a key declared here but not whitelisted is a
            # control that renders, writes, and 400s. Neither is a type error
            # on either side - the same blind spot the rows above exist for.
            #
            # defaults() is the right object to diff against precisely because
            # it is the resolution layer: it has one entry per whitelisted key
            # by construction, so it cannot drift from KEYS without the
            # assertion below failing first.
            ("Profile", [userconfig.defaults()]),
            # accounts-boards-prd phase 2, same drift, one layer up: a board
            # crosses the wire as a whole record on /me, so a field the daemon
            # adds and the app never declares is a column layout the app
            # silently cannot render. Checked against a REAL board (the seeded
            # default one) rather than a hand-written sample, so the shape
            # under test is the shape the daemon actually serves.
            ("Board", [_board]),
            ("BoardColumn", _board["columns"]),
        ]
        for name, objs in contract:
            ts = fields(name)
            check(bool(ts), "interface %s is declared in client.ts and parsed" % name)
            if not ts or not objs:
                continue
            need = {k for k, req in ts.items() if req}
            missing, extra = set(), set()
            for o in objs:
                missing |= {k for k in need if k not in o}
                extra |= {k for k in o if k not in ts
                          and (name, k) not in DELIBERATE_EXTRAS}
            check(not missing,
                  "%s: every REQUIRED field the app declares is exported "
                  "(missing: %s)" % (name, sorted(missing)))
            check(not extra,
                  "%s: the daemon exports nothing the app has not declared - "
                  "add it to client.ts or to DELIBERATE_EXTRAS with a reason "
                  "(undeclared: %s)" % (name, sorted(extra)))

        # The whitelist IS the contract, so hold the two halves of it equal
        # directly rather than only through defaults(): every writable key must
        # resolve to something, and every resolvable key must be writable. A
        # key in one and not the other is a knob that either cannot be saved or
        # cannot be read back, and the loop above would not see it.
        check(set(userconfig.KEYS) == set(userconfig.defaults()),
              "userconfig.KEYS (what PUT /me/config accepts) and defaults() "
              "(what GET /me resolves) name the same keys "
              "(write-only: %s, read-only: %s)"
              % (sorted(set(userconfig.KEYS) - set(userconfig.defaults())),
                 sorted(set(userconfig.defaults()) - set(userconfig.KEYS))))
        check(set(userconfig.KEYS) <= set(fields("Profile")),
              "every whitelisted profile key is declared on the app's Profile "
              "interface - an undeclared key is a value the daemon stores and "
              "the app can never read (undeclared: %s)"
              % sorted(set(userconfig.KEYS) - set(fields("Profile"))))
        check(all(not req for req in fields("Profile").values()),
              "every Profile field is OPTIONAL - the app must survive an older "
              "daemon that predates the key, and a phone renders the cached "
              "profile from before it existed")

        # the gate is an intersection type (LoopNode & {between}), which the
        # parser above deliberately does not model - so state its extra field here
        need = {k for k, req in fields("LoopNode").items() if req} | {"between"}
        check(not (need - set(f["gate"])),
              "the gate node carries LoopNode's required fields plus `between` "
              "(missing: %s)" % sorted(need - set(f["gate"])))

        # and the two enums the UI switches on must hold, or a node renders untagged
        every = list(m["states"]) + list(f["nodes"]) + [f["gate"]]
        check(all(n.get("kind") in ("fixed", "policy") for n in every),
              "every state/lane/gate is tagged exactly fixed|policy - the app "
              "picks its lock-vs-options badge off this")
        check(all(isinstance(s.get("source"), str) and ":" in s["source"]
                  for s in m["states"]),
              "every build-loop state cites file:line, read from source at call "
              "time - a fixed node must be checkable, not merely asserted")

        # WHY, not just WHETHER. The map draws a padlock off `kind`; before
        # `why` existed it could say nothing about the reason, and the owner
        # read the whole screen as arbitrarily locked. The app falls back to a
        # generic sentence when `why` is absent - which is the honest thing for
        # an older daemon and exactly the wrong thing for a state added here
        # today, because it degrades silently and looks fine in a screenshot.
        # So the reason is required at the declaration, next to `kind`.
        nowhy = [n["key"] for n in every if not (n.get("why") or "").strip()]
        check(not nowhy,
              "every state/lane/gate declares WHY it is fixed (or what is "
              "adjustable) next to its `kind` - the app must never have to "
              "invent the reason behind a padlock (missing: %s)" % sorted(nowhy))
        # And the reason must be a sentence, not a restatement of the key.
        check(all(len((n.get("why") or "")) > 40 for n in every),
              "each `why` is a real sentence, not a stub")
        keys = {s["key"] for s in harness.SURFACES}
        check(keys == {"card", "machine", "pm"},
              "the surface keys the app's HarnessSurface union names: %s" % sorted(keys))
    finally:
        if old is not None:
            os.environ["HELMDECK_WORKTREE"] = old


def test_policy_knob_contract():
    """The OTHER declarative table: /automation's config_schema.

    Same failure mode as the state machine, different table. The app renders
    each knob generically by switching on `control`, so a knob whose control has
    no branch in that switch renders as NOTHING - silently, on an owner-only
    screen nobody looks at twice. And a labelKey with no dict entry renders the
    raw key. Neither is a type error on either side.

    Reads settings.tsx, not automation.tsx: settings-ia-redesign's
    settings-hub-shell moved the Ctl union + Control component into the hub's
    "automation" door (settings.tsx) - automation.tsx is now a thin redirect
    to it, so the Ctl union no longer lives there."""
    import re
    from spine.http import server
    schema = server._config_schema({})
    check(bool(schema), "server._config_schema() is importable and non-empty")

    auto_tsx = os.path.join(ROOT, "surfaces", "app", "src", "app", "(tabs)", "settings.tsx")
    src = open(auto_tsx, encoding="utf-8").read()
    m = re.search(r'type\s+Ctl\s*=\s*([^;]+);', src)
    check(bool(m), "the app declares its Ctl union in automation.tsx")
    rendered = set(re.findall(r'"(\w+)"', m.group(1))) if m else set()
    # the union is the DECLARATION; the switch is what actually runs, so read
    # both and require the daemon's controls to be in the intersection
    branches = set(re.findall(r'it\.control === "(\w+)"', src))
    emitted = {e["control"] for e in schema}
    check(emitted <= rendered,
          "every control the daemon emits is in the app's Ctl union "
          "(unhandled: %s)" % sorted(emitted - rendered))
    check(emitted <= branches,
          "every control the daemon emits has a real branch in the app's Control "
          "component - a knob with no branch renders NOTHING (unhandled: %s)"
          % sorted(emitted - branches))
    check(set(server.CONTROLS) == rendered,
          "server.CONTROLS and the app's Ctl union are the same set "
          "(daemon-only: %s, app-only: %s)"
          % (sorted(set(server.CONTROLS) - rendered), sorted(rendered - set(server.CONTROLS))))

    dict_src = open(os.path.join(ROOT, "surfaces", "app", "src", "i18n", "dict", "screens.ts"),
                    encoding="utf-8").read()
    for e in schema:
        hit = re.search(r'"%s"\s*:\s*\{([^}]*)\}' % re.escape(e["labelKey"]), dict_src)
        check(bool(hit), "%s has an i18n entry" % e["labelKey"])
        if hit:
            check("de:" in hit.group(1) and "en:" in hit.group(1),
                  "%s carries BOTH languages" % e["labelKey"])
    check(all(len(e["path"].split(".")) == 2 for e in schema),
          "every knob path is exactly two levels - the app's nest() splits on one dot")
    check(all(e["group"] in ("policy", "night") for e in schema),
          "every knob is in a group the app has a panel for")
    check(all(e.get("options") for e in schema if e["control"] in ("multi", "single")),
          "every multi/single knob ships its options - the app renders an empty "
          "chip row otherwise")
    check(all(e.get("keys") for e in schema if e["control"] == "labels"),
          "every labels knob ships its keys")

    # settings-ia-redesign phase 1 (settings-schema-v2): door/level/descKey/
    # scope are the metadata the planned settings hub reads to place and
    # describe each knob without a second hand-maintained table. Held to the
    # same rigor as control/labelKey above - a knob missing one of these
    # would render in the wrong door, in the wrong tier, or with no
    # explanation, silently.
    check(all(e.get("door") for e in schema), "every knob names its settings-hub door")
    check(all(e.get("level") in ("basic", "advanced") for e in schema),
          "every knob is basic or advanced (progressive disclosure)")
    check(all(e.get("scope") in ("workspace", "device", "personal") for e in schema),
          "every knob names its scope (workspace/device/personal)")
    for e in schema:
        dk = e.get("descKey")
        check(bool(dk), "%s has a descKey" % e["path"])
        if not dk:
            continue
        hit = re.search(r'"%s"\s*:\s*\{([^}]*)\}' % re.escape(dk), dict_src)
        check(bool(hit), "%s has an i18n entry" % dk)
        if hit:
            check("de:" in hit.group(1) and "en:" in hit.group(1),
                  "%s carries BOTH languages" % dk)


for fn in (test_no_drift, test_ask_protocol, test_cli_args,
           test_never_breaks_a_spawn, test_loop_state, test_one_definition,
           test_export_matches_the_app_contract, test_policy_knob_contract):
    print(fn.__name__)
    fn()

print(("FAILED: %d" % len(_fails)) if _fails else "all harness-layer checks passed")
sys.exit(1 if _fails else 0)
