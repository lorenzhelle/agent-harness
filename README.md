# lors-plugin

Personal Claude Code plugin with custom skills for my workspace.

## Skills

| Skill | Description |
|---|---|
| `daily-note` | Creates today's Obsidian daily note with Jira tickets, Outlook calendar, backlog triage, and inbox review |
| `close-day` | Plays back today's daily note into project files — meeting notes, people, TODOs |
| `close-project` | Structured PARA project closing ceremony: distill, clean, archive |
| `youtube-summary` | Fetches a YouTube video's transcript and summarizes it |
| `ai-briefing` | Fetches new items from configured YouTube channels/podcasts/newsletters, filters for relevance, transcribes and summarizes into a digest |
| `token-audit` | Audits what's consuming tokens in Claude Code requests — system prompt, tools/MCP schemas, catalog — cross-referenced against real usage history |

## Install this plugin in Claude Code

### Step 1 — Add the marketplace

This repo doubles as its own marketplace. Add it once:

```shell
/plugin marketplace add lorenzhelle/claude-plugin
```

### Step 2 — Install the plugin

```shell
/plugin install lors-plugin@lors-plugins
```

Choose **User scope** to have the skills available in all your projects.

### Step 3 — Activate

```shell
/reload-plugins
```

Skills are now available as `/lors-plugin:daily-note`, `/lors-plugin:close-day`, etc.

---

## Marketplace structure

The `.claude-plugin/plugin.json` at the repo root describes the plugin.
Claude Code discovers it automatically when you add the repo as a marketplace.

To browse available plugins before installing:

```shell
/plugin
```

Go to the **Discover** tab and find `lors-plugin` in the list.
