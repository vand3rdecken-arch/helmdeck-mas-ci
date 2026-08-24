# -*- coding: utf-8 -*-
"""A PROJECT is the billable unit - replaces per-card `value` guessing with two
real contract shapes:

  fixed  - a SOW for an agreed price. Cards under it consume effort, not value;
           the price only counts once the whole SOW is delivered (every card done).
  tm     - time & material: the client pays `rate` per hour actually worked.
           Value accrues with real elapsed time, not a per-card guess.

Cards opt in via `project_id` (sessions.EDITABLE); a card with no project keeps
today's behavior (its own `value`, counted on acceptance) - nothing regresses.
events.metrics() reads real hours from real lane-in-"working" duration
(events.time_in_work), not the touch-count tariff (that stays what it is:
human capacity/utilization, unrelated to billing)."""
import time
from spine.storage import db

BILLINGS = ("fixed", "tm")


def _slug(s):
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:32] or "project"


def list_projects():
    return db.projects_all()


def get_project(pid):
    return db.project_get(pid)


def new_project(name, billing, client="", fixed_price=None, rate=None, actor="owner"):
    if billing not in BILLINGS:
        raise ValueError("billing must be one of %s" % (BILLINGS,))
    if billing == "fixed" and fixed_price is None:
        raise ValueError("fixed price project needs fixed_price")
    if billing == "tm" and rate is None:
        raise ValueError("time & material project needs an hourly rate")
    pid = time.strftime("%Y%m%d-%H%M%S") + "-" + _slug(name)
    p = {"id": pid, "name": name, "client": client, "billing": billing,
         "fixed_price": float(fixed_price) if fixed_price is not None else None,
         "rate": float(rate) if rate is not None else None,
         "status": "active", "actor": actor,
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    db.project_put(p)
    return p


EDITABLE = ("name", "client", "billing", "fixed_price", "rate", "status")


def update_project(pid, patch, actor="owner"):
    p = db.project_get(pid)
    if not p:
        raise RuntimeError("no such project: " + pid)
    for k in EDITABLE:
        if k in patch and patch[k] is not None:
            p[k] = float(patch[k]) if k in ("fixed_price", "rate") else patch[k]
    if p["billing"] not in BILLINGS:
        raise ValueError("billing must be one of %s" % (BILLINGS,))
    p["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    db.project_put(p)
    return p


def delete_project(pid, actor="owner"):
    if not db.project_get(pid):
        raise RuntimeError("no such project: " + pid)
    db.project_delete(pid)
    return {"deleted": pid}


def billed_value(project, hours, all_done):
    """What this project has earned so far, given the real hours worked across
    its cards and whether every one of its cards has reached 'done'.

    fixed: the whole SOW price counts once fully delivered - not before (avoids
           recognizing revenue on a partially-done contract), and not per-card.
    tm:    hours * rate, counted as worked - a client on time & material pays
           for time spent regardless of which individual card is done yet."""
    if project["billing"] == "fixed":
        return project["fixed_price"] if all_done else 0.0
    return round(hours * project["rate"], 2)
