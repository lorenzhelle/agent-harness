#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["feedparser"]
# ///
"""
fetch_feed.py - Fetches an RSS/Atom feed (YouTube channel feed, podcast RSS, or
newsletter RSS) and prints new entries as JSON.

Usage:
    python fetch_feed.py --url <feed_url> [--since-days 3] [--seen-ids id1,id2,...]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser


def entry_id(entry) -> str:
    return entry.get("id") or entry.get("guid") or entry.get("link") or entry.get("title", "")


def entry_timestamp(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(mktime(value), tz=timezone.utc)
    return None


def entry_audio_url(entry) -> str | None:
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" or (link.get("type") or "").startswith("audio/"):
            return link.get("href")
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="feed URL")
    parser.add_argument(
        "--since-days", type=float, default=3, help="only include entries newer than this many days"
    )
    parser.add_argument(
        "--seen-ids", default="", help="comma-separated entry ids to exclude (already processed)"
    )
    args = parser.parse_args()

    seen = {s.strip() for s in args.seen_ids.split(",") if s.strip()}
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    parsed = feedparser.parse(args.url)
    if parsed.bozo and not parsed.entries:
        print(f"error: could not parse feed {args.url}: {parsed.bozo_exception}", file=sys.stderr)
        sys.exit(1)

    items = []
    for entry in parsed.entries:
        eid = entry_id(entry)
        if not eid or eid in seen:
            continue

        ts = entry_timestamp(entry)
        if ts is not None and ts < cutoff:
            continue

        items.append(
            {
                "id": eid,
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": ts.isoformat() if ts else None,
                "summary": entry.get("summary", ""),
                "audio_url": entry_audio_url(entry),
            }
        )

    print(json.dumps(items, indent=2))


if __name__ == "__main__":
    main()
