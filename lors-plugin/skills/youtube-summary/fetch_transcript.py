#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["youtube-transcript-api"]
# ///
"""
fetch_transcript.py - Fetches the transcript for a YouTube video and prints it as plain text.

Usage:
    python fetch_transcript.py <youtube_url_or_id> [--lang en,de] [--with-timestamps]

--with-timestamps prefixes each line with its start time in seconds, e.g.
"[83s] some caption text" - useful when the caller needs to point back at a
specific moment in the video (e.g. a slide/diagram the words alone don't
capture), without downloading the video or extracting frames.
"""

import argparse
import re
import sys

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)


def extract_video_id(url_or_id: str) -> str:
    patterns = [
        r"(?:v=|/videos/|embed/|youtu\.be/|/v/|/shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url_or_id):
        return url_or_id
    raise ValueError(f"could not extract video id from: {url_or_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="YouTube URL or video ID")
    parser.add_argument(
        "--lang", default="en,de", help="comma-separated preferred language codes"
    )
    parser.add_argument(
        "--with-timestamps",
        action="store_true",
        help="prefix each line with its start time in seconds, e.g. '[83s] ...'",
    )
    args = parser.parse_args()

    video_id = extract_video_id(args.url)
    languages = [lang.strip() for lang in args.lang.split(",")]

    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=languages)
    except (TranscriptsDisabled, NoTranscriptFound) as e:
        print(f"error: no transcript available for {video_id}: {e}", file=sys.stderr)
        sys.exit(1)
    except VideoUnavailable as e:
        print(f"error: video unavailable {video_id}: {e}", file=sys.stderr)
        sys.exit(1)

    for snippet in transcript:
        if args.with_timestamps:
            print(f"[{int(snippet.start)}s] {snippet.text}")
        else:
            print(snippet.text)


if __name__ == "__main__":
    main()
