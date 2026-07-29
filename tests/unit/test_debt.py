# -*- coding: utf-8 -*-
"""Debt register well-formedness - the register is data reviewed like code,
so its shape is a contract: every item must render in the History view,
be convertible to a fix card, and keep paid items listed."""
import debt

REQUIRED_KEYS = {"id", "title", "status", "what", "why_it_bites",
                 "trigger", "fix", "order"}
STATUSES = {"open", "in_progress", "paid"}


def test_every_item_has_required_keys():
    for item in debt.DEBT:
        missing = REQUIRED_KEYS - set(item)
        assert not missing, "%s missing keys: %s" % (item.get("id"), missing)


def test_string_fields_are_nonempty_strings():
    for item in debt.DEBT:
        for key in ("id", "title", "what", "why_it_bites", "trigger", "fix"):
            v = item[key]
            assert isinstance(v, str) and v.strip(), \
                "%s.%s must be a non-empty string" % (item["id"], key)


def test_status_is_known():
    for item in debt.DEBT:
        assert item["status"] in STATUSES, \
            "%s has unknown status %r" % (item["id"], item["status"])


def test_ids_are_unique_slugs():
    ids = [item["id"] for item in debt.DEBT]
    assert len(ids) == len(set(ids)), "duplicate debt ids: %s" % ids
    for i in ids:
        assert i == i.lower() and " " not in i, \
            "id %r should be a lowercase slug" % i


def test_orders_are_unique_ints():
    orders = [item["order"] for item in debt.DEBT]
    assert all(isinstance(o, int) for o in orders)
    assert len(orders) == len(set(orders)), "duplicate order values: %s" % orders


def test_list_debt_keeps_paid_items_listed():
    # paid items document why the code looks the way it does - never dropped
    assert len(debt.list_debt()) == len(debt.DEBT)


def test_list_debt_sorts_unpaid_first_then_by_order():
    listed = debt.list_debt()
    statuses = [item["status"] for item in listed]
    first_paid = statuses.index("paid") if "paid" in statuses else len(listed)
    assert all(s == "paid" for s in statuses[first_paid:]), \
        "an unpaid item sorted after a paid one: %s" % statuses
    unpaid = [i["order"] for i in listed[:first_paid]]
    paid = [i["order"] for i in listed[first_paid:]]
    assert unpaid == sorted(unpaid)
    assert paid == sorted(paid)


def test_fix_task_carries_the_full_story():
    item = debt.DEBT[0]
    task = debt.fix_task(item)
    for key in ("id", "title", "what", "why_it_bites", "fix"):
        assert item[key] in task, "fix card is missing the item's %s" % key
    # the card must instruct the agent to flip status, not delete the entry
    assert "paid" in task and "daemon/debt.py" in task
