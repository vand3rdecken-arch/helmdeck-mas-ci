# -*- coding: utf-8 -*-
"""HelmDeck's build loop - the FORWARD work loop a request travels through,
enforced the glass-harness way (states computed from artifacts on disk, Stop
hook blocks resting mid-loop, SessionStart re-orients fresh context).

The loop:

    ALIGN    work started (dirty tree) but no .loop/workorder.md - write it:
             what the request is, and does it fit the repo philosophy
             (CLAUDE.md laws + daemon/charter.py)? Refuse or adjust if not.
    ANALYZE  workorder lacks '## Analysis' - architecture impact + debt delta:
             which modules/laws are touched, does a load-bearing shortcut ship
             (then register it in daemon/debt.py in the same change)? Includes
             the NO-MONKEY-PATCH check (CLAUDE.md law): state must be DERIVED
             from runtime signals at ONE owner - a shipped heuristic
             reconstruction is debt, named in the same commit.
    EXECUTE  checks are red - build/fix until green: touched daemon/*.py compile,
             app (Expo) tsc clean, daemon modules import, and DESIGN LINT passes
             (ops/tools/design_lint.py - the enforceable subset of the design skill:
             web-shell color-scheme, theme tokens not hex, semantic z-scale).
    TEST     checks green but workorder lacks '## Verified' - run the real
             thing (e2e/screenshot for UI - JUDGE it, don't just render it),
             AND adversarial-test the specific feature you built (write its
             own break-it cases per .claude/skills/adversarial-test - a
             principle applied per feature, not a canned suite), and record
             what was verified.
    CLEAN    hygiene broken - debt register malformed, or secret files
             (settings.json / users.json / *.db) tracked/staged.
    COMMIT   loop complete and edits gone quiet - propose the commit; on a
             clean tree the workorder is archived to .loop/history/.
    WIP      (overlay, never blocks) recent edits mid-flight - serve the user.
    DONE     clean tree, no open workorder.

Usage:
    python ops/tools/loop_state.py                  # table + THE next action
    python ops/tools/loop_state.py --stop-hook      # Stop hook (blocks once)
    python ops/tools/loop_state.py --session-start  # orientation for fresh context

Never fails (exit 0) - a state doctor, not a gate."""
import hashlib, json, os, subprocess, sys, time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAEMON = os.path.join(ROOT, "daemon")
APP = os.path.join(ROOT, "surfaces", "app")   # the Expo app - the only frontend (web/ archived)
LOOPDIR = os.path.join(ROOT, ".loop")
WORKORDER = os.path.join(LOOPDIR, "workorder.md")
WIP_MIN = int(os.environ.get("SWARM_WIP_MINUTES", "30"))

# Fully package-qualified now that daemon/ is a real Python package (import
# cells.copilot.pm, not a sys.path trick) - each entry is checked via
# `import <entry>` in a fresh subprocess run with cwd=ROOT (repo root).
CORE_MODULES = ["spine.storage.db", "spine.storage.events",
                "cells.engineer.sessions", "spine.agent.drivers",
                "cells.engineer.processes", "cells.copilot.copilot",
                "cells.engineer.connectors", "spine.auth.charter",
                "spine.ops.checkpoints", "spine.auth.auth",
                "spine.ops.importers", "spine.registry.debt",
                "spine.http.server"]
SECRET_NAMES = ("settings.json", "users.json", "helmdeck.db", "helmdeck.db-wal",
                "helmdeck.db-shm", "copilot_log.json",
                "plane_credentials.txt", "sessions.json")

# Testable override, sandboxed tests point this at a temp dir instead of the
# real daemon/ - never mutate this from anywhere except a test's own setup.
_POLICY_ROOT = DAEMON


def _build_loop_enabled():
    """The build loop is Cell #6 (cells.py 'buildloop') - but it is NOT
    daemon-hosted like the other 5: it governs THIS agent's own workflow via
    Claude Code's hooks (.claude/settings.json -> this script), not a spawned
    daemon worker. No HTTP round-trip - reads daemon/policy_live.json (falling
    back to policy_seed.json, mirroring daemon/policy.py's own seed-then-live
    semantics) DIRECTLY, so the flag works even when the daemon isn't running.

    Fails OPEN (True) on any read error or missing key - a missing/corrupt
    policy file, or an old checkout without buildLoopEnabled seeded yet, must
    never silently disable the safety net."""
    for name in ("policy_live.json", "policy_seed.json"):
        path = os.path.join(_POLICY_ROOT, name)
        try:
            with open(path, encoding="utf-8") as f:
                return bool(json.load(f).get("policies", {}).get("buildLoopEnabled", True))
        except (OSError, ValueError):
            continue
    return True

WORKORDER_TEMPLATE = """# Workorder

## Request
<what the user asked for, in one or two sentences>

## Alignment
<does it fit CLAUDE.md laws + the charter? yes / adjusted-because / refused-because>

## Analysis
<architecture impact: modules touched, laws grazed, debt delta (register in
daemon/debt.py if a shortcut ships).
NO-MONKEY-PATCH check (CLAUDE.md law): does this change DERIVE its state from
the runtime's own signals at ONE owner - or does it assume a stored flag /
re-scan artifacts / adopt without evidence? Name which. A shipped heuristic
reconstruction = a debt entry in the same commit.>

## Verified
<what was actually run/judged: checks, e2e, screenshots (UI = judged, not
just rendered)>
"""


def card_mode():
    """True when this checkout IS a HelmDeck card's worktree.

    DERIVED from the runtime's own signal at its ONE owner: drivers._card_env
    exports HELMDECK_WORKTREE into the agent's environment at spawn, and the
    hooks run inside that process tree, so they inherit it. Nothing is
    reconstructed and nothing is re-scanned.

    And VERIFIED, not adopted: the value must actually resolve to THIS checkout.
    An inherited-but-stale variable (a shell that once ran a card, a nested
    invocation) would otherwise silently put the main repo into card mode and
    switch off the workorder discipline exactly where it is wanted most. If the
    path does not match, we are not that card, whatever the variable says."""
    wt = os.environ.get("HELMDECK_WORKTREE")
    if not wt:
        return False
    try:
        return os.path.normcase(os.path.realpath(wt)) == \
               os.path.normcase(os.path.realpath(ROOT))
    except OSError:
        return False


def _git(*args):
    r = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def dirty_files():
    out = []
    for line in _git("status", "--porcelain").splitlines():
        if len(line) > 3:
            p = line[3:].strip().strip('"')
            if not p.startswith(".loop/"):
                out.append(p)
    return out


def newest_mtime(paths):
    newest = 0
    for p in paths:
        fp = os.path.join(ROOT, p)
        if os.path.isfile(fp):
            newest = max(newest, os.path.getmtime(fp))
    return newest


def workorder():
    try:
        with open(WORKORDER, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def section_filled(text, header):
    """True if the section under `header` has real content (not the template stub)."""
    if header not in text:
        return False
    body = text.split(header, 1)[1].split("\n## ", 1)[0]
    body = body.replace("\n", " ").strip()
    return len(body) > 10 and not body.startswith("<")


def checks_red(touched):
    problems = []
    for p in touched:
        if p.startswith("daemon/") and p.endswith(".py"):
            r = subprocess.run([sys.executable, "-m", "py_compile",
                                os.path.join(ROOT, p)], capture_output=True, text=True)
            if r.returncode != 0:
                problems.append("%s: %s" % (p, (r.stderr or "").strip().splitlines()[-1][:100]))
    if any(p.startswith(("app/", "cells/")) and p.endswith((".ts", ".tsx")) for p in touched) and \
       os.path.isdir(os.path.join(APP, "node_modules")):
        try:
            npx = r"C:\Program Files\nodejs\npx.cmd"
            if not os.path.exists(npx):
                npx = "npx.cmd" if os.name == "nt" else "npx"
            env = dict(os.environ)
            env["PATH"] = r"C:\Program Files\nodejs;" + env.get("PATH", "")
            # tsconfig.typecheck.json, not tsconfig.json: the bare-module
            # fallback for cells/<id>/ui/ files must stay invisible to Metro
            # (which reads tsconfig.json's paths for runtime resolution).
            r = subprocess.run([npx, "tsc", "--noEmit", "-p", "tsconfig.typecheck.json"],
                               cwd=APP, capture_output=True, text=True, env=env, timeout=180)
            if r.returncode != 0:
                first = (r.stdout or r.stderr or "").strip().splitlines()
                problems.append("app types: " + (first[0][:120] if first else "tsc failed"))
        except (OSError, subprocess.SubprocessError):
            pass   # a state doctor must never crash; types are re-checked in session
    if not problems and any(p.startswith("daemon/") and p.endswith(".py") for p in touched):
        r = subprocess.run(
            [sys.executable, "-c", "import " + ",".join(CORE_MODULES)],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            problems.append("daemon wiring: " + (r.stderr or "").strip().splitlines()[-1][:120])
    try:
        sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))
        import design_lint
        problems += ["design: " + v for v in design_lint.lint(touched)]
    except Exception:
        pass   # never crash the doctor
    return problems


def hygiene_problems():
    problems = []
    tracked = _git("ls-files").splitlines()
    for t in tracked:
        base = os.path.basename(t)
        if (base in SECRET_NAMES or base.endswith(".env")) and not t.startswith(".claude/"):
            problems.append("secret file tracked: " + t)
    try:
        sys.path.insert(0, ROOT)
        import importlib
        import spine.registry.debt as _d
        importlib.reload(_d)
        for item in _d.DEBT:
            if item.get("status") not in ("open", "in_progress", "paid"):
                problems.append("debt register: %s bad status" % item.get("id"))
            for k in ("id", "title", "status", "what", "why_it_bites", "trigger", "fix"):
                if k not in item:
                    problems.append("debt register: %s missing %s" % (item.get("id", "?"), k))
    except Exception as e:
        problems.append("debt.py unreadable: %s" % str(e)[:100])
    return problems


def archive_workorder():
    wo = workorder()
    if wo is None:
        return
    hist = os.path.join(LOOPDIR, "history")
    os.makedirs(hist, exist_ok=True)
    dst = os.path.join(hist, time.strftime("%Y%m%d-%H%M%S") + ".md")
    os.replace(WORKORDER, dst)


# each shippable artifact vs ONLY the source that feeds it. Repointed to the
# Expo stack (paid part of the expo-cutover-pipeline debt): the mobile app's JS
# ships via OTA (ops/deploy/push_update.sh), NOT the APK - so a JS/daemon change must
# NOT flag the APK stale. Only NATIVE sources gate the signed APK; a fresh APK is
# only needed for native changes. web/ and apk/ (Kotlin) are archived and gone.
# Only the signed Android APK is auto-tracked (native-only sources). The desktop
# installer and the glasses zip are built on demand (ops/tools/release.sh /
# build_all.sh glasses) and are not part of the mobile launch pipeline, so they
# don't nag the loop before rest.
ARTIFACT_SRC = {
    "surfaces/app/android/app/build/outputs/apk/release/app-release.apk":
        ("surfaces/app/android/app/src/main", "app/app.json", "surfaces/app/package.json"),
}
# The subset of the above that `git status` can actually SEE. The whole of
# surfaces/app/android/ is git-ignored (app/.gitignore: `/android`), so a change under
# surfaces/app/android/app/src/main never appears in dirty_files() and can never be the
# thing that triggers a rebuild nag. surfaces/app/package.json is listed because ship.sh's
# native fingerprint hashes its expo/react-native lines - it is a real native
# input, and it was missing from ARTIFACT_SRC above.
ARTIFACT_TRIGGERS = ("app/app.json", "surfaces/app/package.json", "surfaces/app/android/")
_SKIP = ("node_modules", ".next", "__pycache__", os.sep + "build", os.sep + "dist")
# only SOURCE files count - not the running daemon's data (events.jsonl,
# helmdeck.db, settings.json, ...), which would otherwise flag every artifact
# stale on each turn.
_CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".kt", ".kts")


def _src_mtime(srcs):
    paths = []
    for s in srcs:
        sp = os.path.join(ROOT, s)
        if os.path.isdir(sp):
            for root, _, files in os.walk(sp):
                if any(x in root for x in _SKIP):
                    continue
                paths.extend(os.path.join(root, f) for f in files if f.endswith(_CODE_EXT))
        elif os.path.exists(sp):
            paths.append(sp)
    return newest_mtime(paths)


# ops/deploy/ship.sh's AUTHORITATIVE native fingerprint. mtime alone lied: an OTA
# version bump re-touches app.json without changing a single native byte, and
# the APK then read 'stale' forever (the recurring BUILD nag with nothing to
# build). The fingerprint EXCLUDES the churning version fields, so it moves
# only on a real native change - the same call ship.sh makes to decide
# native-vs-JS.
#
# INCIDENT (2026-08-18): this used to be a hand-reimplemented sed/grep pipe
# "reproduced byte-for-byte" from ship.sh's native_fp(). It drifted - the
# reimplementation raw-grepped app.json's whole text (catching ios/extra
# fields ship.sh deliberately excludes, see ship.sh's own incident note on
# that), while ship.sh does a semantic JSON diff. Result: this function
# reported a stale APK (moved fingerprint) when ship.sh's real algorithm said
# nothing native had changed - a false-positive BUILD nag that triggered a
# real, unnecessary APK rebuild.
#
# Fix considered and REJECTED: `bash -c "source ops/deploy/ship.sh; native_fp"`.
# ship.sh is a top-level SCRIPT, not a function library guarded by a __main__
# check - sourcing it runs its whole body (the CUR/LAST compare and the
# bump-version/build-APK/push branch), not just the function definitions.
# Confirmed live: an attempted source during this incident's investigation
# started "APK build starting... version bump failed" before `py` even
# resolved on that shell's PATH. Actually reusing ship.sh's function has no
# safe path without refactoring ship.sh itself (out of scope here), so this
# stays pure Python, hand-kept identical to ship.sh's native_fp() (same
# excluded fields) - the drift risk is real but at least no longer entangled
# with an accidental deploy trigger.
def _native_fp():
    """Mirrors ops/deploy/ship.sh's native_fp() EXACTLY (same excluded fields:
    version/versionCode, app.json's ios/extra objects, EXPO_RUNTIME_VERSION
    lines) - keep the two in sync by hand if either changes. Returns "" on
    any read error, so the caller falls back to the mtime check rather than
    guessing."""
    try:
        with open(os.path.join(ROOT, "surfaces", "app", "app.json"), encoding="utf-8") as f:
            d = json.load(f)
        e = {k: v for k, v in d.get("expo", {}).items() if k not in ("ios", "extra")}
        e.pop("version", None)
        android = dict(e.get("android") or {})
        android.pop("versionCode", None)
        e["android"] = android
        blob = json.dumps(e, sort_keys=True)
        try:
            with open(os.path.join(ROOT, "surfaces", "app", "package.json"), encoding="utf-8") as f:
                blob += f.read()
        except OSError:
            pass
        try:
            # pre-four-folder path ("app/android/...") predates the
            # spine/cells/surfaces/ops split - it never existed under that
            # name and this silently no-op'd via the blanket except below,
            # so the manifest half of the fingerprint was ALWAYS missing
            # here while ship.sh's real cfg_fp (which uses the correct
            # surfaces/app/android/... path) included it - a second,
            # independent source of drift from the one this function's
            # docstring already warns about, found while fixing that one.
            manifest_path = os.path.join(
                ROOT, "surfaces", "app", "android", "app", "src", "main", "AndroidManifest.xml")
            with open(manifest_path, encoding="utf-8") as f:
                blob += "\n".join(
                    l for l in f.read().splitlines() if "EXPO_RUNTIME_VERSION" not in l)
        except OSError:
            pass
        import glob as _glob
        # ICON/SPLASH ASSET BYTES - mirrors ship.sh's cfg_fp() addition
        # (2026-08-26, the logo redesign): app.json only stores PATHS to
        # these files, so a PNG-only redesign moved neither this hash nor
        # ship.sh's without this block - which is exactly the drift this
        # function's own docstring warns about. os.path.isfile guards
        # against the glob yielding directories (Windows raises
        # PermissionError, not IsADirectoryError, opening one).
        #
        # The expo.icon glob MUST run as ship.sh runs it: a bare relative
        # pattern under cwd==ROOT. glob.glob on Windows returns forward
        # slashes for the literal prefix you typed but backslashes for the
        # parts IT fills in recursing - "surfaces/app/assets/expo.icon\\
        # Assets\\grid.png" - a mixed-separator string that's a pain to
        # reconstruct by hand from an absolute path (relpath+replace
        # normalizes to all-forward-slash, which is a DIFFERENT string and
        # produced a real mismatch, measured 2026-08-26). Reproducing
        # ship.sh's own cwd-relative call sidesteps needing to know its
        # separator quirks at all.
        _prev_cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            expo_icon_paths = _glob.glob("surfaces/app/assets/expo.icon/**/*", recursive=True)
        finally:
            os.chdir(_prev_cwd)
        for rel in sorted(
            ["surfaces/app/assets/images/icon.png",
             "surfaces/app/assets/images/splash-icon.png",
             "surfaces/app/assets/images/android-icon-foreground.png",
             "surfaces/app/assets/images/android-icon-background.png",
             "surfaces/app/assets/images/android-icon-monochrome.png"]
            + expo_icon_paths
        ):
            path = os.path.join(ROOT, rel)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as f:
                    blob += rel + hashlib.sha256(f.read()).hexdigest()
            except OSError:
                pass
        cfg = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        # source half (ship.sh kt_fp, added 2026-08-23): every .kt/.java under
        # app/plugins and surfaces/app/modules is compiled into the APK. Combined as
        # sha256("<cfg> <kt>") - exactly ship.sh's combine_fp shape.
        # Same separator trap as the expo.icon glob above: ship.sh's kt_fp
        # globs RELATIVE patterns under cwd==ROOT, and the resulting
        # mixed-separator strings ("surfaces/app/plugins\\...") go into the
        # blob verbatim - relpath+replace normalization produced a different
        # string and therefore a different hash (measured 2026-08-26).
        _prev_cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            kt_srcs = sorted(
                _glob.glob("surfaces/app/plugins/**/*.kt", recursive=True)
                + _glob.glob("surfaces/app/plugins/**/*.java", recursive=True)
                + _glob.glob("surfaces/app/modules/**/*.kt", recursive=True)
                + _glob.glob("surfaces/app/modules/**/*.java", recursive=True))
        finally:
            os.chdir(_prev_cwd)
        kb = ""
        for src in kt_srcs:
            try:
                with open(os.path.join(ROOT, src), encoding="utf-8") as f:
                    kb += src + "\n" + f.read()
            except OSError:
                pass
        kt = hashlib.sha256(kb.encode("utf-8")).hexdigest()
        return hashlib.sha256((cfg + " " + kt).encode("utf-8")).hexdigest()
    except (OSError, ValueError):
        return ""


def touches_native(touched):
    """Did this change touch anything that can move the native fingerprint?"""
    return any(p.startswith(ARTIFACT_TRIGGERS) for p in (touched or ()))


def _ship_marker():
    """The native fingerprint ops/deploy/ship.sh recorded at the last ship, or "".

    "" means this checkout has never shipped a native build (the marker is
    git-ignored, so a fresh clone and every card worktree start without one)."""
    mp = os.path.join(ROOT, "ops", "deploy", ".native_fp")
    try:
        with open(mp, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def build_stale(touched=()):
    """True if a shippable artifact is missing or its NATIVE inputs changed since
    the last ship - so the loop nudges a rebuild before it rests. Only checked
    once work has gone quiet, so it never runs on every keystroke.

    ASK THE AUTHORITATIVE SIGNAL FIRST, and only fall back to guessing.

    There are two signals here and they are not equal. `_native_fp()` vs the
    marker ship.sh wrote is a DERIVED, VERIFIED answer: it hashes the actual
    native inputs and compares them to what was actually shipped, so it is right
    regardless of how the change arrived. `touches_native(touched)` is a
    heuristic pre-filter reconstructed from `git status --porcelain`, and it has
    a blind spot by construction - app/.gitignore ignores all of /android, so an
    edit under surfaces/app/android/ can never appear in `touched` at all.

    Ordering the heuristic FIRST (as this did until 2026-08-16) let that blind
    spot veto the authoritative check: a real native change that git could not
    see was reported fresh, with confidence. Ordering the fingerprint first
    removes git-visibility from the decision entirely - `touched` now only gates
    the DEGRADED paths below, which is the only place a guess belongs.

    The false-positive fix this replaces stays fixed, and for a better reason
    than before. A card worktree has no marker (git-ignored) and no APK
    (git-ignored), so it lands in the degraded branch and `touched` still holds
    it silent - no card is told to run a 30-minute Android build it cannot run
    and whose output the worktree would discard.
    """
    marker = _ship_marker()
    fp = _native_fp() if marker else ""
    if fp and marker:
        # AUTHORITATIVE: the fingerprint answers for every native input,
        # including the ones under the git-ignored surfaces/app/android/ tree.
        return fp != marker
    # DEGRADED - no marker (never shipped from this checkout) or no git-bash to
    # compute the fingerprint. Now we are guessing, so only guess when the change
    # we CAN see could plausibly have moved the native inputs.
    if not touches_native(touched):
        return False
    for art, srcs in ARTIFACT_SRC.items():
        ap = os.path.join(ROOT, art)
        if not os.path.exists(ap):
            return True
        if _src_mtime(srcs) > os.path.getmtime(ap):
            return True
    return False


def _design_hint(touched):
    """The design-skill nudge, when this change touches app UI. Shared by both
    modes - a card doing UI work is held to the same bar as the main checkout."""
    ui_work = any(p.startswith("surfaces/app/src/") and p.endswith((".ts", ".tsx"))
                  for p in touched)
    if not (ui_work and os.path.isdir(os.path.join(ROOT, ".claude", "skills", "impeccable"))):
        return ""
    return (" DESIGN MODE: apply .claude/skills/impeccable (read its SKILL.md "
            "before writing UI; tokens in surfaces/app/src/theme/tokens.ts - generated "
            "by ops/tools/gen_tokens.py - win on conflict).")


def transitions():
    """Ordered (STATE, action); first is THE next action.

    TWO MODES, one machine. In the main checkout a request arrives as prose and
    the workorder ceremony is what turns it into aligned, analysed, verified work.
    A CARD is not that: it arrives with its task already written on it and its
    acceptance already defined by the gate, in a worktree that is thrown away when
    the card is accepted. Asking it to open a workorder makes it re-derive, in a
    file nobody will read, an alignment the board already performed - and then
    blocks it from resting until it does. So a card runs the half of the loop that
    is about the CODE (checks red, hygiene, commit) and skips the half that is
    about the REQUEST (ALIGN/ANALYZE/TEST's Verified section, BUILD)."""
    card = card_mode()
    touched = dirty_files()
    wo = workorder()

    if not touched:
        if wo is not None:            # loop finished by a commit - close the book
            archive_workorder()
        return []

    t = []
    if card:
        # EXECUTE keeps its full force here: compile, types, daemon wiring and
        # design-lint are exactly what the gate will re-run at Review, so a card
        # that ignores them just bounces.
        red = checks_red(touched)
        if red:
            return [("EXECUTE", "checks red - build/fix: " + " | ".join(red[:2])
                     + _design_hint(touched))]
        hyg = hygiene_problems()
        if hyg:
            return [("CLEAN", " | ".join(hyg[:2]))]
        if (time.time() - newest_mtime(touched)) > WIP_MIN * 60:
            return [("COMMIT", "card work quiet (%d file(s)) - commit on THIS branch, "
                     "then hand off: 'Ready for Review'. %s"
                     % (len(touched), ", ".join(touched[:4])))]
        return [("WIP", "card work in flight (%d files) - carry on" % len(touched))]

    if wo is None:
        os.makedirs(LOOPDIR, exist_ok=True)
        t.append(("ALIGN", "work in flight without a workorder - create .loop/workorder.md "
                  "(template written) and fill '## Request' + '## Alignment': does this fit "
                  "CLAUDE.md laws + the charter? Refuse or adjust if not."))
        try:
            if not os.path.exists(WORKORDER):
                with open(WORKORDER, "w", encoding="utf-8") as f:
                    f.write(WORKORDER_TEMPLATE)
        except OSError:
            pass
        return t
    if not (section_filled(wo, "## Request") and section_filled(wo, "## Alignment")):
        t.append(("ALIGN", "fill '## Request' + '## Alignment' in .loop/workorder.md - "
                  "the request vs repo philosophy (CLAUDE.md laws, charter)."))
        return t
    if not section_filled(wo, "## Analysis"):
        t.append(("ANALYZE", "fill '## Analysis' in .loop/workorder.md - architecture "
                  "impact + debt delta (register shortcuts in daemon/debt.py). Include "
                  "the NO-MONKEY-PATCH check: is state DERIVED from runtime signals at "
                  "ONE owner, or assumed/re-scanned/adopted-without-evidence? A shipped "
                  "heuristic = a debt entry in the same commit."))
        return t

    design = _design_hint(touched)
    red = checks_red(touched)
    if red:
        t.append(("EXECUTE", "checks red - build/fix: " + " | ".join(red[:2]) + design))
        return t

    if not section_filled(wo, "## Verified"):
        adv = (" Then adversarial-test THIS feature (not a generic walk): apply "
               ".claude/skills/adversarial-test - list how a careless/hostile user "
               "breaks the thing you just built, try each, record pass/fail in Verified.")
        t.append(("TEST", "checks green but nothing verified - run the real thing "
                  "(e2e; UI = screenshot and JUDGE) and fill '## Verified'." + design + adv))
        return t

    hyg = hygiene_problems()
    if hyg:
        t.append(("CLEAN", " | ".join(hyg[:2])))
        return t

    quiet = (time.time() - newest_mtime(touched)) > WIP_MIN * 60
    if quiet and build_stale(touched):
        t.append(("BUILD", "verified & quiet, but a NATIVE artifact is stale - only native "
                  "app changes need this (JS ships via OTA: `bash ops/deploy/push_update.sh`). "
                  "For a native change run `bash ops/tools/release.sh android` (signed APK), "
                  "THEN propose the commit."))
        return t
    if quiet:
        t.append(("COMMIT", "loop complete, %d file(s) quiet - propose the commit "
                  "(workorder archives on clean tree): %s"
                  % (len(touched), ", ".join(touched[:4]))))
    else:
        t.append(("WIP", "loop complete, edits still fresh (%d files) - serve the user; "
                  "propose the commit when work goes quiet" % len(touched)))
    return t


# -- the build loop, AS DATA ------------------------------------------------
# THE POINT: transitions() above is the real machine, but it is control flow -
# a UI cannot render control flow. So server.py used to carry a hand-typed copy
# of the loop in /loop/map and ANOTHER one in /automation. They drifted, from
# each other and from this file: /loop/map lost BUILD entirely, and /automation
# still tells the owner that BUILD rebuilds "Installer / APK / glasses" when
# ARTIFACT_SRC has held nothing but the APK since the Expo cutover.
#
# Two copies of a state machine is one copy too many. This is the single
# definition; both endpoints render it.
#
#   modes    - which mode the state exists in. A card has a task and a gate, so
#              the workorder ceremony (ALIGN/ANALYZE/TEST) and BUILD are not part
#              of its loop at all - see transitions().
#   kind     - fixed (harness law) vs policy (data). `settings` names the knob.
#   why      - WHY it is fixed, or what exactly is adjustable on a policy state.
#              Declared here next to `kind` for the same reason `source` is read
#              from this file: the module that decides a state is fixed is the
#              only honest place to say why. A reason invented in the renderer
#              would be a claim about code the renderer cannot see - and a bare
#              padlock with no reason is what made this screen read as
#              arbitrarily locked instead of deliberately fixed.
LOOP_STATES = [
    {"key": "ALIGN", "kind": "fixed", "modes": ["repo"], "settings": [],
     "instruction": "Arbeit begonnen, aber kein Workorder - Request + passt es zu den "
                    "Gesetzen/Charter?",
     "why": "Fix, weil ungeprüft begonnene Arbeit nicht abnehmbar ist: erst Auftrag "
            "und Charter-Abgleich, dann Code."},
    {"key": "ANALYZE", "kind": "fixed", "modes": ["repo"], "settings": [],
     "instruction": "Architektur-Impact + Debt-Delta (Abkürzungen in debt.py registrieren). "
                    "Enthält den NO-MONKEY-PATCH-Check.",
     "why": "Fix, weil Abkürzungen sonst unsichtbar bleiben - das Debt-Register hängt "
            "an genau dieser Stufe."},
    {"key": "EXECUTE", "kind": "fixed", "modes": ["repo", "card"], "settings": [],
     "instruction": "Checks rot -> bauen/fixen bis grün (py_compile, tsc, daemon-Import, "
                    "design-lint).",
     "why": "Fix, weil rote Checks objektiv sind: was 'grün' heißt, entscheidet der "
            "Code und nicht der Agent."},
    {"key": "TEST", "kind": "fixed", "modes": ["repo"], "settings": [],
     "instruction": "Grün heißt nicht fertig: das echte Ding prüfen (UI = beurteilt, "
                    "nicht nur gerendert) + adversarial testen.",
     "why": "Fix, weil 'gerendert' nicht 'geprüft' heißt - sonst wäre jede Abnahme "
            "nur eine Vermutung."},
    {"key": "CLEAN", "kind": "fixed", "modes": ["repo", "card"], "settings": [],
     "instruction": "Hygiene: Debt-Register wohlgeformt, keine Secrets getrackt.",
     "why": "Fix, weil ein getracktes Secret oder ein kaputtes Debt-Register keine "
            "Abnahme passieren darf."},
    {"key": "BUILD", "kind": "fixed", "modes": ["repo"], "settings": [],
     "instruction": "Nur wenn die Änderung NATIVE Quellen berührt hat: signiertes APK neu "
                    "bauen. JS geht per OTA (ops/deploy/push_update.sh), nicht über das APK.",
     "why": "Fix, weil über 'stale' der echte Fingerprint der nativen Quellen "
            "entscheidet - nie ein Datum und nie ein Gefühl."},
    {"key": "COMMIT", "kind": "policy", "modes": ["repo", "card"],
     "settings": ["env.SWARM_WIP_MINUTES"],
     "instruction": "Loop komplett und die Arbeit ist ruhig -> Commit vorschlagen; "
                    "der Workorder wird beim sauberen Baum archiviert.",
     "why": "Einstellbar ist nur, wie lange 'ruhig' dauert (SWARM_WIP_MINUTES). "
            "DASS am Ende committet wird, bleibt fix."},
    {"key": "WIP", "kind": "policy", "modes": ["repo", "card"],
     "settings": ["env.SWARM_WIP_MINUTES"],
     "instruction": "Overlay, blockiert nie: die Edits sind noch frisch - den Nutzer bedienen.",
     "why": "Blockiert nie. Einstellbar ist allein das Zeitfenster (SWARM_WIP_MINUTES)."},
    {"key": "DONE", "kind": "fixed", "modes": ["repo", "card"], "settings": [],
     "instruction": "Sauberer Baum, kein offener Workorder.",
     "why": "Fix, weil 'fertig' aus dem Zustand des Baums abgeleitet wird und nicht "
            "aus einer Meldung."},
]

# from -> to with the CONDITION transitions() actually tests, so the graph and
# the code say the same thing.
LOOP_EDGES = [
    {"from": "ALIGN", "to": "ANALYZE", "when": "'## Request' + '## Alignment' gefüllt"},
    {"from": "ANALYZE", "to": "EXECUTE", "when": "'## Analysis' gefüllt"},
    {"from": "EXECUTE", "to": "TEST", "when": "keine roten Checks mehr"},
    {"from": "TEST", "to": "CLEAN", "when": "'## Verified' gefüllt"},
    {"from": "CLEAN", "to": "BUILD", "when": "Hygiene sauber"},
    {"from": "BUILD", "to": "COMMIT", "when": "kein natives Artefakt stale"},
    {"from": "COMMIT", "to": "DONE", "when": "committed - Baum sauber"},
    {"from": "WIP", "to": "COMMIT", "when": "Edits länger als SWARM_WIP_MINUTES ruhig"},
    # a card enters the loop at EXECUTE: its request was aligned on the board and
    # its verification is the gate, so those states never apply to it.
    {"from": "EXECUTE", "to": "CLEAN", "when": "card-mode: keine roten Checks",
     "modes": ["card"]},
]


def _decl_lines(keys, path=None, rel="ops/tools/loop_state.py"):
    """{key: "ops/tools/loop_state.py:466"} - where each state is DECLARED.

    Read out of the source file at call time, never written down. The map shows
    a fixed node's file:line so "structure is code" is checkable rather than
    merely asserted, and a hand-maintained line number would be wrong the first
    time anyone inserted a line above it - a citation that rots is worse than no
    citation, because it sends the reader to the wrong place with confidence."""
    out = {}
    try:
        with open(path or os.path.abspath(__file__), encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return out
    want = {'"key": "%s"' % k: k for k in keys}
    for i, line in enumerate(lines, 1):
        for needle, k in want.items():
            if needle in line and k not in out:
                out[k] = "%s:%d" % (rel, i)
    return out


def machine():
    """The build loop as DATA: the states, the edges, which mode we are in, and
    where this checkout currently sits. One definition, rendered by /loop/map and
    /automation instead of two hand-written copies."""
    card = card_mode()
    mode = "card" if card else "repo"
    cur = transitions() or []
    active = cur[0][0] if cur else "DONE"
    src = _decl_lines([s["key"] for s in LOOP_STATES])
    states = []
    for s in LOOP_STATES:
        if mode not in s["modes"]:
            continue
        s = dict(s)
        s["active"] = (s["key"] == active)
        s["source"] = src.get(s["key"], "ops/tools/loop_state.py")
        states.append(s)
    # An edge only exists if BOTH its ends do in this mode - otherwise card mode
    # would render ALIGN -> ANALYZE arrows between states it does not have.
    keys = {s["key"] for s in states}
    edges = [e for e in LOOP_EDGES
             if mode in e.get("modes", ["repo", "card"])
             and e["from"] in keys and e["to"] in keys]
    return {
        "id": "build-loop",
        "title": "Wie Änderungen gebaut werden",
        "mode": mode,
        "mode_note": ("Karten-Modus: diese Arbeitskopie IST der Worktree einer Karte "
                      "(HELMDECK_WORKTREE). Die Workorder-Zeremonie entfällt - die Karte "
                      "hat ihre Aufgabe und ihren Gate bereits."
                      if card else
                      "Repo-Modus: der volle Loop inklusive Workorder."),
        "states": states,
        "edges": edges,
        "active": active,
        "current": [{"state": st, "action": ac} for st, ac in cur],
    }


def print_table():
    t = transitions()
    if not t:
        print("[loop_state] DONE - clean tree, no open workorder. Loop: "
              "ALIGN > ANALYZE > EXECUTE > TEST > CLEAN > BUILD > COMMIT.")
        return
    print("[loop_state] loop position:")
    for st, act in t:
        print("  %-8s %s" % (st, act))
    print("NEXT: %s -> %s" % t[0])


def stop_hook():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if payload.get("stop_hook_active"):
        return
    if not _build_loop_enabled():
        return
    t = [x for x in transitions() if x[0] != "WIP"]
    if not t:
        return
    st, act = t[0]
    print(json.dumps({
        "decision": "block",
        "reason": "[loop_state] The build loop is not at a resting state: %s - %s "
                  "Do this now if it needs no user input; if you are genuinely blocked "
                  "on the user (or a check stayed red after ~3 fix attempts), say exactly "
                  "what you need and stop. Full picture: python ops/tools/loop_state.py" % (st, act)
    }))


def session_start():
    print("[loop_state] Session (re)start - loop position recomputed from disk:")
    print_table()
    print("Rule: ALIGN before code, ANALYZE before building, TEST means judged not "
          "rendered, COMMIT closes the loop. If the next action needs no user input, "
          "do it now.")
    if not _build_loop_enabled():
        # The safety net going quiet must never be silent about being off -
        # this line has no --stop-hook equivalent (that path prints nothing
        # at all when disabled, by design), so session start is the one place
        # a disabled build loop is visibly announced.
        print("[loop_state] NOTE: buildLoopEnabled=false (policy) - the Stop "
              "hook will NOT block this session, even mid-loop.")


if __name__ == "__main__":
    if "--stop-hook" in sys.argv:
        stop_hook()
    elif "--session-start" in sys.argv:
        session_start()
    else:
        print_table()
    sys.exit(0)
