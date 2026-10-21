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


# --- card screen -----------------------------------------------------------
# More blocks (protocol v1, additive):
#   preview {title, text, lines, style, detail_title}  - a short card that opens
#           the FULL text on its own screen; style: title | outlined | surface
#   text    may carry `status` (colour key, the same table as the board)
#   button  may carry `selected` (key/value pair shown with a "> ") and
#           `needs` (pick keys that must be set before it is enabled)
# More actions:
#   {"do": "back"}
#   {"do": "pick", "key": ..., "value": ..., "then": <action>}
#   {"do": "post", "path": ..., "body": {...}, "picks_into": "answers",
#    "busy": ..., "ok": ..., "fail": ...}        - a generic authed POST
#   {"do": "dictate", "prompt": ..., "card": id}  - speech -> Henry about a card

_REASON_LABEL = {
    "gate": "Gate rot", "conflict": "Merge-Konflikt", "failed": "Fehlgeschlagen",
    "question": "Frage offen", "review": "Wartet auf Abnahme",
    "delivered": "Fertig - abnehmen", "yours": "Nur von dir startbar",
    "working": "In Arbeit", "backlog": "Backlog",
}


def _flat(s):
    return " ".join((s or "").split())


def card_screen(row, reason):
    """The card as a screen description. `row` is one board row (needs_you /
    yours / pipeline) with its `body`, `detail`, `question`, `status`."""
    cid = row.get("id") or ""
    task = row.get("task") or cid
    status = row.get("status") or ""
    detail, body = row.get("detail") or "", row.get("body") or ""
    items = [
        {"t": "header", "text": "Karte"},
        {"t": "button", "label": "Zurück", "icon": "", "style": "child",
         "action": {"do": "back"}},
        {"t": "preview", "title": "Aufgabe", "text": task, "lines": 3,
         "style": "title", "detail_title": "Aufgabe"},
    ]
    label = _REASON_LABEL.get(reason, "")
    if label:
        items.append({"t": "text", "text": label, "status": status or reason})
    # `detail` is often just the top of `body` (blockers.blocker() builds it
    # from last_reply); show it only when it adds something.
    if detail and not _flat(body).startswith(_flat(detail)[:40]):
        items.append({"t": "preview", "title": "", "text": detail, "lines": 3,
                      "style": "outlined", "detail_title": "Grund"})
    if body:
        items.append({"t": "preview", "title": "", "text": body, "lines": 3,
                      "style": "surface", "detail_title": "Antwort"})
    q = row.get("question") or {}
    qs = q.get("questions") or []
    answer = {"do": "post", "path": "/tracks/%s/answer" % cid,
              "body": {"request_id": q.get("id") or ""}, "picks_into": "answers",
              "busy": "Sende…", "ok": "Beantwortet", "fail": "Fehlgeschlagen"}
    for one in qs:
        items.append({"t": "preview", "title": "Frage", "text": one.get("question") or "",
                      "lines": 3, "style": "title", "detail_title": "Frage"})
        opts = one.get("options") or []
        if opts:
            items.append({"t": "header", "text": "Antworten"})
        for o in opts:
            act = {"do": "pick", "key": one.get("header") or "", "value": o.get("label") or ""}
            # one single-select question IS the whole answer: submit on the tap
            if len(qs) == 1 and not one.get("multiSelect"):
                act["then"] = answer
            items.append({"t": "button", "label": o.get("label") or "", "icon": "",
                          "style": "filled", "action": act,
                          "selected": {"key": act["key"], "value": act["value"]}})
    if len(qs) > 1:
        items.append({"t": "button", "label": "Senden", "icon": "", "style": "filled",
                      "action": answer, "needs": [one.get("header") or "" for one in qs]})
    items.append({"t": "header", "text": "Henry fragen"})
    items.append({"t": "button", "label": "Sprechen", "icon": "mic", "style": "filled",
                  "action": {"do": "dictate", "prompt": "Frage an Henry", "card": cid}})
    return {"v": SCREEN_VERSION, "items": items}
