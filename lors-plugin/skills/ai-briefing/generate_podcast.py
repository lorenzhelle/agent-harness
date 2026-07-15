#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
generate_podcast.py - Turns a plain-text podcast script into a single-narrator
MP3 via ElevenLabs text-to-speech, chunking long input and concatenating the
resulting audio with ffmpeg.

Usage:
    python generate_podcast.py --list-voices
    python generate_podcast.py <input.txt> <output.mp3> --voice-id <id> \
        [--model eleven_multilingual_v2]

Requires the ELEVENLABS_API_KEY environment variable and a local ffmpeg
(installed automatically via `brew install ffmpeg` if missing on macOS).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import requests

API_BASE = "https://api.elevenlabs.io/v1"
MAX_CHUNK_CHARS = 2000


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        print(
            "error: ELEVENLABS_API_KEY is not set. Set it in your shell profile, "
            "e.g. `export ELEVENLABS_API_KEY=...`",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


def list_voices() -> None:
    response = requests.get(f"{API_BASE}/voices", headers={"xi-api-key": api_key()}, timeout=30)
    response.raise_for_status()
    voices = response.json().get("voices", [])
    print(json.dumps([{"id": v.get("voice_id"), "name": v.get("name"), "labels": v.get("labels")} for v in voices], indent=2))


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on paragraph, then sentence boundaries, keeping each chunk under
    max_chars without cutting mid-sentence."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks = []
    current = ""

    def flush():
        nonlocal current
        if current:
            chunks.append(current.strip())
            current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue

        # Paragraph itself may be too long for the running chunk (or even on
        # its own) - fall back to sentence-level splitting.
        flush()
        sentences = re.split(r"(?<=[.!?])\s+", para)
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
            else:
                flush()
                current = sentence
    flush()
    return chunks


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg"):
        return
    if not shutil.which("brew"):
        print(
            "error: ffmpeg is required but not installed, and `brew` is not available "
            "to install it. Install ffmpeg manually and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("ffmpeg not found - installing via `brew install ffmpeg`...", file=sys.stderr)
    subprocess.run(["brew", "install", "ffmpeg"], check=True)
    if not shutil.which("ffmpeg"):
        print("error: ffmpeg installation via brew did not succeed.", file=sys.stderr)
        sys.exit(1)


def synthesize_chunk(text: str, voice_id: str, model_id: str, out_path: str) -> None:
    response = requests.post(
        f"{API_BASE}/text-to-speech/{voice_id}",
        headers={"xi-api-key": api_key(), "Content-Type": "application/json"},
        json={"text": text, "model_id": model_id},
        timeout=120,
    )
    if not response.ok:
        print(
            f"error: ElevenLabs request failed ({response.status_code}): {response.text}",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(out_path, "wb") as f:
        f.write(response.content)


def concat_audio(chunk_paths: list[str], output_path: str) -> None:
    fd, list_path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w") as f:
            for path in chunk_paths:
                f.write(f"file '{path}'\n")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path],
            check=True,
            capture_output=True,
        )
    finally:
        os.remove(list_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-voices", action="store_true", help="list available ElevenLabs voices and exit")
    parser.add_argument("input", nargs="?", help="path to the input text script")
    parser.add_argument("output", nargs="?", help="path to write the output MP3")
    parser.add_argument("--voice-id", help="ElevenLabs voice id")
    parser.add_argument("--model", default="eleven_multilingual_v2", help="ElevenLabs model id")
    args = parser.parse_args()

    if args.list_voices:
        list_voices()
        return

    if not args.input or not args.output or not args.voice_id:
        parser.error("input, output, and --voice-id are required unless --list-voices is passed")

    ensure_ffmpeg()

    with open(args.input, encoding="utf-8") as f:
        text = f.read()

    chunks = chunk_text(text)
    if not chunks:
        print("error: input file has no text to synthesize", file=sys.stderr)
        sys.exit(1)

    tmp_dir = tempfile.mkdtemp(prefix="podcast_chunks_")
    try:
        chunk_paths = []
        for i, chunk in enumerate(chunks):
            chunk_path = os.path.join(tmp_dir, f"chunk_{i:03d}.mp3")
            synthesize_chunk(chunk, args.voice_id, args.model, chunk_path)
            chunk_paths.append(chunk_path)

        if len(chunk_paths) == 1:
            shutil.move(chunk_paths[0], args.output)
        else:
            concat_audio(chunk_paths, args.output)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
