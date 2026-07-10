#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["faster-whisper", "requests"]
# ///
"""
transcribe_podcast.py - Downloads a podcast episode's audio and transcribes it
locally with faster-whisper, printing the transcript as plain text.

Usage:
    python transcribe_podcast.py <audio_url> [--model small]
"""

import argparse
import os
import sys
import tempfile

import requests
from faster_whisper import WhisperModel


USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def download_audio(url: str, dest_path: str) -> None:
    # Some podcast hosts (e.g. Buzzsprout) return 403 for the default
    # python-requests user agent; a browser-like one works.
    headers = {"User-Agent": USER_AGENT}
    with requests.get(url, headers=headers, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 16):
                f.write(chunk)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_url", help="direct URL to the episode's audio file")
    parser.add_argument(
        "--model", default="small", help="faster-whisper model size (tiny/base/small/medium/large-v3)"
    )
    args = parser.parse_args()

    fd, tmp_path = tempfile.mkstemp(suffix=".audio")
    os.close(fd)

    try:
        try:
            download_audio(args.audio_url, tmp_path)
        except requests.RequestException as e:
            print(f"error: failed to download audio from {args.audio_url}: {e}", file=sys.stderr)
            sys.exit(1)

        model = WhisperModel(args.model, device="auto", compute_type="auto")
        segments, _info = model.transcribe(tmp_path, beam_size=5)

        for segment in segments:
            print(segment.text.strip())
    finally:
        os.remove(tmp_path)


if __name__ == "__main__":
    main()
