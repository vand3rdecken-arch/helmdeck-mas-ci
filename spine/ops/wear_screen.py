# -*- coding: utf-8 -*-
"""Screen descriptions for the watch (protocol v1) - the daemon says WHAT the
screen is, the watch's generic renderer (plugins/wear/ScreenRenderer.kt) only
knows HOW to draw a handful of block types.

Why this exists (ops/docs/backlog/native-release-diet): every wording, order or
section change on the watch used to be Kotlin, i.e. a native build and a store
submission. Here it is a daemon change. The vocabulary is closed and small on
purpose - a new block TYPE is a native release, a new screen is not.

Blocks (every one carries only what it draws):
  header  {text}
  text    {text}
  age     {ts, prefix}                 - rendered client-side ("vor 5 min")
  card    {title, sub, status, action}  - `status` picks the colour on the watch
  button  {label, icon, style, action}  - style: tonal | child
Actions:
  {"do": "open_card", "id": ...}  {"do": "nav", "to": "henry"}  {"do": "reload"}

Additive: the board route keeps every old key, so a watch build without the
renderer ignores `screen` and draws its own native board.
"""

SCREEN_VERSION = 1


def _card(row, action_id=None):
    return {"t": "card", "title": row.get("task") or row.get("id") or "",
            "sub": row.get("status") or "", "status": row.get("status") or "",
            "action": {"do": "open_card", "id": action_id or row.get("id") or ""}}


def board_screen(payload):
    """The board as a screen description, built from the board payload the
    route already assembled (needs_you / yours / pipeline / econ / ts)."""
    needs = payload.get("needs_you") or []
    yours = payload.get("yours") or []
    pipe = payload.get("pipeline") or {}
    working, backlog = pipe.get("working") or [], pipe.get("backlog") or []
    econ = payload.get("econ") or {}
    wip_limit = int(econ.get("wip_limit") or 0)

    items = [{"t": "header", "text": "HelmDeck"}]
    if not needs:
        items.append({"t": "text", "text": "Nichts wartet auf dich"})
    elif len(needs) == 1:
        items.append({"t": "text", "text": "1 wartet auf dich"})
    else:
        items.append({"t": "text", "text": "%d warten auf dich" % len(needs)})
    items += [_card(r) for r in needs]
    if yours:
        items.append({"t": "text", "text": "Von dir"})
        items += [_card(r) for r in yours]
    wtotal = int(pipe.get("working_total") or 0)
    if wtotal > 0:
        items.append({"t": "text", "text": "In Arbeit: %d von %d" % (wtotal, wip_limit)
                      if wip_limit > 0 else "In Arbeit: %d" % wtotal})
        items += [_card(r) for r in working]
    btotal = int(pipe.get("backlog_total") or 0)
    if btotal > 0:
        items.append({"t": "text", "text": "Backlog: %d" % btotal})
        items += [_card(r) for r in backlog]
    if payload.get("ts"):
        items.append({"t": "age", "ts": int(payload["ts"]), "prefix": "Stand: "})
    items.append({"t": "button", "label": "Henry", "icon": "mic", "style": "tonal",
                  "action": {"do": "nav", "to": "henry"}})
    items.append({"t": "button", "label": "Neu laden", "icon": "", "style": "child",
                  "action": {"do": "reload"}})
    return {"v": SCREEN_VERSION, "items": items}
