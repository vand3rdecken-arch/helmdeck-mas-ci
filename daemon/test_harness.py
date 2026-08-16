# -*- coding: utf-8 -*-
"""The harness LOADER and its WRITE path, checked against the resolved spawn.

Companion to tests/test_harness_layer.py, which holds harness/agents/*.md equal
to the built-in fallbacks and covers the loop state machine. This one goes at
the loader itself and asks the three questions that a "no exception was raised"
test would answer wrongly:

1. THE FALLBACK IS TOTAL. harness.py's one law is that it can never break a
   spawn. Every public function is fed a missing / empty / truncated / garbage /
   wrong-type file and must still return something a spawn can use - and, just
   as important, must REPORT the breakage in errors() rather than swallow it.

2. THE WRITE PATH IS LOUD. It is the deliberate mirror of (1): the read path may
   never raise, the write path must. A rejected edit that returned quietly would
   leave the owner believing a brief is live when it is not. So each rejection
   is asserted to raise AND to leave the file on disk untouched.

3. THE ISOLATION IS REAL, MEASURED ON THE RESOLVED ARGV AND ENV. This is the
   part a shallow test gets wrong. "harness.cli_args() returned two flags" says
   nothing about whether a card is actually isolated: the flags could be in the
   wrong order, name a settings file that does not parse (which the CLI then
   ignores in SILENCE), or be assembled by build_argv into an argv the preview
   never sees. So the assertions here run the REAL builders - drivers.build_argv
   and copilot.build_argv, the same two functions a live spawn calls - and check
   the resolved argv, the resolved ENV (drivers._env), and harness.preview()'s
   provenance table, which is what actually decides whether the operator's
   ~/.claude reaches a worker.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM
   Whether the CLI HONOURS those flags is not a question a unit test can answer
   - it can only be measured against the real binary, which is what
   daemon/probe_harness_settings.py is for (`--validate` for the shipped files,
   `--skills` for the per-surface discovery set). Asserting flag semantics here
   would be pretending, and the last thing this layer needs is a test that is
   confidently wrong about the one thing it exists to guarantee.

Self-sandboxing: temp dirs only. No daemon, no git, no network, no spawn, and
the real harness/ tree is never written to - AGENTS / SETTINGS / VERSIONS are
redirected for every test that writes, and restored in a finally.

Run: py -3.12 daemon/test_harness.py
"""
import json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import harness

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def raises(fn, why):
    """The write path must reject loudly. Returns the message so a caller can
    assert it names the actual problem - a ValueError that says nothing useful
    is only marginally better than silence."""
    try:
        fn()
    except ValueError as e:
        return str(e)
    except Exception as e:                                   # noqa: BLE001
        _fails.append("%s -> raised %s, want ValueError" % (why, type(e).__name__))
        print("  FAIL %s -> %s" % (why, type(e).__name__))
        return ""
    _fails.append("%s -> did NOT raise" % why)
    print("  FAIL %s -> accepted, want ValueError" % why)
    return ""


class Sandbox:
    """Redirect harness.py's three writable directories into a temp tree.

    The write path is exercised for real here (it is half of what is under
    test), so it must not be able to touch the tracked harness/ files - a test
    that rewrites the repo's own briefs would 'pass' while corrupting the thing
    it validates."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="hd-harness-test-")
        self.saved = (harness.AGENTS, harness.SETTINGS, harness.VERSIONS)
        harness.AGENTS = os.path.join(self.tmp, "agents")
        harness.SETTINGS = os.path.join(self.tmp, "settings")
        harness.VERSIONS = os.path.join(self.tmp, ".versions")
        os.makedirs(harness.AGENTS)
        os.makedirs(harness.SETTINGS)
        harness._cache.clear()
        harness._errors.clear()
        return self

    def agent(self, name, text):
        p = os.path.join(harness.AGENTS, "%s.md" % name)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        harness._cache.clear()
        return p

    def settings(self, key, text):
        p = os.path.join(harness.SETTINGS, "%s.json" % key)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        harness._cache.clear()
        return p

    def __exit__(self, *a):
        harness.AGENTS, harness.SETTINGS, harness.VERSIONS = self.saved
        harness._cache.clear()
        harness._errors.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


GOOD_AGENT = ("---\n"
              "name: card-worker\n"
              "description: test brief\n"
              "settings: card\n"
              "setting_sources: project\n"
              "ask_protocol: true\n"
              "---\n"
              "A usable body.\n")


# ---------------------------------------------------------------------------
# 1. THE LAW: a broken file costs the customisation, never the spawn
# ---------------------------------------------------------------------------
def test_fallback_on_malformed():
    print("1. loader falls back on every way a file can be broken")
    # Each case is a file the loader must survive. `usable` says whether the
    # body is real enough to be used; when it is not, the BUILT-IN default must
    # come back - not an empty prompt, which would silently lobotomise a worker.
    cases = [
        ("missing (no file at all)", None, False),
        ("empty file", "", False),
        ("whitespace only", "   \n\n  \n", False),
        ("frontmatter, no body", "---\nname: card-worker\n---\n", False),
        ("unterminated frontmatter", "---\nname: card-worker\nno end marker", True),
        ("garbage yaml + real body", "---\n\tname: [unclosed\n---\nreal body\n", True),
        ("frontmatter is a LIST not a map", "---\n- a\n- b\n---\nbody here\n", True),
        ("frontmatter is a bare scalar", "---\njust a string\n---\nbody here\n", True),
        ("no frontmatter at all", "a body and nothing else\n", True),
        ("NUL bytes in the body", "---\nname: card-worker\n---\nbo\x00dy\n", True),
        # usable=True on purpose. A body of nothing but the marker is a WEIRD
        # edit, not a malformed file: the owner wrote a real body, it just
        # resolves to the ask protocol and no role text. The loader's law is
        # about broken files, not about unwise ones, and silently substituting
        # the built-in default here would overrule a deliberate edit - the exact
        # failure the errors()/fallback split exists to avoid.
        ("only the ask marker as body", "---\nname: card-worker\n---\n{{ask_protocol}}\n", True),
    ]
    for label, body, usable in cases:
        with Sandbox() as sb:
            sb.settings("card", "{}")
            if body is not None:
                sb.agent("card-worker", body)
            got = harness.brief("card-worker")
            check(bool(got and got.strip()), "%s -> still a usable brief" % label)
            # the marker must never survive into a live prompt, whatever happened
            check(harness.ASK_MARKER not in got,
                  "%s -> the {{ask_protocol}} marker is never handed to the model" % label)
            if not usable:
                check(harness._DEFAULT_CARD.split(".")[0] in got,
                      "%s -> falls back to the BUILT-IN brief, not to empty" % label)
            for fn, name in ((harness.meta, "meta"), (harness.cli_args, "cli_args"),
                             (harness.settings_file, "settings_file")):
                try:
                    fn("card-worker")
                except Exception as e:                       # noqa: BLE001
                    check(False, "%s -> %s() raised %s" % (label, name, type(e).__name__))
            check(isinstance(harness.cli_args("card-worker"), list),
                  "%s -> cli_args is still a list" % label)
            check(isinstance(harness.describe(), dict),
                  "%s -> describe() still renders (this is what /loop/map serves)" % label)


def test_broken_is_reported_not_swallowed():
    print("2. a broken file is REPORTED - the fallback is silent, the loader is not")
    with Sandbox() as sb:
        sb.settings("card", "{ not json")
        sb.agent("card-worker", GOOD_AGENT)
        args = harness.cli_args("card-worker")
        # THE trap this guards: the CLI ignores an invalid --settings file in
        # SILENCE. Passing it would look exactly like isolation while providing
        # none, so a file that does not parse must never reach the argv.
        check("--settings" not in args,
              "settings JSON that does not parse is DROPPED, never passed to the CLI")
        check(harness.settings_file("card-worker") == "",
              "settings_file() returns '' rather than a path to a broken file")
        errs = harness.errors()
        check(any("card.json" in k for k in errs),
              "the broken settings file is named in errors()")
        # and it must clear once fixed, or a transient error would be reported forever
        sb.settings("card", "{}")
        harness.settings_file("card-worker")
        check(not any("card.json" in k for k in harness.errors()),
              "errors() CLEARS once the file loads again")


def test_directory_where_a_file_belongs():
    print("3. a directory in place of a file (a real mis-restore) is survivable")
    with Sandbox() as sb:
        sb.settings("card", "{}")
        os.makedirs(os.path.join(harness.AGENTS, "card-worker.md"))
        harness._cache.clear()
        got = harness.brief("card-worker")
        check(bool(got and got.strip()), "a DIRECTORY named card-worker.md -> built-in brief")
        check(isinstance(harness.cli_args("card-worker"), list), "cli_args survives it")
        check(bool(harness.errors()), "and it is reported")


# ---------------------------------------------------------------------------
# 4. $schema validation on write - the loud mirror of the total read path
# ---------------------------------------------------------------------------
def _shipped_schema(sb):
    """Copy the REAL schemas into the sandbox: validation must be tested against
    the schemas that actually ship, not against a fixture that can drift."""
    os.makedirs(os.path.join(sb.tmp, "schema"), exist_ok=True)
    for which in ("agent", "settings"):
        shutil.copy(os.path.join(ROOT, "harness", "schema", "%s.schema.json" % which),
                    os.path.join(sb.tmp, "schema", "%s.schema.json" % which))
    harness.SCHEMA = os.path.join(sb.tmp, "schema")
    harness._cache.clear()


def test_write_validates_against_schema():
    print("4. write_agent/write_settings validate against harness/schema/*.json")
    saved_schema = harness.SCHEMA
    with Sandbox() as sb:
        try:
            _shipped_schema(sb)
            sb.settings("card", "{}")
            path = os.path.join(harness.AGENTS, "card-worker.md")

            res = harness.write_agent("card-worker", GOOD_AGENT, actor="test")
            check(os.path.exists(path), "a valid agent file is written")
            check(res["validator"] in ("jsonschema", "builtin-subset"),
                  "the write SAYS which validator ran (%s) - 'validated' means two "
                  "different things here" % res["validator"])
            before = open(path, encoding="utf-8").read()

            # Every rejection must raise AND leave the file exactly as it was.
            # `want` is deliberately a token BOTH validators emit (the offending
            # key or value), never one validator's prose: jsonschema says
            # "Additional properties are not allowed ('setings' was unexpected)"
            # where the builtin subset says "unbekannter Schluessel: setings".
            # Asserting either wording would make this test pass or fail on
            # whether jsonschema happens to be installed, which is precisely the
            # difference test_both_validator_paths_agree exists to erase.
            bad = [
                ("unknown frontmatter key",
                 GOOD_AGENT.replace("settings: card", "settings: card\nsetings: card"),
                 "setings"),
                ("wrong type for ask_protocol",
                 GOOD_AGENT.replace("ask_protocol: true", "ask_protocol: 7"), "ask_protocol"),
                ("setting_sources outside the enum",
                 GOOD_AGENT.replace("setting_sources: project",
                                    "setting_sources: everything"), "setting_sources"),
                ("required `description` missing",
                 GOOD_AGENT.replace("description: test brief\n", ""), "description"),
                ("frontmatter name != filename",
                 GOOD_AGENT.replace("name: card-worker", "name: someone-else"), "passt nicht"),
                ("settings: names a file that does not exist",
                 GOOD_AGENT.replace("settings: card", "settings: nope"), "nope"),
                ("body is empty (frontmatter only)",
                 "---\nname: card-worker\ndescription: x\n---\n", "Body"),
                ("whole file empty", "   ", "leerer"),
            ]
            for label, text, want in bad:
                msg = raises(lambda t=text: harness.write_agent("card-worker", t, actor="test"),
                             label)
                if msg:
                    check(want.lower() in msg.lower(),
                          "%s -> rejected, and the message names it (%r)" % (label, want))
                check(open(path, encoding="utf-8").read() == before,
                      "%s -> the file on disk is UNCHANGED" % label)

            check(harness.write_agent("card-worker", GOOD_AGENT, actor="test")["path"],
                  "a valid edit still lands after all those rejections")

            # -- settings ---------------------------------------------------
            spath = os.path.join(harness.SETTINGS, "card.json")
            harness.write_settings("card", '{"env": {"A": "b"}}\n', actor="test")
            sbefore = open(spath, encoding="utf-8").read()
            for label, text, want in [
                    ("not JSON at all", "{ nope", "JSON"),
                    ("valid JSON but a LIST", "[1,2]", "Objekt"),
                    ("valid JSON but a string", '"hi"', "Objekt"),
                    ("unknown key inside permissions",
                     '{"permissions": {"allowed": ["x"]}}', "permissions"),
                    ("permissions.allow is not an array",
                     '{"permissions": {"allow": "Bash"}}', "allow")]:
                msg = raises(lambda t=text: harness.write_settings("card", t, actor="test"), label)
                if msg and want:
                    check(want.lower() in msg.lower(),
                          "%s -> rejected, message names it (%r)" % (label, want))
                check(open(spath, encoding="utf-8").read() == sbefore,
                      "%s -> settings on disk UNCHANGED" % label)

            raises(lambda: harness.write_agent("not-a-surface", GOOD_AGENT), "unknown surface")
            raises(lambda: harness.write_settings("not-a-layer", "{}"), "unknown settings layer")
        finally:
            harness.SCHEMA = saved_schema
            harness._cache.clear()


def test_both_validator_paths_agree():
    print("5. the builtin-subset validator rejects what jsonschema rejects")
    # validate() falls back to a hand-written subset on a box without
    # jsonschema. If the two disagree, the harness accepts on one machine what it
    # rejects on another - so force the fallback and compare verdicts.
    saved_schema = harness.SCHEMA
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def no_jsonschema(name, *a, **kw):
        if name == "jsonschema":
            raise ImportError("forced for this test")
        return real_import(name, *a, **kw)

    with Sandbox() as sb:
        try:
            _shipped_schema(sb)
            samples = [
                ({"name": "card-worker", "description": "x"}, True, "the minimum valid frontmatter"),
                ({"name": "card-worker"}, False, "missing required description"),
                ({"name": "card-worker", "description": "x", "nope": 1}, False, "unknown key"),
                ({"name": "card-worker", "description": "x", "ask_protocol": "yes"}, False,
                 "ask_protocol as a string"),
                ({"name": "card-worker", "description": "x", "setting_sources": "nonsense"},
                 False, "setting_sources outside the enum"),
            ]
            for obj, want_ok, label in samples:
                errs_js, v_js = harness.validate(obj, "agent")
                if isinstance(__builtins__, dict):
                    __builtins__["__import__"] = no_jsonschema
                else:
                    __builtins__.__import__ = no_jsonschema
                try:
                    errs_bi, v_bi = harness.validate(obj, "agent")
                finally:
                    if isinstance(__builtins__, dict):
                        __builtins__["__import__"] = real_import
                    else:
                        __builtins__.__import__ = real_import
                check(v_bi == "builtin-subset",
                      "%s: the fallback validator really ran (%s)" % (label, v_bi))
                check((not errs_js) == want_ok,
                      "%s: jsonschema verdict is %s" % (label, "accept" if want_ok else "reject"))
                check((not errs_bi) == want_ok,
                      "%s: builtin-subset AGREES with jsonschema" % label)
        finally:
            harness.SCHEMA = saved_schema
            harness._cache.clear()


def test_versions_round_trip():
    print("6. every write keeps the bytes it replaced, newest first")
    saved_schema = harness.SCHEMA
    with Sandbox() as sb:
        try:
            _shipped_schema(sb)
            sb.settings("card", "{}")
            v1 = GOOD_AGENT.replace("A usable body.", "VERSION ONE")
            v2 = GOOD_AGENT.replace("A usable body.", "VERSION TWO")
            v3 = GOOD_AGENT.replace("A usable body.", "VERSION THREE")
            harness.write_agent("card-worker", v1, actor="owner")
            harness.write_agent("card-worker", v2, actor="owner")
            harness.write_agent("card-worker", v3, actor="owner")
            vs = harness.versions("agents", "card-worker")
            check(len(vs) == 2, "two prior versions archived (the third IS the file)")
            # These three writes land inside one second, which is exactly the
            # collision the id's zero-padded sequence exists for. Newest-first
            # must still hold, or "restore the most recent" restores the oldest.
            newest = harness.version_text("agents", "card-worker", vs[0]["id"])
            check("VERSION TWO" in (newest or ""),
                  "the NEWEST archived version is the one written last "
                  "(same-second ordering holds)")
            harness.restore("agents", "card-worker", vs[0]["id"], actor="owner")
            live = open(os.path.join(harness.AGENTS, "card-worker.md"), encoding="utf-8").read()
            check("VERSION TWO" in live, "restore puts those bytes back")
            check(len(harness.versions("agents", "card-worker")) == 3,
                  "the restore is ITSELF versioned - reverting a revert is possible")
            check(harness.version_text("agents", "card-worker", "../../../etc/passwd") is None,
                  "a traversing version id is refused")
        finally:
            harness.SCHEMA = saved_schema
            harness._cache.clear()


# ---------------------------------------------------------------------------
# 7-9. THE ISOLATION, on the RESOLVED argv and env
# ---------------------------------------------------------------------------
def test_card_argv_excludes_the_operator_layer():
    print("7. a CARD spawn's resolved argv excludes the personal ~/.claude layer")
    import drivers
    argv = [str(a) for a in drivers.build_argv(
        "card-worker", {"type": "claude", "perm": "acceptEdits", "model": "claude-opus-4-8"},
        "<brief>", session_id="sess-1")]

    check("--setting-sources" in argv, "the argv carries --setting-sources at all")
    src = argv[argv.index("--setting-sources") + 1]
    check(src == "project",
          "its value is exactly 'project' - the user layer is dropped, the repo's "
          "own build-loop hooks are kept (got %r)" % src)
    # `--settings` alone is ADDITIVE and excludes nothing (measured in
    # probe_harness_settings.py), so the presence of a settings file is NOT
    # evidence of isolation. Only --setting-sources is, hence the check above.
    check("--settings" in argv, "and HelmDeck's own layer is added on top")
    sf = argv[argv.index("--settings") + 1]
    check(os.path.isabs(sf) and os.path.exists(sf),
          "the settings path is ABSOLUTE and exists - a relative path would "
          "resolve against the card's worktree, not the repo")
    check(json.load(open(sf, encoding="utf-8")).get("env", {}).get("HELMDECK_SURFACE") == "card",
          "and it is the CARD layer, not some other surface's")

    # the brief must travel as its own argv element, never spliced into another
    check("--append-system-prompt" in argv, "the brief rides on --append-system-prompt")
    check(argv[argv.index("--append-system-prompt") + 1] == "<brief>",
          "as a single discrete argument")
    check(argv.count("--setting-sources") == 1 and argv.count("--settings") == 1,
          "each isolation flag appears exactly ONCE - a duplicate would make the "
          "effective value depend on CLI precedence nobody has measured")
    # the operator's pin must lose to the card's own pick
    check(argv[argv.index("--model") + 1] == "claude-opus-4-8",
          "the card's model choice is the one on the command line")


def test_pm_argv_is_its_own_isolated_layer():
    print("8. a PM spawn gets its OWN layer and no ambient one")
    import copilot
    argv, role_in_turn = copilot.build_argv("claude-opus-4-8", "sess-2", "<role>")
    argv = [str(a) for a in argv]
    check("--setting-sources" in argv, "the copilot argv carries --setting-sources")
    src = argv[argv.index("--setting-sources") + 1]
    check(src == "",
          "its value is the EMPTY string - no ambient layer at all, not even the "
          "repo's, whose Stop hook would block a surface with no build loop (got %r)" % src)
    sf = argv[argv.index("--settings") + 1]
    check(os.path.basename(sf) == "copilot.json",
          "the copilot gets copilot.json, not the card's layer")
    check(json.load(open(sf, encoding="utf-8")).get("env", {}).get("HELMDECK_SURFACE") == "copilot",
          "and that file really is the copilot surface's")

    import drivers
    card_sf = [str(a) for a in drivers.build_argv("card-worker", {"type": "claude"}, "<b>")]
    card_sf = card_sf[card_sf.index("--settings") + 1]
    check(os.path.abspath(sf) != os.path.abspath(card_sf),
          "the two surfaces do NOT share a settings file")
    check(role_in_turn is (not drivers.argv_form_safe(copilot.CLAUDE)),
          "role_in_turn tracks whether args really travel as an argv list")
    if not role_in_turn:
        check("--append-system-prompt" in argv,
              "on the argv-list form the role travels as a system prompt, not "
              "stapled to the front of every user turn")


def test_resolved_env():
    print("9. the resolved ENV: the card overlay is in, the control keys are out")
    import drivers
    card = drivers._card_env({"id": "c1", "worktree": r"C:\wt\c1",
                              "dev_port": 3706, "branch": "feat/x"})
    check(card.get("HELMDECK_WORKTREE") == r"C:\wt\c1",
          "HELMDECK_WORKTREE is exported - loop_state.card_mode() derives the "
          "card discipline from it")
    check(card.get("HELMDECK_DEV_PORT") == "3706",
          "HELMDECK_DEV_PORT is exported, as a STRING (env values must be str)")
    check(card.get("HELMDECK_BRANCH") == "feat/x", "HELMDECK_BRANCH for a card")
    check(not any("SOURCE" in k or "CHECKOUT" in k for k in card),
          "the source checkout path is NOT exported - that is where the secrets "
          "the worktree was isolated away from live")
    mach = drivers._card_env({"id": "m1", "worktree": r"C:\work", "machine": True,
                              "branch": "feat/x"})
    check("HELMDECK_BRANCH" not in mach,
          "a MACHINE task gets no branch - it has no worktree and no branch")

    saved = dict(os.environ)
    try:
        os.environ["HELMDECK_CLAUDE"] = "C:/evil/claude.cmd"
        os.environ["BASH_ENV"] = "C:/evil/rc.sh"
        os.environ["HELMDECK_TLS_KEY"] = "secret-key-path"
        env = drivers._env({"type": "claude", "env": {"JAVA_HOME": "C:/jdk17"}}, card)
        for k in ("HELMDECK_CLAUDE", "BASH_ENV", "HELMDECK_TLS_KEY"):
            check(k not in env,
                  "%s is STRIPPED from the agent env (supervision config and a "
                  "file that could rewrite every shell behind our back)" % k)
        check(env.get("HELMDECK_WORKTREE") == r"C:\wt\c1",
              "the card overlay survives into the final env")
        check(env.get("JAVA_HOME") == "C:/jdk17",
              "the driver's declared build env is layered in")
        check(env.get("BASH_DEFAULT_TIMEOUT_MS") and env.get("BASH_MAX_TIMEOUT_MS"),
              "the per-TOOL bash timeouts are set (bound the tool, not the turn)")
        check(all(isinstance(v, str) for v in env.values()),
              "every env value is a str - a non-str would fail the spawn on Windows")
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_preview_provenance():
    print("10. preview() names the operator's layer as PRESENT-BUT-EXCLUDED")
    # Not seeing the operator's rtk hook is a different answer from seeing that
    # it exists and is excluded. Only the second one proves the isolation ran.
    p = harness.preview("card")
    check(not p.get("argv_error"), "the card preview builds an argv: %s" % p.get("argv_error"))
    layers = {l["layer"]: l for l in p["layers"]}
    check(set(layers) == {"user", "project", "local"},
          "all three ambient layers are accounted for, not just the included ones")
    check(layers["user"]["included"] is False,
          "the operator's personal layer is reported EXCLUDED for a card")
    check(layers["project"]["included"] is True,
          "the repo's project layer is reported INCLUDED (the build-loop hooks)")
    check(layers["user"]["reason"] and "setting-sources" in layers["user"]["reason"],
          "and the reason cites the flag that did it")

    pm = harness.preview("pm")
    pml = {l["layer"]: l for l in pm["layers"]}
    check(not any(l["included"] for l in pml.values()),
          "the PM surface includes NO ambient layer at all")

    # the hook matrix must count only what actually fires
    for row in p["hooks"]:
        check(isinstance(row.get("included"), bool),
              "every hook row says whether it is included")
    check(p["hooks_active"] == sum(1 for r in p["hooks"] if r["included"]),
          "hooks_active counts the INCLUDED rows only")
    if layers["user"]["exists"]:
        user_rows = [r for r in p["hooks"] if r["layer"] == "user"]
        check(all(not r["included"] for r in user_rows),
              "no hook from the operator's layer is active in a card (%d listed)"
              % len(user_rows))

    check(p["brief"]["resolved_sha256"] and p["brief"]["resolved_chars"] > 0,
          "the RESOLVED brief is hashed - the file hash alone would not cover "
          "the ask protocol, which is spliced in after the file is read")
    check(p["exec"] and p["exec_form"],
          "the preview shows the REAL exec form, after the .cmd-shim rewrite")


def test_memory_isolation():
    print("12. the shared auto-memory dir is denied WRITE, in the SHIPPED files")
    # debt: card-shares-the-operators-auto-memory. Every surface's
    # memory_paths.auto resolves to the operator's personal
    # ~/.claude/projects/<slug>/memory/, which is NOT git-backed (measured: no
    # .git anywhere under ~/.claude) - so unlike every other tracked file this
    # harness protects, a bad write there has no revert path. The fix denies
    # Write/Edit and leaves Read open, using the exact mechanism that already
    # protects daemon/settings.json two lines above it in the same file - no
    # new permission mechanism, no new code path.
    for key in ("card", "pm"):
        p = harness.preview(key)
        mem = p.get("memory") or {}
        check(mem.get("denied") is True,
              "%s: the SHIPPED settings layer denies the shared memory dir" % key)
        check(any("Write(" in pat for pat in mem.get("patterns") or []),
              "%s: a Write() pattern is present" % key)
        check(any("Edit(" in pat for pat in mem.get("patterns") or []),
              "%s: an Edit() pattern is present too - Edit is a separate tool "
              "from Write and needs its own deny" % key)

    with Sandbox() as sb:
        # a settings file that forgot the memory deny - preview() must SAY so,
        # not silently assume the fix is universal
        sb.settings("card", '{"permissions": {"deny": ["Read(./x)"]}}')
        sb.agent("card-worker", GOOD_AGENT)
        p = harness.preview("card")
        mem = p.get("memory") or {}
        check(mem.get("denied") is False,
              "a settings file WITHOUT the memory deny is reported writable, "
              "not silently assumed safe")
        check(mem.get("note"),
              "and the note names the gap - this is the same 'a broken/missing "
              "protection must be visible, not swallowed' law as errors()")

        # no settings file at all (declared but unreadable) must not raise
        sb2 = harness
        sb2._cache.clear()
        import os as _os
        _os.remove(os.path.join(harness.SETTINGS, "card.json"))
        harness._cache.clear()
        p = harness.preview("card")
        check(isinstance(p.get("memory"), dict) and p["memory"]["denied"] is False,
              "no settings file at all -> memory isolation reported off, not a crash")


def test_preview_never_raises():
    print("11. preview() is a diagnostic - it must survive what it diagnoses")
    with Sandbox() as sb:
        sb.agent("card-worker", "---\n\tbroken: [\n---\n")
        sb.settings("card", "{ not json")
        for key in ("card", "machine", "pm", "nonexistent-surface"):
            try:
                out = harness.preview(key)
                check(isinstance(out, dict), "preview(%r) returns a dict" % key)
            except Exception as e:                           # noqa: BLE001
                check(False, "preview(%r) raised %s" % (key, type(e).__name__))
        try:
            check(isinstance(harness.document(), dict),
                  "document() (what /harness serves) survives a broken tree")
        except Exception as e:                               # noqa: BLE001
            check(False, "document() raised %s" % type(e).__name__)


for fn in (test_fallback_on_malformed, test_broken_is_reported_not_swallowed,
           test_directory_where_a_file_belongs, test_write_validates_against_schema,
           test_both_validator_paths_agree, test_versions_round_trip,
           test_card_argv_excludes_the_operator_layer,
           test_pm_argv_is_its_own_isolated_layer, test_resolved_env,
           test_preview_provenance, test_memory_isolation, test_preview_never_raises):
    fn()

print(("FAILED: %d" % len(_fails)) if _fails else "\nall harness loader/write/isolation checks passed")
sys.exit(1 if _fails else 0)
