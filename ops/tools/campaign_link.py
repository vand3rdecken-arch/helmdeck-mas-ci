#!/usr/bin/env python3
"""Generate a per-post campaign link for helmdeck.de and log it for later lookup.

Every post gets its own utm_content on top of the channel-level utm_source/
utm_medium/utm_campaign already documented in ops/docs/marketing/utm-links.md.
That is the one thing PostHog and the site's own D1 reach measurement could
not tell apart before: "came from t.co" vs. "came from the Show HN post" vs.
"came from the reply to @16vchq".

Usage:
    py -3.12 ops/tools/campaign_link.py --platform x --campaign teamharness --label show-hn-announce
    py -3.12 ops/tools/campaign_link.py --platform x --campaign teamharness --label reply-16vchq \
        --note "Reply to @16vchq's thread about agent harnesses"

    # once the post is live, attach its URL to the row already logged:
    py -3.12 ops/tools/campaign_link.py --posted show-hn-announce --url https://news.ycombinator.com/item?id=...

Reads/writes ops/docs/marketing/campaign-links.csv (date, platform, medium,
campaign, content, note, post_url) so a post's URL and its utm_content sit
side by side. Read the results back with:
    py -3.12 ops/tools/site_stats.py --days 30    (per-post breakdown table)
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

LOG = Path(__file__).resolve().parents[2] / "ops" / "docs" / "marketing" / "campaign-links.csv"
FIELDS = ["date", "platform", "medium", "campaign", "content", "note", "post_url"]
BASE_URL = "https://helmdeck.de/"

# Channel -> medium, the same mapping already documented in
# ops/docs/marketing/utm-links.md, so a link generated here always matches
# the channel-level scheme. Add a row here (and there) before using a new
# platform for the first time.
PLATFORM_MEDIUM = {
    "x": "social",
    "linkedin": "social",
    "reddit": "community",
    "hackernews": "community",
    "discord": "community",
    "devto": "content",
    "producthunt": "launch",
    "youtube": "video",
}


def _read_rows():
    if not LOG.exists():
        return []
    with LOG.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_rows(rows):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def make_link(platform, campaign, label, medium=None, base_url=BASE_URL):
    medium = medium or PLATFORM_MEDIUM.get(platform)
    if not medium:
        sys.exit(
            f"unknown platform '{platform}' - pass --medium explicitly, or add it "
            f"to PLATFORM_MEDIUM in this script (known: {', '.join(sorted(PLATFORM_MEDIUM))})"
        )
    qs = urlencode({
        "utm_source": platform, "utm_medium": medium,
        "utm_campaign": campaign, "utm_content": label,
    })
    return f"{base_url}?{qs}", medium


def cmd_generate(args):
    url, medium = make_link(args.platform, args.campaign, args.label, args.medium, args.base_url)
    rows = _read_rows()
    rows.append({
        "date": date.today().isoformat(),
        "platform": args.platform,
        "medium": medium,
        "campaign": args.campaign,
        "content": args.label,
        "note": args.note or "",
        "post_url": "",
    })
    _write_rows(rows)
    print(url)


def cmd_posted(args):
    rows = _read_rows()
    match = None
    for row in reversed(rows):  # most recent entry wins if a label was ever reused
        if row["content"] == args.posted:
            match = row
            break
    if match is None:
        sys.exit(f"no logged link with content '{args.posted}' in {LOG} - generate it first")
    match["post_url"] = args.url
    _write_rows(rows)
    print(f"recorded post_url for '{args.posted}'")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform", help="channel, e.g. x, reddit, hackernews, devto, producthunt, youtube, discord, linkedin")
    ap.add_argument("--campaign", help="utm_campaign, e.g. teamharness")
    ap.add_argument("--label", help="utm_content, one short slug per individual post, e.g. show-hn-announce")
    ap.add_argument("--medium", help="override the platform's default utm_medium")
    ap.add_argument("--note", help="short plain-text summary of the post, stored alongside the link")
    ap.add_argument("--base-url", default=BASE_URL, help=f"default {BASE_URL}")
    ap.add_argument("--posted", metavar="LABEL", help="instead of generating a link, attach --url to the row already logged under this utm_content")
    ap.add_argument("--url", help="the live post URL, used together with --posted")
    args = ap.parse_args()

    if args.posted:
        if not args.url:
            sys.exit("--posted needs --url")
        cmd_posted(args)
        return
    if not (args.platform and args.campaign and args.label):
        sys.exit("need --platform, --campaign and --label (or --posted LABEL --url URL)")
    cmd_generate(args)


if __name__ == "__main__":
    main()
