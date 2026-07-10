---
name: youtube-summary
description: >
  Use this skill when the user gives a YouTube URL and wants a transcript and/or
  summary of the video content. Trigger on "summarize this youtube video",
  "transcript of this video", "fasse das video zusammen", "youtube summary",
  or when the user pastes a youtube.com/youtu.be link and asks what it's about.
version: 1.0.0
---

# YouTube Summary Skill

Fetches the transcript of a YouTube video and produces a summary. No download,
no whisper transcription - uses the video's existing captions (auto-generated
or manual) via `youtube-transcript-api`.

## Workflow

### 1. Extract the video URL

Take the YouTube URL (or bare video ID) from the user's message.

### 2. Fetch the transcript

```bash
uv run /Users/lors/Repos/claude-plugin/lors-plugin/skills/youtube-summary/fetch_transcript.py "<url>"
```

Prints the transcript as plain text (one line per caption snippet, no
timestamps by default - pass `--with-timestamps` to prefix each line with its
start time in seconds, e.g. `[83s] ...`, useful when you need to point back at
a specific moment in the video). Default language preference is `en,de` -
pass `--lang` to override, e.g. `--lang de,en`.

If the script errors with "no transcript available": tell the user the video
has no captions (disabled or none exist) and stop - do not fall back to audio
download/transcription.

### 3. Summarize

Read the transcript output and produce a summary directly (no extra tool
needed - this is a normal reasoning step). Default to:

- 3-6 bullet points of the core content
- Match the summary's language to the transcript's language, unless the user
  asked for a specific language

If the user only asked for "the transcript", skip summarizing and just return
the raw text.

### 4. Long videos

The script prints the full transcript regardless of length. For very long
videos, read it in full before summarizing rather than truncating - the
transcript is plain text and cheap to process.
