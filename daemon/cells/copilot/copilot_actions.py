# -*- coding: utf-8 -*-
"""Board-copilot reply/action parsing - extracted from copilot.py. Pure text:
_parse_reply_actions splits a reply into (prose, actions[]) via the trailing
```actions [...]``` fence (legacy {"reply","actions"} JSON blob as fallback);
_strip_actions_live is the live-stream view that hides the action tail so the
user watches prose stream in. copilot.py re-imports both. Not monkeypatched.
"""
import json
import re

_ACTIONS_FENCE = re.compile(r"```actions\s*(.*?)```", re.S)


def _strip_actions_live(partial):
    """The live view of a streaming reply: drop everything from the ```actions
    fence (or a lone ``` / a leading raw-JSON blob) onward, so the user watches
    PROSE stream in, not the raw action tail."""
    if not partial:
        return partial
    s = partial.lstrip()
    if s.startswith("{"):          # legacy JSON-blob reply - nothing prose to show yet
        return ""
    for marker in ("```actions", "```"):
        i = partial.find(marker)
        if i != -1:
            return partial[:i].rstrip()
    return partial


def _parse_reply_actions(txt):
    """(reply_prose, actions[]). New contract: prose reply + optional trailing
    ```actions [..]``` block. Falls back to the legacy {"reply","actions"} JSON
    blob, then to 'the whole text is the reply'."""
    txt = txt or ""
    mf = _ACTIONS_FENCE.search(txt)
    if mf:
        reply = txt[:mf.start()].strip()
        try:
            acts = json.loads(mf.group(1).strip())
            acts = [acts] if isinstance(acts, dict) else acts
            return reply, (acts if isinstance(acts, list) else [])
        except ValueError:
            return reply, []
    mb = re.search(r"\{.*\}", txt, re.S)      # legacy blob
    if mb:
        try:
            o = json.loads(mb.group(0))
            if isinstance(o, dict) and ("reply" in o or "actions" in o):
                return o.get("reply", ""), (o.get("actions") or [])
        except ValueError:
            pass
    return txt.strip(), []
