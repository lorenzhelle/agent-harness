---
name: ai-briefing
description: >
  Use this skill when the user wants to set up, configure, or troubleshoot
  the nightly AI knowledge briefing pipeline. Trigger on "ai briefing",
  "knowledge pipeline", "set up the n8n briefing", "configure my AI briefing",
  "morning briefing", "daily AI summary", "KI briefing einrichten", or when
  the user asks about the automated AI news digest that writes to Obsidian.
version: 1.0.0
---

# AI Briefing Skill

Nightly n8n workflow that fetches AI news from YouTube, Reddit, newsletters,
and podcasts — summarizes via Claude — and writes a markdown note directly
into the Obsidian vault. Runs at 07:05 every morning.

Sources: YouTube channel RSS feeds, Reddit (r/MachineLearning etc.), any
Substack/Beehiw/podcast RSS feed. Claude (claude-opus-4-8) synthesizes a
~400-word briefing note.

The workflow JSON lives at:
`lors-plugin/skills/ai-briefing/n8n-workflow.json`

## Setup Workflow

### 1. Import the workflow into n8n

Open n8n → **Workflows** → **⋯ menu** → **Import from JSON** → paste the
contents of `n8n-workflow.json` (or upload the file directly).

### 2. Configure the `⚙️ Config` node

Edit the **Set** node named `⚙️ Config` and fill in:

| Variable | Value |
|---|---|
| `anthropicApiKey` | Your Anthropic API key (get from console.anthropic.com) |
| `obsidianVaultPath` | Absolute path to the folder that should receive briefings, e.g. `/Users/lors/Documents/vault/AI Briefings` |
| `redditSubs` | Subreddits joined with `+`, e.g. `MachineLearning+artificial+LocalLLaMA` |

### 3. Add YouTube channels

For each YouTube channel to follow:
1. Duplicate one of the existing **YouTube: Channel N** nodes
2. Replace `REPLACE_CHANNEL_ID_N` in the URL with the actual channel ID
   - Find it in the channel's **About** page URL, or extract from any
     channel video URL: `youtube.com/channel/UCxxxxxxx`
3. Connect the new node to the **Merge: YouTube** node (second input)
   - For more than 2 channels, add additional Merge nodes chained together

### 4. Add newsletters and podcasts

Replace the placeholder URLs in **Newsletter RSS** and **Podcast RSS**:

- **Substack**: `https://yourname.substack.com/feed`
- **Beehiw**: check the newsletter's footer for the RSS link
- **Podcast**: find the RSS URL from Podchaser or the show's own website
  (Spotify doesn't expose RSS directly — use ListenNotes.com to look it up)
- **The Rundown AI**: `https://www.therundown.ai/rss`
- **TLDR AI**: `https://tldr.tech/ai/rss`

To add more sources, duplicate any RSS node and chain a new Merge node.

### 5. Create the Obsidian folder

Create the `AI Briefings` (or whatever you named it) folder in your vault
before the first run, otherwise the Write node will error.

Optional: embed today's briefing in your daily note template:

```
![[AI Briefings/AI Briefing - {{date:YYYY-MM-DD}}]]
```

### 6. Test manually

In n8n, click **Execute Workflow** on the `⚙️ Config` node to trigger a
manual run. All nodes should turn green. Check the **Obsidian vault** folder
for the new note.

### 7. Activate

Toggle the workflow to **Active** in n8n. It will fire at 07:05 local time
every morning.

## Troubleshooting

**No items found (0 items, skip Claude)** — normal if all sources are quiet
in the last 24h. The `Items Found?` IF node short-circuits gracefully.

**Reddit 429 / rate limit** — the public Reddit JSON API has a soft rate
limit. Add a few seconds of wait with a Wait node before the Reddit node, or
replace with a Reddit OAuth node if you have API credentials.

**YouTube 0 items** — YouTube RSS only includes the last 15 videos. If a
channel posts less than once a week, it's normal to get 0 results for today's
24h window.

**Claude API error** — check the `anthropicApiKey` value and that your
Anthropic account has credits.

**File write fails** — confirm the `obsidianVaultPath` exists and that n8n
has filesystem write permissions to that path (relevant for Docker installs:
mount the vault as a volume).

## Customising the briefing prompt

The summarization prompt is in the **Normalize & Build Prompt** Code node.
Edit the `promptText` template to change tone, format, or focus areas.
The default output format is:

```markdown
## 🤖 AI Briefing – Monday, July 10, 2026

### Key Developments
- ...

### Worth Reading
- ...

### Community Pulse
- ...

---
*47 items analyzed*
```
