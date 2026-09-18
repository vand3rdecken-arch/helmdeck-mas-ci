#!/usr/bin/env python3
"""Read the cookieless helmdeck.de reach measurement (D1 db helmdeck-site-stats).

Runs no browser and needs no separate API token: it shells out to
`npx wrangler d1 execute --remote --json`, reusing the same Cloudflare OAuth
session `ops/deploy/push_site.sh` already relies on. See
ops/deploy/waitlist/schema.sql for what is stored and
ops/docs/marketing/gtm-messung-2026-09.md section 4b for the design.

Usage:
    py -3.12 ops/tools/site_stats.py                  # last 7 days
    py -3.12 ops/tools/site_stats.py --days 30
    py -3.12 ops/tools/site_stats.py --include-test    # keep ?hd_test=1 visits in
    py -3.12 ops/tools/site_stats.py --section-order problem,founder,why

Every number excludes rows flagged bot=1 (User-Agent looked bot-like, never
stored raw) and, by default, rows flagged test=1 (your own ?hd_test=1 visits
while verifying a deploy) - pass --include-test to see everything.

All queries for one report run in a SINGLE `wrangler d1 execute` call
(semicolon-joined `--command`, which wrangler answers as one JSON array with
one result-set per statement, in the order given) instead of one process per
query - that is what took this tool from ~2 minutes to a few seconds.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

WAITLIST_DIR = Path(__file__).resolve().parents[2] / "ops" / "deploy" / "waitlist"
DB_NAME = "helmdeck-site-stats"

# The order sections actually appear in on the page (src/index.js page()) -
# used only to print the funnel in reading order, not to filter anything.
DEFAULT_SECTION_ORDER = ["problem", "founder", "why", "proof", "steps", "downloads", "cloud", "waitlist"]


def _npx_cmd():
    npx = shutil.which("npx")
    if not npx:
        for candidate in (r"C:\Program Files\nodejs\npx.cmd",):
            if os.path.exists(candidate):
                npx = candidate
                break
    if not npx:
        sys.exit("npx not found on PATH. Install Node.js (or add it to PATH) and try again.")
    return [npx]


def d1_query_batch(statements):
    """Run a list of SELECT statements in ONE wrangler invocation. Returns a
    list of row-lists, one per statement, in the same order they were given."""
    command = "; ".join(s.rstrip(";") for s in statements) + ";"
    cmd = _npx_cmd() + ["wrangler", "d1", "execute", DB_NAME, "--remote", "--json", "--command", command]
    try:
        proc = subprocess.run(cmd, cwd=WAITLIST_DIR, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        sys.exit("wrangler d1 execute timed out after 60s.")
    if proc.returncode != 0:
        sys.exit(f"wrangler d1 execute failed (exit {proc.returncode}):\n{proc.stderr or proc.stdout}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit(f"could not parse wrangler output as JSON:\n{proc.stdout[:2000]}")
    if len(data) != len(statements):
        sys.exit(f"expected {len(statements)} result sets, got {len(data)}:\n{proc.stdout[:2000]}")
    for entry in data:
        if not entry.get("success"):
            sys.exit(f"a batched query did not succeed:\n{proc.stdout[:2000]}")
    return [entry.get("results", []) for entry in data]


def fetch_all(cutoff_ts, include_test):
    test_clause = "" if include_test else "AND test = 0"
    where = f"AND ts >= {cutoff_ts} AND bot = 0 {test_clause}"

    # Order here is load-bearing: d1_query_batch() returns rows back in this
    # same order, unpacked positionally right below.
    keys = [
        "visits_per_day", "referrers", "utm_sources", "devices", "countries",
        "funnel_view", "funnel_sections", "funnel_cta", "funnel_form_start", "funnel_form_submit",
        "dwell_raw", "last_section", "posts_traffic", "posts_dwell", "posts_cta", "posts_submit",
    ]
    statements = [
        f"SELECT date(ts, 'unixepoch') AS day, COUNT(*) AS n FROM events "
        f"WHERE type = 'server_view' {where} GROUP BY day ORDER BY day",

        f"SELECT COALESCE(NULLIF(ref_host, ''), '(direct/organic)') AS ref, COUNT(*) AS n FROM events "
        f"WHERE type = 'view' {where} GROUP BY ref ORDER BY n DESC LIMIT 20",

        f"SELECT COALESCE(NULLIF(utm_source, ''), '(none)') AS src, COUNT(*) AS n FROM events "
        f"WHERE type = 'view' {where} GROUP BY src ORDER BY n DESC LIMIT 20",

        f"SELECT COALESCE(NULLIF(device, ''), '(unknown)') AS device, COUNT(*) AS n FROM events "
        f"WHERE type = 'view' {where} GROUP BY device ORDER BY n DESC",

        f"SELECT COALESCE(NULLIF(country, ''), '(unknown)') AS country, COUNT(*) AS n FROM events "
        f"WHERE type = 'server_view' {where} GROUP BY country ORDER BY n DESC LIMIT 30",

        f"SELECT COUNT(DISTINCT vid) AS n FROM events WHERE type = 'view' {where}",

        f"SELECT section, COUNT(DISTINCT vid) AS n FROM events "
        f"WHERE type = 'section_seen' {where} GROUP BY section",

        f"SELECT COUNT(DISTINCT vid) AS n FROM events WHERE type = 'cta_click' {where}",

        f"SELECT COUNT(DISTINCT vid) AS n FROM events WHERE type = 'form_start' {where}",

        f"SELECT COUNT(DISTINCT vid) AS n FROM events WHERE type = 'form_submit' {where}",

        f"SELECT seconds FROM events WHERE type = 'leave' AND seconds IS NOT NULL {where}",

        f"SELECT COALESCE(NULLIF(section, ''), '(none)') AS section, COUNT(*) AS n FROM events "
        f"WHERE type = 'leave' {where} GROUP BY section ORDER BY n DESC",

        # Per-post (utm_content): traffic split by bot flag, so we can report
        # a bot share per post without dropping bot rows from the count.
        f"SELECT COALESCE(NULLIF(utm_content, ''), '(none)') AS content, "
        f"MAX(NULLIF(utm_source, '')) AS src, MAX(NULLIF(utm_campaign, '')) AS campaign, "
        f"bot, COUNT(DISTINCT vid) AS n FROM events "
        f"WHERE type = 'view' AND utm_content != '' AND ts >= {cutoff_ts} {test_clause} "
        f"GROUP BY content, bot",

        f"SELECT COALESCE(NULLIF(utm_content, ''), '(none)') AS content, "
        f"AVG(seconds) AS avg_seconds, AVG(pct) AS avg_pct FROM events "
        f"WHERE type = 'leave' AND utm_content != '' {where} GROUP BY content",

        f"SELECT COALESCE(NULLIF(utm_content, ''), '(none)') AS content, COUNT(DISTINCT vid) AS n FROM events "
        f"WHERE type = 'cta_click' AND utm_content != '' {where} GROUP BY content",

        f"SELECT COALESCE(NULLIF(utm_content, ''), '(none)') AS content, COUNT(DISTINCT vid) AS n FROM events "
        f"WHERE type = 'form_submit' AND utm_content != '' {where} GROUP BY content",
    ]
    if not include_test:
        keys.append("excluded_test")
        statements.append(
            f"SELECT COUNT(*) AS n FROM events WHERE type = 'server_view' AND test = 1 AND ts >= {cutoff_ts}"
        )

    results = dict(zip(keys, d1_query_batch(statements)))

    posts = {}
    for row in results["posts_traffic"]:
        p = posts.setdefault(row["content"], {
            "content": row["content"], "src": row["src"] or "", "campaign": row["campaign"] or "",
            "visits": 0, "bot_visits": 0, "avg_seconds": None, "avg_pct": None, "cta_click": 0, "form_submit": 0,
        })
        n = row["n"] or 0
        p["visits"] += n
        if row["bot"]:
            p["bot_visits"] += n
    for row in results["posts_dwell"]:
        posts.setdefault(row["content"], {
            "content": row["content"], "src": "", "campaign": "", "visits": 0, "bot_visits": 0,
            "avg_seconds": None, "avg_pct": None, "cta_click": 0, "form_submit": 0,
        })
        posts[row["content"]]["avg_seconds"] = row["avg_seconds"]
        posts[row["content"]]["avg_pct"] = row["avg_pct"]
    for row in results["posts_cta"]:
        posts.setdefault(row["content"], {
            "content": row["content"], "src": "", "campaign": "", "visits": 0, "bot_visits": 0,
            "avg_seconds": None, "avg_pct": None, "cta_click": 0, "form_submit": 0,
        })
        posts[row["content"]]["cta_click"] = row["n"] or 0
    for row in results["posts_submit"]:
        posts.setdefault(row["content"], {
            "content": row["content"], "src": "", "campaign": "", "visits": 0, "bot_visits": 0,
            "avg_seconds": None, "avg_pct": None, "cta_click": 0, "form_submit": 0,
        })
        posts[row["content"]]["form_submit"] = row["n"] or 0
    # "Wirkung" (impact): waitlist signups first, then CTA clicks, then reach.
    posts_ranked = sorted(posts.values(), key=lambda p: (p["form_submit"], p["cta_click"], p["visits"]), reverse=True)

    return {
        "visits_per_day": results["visits_per_day"], "referrers": results["referrers"],
        "utm_sources": results["utm_sources"], "devices": results["devices"], "countries": results["countries"],
        "funnel": {
            "view": results["funnel_view"][0]["n"] if results["funnel_view"] else 0,
            "sections": {row["section"]: row["n"] for row in results["funnel_sections"] if row["section"]},
            "cta_click": results["funnel_cta"][0]["n"] if results["funnel_cta"] else 0,
            "form_start": results["funnel_form_start"][0]["n"] if results["funnel_form_start"] else 0,
            "form_submit": results["funnel_form_submit"][0]["n"] if results["funnel_form_submit"] else 0,
        },
        "dwell_seconds": [row["seconds"] for row in results["dwell_raw"]],
        "last_section": results["last_section"],
        "posts": posts_ranked,
        "excluded_test": results["excluded_test"][0]["n"] if not include_test and results["excluded_test"] else 0,
    }


def bucket_dwell(seconds_list):
    buckets = [(0, 10), (10, 30), (30, 60), (60, 180), (180, 600), (600, None)]
    labels = ["0-10s", "10-30s", "30-60s", "1-3min", "3-10min", "10min+"]
    counts = [0] * len(buckets)
    for s in seconds_list:
        for i, (lo, hi) in enumerate(buckets):
            if s >= lo and (hi is None or s < hi):
                counts[i] += 1
                break
    return list(zip(labels, counts))


def pct(n, total):
    return f"{(100.0 * n / total):.0f}%" if total else "0%"


def print_table(title, rows, key, count_key="n"):
    print(f"\n{title}")
    if not rows:
        print("  (keine Daten / no data)")
        return
    for row in rows:
        print(f"  {row[key]:<28} {row[count_key]}")


def print_posts(posts):
    print("\nJe Post (utm_content), sortiert nach Wirkung:")
    if not posts:
        print("  (keine Daten / no data - Links noch ohne utm_content gepostet?)")
        return
    header = f"  {'content':<24} {'src/campaign':<22} {'visits':>7} {'bots':>6} {'dwell':>7} {'scroll':>7} {'cta':>5} {'signup':>6}"
    print(header)
    for p in posts:
        dwell = f"{p['avg_seconds']:.0f}s" if p["avg_seconds"] is not None else "-"
        scroll = f"{p['avg_pct']:.0f}%" if p["avg_pct"] is not None else "-"
        bot_share = pct(p["bot_visits"], p["visits"])
        src_campaign = "/".join(x for x in (p["src"], p["campaign"]) if x) or "-"
        print(f"  {p['content']:<24} {src_campaign:<22} {p['visits']:>7} {bot_share:>6} {dwell:>7} {scroll:>7} {p['cta_click']:>5} {p['form_submit']:>6}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7, help="how many days back to report (default 7)")
    ap.add_argument("--include-test", action="store_true", help="include ?hd_test=1 visits (excluded by default)")
    ap.add_argument("--section-order", default=",".join(DEFAULT_SECTION_ORDER),
                     help="comma-separated section ids in page order, for the funnel print-out")
    args = ap.parse_args()

    cutoff_ts = int(time.time()) - args.days * 86400
    data = fetch_all(cutoff_ts, args.include_test)

    print(f"== helmdeck.de Reichweite, letzte {args.days} Tage ==")
    if data["excluded_test"]:
        print(f"(ausgeschlossen: {data['excluded_test']} eigene Testbesuche mit ?hd_test=1 - siehe --include-test)")

    print_table("Besuche pro Tag (server_view, JS + no-JS):", data["visits_per_day"], "day")
    print_table("Herkunft (Referrer-Host, view):", data["referrers"], "ref")
    print_table("utm_source (view):", data["utm_sources"], "src")
    print_table("Geraeteklasse (view):", data["devices"], "device")
    print_table("Land (server_view, request.cf.country):", data["countries"], "country")

    print("\nTrichter (eindeutige Besuche je Schritt, view = 100%):")
    f = data["funnel"]
    view_n = f["view"]
    print(f"  {'view':<28} {view_n} (100%)")
    for section in [s.strip() for s in args.section_order.split(",") if s.strip()]:
        n = f["sections"].get(section, 0)
        print(f"  {'section_seen:' + section:<28} {n} ({pct(n, view_n)})")
    print(f"  {'cta_click':<28} {f['cta_click']} ({pct(f['cta_click'], view_n)})")
    print(f"  {'form_start':<28} {f['form_start']} ({pct(f['form_start'], view_n)})")
    print(f"  {'form_submit':<28} {f['form_submit']} ({pct(f['form_submit'], view_n)})")

    print("\nVerweildauer (aus 'leave', Sekunden auf der Seite):")
    dwell = bucket_dwell(data["dwell_seconds"])
    total_dwell = len(data["dwell_seconds"])
    if total_dwell:
        for label, n in dwell:
            print(f"  {label:<28} {n} ({pct(n, total_dwell)})")
    else:
        print("  (keine Daten / no data)")

    print_table("Letzter gesehener Abschnitt beim Verlassen ('leave'):", data["last_section"], "section")

    print_posts(data["posts"])


if __name__ == "__main__":
    main()
