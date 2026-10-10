# -*- coding: utf-8 -*-
"""Headless test for DICTATION CLEANUP (spine/media/dictation_cleanup.py).

Pins what was MEASURED on 2026-10-07 (claude CLI 2.1.284, haiku-4-5):
 1. the two flags that took a cleanup call from 19,886 context tokens / 10.5 s /
    $0.0046 to 519 tokens / 4.9 s / $0.0006 stay in the command line:
    --strict-mcp-config with an EMPTY mcp config, and MAX_THINKING_TOKENS=0
    in the child env. Lose either one and it silently costs 10-30x.
 2. the dictation travels on STDIN, never in argv (argv is logged and has a
    length limit; the --mcp-config flag also swallows a trailing positional).
 3. failure shapes seen in the real runs are REJECTED and the original text
    returned: the model answering a question, a preface ("Hier ist ..."),
    markdown, an empty reply, a reply that is far too short/long.
 4. a question stays a question; tags the model echoes are stripped.
 5. short input and a settings switch skip the model entirely (no spawn, no spend).
 6. an exception or timeout returns the original, never raises.
 7. each REAL call records its spend once (source "dictation_clean").
 8. owner vocabulary from settings.voice_vocab joins the built-in list, no dupes.
No model, no CLI spawn, no live db: runner / settings_fn / spend_fn are replaced.
Run: py -3.12 ops/tests/test_dictation_cleanup.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from spine.media import dictation_cleanup as dc            # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


SPENT, CALLS = [], []
SETTINGS = {}
REPLY = {"result": "", "usage": {"input_tokens": 9}, "cost": 0.0006, "models": ["claude-haiku-4-5"]}


CTX_SEEN = []


def fake_runner(text, context="", model=None):
    CALLS.append(text)
    CTX_SEEN.append(context)
    if isinstance(REPLY.get("raise"), Exception):
        raise REPLY["raise"]
    return {k: REPLY[k] for k in ("result", "usage", "cost", "models")}


dc.runner = fake_runner
dc.settings_fn = lambda: SETTINGS
PROFILE = {"on": True, "model": "haiku"}      # the account's `polish` row (the ONE switch + model)
dc.profile_fn = lambda user: PROFILE
dc.spend_fn = lambda models, usage, cost: SPENT.append((models, usage, cost))


def reset(result="", **extra):
    CALLS.clear(); SPENT.clear(); SETTINGS.clear(); CTX_SEEN.clear(); PROFILE.update({"on": True, "model": "haiku"})
    REPLY.clear()
    REPLY.update({"result": result, "usage": {"input_tokens": 9}, "cost": 0.0006, "models": ["claude-haiku-4-5"]})
    REPLY.update(extra)


# 1+2: the command line and the child env
a = dc.argv()
a = a if isinstance(a, list) else str(a).split()
joined = " ".join(map(str, a))
check("--strict-mcp-config" in a, "argv has --strict-mcp-config (no auto-loaded MCP tool schemas)")
i = a.index("--mcp-config") if "--mcp-config" in a else -1
check(i >= 0 and os.path.exists(a[i + 1]) and open(a[i + 1], encoding="utf-8").read().replace(" ", "") == '{"mcpServers":{}}',
      "--mcp-config points at an EMPTY server list: %r" % (a[i + 1] if i >= 0 else None))
check(dc.ENV_EXTRA.get("MAX_THINKING_TOKENS") == "0", "child env switches thinking OFF (MAX_THINKING_TOKENS=0)")
check("--tools" in a and a[a.index("--tools") + 1] == "", "no tools at all (--tools '')")
check("--no-session-persistence" in a, "no session file left behind per dictation")
check(dc.MODEL in a, "model is pinned: %s" % dc.MODEL)
check("--system-prompt" in a and "Build" in a[a.index("--system-prompt") + 1], "system prompt carries the vocabulary")
check("diktat" not in " ".join(str(x) for x in a[:a.index("--system-prompt")]), "the dictation is not in argv before the prompt flag")

# 3: accepted + rejected shapes
SRC = "Also äh starte den Bild und pushe dann den Brunch auf GTO, nein warte, auf GitHub."
reset("Starte den Build und pushe dann den Branch auf GitHub.")
r = dc.clean(SRC)
check(r["changed"] and r["text"] == "Starte den Build und pushe dann den Branch auf GitHub." and not r["skipped"],
      "a good cleanup is accepted: %r" % r["text"])
check(len(SPENT) == 1, "the real call recorded its spend once")

Q = "Wie ist der Stand von der Glass Bild und wann ist das fertig?"
reset("Ich kann Ihnen gerne helfen, aber ich benötige dazu mehr Informationen. Wo soll ich suchen?")
r = dc.clean(Q)
check(r["text"] == Q and "rejected" in (r["skipped"] or ""), "the model ANSWERING a question is rejected -> original: %s" % r["skipped"])

reset("Wie ist der Stand von der Glass Build und wann ist das fertig.")
r = dc.clean(Q)
check(r["text"] == Q and "answered" in (r["skipped"] or ""), "a question that lost its '?' counts as answered -> original")

reset("Wie ist der Stand vom Glass Build und wann ist das fertig?")
r = dc.clean(Q)
check(r["changed"] and r["text"].endswith("?"), "a cleaned question stays a question and is accepted")

reset("Hier ist der bereinigte Text: Starte den Build und pushe dann den Branch auf GitHub.")
r = dc.clean(SRC)
check(r["text"] == SRC and "preface" in (r["skipped"] or ""), "a preface is rejected")

reset("**Starte den Build** und pushe den Branch auf GitHub.")
check(dc.clean(SRC)["text"] == SRC, "markdown is rejected")

reset("")
r = dc.clean(SRC)
check(r["text"] == SRC and "empty" in (r["skipped"] or ""), "an empty reply returns the original")

reset("Build.")
r = dc.clean(SRC)
check(r["text"] == SRC and "length" in (r["skipped"] or ""), "a far too short reply is rejected")

reset(SRC + " " + SRC)
r = dc.clean(SRC)
check(r["text"] == SRC and "length" in (r["skipped"] or ""), "a far too long reply is rejected")

# 4: echoed tags are stripped
reset("<diktat>Starte den Build und pushe dann den Branch auf GitHub.</diktat>")
r = dc.clean(SRC)
check(r["changed"] and "<" not in r["text"], "echoed <diktat> tags are stripped: %r" % r["text"])

# 5: skips never spawn and never spend
reset("x")
r = dc.clean("ok danke")
check(r["skipped"] == "short" and not CALLS and not SPENT, "short input: no model, no spend")
PROFILE["on"] = False
r = dc.clean(SRC)
check(r["skipped"] == "off" and not CALLS and not SPENT, "switched off in the profile: no model, no spend")
reset("x")
r = dc.clean("wort " * 2000)
check(r["skipped"] == "long" and not CALLS, "an over-long text is not sent")

# 6: failures return the original
reset("x", **{"raise": RuntimeError("boom")})
r = dc.clean(SRC)
check(r["text"] == SRC and (r["skipped"] or "").startswith("error"), "a failing call returns the original: %s" % r["skipped"])
check(not SPENT, "a failed call records no spend")

# 8: vocabulary
reset("x")
SETTINGS["voice_vocab"] = ["Kubernetes", "build", " "]
v = dc.vocab()
check("Kubernetes" in v and v.count("Build") == 1 and not any(w.lower() == "build" and w != "Build" for w in v),
      "owner words join the list, case-insensitive duplicates dropped: %s" % v[:5])

# 9: chat context ("a few chats from before, not so much")
LOG = [("Nutzer", "alt eins"), ("Henry", "x" * 400), ("Nutzer", "Wie steht der Glass Build?"),
       ("Henry", "Der Build läuft noch."), ("Nutzer", "Dann warte ich."), ("Henry", "Ok, ich melde mich.")]
dc.history_fn = lambda user, n: LOG[-n:]
ctx = dc.context_block("owner")
check(ctx.count("\n") + 1 <= dc.CTX_MESSAGES, "at most %d earlier messages: %d lines" % (dc.CTX_MESSAGES, ctx.count("\n") + 1))
check("Nutzer:" in ctx and "Henry:" in ctx, "the context names who said what")
check(len(ctx) <= dc.CTX_TOTAL, "the whole context stays under %d chars (%d)" % (dc.CTX_TOTAL, len(ctx)))
dc.history_fn = lambda user, n: [("Henry", "y" * 5000)] * n
long_ctx = dc.context_block("owner")
check(all(len(ln) <= dc.CTX_EACH + 12 for ln in long_ctx.split("\n")) and len(long_ctx) <= dc.CTX_TOTAL,
      "one very long message is trimmed per line and in total (%d chars)" % len(long_ctx))
check(dc.context_block(None) == "" and dc.context_block("") == "", "no account -> no context")


def _boom(user, n):
    raise RuntimeError("db gone")


dc.history_fn = _boom
check(dc.context_block("owner") == "", "a failing history read never breaks the cleanup")
dc.history_fn = lambda user, n: LOG[-n:]
reset("Starte den Build und pushe dann den Branch auf GitHub.")
dc.clean(SRC, "owner")
check(bool(CTX_SEEN) and "Dann warte ich" in CTX_SEEN[0], "clean(text, user) hands the recent chat to the model call")
reset("Starte den Build und pushe dann den Branch auf GitHub.")
dc.clean(SRC)
check(bool(CTX_SEEN) and CTX_SEEN[0] == "", "without an account the call carries no context")
check("kontext" in a[a.index("--system-prompt") + 1].lower(), "the system prompt explains the context block")

# 10: the WARM worker, against a fake child that speaks the real stream-json shape
import subprocess                                          # noqa: E402
import tempfile                                            # noqa: E402
import threading                                           # noqa: E402
import time                                                # noqa: E402

FAKE = os.path.join(tempfile.gettempdir(), "fake_claude_stream.py")
with open(FAKE, "w", encoding="utf-8") as f:
    f.write('''import sys, json, os, time
total = 0.0
for line in sys.stdin:
    j = json.loads(line)
    txt = j["message"]["content"]
    if "HANG" in txt:
        time.sleep(120)
    if "CRASH" in txt:
        os._exit(3)
    if "ERRORRESULT" in txt:
        print(json.dumps({"type": "result", "is_error": True, "result": "overloaded"}), flush=True)
        continue
    total += 0.001
    body = txt.split("<diktat>")[1].split("</diktat>")[0]
    print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "result": "%d|%s" % (os.getpid(), body), "usage": {"input_tokens": 5},
                      "total_cost_usd": total, "modelUsage": {"claude-haiku-4-5": {}}}), flush=True)
''')
SPAWNS = []


def fake_spawn(args, env):
    SPAWNS.append((args, dict(env)))
    return subprocess.Popen([sys.executable, "-u", FAKE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")


dc.spawn_fn = fake_spawn
W = dc._WARM


def fresh_worker():
    W.close(); SPAWNS.clear()
    dc.WARM_MAX_TURNS, dc.WARM_IDLE_S, dc.WARM_TIMEOUT_S = 6, 600, 12


def pid_of(r):
    return r["result"].split("|")[0]


fresh_worker()
r1, r2, r3 = W.ask("eins", ""), W.ask("zwei", ""), W.ask("drei", "")
check(pid_of(r1) == pid_of(r2) == pid_of(r3) and len(SPAWNS) == 1,
      "one process serves consecutive dictations (spawned %d time)" % len(SPAWNS))
check([r["result"].split("|")[1] for r in (r1, r2, r3)] == ["eins", "zwei", "drei"], "each answer belongs to its own dictation")
check(abs(r2["cost"] - 0.001) < 1e-9 and abs(r3["cost"] - 0.001) < 1e-9,
      "cumulative total_cost_usd becomes a per-turn DELTA (%.4f, %.4f), not a running sum" % (r2["cost"], r3["cost"]))
args, env = SPAWNS[0]
args = args if isinstance(args, list) else str(args).split()
check("--input-format" in args and args[args.index("--output-format") + 1] == "stream-json" and "--strict-mcp-config" in args,
      "the persistent form keeps the cost flags and speaks stream-json")
check(env.get("MAX_THINKING_TOKENS") == "0", "the persistent process also runs with thinking off")

fresh_worker(); dc.WARM_MAX_TURNS = 3
pids = [pid_of(W.ask("t%d" % i, "")) for i in range(7)]
check(len(set(pids)) == 3 and len(SPAWNS) == 3, "recycled after WARM_MAX_TURNS turns: %d processes for 7 dictations" % len(set(pids)))

fresh_worker(); dc.WARM_IDLE_S = 0.2
a = pid_of(W.ask("alt", "")); time.sleep(0.4); b = pid_of(W.ask("neu", ""))
check(a != b, "a process idle longer than WARM_IDLE_S is not reused")

fresh_worker()
a = pid_of(W.ask("vor dem Absturz", ""))
try:
    W.ask("CRASH jetzt", "")
    check(False, "a crashing process raises")
except RuntimeError as e:
    check("exited" in str(e) or "gone" in str(e), "a crash surfaces as an error: %s" % e)
b = pid_of(W.ask("danach", ""))
check(a != b and W.alive(), "the next dictation after a crash gets a NEW, living process")

fresh_worker(); dc.WARM_TIMEOUT_S = 1.0
t0 = time.time()
try:
    W.ask("HANG ewig", "")
    check(False, "a hanging process raises")
except RuntimeError as e:
    check("timed out" in str(e) and time.time() - t0 < 4, "a hang times out in about WARM_TIMEOUT_S: %.1f s" % (time.time() - t0))
check(not W.alive(), "the hung process was killed, not left running")
dc.WARM_TIMEOUT_S = 12
check(W.ask("wieder da", "")["result"].endswith("wieder da"), "and the next dictation works")

fresh_worker()
try:
    W.ask("ERRORRESULT", "")
    check(False, "an error result raises")
except RuntimeError as e:
    check("model error" in str(e), "an error result raises and drops the process: %s" % e)

fresh_worker()
out = {}


def worker(k):
    out[k] = W.ask("text%d" % k, "")["result"].split("|")[1]


ths = [threading.Thread(target=worker, args=(k,)) for k in range(6)]
[th.start() for th in ths]; [th.join() for th in ths]
check(all(out[k] == "text%d" % k for k in range(6)), "6 simultaneous dictations never mix up their answers")

fresh_worker()
t0 = time.time(); W.prewarm(); took = time.time() - t0
check(W.alive() and len(SPAWNS) == 1 and took < 2, "prewarm boots the process without waiting for a request (%.2f s)" % took)
W.prewarm()
check(len(SPAWNS) == 1, "a second prewarm does not spawn another one")
W.close()
check(not W.alive(), "close() ends the process")

# prewarm respects the switches; the default runner honours the one-shot switch
fresh_worker()
PROFILE["on"] = False
dc.prewarm("u")
check(not W.alive() and not SPAWNS, "prewarm does nothing when cleanup is switched off")
PROFILE["on"] = True
dc.settings_fn = lambda: {"dictation_cleanup_warm": False}
dc.prewarm("u")
check(not W.alive() and not SPAWNS, "prewarm does nothing when the warm process is switched off")
dc.settings_fn = lambda: SETTINGS
W.close()

# ONE setting for both paths: the account's `polish` row decides switch AND model
print("\npolish (shared by our own dictation and keyboard text)")
from spine.storage import userconfig                            # noqa: E402
MODELS = []
def model_runner(text, context="", model=None):
    MODELS.append(model)
    return {"result": "Starte den Build fuer iOS bitte", "usage": None, "cost": 0.0, "models": []}
dc.runner = model_runner
SRC2 = "aeh starte den Bild fuer iOS bitte"
reset(); PROFILE.update({"on": False, "model": "haiku"})
check(dc.clean(SRC2, "u")["skipped"] == "off" and not MODELS, "account switch off -> no model call")
PROFILE.update({"on": True, "model": "sonnet"})
r = dc.clean(SRC2, "u")
check(r["changed"] and MODELS == [userconfig.POLISH_MODELS["sonnet"]], "the account's model is passed to the runner")
SETTINGS.update({"dictation_cleanup": False})
check(dc.clean(SRC2, "u")["changed"], "the old workspace switch no longer matters")
check(userconfig.POLISH_DEFAULT["on"] is True, "polish is ON by default (own dictation always was)")
check(userconfig.validate({"polish": {"on": True, "model": "opus"}})[1] is not None, "validator refuses a model outside the closed list")
check(userconfig.validate({"polish": {"on": True, "model": "haiku", "x": 1}})[1] is not None, "validator refuses unknown sub-keys")
check(userconfig.validate({"polish": {"on": True, "model": "sonnet"}})[1] is None, "validator accepts haiku/sonnet")
w = dc._warm_for(userconfig.POLISH_MODELS["sonnet"])
check(w is not dc._WARM and w.model == "claude-sonnet-5-5" and dc._warm_for(None) is dc._WARM, "one warm process per model")
a2 = dc.argv(model="claude-sonnet-5-5")
check("claude-sonnet-5-5" in a2 and dc.MODEL not in a2, "argv takes the model")

print("\n%d failure(s)" % len(FAILS) if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
