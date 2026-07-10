---
name: ai-briefing
description: >
  Use this skill when the user wants to run, set up, or configure the AI
  knowledge briefing pipeline. Trigger on "ai briefing", "knowledge pipeline",
  "run my ai briefing", "configure my AI briefing", "morning briefing",
  "daily AI summary", "KI briefing", or when the user asks about the
  automated AI news digest from YouTube/podcasts/newsletters.
version: 2.0.0
---

# AI Briefing Skill

Fetches new items from configured YouTube channels and RSS feeds (podcasts,
newsletters), picks the relevant ones, transcribes/reads them, summarizes,
and writes a single digest markdown file. Runs on demand — no external
automation tool (n8n etc.) involved, this skill does the whole pipeline
as a reasoning + script-calling workflow.

Files in this skill's directory:
- `config.json` — the list of YouTube channels and feeds to check
- `state.json` — last run timestamp + ids already included in a past digest
- `interests.md` — learned notes on what's relevant, updated from your feedback
- `fetch_feed.py` — fetches new entries from one feed/channel
- `transcribe_podcast.py` — downloads + locally transcribes a podcast episode
- `output/` — generated digests, one per run, e.g. `output/2026-07-10.md`

## Workflow

### 1. Load config + state

Read `config.json`, `state.json`, and `interests.md` in this skill's directory. `state.json`
is gitignored (it's runtime data) — if it doesn't exist yet, treat it as
`{"last_run": null, "seen": {}}` and create it in step 7.

### 2. Fetch candidates

For each entry in `config.json`:

- **YouTube channels**: build the feed URL
  `https://www.youtube.com/feeds/videos.xml?channel_id=<channel_id>` and run:
  ```bash
  uv run /Users/lors/Repos/claude-plugin/lors-plugin/skills/ai-briefing/fetch_feed.py \
    --url "https://www.youtube.com/feeds/videos.xml?channel_id=<channel_id>" \
    --since-days 3 \
    --seen-ids "<comma-separated ids from state.json seen['youtube:<channel_id>']>"
  ```
- **Feeds** (podcast/newsletter): same script, pointed at the feed's `url`, with
  `--seen-ids` from `state.json seen['feed:<url>']`.

Each call prints a JSON list of new items: `{id, title, link, published, summary, audio_url}`.
`audio_url` is only present for podcast episodes (feed entries with an audio enclosure).
Collect all items, tagged with their source name and type (youtube/podcast/newsletter).

If everything returns empty, tell the user nothing new was found in the last 3 days and stop
— don't write an empty digest.

### 3. Relevance pass

Look at titles + summaries only (no transcription yet). Using general AI/ML judgment plus
the notes in `interests.md`, decide which items are actually worth a full read/listen. Be
selective — most items should get dropped here to keep transcription cost/time down. Briefly
tell the user which items you picked and which you skipped and why, in case they want to
correct you (also captured in step 8's feedback pass).

### 4. Get full content for selected items

- **YouTube video**: fetch its transcript via the youtube-summary skill's script:
  ```bash
  uv run /Users/lors/Repos/claude-plugin/lors-plugin/skills/youtube-summary/fetch_transcript.py "<video link>"
  ```
- **Podcast episode**: transcribe the audio locally:
  ```bash
  uv run /Users/lors/Repos/claude-plugin/lors-plugin/skills/ai-briefing/transcribe_podcast.py "<audio_url>"
  ```
  First run downloads faster-whisper model weights — expect a delay the first time.
- **Newsletter**: use the feed entry's `summary` field directly (usually the full issue
  text). If it looks truncated, WebFetch the entry's `link` for the full content.

### 5. Per-item extraction

For each selected item, pull out the points specifically relevant to Lorenz and write a
short summary (a few bullets). This is a normal reasoning step, no script needed.

### 6. Merge into one digest

Combine all per-item summaries into a single markdown file at
`output/<YYYY-MM-DD>.md` (today's date), grouped by source type:

```markdown
# AI Briefing – <weekday>, <full date>

## YouTube
### <video title>
- ...

## Podcasts
### <episode title>
- ...

## Newsletters
### <issue title>
- ...
```

If a group has no items, omit that section entirely.

### 7. Update state

For every item included in the digest, append its id to `state.json`'s
`seen["youtube:<channel_id>"]` or `seen["feed:<url>"]` list (create the key if missing, trim
to the most recent ~200 ids per source). Set `last_run` to now. Write `state.json` back.

### 8. Ask for feedback

Show the user the digest (or its path). Ask what was relevant and what wasn't. Append their
answer as a new dated bullet to `interests.md` so future relevance passes improve.

## Adding sources

Edit `config.json` directly:
- New YouTube channel: add `{ "name": "...", "channel_id": "UCxxxxxxx" }` to
  `youtube_channels`. Find the channel ID from the channel's page source
  (search for `"channelId"`) or a tool like commentpicker.com/youtube-channel-id.php.
- New feed: add `{ "name": "...", "url": "https://...", "type": "podcast" | "newsletter" }`
  to `feeds`. `type` is just for grouping the digest — `fetch_feed.py` treats both the same
  and auto-detects audio enclosures regardless of the declared type.

## Troubleshooting

**0 items from a source** — normal if that channel/feed hasn't published in the last 3 days.

**Podcast feed has no `audio_url` on an entry** — some podcast feeds put the audio link
elsewhere in nonstandard tags; treat that entry like a newsletter (use `summary`/`link`) or
tell the user the feed needs a manual check.

**faster-whisper is slow** — first invocation downloads model weights; also long episodes
take real time to transcribe locally. Default model is `small`; pass `--model tiny` for
faster/lower-quality, or `--model medium`/`large-v3` for better quality if you have the time.

**YouTube feed 0 items** — the channel feed only includes the last 15 videos; if a channel
posts less than once every few days that's expected.
