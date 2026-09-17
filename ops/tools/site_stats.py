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


def d1_query(sql, params=None):
    """Run one SQL statement against the remote D1 db, return its result rows."""
    cmd = _npx_cmd() + ["wrangler", "d1", "execute", DB_NAME, "--remote", "--json", "--command", sql]
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
    if not data or not data[0].get("success"):
        sys.exit(f"query did not succeed:\n{proc.stdout[:2000]}")
    return data[0].get("results", [])


def fetch_all(cutoff_ts, include_test):
    """One round-trip per report section - traffic here is low enough that
    a handful of sequential queries is simpler and clearer than one giant
    UNION, and each is independently readable/debuggable."""
    test_clause = "" if include_test else "AND test = 0"
    bot_clause = "AND bot = 0"
    where = f"WHERE ts >= {cutoff_ts} {bot_clause} {test_clause}"

    visits_per_day = d1_query(
        f"SELECT date(ts, 'unixepoch') AS day, COUNT(*) AS n FROM events "
        f"WHERE type = 'server_view' {where.replace('WHERE ts', 'AND ts')} "
        f"GROUP BY day ORDER BY day"
    )
    referrers = d1_query(
        f"SELECT COALESCE(NULLIF(ref_host, ''), '(direct/organic)') AS ref, COUNT(*) AS n FROM events "
        f"WHERE type = 'view' {where.replace('WHERE ts', 'AND ts')} "
        f"GROUP BY ref ORDER BY n DESC LIMIT 20"
    )
    utm_sources = d1_query(
        f"SELECT COALESCE(NULLIF(utm_source, ''), '(none)') AS src, COUNT(*) AS n FROM events "
        f"WHERE type = 'view' {where.replace('WHERE ts', 'AND ts')} "
        f"GROUP BY src ORDER BY n DESC LIMIT 20"
    )
    devices = d1_query(
        f"SELECT COALESCE(NULLIF(device, ''), '(unknown)') AS device, COUNT(*) AS n FROM events "
        f"WHERE type = 'view' {where.replace('WHERE ts', 'AND ts')} "
        f"GROUP BY device ORDER BY n DESC"
    )
    countries = d1_query(
        f"SELECT COALESCE(NULLIF(country, ''), '(unknown)') AS country, COUNT(*) AS n FROM events "
        f"WHERE type = 'server_view' {where.replace('WHERE ts', 'AND ts')} "
        f"GROUP BY country ORDER BY n DESC LIMIT 30"
    )
    funnel_view = d1_query(
        f"SELECT COUNT(DISTINCT vid) AS n FROM events WHERE type = 'view' {where.replace('WHERE ts', 'AND ts')}"
    )
    funnel_sections = d1_query(
        f"SELECT section, COUNT(DISTINCT vid) AS n FROM events "
        f"WHERE type = 'section_seen' {where.replace('WHERE ts', 'AND ts')} "
        f"GROUP BY section"
    )
    funnel_cta = d1_query(
        f"SELECT COUNT(DISTINCT vid) AS n FROM events WHERE type = 'cta_click' {where.replace('WHERE ts', 'AND ts')}"
    )
    funnel_form_start = d1_query(
        f"SELECT COUNT(DISTINCT vid) AS n FROM events WHERE type = 'form_start' {where.replace('WHERE ts', 'AND ts')}"
    )
    funnel_form_submit = d1_query(
        f"SELECT COUNT(DISTINCT vid) AS n FROM events WHERE type = 'form_submit' {where.replace('WHERE ts', 'AND ts')}"
    )
    dwell_raw = d1_query(
        f"SELECT seconds FROM events WHERE type = 'leave' AND seconds IS NOT NULL {where.replace('WHERE ts', 'AND ts')}"
    )
    last_section = d1_query(
        f"SELECT COALESCE(NULLIF(section, ''), '(none)') AS section, COUNT(*) AS n FROM events "
        f"WHERE type = 'leave' {where.replace('WHERE ts', 'AND ts')} "
        f"GROUP BY section ORDER BY n DESC"
    )
    excluded_test = 0
    if not include_test:
        r = d1_query(f"SELECT COUNT(*) AS n FROM events WHERE type = 'server_view' AND test = 1 AND ts >= {cutoff_ts}")
        excluded_test = r[0]["n"] if r else 0

    return {
        "visits_per_day": visits_per_day, "referrers": referrers, "utm_sources": utm_sources,
        "devices": devices, "countries": countries,
        "funnel": {
            "view": funnel_view[0]["n"] if funnel_view else 0,
            "sections": {row["section"]: row["n"] for row in funnel_sections if row["section"]},
            "cta_click": funnel_cta[0]["n"] if funnel_cta else 0,
            "form_start": funnel_form_start[0]["n"] if funnel_form_start else 0,
            "form_submit": funnel_form_submit[0]["n"] if funnel_form_submit else 0,
        },
        "dwell_seconds": [row["seconds"] for row in dwell_raw],
        "last_section": last_section,
        "excluded_test": excluded_test,
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


if __name__ == "__main__":
    main()
