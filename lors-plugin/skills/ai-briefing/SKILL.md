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
- **Feeds** (podcast/newsletter): same script, pointed at the feed's `url`. Pass through
  whatever `since_days`, `title_regex`, and `max_items` are set on that feed's entry in
  `config.json` (as `--since-days`, `--title-regex`, `--max-items`) — these push filtering
  into the script instead of costing LLM reasoning over items you'd drop anyway. E.g. the
  Programmierbar feed is configured with `title_regex: "^News AI\\b"` and `max_items: 1` to
  fetch only the latest AI-focused news episode (skips general-tech "News ..." episodes and
  "Deep Dive"/interview episodes entirely — those would otherwise burn a full transcription
  on content that isn't the AI news Lorenz wants). Use `--seen-ids` from
  `state.json seen['feed:<url>']` as before.

Each call prints a JSON list of new items: `{id, title, link, published, summary, audio_url}`.
`audio_url` is only present for podcast episodes (feed entries with an audio enclosure).
Collect all items, tagged with their source name and type (youtube/podcast/newsletter).

If everything returns empty, tell the user nothing new was found and stop — don't write an
empty digest.

### 3. Relevance pass (YouTube only)

Feed-level filtering (step 2) already narrowed podcasts/newsletters to at most one candidate
each, so this pass is really only needed for the YouTube channels, which can return many
items per run. Look at titles + summaries only (no transcription yet). Using general AI/ML
judgment plus the notes in `interests.md`, decide which videos are actually worth a full
watch. Be selective — most items should get dropped here to keep transcription cost/time
down. Briefly tell the user which items you picked and which you skipped and why, in case
they want to correct you (also captured in step 8's feedback pass).

Mark every item considered here (picked or skipped) for step 7's state update — skipped
items must not resurface in the next run just because they weren't included in a digest.

### 4. Get full content + per-item extraction, delegated to a subagent per item

Do NOT fetch a transcript into this conversation and then summarize it here — a raw
transcript (YouTube video or full podcast episode) is hundreds to over a thousand lines and
is only useful for producing a handful of bullets; reading it into the main context wastes
most of those tokens. Instead, for each selected item, spawn one subagent (Agent tool,
general-purpose type; independent items can run in parallel in a single message) and give it:

- the fetch command to run itself:
  - **YouTube video**: `uv run /Users/lors/Repos/claude-plugin/lors-plugin/skills/youtube-summary/fetch_transcript.py "<video link>" --with-timestamps`
    (the timestamps are for step 5's slide/diagram callouts, not shown in the digest itself)
  - **Podcast episode**: `uv run /Users/lors/Repos/claude-plugin/lors-plugin/skills/ai-briefing/transcribe_podcast.py "<audio_url>"`
    (first run downloads faster-whisper model weights — expect a delay the first time)
  - **Newsletter**: use the feed entry's `summary` field directly (pass it in the prompt —
    it's usually the full issue text already, no fetch needed). If it looks truncated, have
    the subagent WebFetch the entry's `link` instead.
- the item's title/link/context and a note on what Lorenz cares about (from `interests.md`)
- instructions to return ONLY a short markdown summary (a few bullets, pulling out points
  specifically relevant to Lorenz) as its final message — not the transcript, not a
  play-by-play of what it ran.

The subagent's transcript never enters your context; only its returned bullets do. This is
the main lever for keeping this skill's token cost down — don't skip it even for a single
item.

For YouTube videos, tell the subagent: if the transcript references a slide/diagram/chart in
a way where the visual clearly carried information the words don't (e.g. "as you can see
here", a benchmark chart, an architecture diagram, code on screen) and the transcript has
timestamps, note the approximate timestamp and a one-line description of what's likely shown
in its summary, formatted as a link Lorenz can click: `<link>&t=<seconds>s`. This doesn't
require downloading video or extracting frames — just flag the moment so Lorenz can jump to
it himself if a bullet alone doesn't do it justice. Don't do this for every timestamp
mentioned, only ones where the summary would otherwise lose real information.

### 5. Merge into one digest

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

### 6. Update state

For every item *returned by fetch_feed.py this run* — not just the ones that ended up in
the digest — append its id to `state.json`'s `seen["youtube:<channel_id>"]` or
`seen["feed:<url>"]` list (create the key if missing, trim to the most recent ~200 ids per
source). This includes items dropped in step 3's relevance pass: they were already
evaluated, so they must not be re-fetched and re-evaluated next run. Set `last_run` to now.
Write `state.json` back.

### 7. Ask for feedback

Show the user the digest (or its path). Ask what was relevant and what wasn't. Append their
answer as a new dated bullet to `interests.md` so future relevance passes improve.

## Adding sources

Edit `config.json` directly:
- New YouTube channel: add `{ "name": "...", "channel_id": "UCxxxxxxx" }` to
  `youtube_channels`. Find the channel ID from the channel's page source
  (search for `"channelId"`) or a tool like commentpicker.com/youtube-channel-id.php.
- New feed: add `{ "name": "...", "url": "https://...", "type": "podcast" | "newsletter" }`
  to `feeds`. `type` is just for grouping the digest — `fetch_feed.py` treats both the same
  and auto-detects audio enclosures regardless of the declared type. Optional fields, all
  forwarded straight to `fetch_feed.py`:
  - `since_days` — override the default 3-day lookback window (a fixed weekly cadence would
    need ~10 days of slack to be safe against a late episode; Programmierbar is set to 10.
    Doppelgänger publishes more irregularly — sometimes skipping a week or two — so it's set
    to 21 to avoid a false "nothing new").
  - `title_regex` — only consider entries whose title matches this regex. Use for feeds that
    mix formats (e.g. Programmierbar alternates weekly between "News AI ..." episodes and
    plain "News ..." general-tech episodes, plus one-off "Deep Dive"/"Spezialfolge"
    interviews — `title_regex: "^News AI\\b"` keeps only the AI-focused news episodes) to
    pull just the format you actually want, at zero LLM cost.
  - `max_items` — cap how many of the newest matching entries come back, e.g. `1` for "just
    the latest issue, if it's new."

## Troubleshooting

**0 items from a source** — normal if that channel/feed hasn't published within its
`since_days` window (3 days by default, or whatever's set in `config.json`).

**Podcast feed has no `audio_url` on an entry** — some podcast feeds put the audio link
elsewhere in nonstandard tags; treat that entry like a newsletter (use `summary`/`link`) or
tell the user the feed needs a manual check.

**faster-whisper is slow** — first invocation downloads model weights; also long episodes
take real time to transcribe locally. Default model is `small`; pass `--model tiny` for
faster/lower-quality, or `--model medium`/`large-v3` for better quality if you have the time.
Since transcription now runs inside a subagent (step 4), this cost no longer shows up as
main-conversation latency/tokens — only as wall-clock time for that subagent.

**YouTube feed 0 items** — the channel feed only includes the last 15 videos; if a channel
posts less than once every few days that's expected.
