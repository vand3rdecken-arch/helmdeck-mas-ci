# -*- coding: utf-8 -*-
"""Model auto-discovery (turnopts.list_models): a model id that is written
NOWHERE in the code (not CLAUDE_MODELS, not CTX_WINDOWS) must still reach the
picker once Anthropic's own /v1/models says it exists - the curated manifest
is a seed/fallback, not the only source. Pinned here:
  - a fresh _fetch_models() result surfaces an unlisted model in list_models()
  - the result is cached in the db (runtime_doc row), not re-fetched every call
  - a failed fetch falls back to the last good cache, never an empty picker
  - a fetch failure with NO prior cache falls back to the manifest alone
  - discovery never touches the Auto routing default (owner decree
    2026-09-04: Sonnet 5 stays the Auto model for cards; new models are seed
    data, never an auto-adopted default)
Self-sandboxing: temp db, _fetch_models monkeypatched - no network, no CLI."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp()
# isolate from the real ~/.claude/settings.json too - _settings_models() would
# otherwise fold in whatever custom model ids the developer's machine happens
# to have configured, making the manifest-only assertion below flaky.
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(SANDBOX, "claude-config")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db.init()

from spine.agent import turnopts

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


UNLISTED_ID = "claude-ghost-9-nowhere-in-code"
KNOWN_IDS = {m["id"] for m in turnopts.CLAUDE_MODELS} | set(turnopts.CTX_WINDOWS)
check(UNLISTED_ID not in KNOWN_IDS, "sanity: the probe id is genuinely absent from the manifest")

# 1) a live discovery run surfaces the unlisted model
turnopts._fetch_models = lambda: [{"id": UNLISTED_ID, "display_name": "Ghost 9 (preview)"}]
models = turnopts.list_models()
ids = {m["id"] for m in models}
check(UNLISTED_ID in ids, "an unlisted model appears in list_models() after discovery")
found = next(m for m in models if m["id"] == UNLISTED_ID)
check(found.get("label") == "Ghost 9 (preview)" and found.get("desc") == "auto-discovered",
      "discovered entry carries the API's display_name and is marked auto-discovered")
check(all(m["id"] in ids for m in turnopts.CLAUDE_MODELS),
      "the curated manifest still stands (seed, not replaced)")

# 2) cached in the db - a second call within the TTL does not re-fetch
calls = {"n": 0}
def _counting_fetch():
    calls["n"] += 1
    return [{"id": UNLISTED_ID, "display_name": "Ghost 9 (preview)"}]
turnopts._fetch_models = _counting_fetch
turnopts.list_models()
turnopts.list_models()
check(calls["n"] == 0, "a fresh (<24h) cache serves without calling _fetch_models again")

# 3) fetch fails later -> falls back to the last good cache (picker never empty)
turnopts._fetch_models = lambda: None
cache = db.doc_get(turnopts._MODELS_CACHE_KEY)
cache["at"] = 0   # force staleness so _discovered() actually re-fetches
db.doc_put(turnopts._MODELS_CACHE_KEY, cache)
models = turnopts.list_models()
check(any(m["id"] == UNLISTED_ID for m in models),
      "a failed refresh still serves the last known-good discovered list")

# 4) fetch fails with no prior cache at all -> manifest alone, never empty
# (delete the runtime_doc row in place - respawning a second sandboxed db
# would hit db.conn()'s thread-local caching and silently keep talking to
# sandbox 1's connection, see db.py:81-89)
with db.conn() as c:
    c.execute("DELETE FROM runtime_doc WHERE key=?", (turnopts._MODELS_CACHE_KEY,))
turnopts._fetch_models = lambda: None
models = turnopts.list_models()
ids = {m["id"] for m in models}
check(ids == {m["id"] for m in turnopts.CLAUDE_MODELS},
      "no token/offline with no cache -> exactly the manifest, never empty")
check(len(models) > 0, "the picker is never empty even fully offline")

# 5) discovery never moves the Auto routing default (owner decree 2026-09-04)
check(turnopts.DEFAULT_ROUTING_POLICY["auto_model"] == "claude-sonnet-5",
      "Auto default stays Sonnet 5 regardless of what discovery finds")
picked = turnopts.pick_model("please fix the flaky test in ci")
check(picked == "claude-sonnet-5",
      "an ordinary Auto turn still routes to Sonnet 5 (%r), not a newly discovered model" % picked)

print()
if _fails:
    print("FAILED: %d check(s)" % len(_fails))
    sys.exit(1)
print("ALL GREEN - unlisted models reach the picker via discovery; Auto default untouched")
