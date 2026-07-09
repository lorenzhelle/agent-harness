#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["youtube-transcript-api"]
# ///
"""
fetch_transcript.py - Fetches the transcript for a YouTube video and prints it as plain text.

Usage:
    python fetch_transcript.py <youtube_url_or_id> [--lang en,de]
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
        print(snippet.text)


if __name__ == "__main__":
    main()
