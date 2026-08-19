# -*- coding: utf-8 -*-
"""Does claude CLI 2.1.207 actually give the harness a settings layer?

Companion to the older ask.py probe (daemon/ask.py's own header): the design
for harness/ ASSUMES `--settings`, `--setting-sources` and CLAUDE_CONFIG_DIR do
what their --help says. Help text is not proof, so this measures each one
against the real binary. See harness/README.md for the two traps it found.

THE QUESTION
------------
A card worker is spawned by drivers.py with cwd = the card's worktree. It
therefore loads, today, the OPERATOR'S PERSONAL ~/.claude/settings.json: an
`rtk hook claude` PreToolUse hook on every Bash call (296 observed failures),
a pinned `model: claude-fable-5[1m]`, ~150 skillOverrides, plugins. None of
that is the card's business. What we WANT is:

    user layer      OFF   (operator's personal config stays out of cards)
    project layer   ON    (repo .claude/settings.json = the build-loop hooks)
    explicit layer  ON    (harness/settings/*.json = HelmDeck's own layer)

NOT A THROWAWAY - RE-RUN AFTER A CLI UPGRADE. A silently-changed flag would
not error, it would just quietly hand every card back the operator's config.
This is a permanent regression check, same shelf as tools/probe_driver_env.py.

    python daemon/probe_harness_settings.py             # full sweep, ~20s
    python daemon/probe_harness_settings.py --validate   # fast: are the
                                                           # SHIPPED files
                                                           # actually accepted?

OBSERVATION CHANNELS (never trust one)
  1. hook events: a marker-writing hook per settings layer - ground truth for
     WHICH layer's hooks are live, not just whether the process exited 0.
  2. the init event's `model`: the user layer pins claude-fable-5[1m], so the
     model we end up on says whether the user layer was read.

IF A RE-RUN SUDDENLY REPORTS EVERYTHING "IGNORED", SUSPECT THE RIG, NOT THE CLI.
That happened while this was being written, and the first explanation reached for
- "piping the interpreter via a heredoc breaks the CLI's hook spawn one level
down" - was WRONG. It was tested directly afterwards: same settings file, same
flags, hook command with both backslash and forward-slash paths, invoked once as
a saved file and once as `python - < file`. All four combinations fired the hook.
Whatever the transient was, it was not the invocation form, and this note exists
so nobody re-derives that dead end. Confirm against a KNOWN-GOOD case (a plain
hooks-only settings file) before concluding a flag has regressed.
"""
import json, os, shutil, subprocess, sys, tempfile

CLAUDE = (os.environ.get("HELMDECK_CLAUDE") or shutil.which("claude")
          or r"C:\Program Files\nodejs\claude.cmd")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from daemon.spine.agent import drivers  # _cmd_line: never exec the .cmd shim
from daemon.spine.registry import harness  # the shipped settings files to validate

USER_MODEL = "fable"          # what ~/.claude/settings.json pins (the tell)


def _hook(mark_py, marker_file, label):
    """A settings blob whose only job is to shout its own layer's name."""
    cmd = '"%s" "%s" "%s" "%s"' % (sys.executable, mark_py, marker_file, label)
    one = [{"hooks": [{"type": "command", "command": cmd, "timeout": 30}]}]
    return {"hooks": {"SessionStart": one, "UserPromptSubmit": one}}


def _run(label, argv_extra, cwd, env_extra=None, pin_model=True):
    argv = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
            "--include-hook-events",
            "--permission-mode", "acceptEdits"] + argv_extra
    if pin_model:
        argv += ["--model", "haiku"]
    env = dict(os.environ)
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.update(env_extra or {})
    try:
        p = subprocess.run(drivers._cmd_line(argv), cwd=cwd, input="say OK",
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=180)
    except subprocess.SubprocessError as e:
        return {"label": label, "error": str(e)[:200]}
    out = {"label": label, "rc": p.returncode, "model": "", "hooks": [],
           "err": (p.stderr or "").strip()[-300:]}
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            out["model"] = ev.get("model") or ""
            out["init_keys"] = sorted(ev)[:40]
        blob = json.dumps(ev)
        if "hook" in ev.get("type", "") or ev.get("subtype", "").startswith("hook"):
            out["hooks"].append(blob[:300])
    return out


def _mark_hook(tmp, mark, label):
    """A `hooks` dict (event -> matcher list) - NOT the bare matcher list itself.
    A settings.json "hooks" key must be {"EventName": [...]}; assigning the
    matcher list directly makes the CLI reject the whole file (silently)."""
    mark_py = os.path.join(tmp, "mark_%s.py" % label.lower())
    with open(mark_py, "w", encoding="utf-8") as f:
        f.write("import sys\n"
                "open(sys.argv[1],'a',encoding='utf-8').write(sys.argv[2]+'\\n')\n")
    # BOTH args, always: the marker script writes argv[2] into argv[1], so a
    # 3-token command makes the hook die on IndexError and the run then reads
    # exactly like "the CLI rejected the settings file". That false negative
    # cost real debugging time once already - the observer must not be the thing
    # that fails.
    cmd = '"%s" "%s" "%s" "%s"' % (sys.executable, mark_py, mark, label)
    one = [{"hooks": [{"type": "command", "command": cmd, "timeout": 30}]}]
    return {"SessionStart": one, "UserPromptSubmit": one}


def validate():
    """Fast check: does the CLI actually ACCEPT the files harness/settings/*.json
    ships? A settings file the CLI dislikes is discarded SILENTLY (--help: "Settings
    files that fail validation are silently ignored") - so this bolts an observer
    hook onto each shipped file's own content and asserts the hook FIRES, rather
    than trusting that the file merely parses as JSON.

    Runs each unique settings KEY once (several agents can share one file - both
    worker surfaces use settings/card.json) in a cwd that already carries a
    PROJECT layer, so a `--setting-sources project` case proves the two combine
    (want: [<KEY>, PROJECT]) rather than only proving the explicit file alone."""
    ok = True
    seen = {}
    for name in harness._DEFAULTS:
        m = harness.meta(name)
        key = m.get("settings")
        if not key or key in seen:
            continue
        seen[key] = m.get("setting_sources")
        path = os.path.join(harness.SETTINGS, "%s.json" % key)
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            print("  FAIL  %-10s %s: %s" % (key, path, e))
            ok = False
            continue
        tmp = tempfile.mkdtemp(prefix="hd-validate-")
        mark_py = os.path.join(tmp, "mark.py")
        with open(mark_py, "w", encoding="utf-8") as f:
            f.write("import sys\n"
                    "open(sys.argv[1],'a',encoding='utf-8').write(sys.argv[2]+'\\n')\n")
        mark = os.path.join(tmp, "m.txt")
        # a real project layer in cwd too, so a `--setting-sources project` case
        # (a worker) proves the explicit file COMBINES with it rather than only
        # proving the explicit file alone.
        os.makedirs(os.path.join(tmp, ".claude"), exist_ok=True)
        with open(os.path.join(tmp, ".claude", "settings.json"), "w", encoding="utf-8") as f:
            json.dump(_hook(mark_py, mark, "PROJECT"), f)
        d = dict(d)
        d["hooks"] = _mark_hook(tmp, mark, key.upper())
        p = os.path.join(tmp, "s.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f)
        argv_extra = ["--settings", p]
        src = seen[key]
        if src is not None:
            argv_extra = ["--setting-sources", str(src)] + argv_extra
        r = _run(key, argv_extra, tmp, None)
        try:
            with open(mark, encoding="utf-8") as f:
                fired = sorted(set(x.strip() for x in f if x.strip()))
        except OSError:
            fired = []
        got_explicit = key.upper() in fired
        print("  %-4s %-10s (--setting-sources %-10r) rc=%s fired=%-24s -> %s"
              % ("ok" if got_explicit else "FAIL", key, src, r.get("rc"), fired,
                 "ACCEPTED" if got_explicit else "SILENTLY IGNORED (validation failed!)"))
        ok = ok and got_explicit
    return ok


def main():
    tmp = tempfile.mkdtemp(prefix="hd-probe-")
    print("tmp:", tmp)
    markers = os.path.join(tmp, "markers.txt")
    mark_py = os.path.join(tmp, "mark.py")
    with open(mark_py, "w", encoding="utf-8") as f:
        f.write("import sys\n"
                "open(sys.argv[1],'a',encoding='utf-8').write(sys.argv[2]+'\\n')\n")

    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude"))
    with open(os.path.join(proj, ".claude", "settings.json"), "w", encoding="utf-8") as f:
        json.dump(_hook(mark_py, markers, "PROJECT"), f)

    explicit = os.path.join(tmp, "explicit.json")
    with open(explicit, "w", encoding="utf-8") as f:
        json.dump(_hook(mark_py, markers, "EXPLICIT"), f)

    fake_cfg = os.path.join(tmp, "fakecfg")
    os.makedirs(fake_cfg)
    with open(os.path.join(fake_cfg, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(_hook(mark_py, markers, "FAKEUSER"), f)

    runs = [
        ("A baseline (what a card gets today)", [], None),
        ("B --setting-sources project", ["--setting-sources", "project"], None),
        ("C --setting-sources project + --settings",
         ["--setting-sources", "project", "--settings", explicit], None),
        ("D --settings only", ["--settings", explicit], None),
        ("E CLAUDE_CONFIG_DIR=<fake>", [], {"CLAUDE_CONFIG_DIR": fake_cfg}),
    ]
    results = []
    for label, extra, envx in runs:
        open(markers, "w").close()
        r = _run(label, extra, proj, envx)
        try:
            with open(markers, encoding="utf-8") as f:
                r["markers"] = sorted(set(x.strip() for x in f if x.strip()))
        except OSError:
            r["markers"] = []
        results.append(r)
        print("\n== %s" % label)
        print("   rc=%s model=%s" % (r.get("rc"), r.get("model")))
        print("   markers (hooks that FIRED): %s" % (r["markers"] or "none"))
        print("   user-layer model leaked in: %s"
              % ("YES" if USER_MODEL in (r.get("model") or "") else "no"))
        if r.get("err"):
            print("   stderr: %s" % r["err"])
        if r.get("error"):
            print("   ERROR: %s" % r["error"])

    print("\n---- VERDICT ----")
    by = {r["label"][0]: r for r in results}
    def has(k, m):
        return m in (by.get(k, {}).get("markers") or [])
    print("project layer loads at all      : %s" % has("A", "PROJECT"))
    print("--setting-sources keeps project : %s" % has("B", "PROJECT"))
    print("--settings file is honoured     : %s" % (has("C", "EXPLICIT") or has("D", "EXPLICIT")))
    print("--settings COMBINES with sources: %s" % (has("C", "EXPLICIT") and has("C", "PROJECT")))
    print("CLAUDE_CONFIG_DIR redirects user: %s" % has("E", "FAKEUSER"))

    # ROUND 1b - the copilot's exact combo: --setting-sources "" (nothing ambient)
    # + --settings <file>, in a dir that HAS a project layer to prove it's excluded.
    print("\n\n==== ROUND 1b: --setting-sources '' + --settings (the copilot's combo) ====")
    open(markers, "w").close()
    r1b = _run("F empty-sources + explicit", ["--setting-sources", "", "--settings", explicit], proj, None)
    try:
        with open(markers, encoding="utf-8") as f:
            r1b["markers"] = sorted(set(x.strip() for x in f if x.strip()))
    except OSError:
        r1b["markers"] = []
    print("   markers: %s (want EXPLICIT only, no PROJECT)" % r1b["markers"])
    results.append(r1b)

    # ROUND 2 - the decisive one. Round 1 pinned --model haiku, which BLINDED the
    # second channel: every run reported haiku because we asked for haiku, so
    # nothing there proves the USER layer was excluded (the whole point). The
    # marker files can only see layers this probe planted; the operator's real
    # ~/.claude is untouchable. So drop the model flag and let the user layer
    # speak: it pins `claude-fable-5[1m]`, so the model we LAND on is a direct
    # read of whether that layer was loaded.
    print("\n\n==== ROUND 2: is the USER layer actually excluded? (no --model) ====")
    for label, extra in [("A2 baseline", []),
                         ("B2 --setting-sources project", ["--setting-sources", "project"]),
                         ("D2 --settings only", ["--settings", explicit])]:
        r = _run(label, extra, proj, None, pin_model=False)
        leaked = USER_MODEL in (r.get("model") or "")
        print("   %-32s model=%-28s user layer: %s"
              % (label, r.get("model") or "?", "LOADED" if leaked else "excluded"))
        results.append(r)

    with open(os.path.join(tmp, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print("\nraw: %s" % os.path.join(tmp, "results.json"))

    print("\n\n==== SHIPPED FILES: does the CLI actually accept them? ====")
    validate()


def skills():
    """WHICH SKILLS (and which memory dir) each shipped surface actually gets.

    A third observation channel, and the cheapest honest one: the init event
    carries `skills`, `agents`, `plugins` and `memory_paths` BEFORE any model
    inference, so one throwaway turn measures the real per-surface discovery set
    deterministically. That matters because "the operator's ~150 skillOverrides
    never reach a card" was a claim reasoned from --setting-sources semantics,
    and skillOverrides is a settings KEY while ~/.claude/skills/ is a DIRECTORY.
    Those are two different mechanisms and only one of them is obviously
    governed by the flag. Reason about it and you get a plausible answer; run
    this and you get the real one.

    THE ENV IS SCRUBBED OF CLAUDE*. This probe is usually launched from inside a
    Claude Code session, which exports CLAUDECODE / CLAUDE_CODE_SESSION_ID /
    CLAUDE_CODE_CHILD_SESSION into every child. Measuring a spawn's inherited
    config while inheriting the measurer's own config is how you get a reading
    that is really about the probe. In production the daemon is not a Claude
    Code process and those variables are absent, so scrubbing them is the
    faithful reproduction, not a convenience.
    """
    from daemon.spine.registry import harness
    rows = []
    # The BASELINE matters as much as the surfaces: "the card set differs from
    # the inherit-everything set" is only meaningful against the full other set.
    # Printing a truncated list here once produced a confident, wrong reading
    # (six skills looked "restored by dropping the user layer" that had never
    # been missing) - so every list below is printed WHOLE, and the verdict is
    # computed as a set difference rather than eyeballed.
    surfaces = [("baseline (no flags = the pre-harness card)", None),
                ("card", "card-worker"), ("machine", "machine-worker"),
                ("pm", "board-copilot")]
    for key, agent in surfaces:
        extra = harness.cli_args(agent) if agent else []
        argv = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
                "--permission-mode", "plan", "--model", "haiku"] + extra + ["hi"]
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "CLAUDECODE"}
        try:
            p = subprocess.run(drivers._cmd_line(argv), cwd=harness.ROOT, env=env,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=180)
        except subprocess.SubprocessError as e:
            print("%-8s SPAWN FAILED: %s" % (key, str(e)[:160]))
            continue
        init = None
        for line in (p.stdout or "").splitlines():
            try:
                ev = json.loads(line.strip())
            except ValueError:
                continue
            if ev.get("type") == "system" and ev.get("subtype") == "init":
                init = ev
                break
        if not init:
            print("%-8s NO INIT EVENT (rc=%s) %s" % (key, p.returncode,
                                                     (p.stderr or "")[-200:]))
            continue
        rows.append((key, extra, init))
        print("\n==== %s  (%s) ====" % (key, " ".join(str(x) for x in extra)))
        print("  skills (%d): %s" % (len(init.get("skills") or []),
                                     ", ".join(sorted(init.get("skills") or []))))
        print("  plugins    : %s" % (init.get("plugins") or []))
        print("  memory_paths: %s" % (init.get("memory_paths") or {}))

    if len(rows) < 2:
        return False
    got = {k: set(ev.get("skills") or []) for k, _, ev in rows}
    base = next((v for k, v in got.items() if k.startswith("baseline")), None)
    print("\n---- VERDICT ----")
    if "card" in got and "pm" in got:
        proj_only = got["card"] - got["pm"]
        # .claude/skills/ in this repo ships adversarial-test + impeccable. The
        # card keeps --setting-sources project, the copilot passes "", so the
        # difference between the two sets IS the project skill directory.
        print("project .claude/skills reach the card but not the copilot: %s  %s"
              % (bool(proj_only), sorted(proj_only)))
    if base is not None and "card" in got:
        # Same test one layer up: what the operator's ~/.claude contributes that
        # a card does not get. These are DIRECTORIES, not the skillOverrides key -
        # which is the question this whole mode exists to settle.
        print("user ~/.claude/skills reach the baseline but not the card: %s"
              % sorted(base - got["card"]))
        gained = got["card"] - base
        print("skills a card GAINS by dropping the user layer: %s"
              % (sorted(gained) or "none"))
        if gained:
            print("  (a skillOverrides entry in the user layer was suppressing these)")
    mems = {k: (ev.get("memory_paths") or {}).get("auto") for k, _, ev in rows}
    shared = len(set(v for v in mems.values() if v)) == 1 and len(mems) > 1
    print("every surface shares ONE auto-memory dir: %s" % shared)
    if shared:
        print("  -> %s" % list(mems.values())[0])
        print("  This is the operator's personal directory and --setting-sources")
        print("  does not move it. Registered as debt: card-shares-the-operators-auto-memory")
    return True


if __name__ == "__main__":
    if "--validate" in sys.argv:
        sys.exit(0 if validate() else 1)
    if "--skills" in sys.argv:
        sys.exit(0 if skills() else 1)
    main()
