# -*- coding: utf-8 -*-
"""Hacker News top stories -> backlog cards (stdlib only)."""
import json
import urllib.request

NAME = "hn_top"
DESCRIPTION = "Top 5 Hacker News stories as low-priority backlog cards"

API = "https://hacker-news.firebaseio.com/v0"
STORY_COUNT = 5
MAX_ITEMS = 20
TIMEOUT = 15


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "SwarmDeck/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def run():
    try:
        top = _get_json(API + "/topstories.json")
    except Exception:
        return []
    if not isinstance(top, list):
        return []

    items, seen = [], set()
    for sid in top[:STORY_COUNT]:
        if not isinstance(sid, int) or sid in seen:
            continue
        seen.add(sid)
        try:
            story = _get_json("%s/item/%d.json" % (API, sid))
        except Exception:
            continue
        if not isinstance(story, dict) or story.get("deleted") or story.get("dead"):
            continue
        title = (story.get("title") or "").strip() or "(untitled)"
        url = (story.get("url") or "").strip()
        if not url:
            url = "https://news.ycombinator.com/item?id=%d" % sid
        # [HN <id>] prefix keeps the story id in the task so re-imports can
        # be matched to existing cards (same pattern as the Jira importer).
        items.append({
            "task": "[HN %d] %s\n%s" % (sid, title, url),
            "client": "hn",
            "priority": "low",
            "due": "",
            "value": story.get("score") or 0,
        })
        if len(items) >= MAX_ITEMS:
            break
    return items


if __name__ == "__main__":
    for it in run():
        print(it["task"].splitlines()[0])
