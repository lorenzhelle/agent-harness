#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["feedparser"]
# ///
"""
fetch_feed.py - Fetches an RSS/Atom feed (YouTube channel feed, podcast RSS, or
newsletter RSS) and prints new entries as JSON.

Usage:
    python fetch_feed.py --url <feed_url> [--since-days 3] [--seen-ids id1,id2,...] \
        [--title-regex REGEX] [--max-items N]

--title-regex and --max-items push filtering into the script (cheap, no LLM
tokens) instead of relying on a relevance pass over titles/summaries in the
main conversation. Use --title-regex to keep only entries matching a pattern
(e.g. a podcast's recurring news-format episodes) and --max-items to cap how
many of the newest matching entries come back (e.g. 1 for "just the latest
issue").
"""

import argparse
import json
import re
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
        # Only match enclosures that are actually audio - some feeds (e.g.
        # beehiiv newsletters) attach a cover-image enclosure, which is not
        # a podcast episode and must not be mistaken for one.
        if (link.get("type") or "").startswith("audio/"):
            return link.get("href")
    return None


_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def strip_html(html: str) -> str:
    """Minimal HTML->text: drop tags, collapse whitespace. Good enough for a
    digest that only needs the newsletter's words, not its markup - avoids
    spending tokens on raw HTML once this reaches the summarizing step."""
    # Block-level tags become line breaks so paragraphs don't run together.
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|br)\s*>", "\n", html)
    text = _TAG_RE.sub("", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def entry_body(entry) -> str:
    # Prefer the full HTML/text content over `summary`, which some feeds
    # (e.g. beehiiv newsletters) leave empty and put the entire issue body
    # in `content` instead.
    content = entry.get("content")
    if content:
        value = content[0].get("value", "")
        if value:
            return strip_html(value)
    return entry.get("summary", "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="feed URL")
    parser.add_argument(
        "--since-days", type=float, default=3, help="only include entries newer than this many days"
    )
    parser.add_argument(
        "--seen-ids", default="", help="comma-separated entry ids to exclude (already processed)"
    )
    parser.add_argument(
        "--title-regex", default=None, help="only include entries whose title matches this regex (case-insensitive)"
    )
    parser.add_argument(
        "--max-items", type=int, default=None, help="only return the N newest matching entries"
    )
    args = parser.parse_args()

    seen = {s.strip() for s in args.seen_ids.split(",") if s.strip()}
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    title_re = re.compile(args.title_regex, re.IGNORECASE) if args.title_regex else None

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

        title = entry.get("title", "")
        if title_re and not title_re.search(title):
            continue

        items.append(
            {
                "id": eid,
                "title": title,
                "link": entry.get("link", ""),
                "published": ts.isoformat() if ts else None,
                "summary": entry_body(entry),
                "audio_url": entry_audio_url(entry),
            }
        )

    # Entries come back newest-first from feedparser already; --max-items
    # just caps that, it doesn't re-sort.
    if args.max_items is not None:
        items = items[: args.max_items]

    print(json.dumps(items, indent=2))


if __name__ == "__main__":
    main()
