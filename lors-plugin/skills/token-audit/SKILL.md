---
name: token-audit
description: >
  Analyze what's consuming tokens in Claude Code's requests to the configured
  LiteLLM/Anthropic endpoint — system prompt, tool/MCP schemas, memory, message
  history, and per-MCP-server/per-skill cost cross-referenced against real usage
  history (never-used vs. recently-used, 7/30-day recency buckets). Use when the
  user asks what's eating their tokens, wants a token breakdown of their setup,
  wants to know which MCP servers or skills are unused/stale, or wants to audit
  context/tool overhead.
version: 1.0.0
---

# Token Audit

## Overview

Fires a minimal `claude -p "hey"` probe request with Claude Code's built-in
`OTEL_LOG_RAW_API_BODIES` logging enabled, captures the **exact raw request
body** Claude Code sent to `ANTHROPIC_BASE_URL` (system prompt blocks, every
tool/MCP schema, message history), then gets an exact token count for each
section from the endpoint's own tokenizer and reports a sorted breakdown.

This does NOT estimate tokens (chars/4 heuristics) — it uses the real
tokenizer via `/v1/messages/count_tokens` on the user's own endpoint, so
counts match what they're actually billed for.

## Running it

```bash
uv run /Users/lors/Repos/claude-plugin/lors-plugin/skills/token-audit/scripts/analyze.py
```

Requires `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` (or
`ANTHROPIC_API_KEY`) in the environment — same values Claude Code itself
uses. In this setup they're set via `~/.claude/settings.json`'s `env`
block, so the Bash tool already has them and no extra setup is needed.
Takes ~15-30s for the audit itself (one real `claude -p` turn), plus
another ~15-30s if any heavy discretionary tools are found, since the
script fires a second verification probe to confirm they're actually
removable via `permissions.deny` before suggesting it.

## What it reports

A breakdown into four sections, each sorted heaviest-first:

- **system** — the base agent system prompt (harness instructions +
  CLAUDE.md + memory + environment block), billing/attribution header, SDK
  identity line
- **tools** — every tool and MCP tool schema individually, by name. This is
  usually the biggest chunk — each enabled plugin/MCP server adds its full
  tool schema to every request regardless of whether it's used that turn.
- **messages** — the actual conversation turn only (the user prompt +
  system-reminder wrapper); the catalog reminder below is split out
  separately so it doesn't get counted as one opaque blob.
- **catalog** — the mid-conversation "Available agent types..."
  system-reminder Claude Code injects whenever the Agent tool is present,
  broken into its three independently-toggleable parts: the fixed
  agent-types prose, **one row per connected MCP server** (its per-server
  instructions block), and **one row per registered skill** (its one-line
  catalog entry — name + description). This split is what makes the MCP
  SERVERS and SKILLS sections below possible.

Plus a grand total, a top-10 heaviest-items list across all sections, a
**SUGGESTED FIXES** block for heavy tools, and **MCP SERVERS** /
**SKILLS** sections (see below) that check *every* connected server and
registered skill against usage history regardless of how small its
individual token cost is.

## Suggested fixes: cutting real token cost, verified empirically

Every request-level tool listed in the audit that isn't a core tool (Bash,
Read, Edit, Write, Agent, Skill, WebFetch, WebSearch, NotebookEdit,
AskUserQuestion, plan-mode tools) and contributes >1% of total tokens gets a
concrete fix suggestion, auto-verified with a second live probe request.

**Key finding, confirmed empirically** (not from docs alone — verified by
diffing two `claude -p` probe requests, one with `permissions.deny` set, one
without): a **bare tool name** in `settings.json`'s `permissions.deny` array
removes that tool's schema from the request entirely — Claude never sees
it, and its tokens are gone from every request. This is different from a
scoped/pattern deny rule like `"Bash(rm *)"`, which leaves the tool's full
schema in every request and only blocks that specific call at execution
time — **zero token savings** from scoped rules.

```json
{"permissions": {"deny": ["ToolName"]}}
```

Specific known mechanisms beyond generic deny:
- **`Workflow`** (multi-agent orchestration; often one of the single
  heaviest tools, ~20% of a fresh session in testing): disable via
  `"disableWorkflows": true` in settings.json, `CLAUDE_CODE_DISABLE_WORKFLOWS=1`
  env var, or `/config` → "Dynamic workflows" toggle — any of these is
  equivalent to (and preferred over) denying it by name.
- **MCP-namespaced tools** (`mcp__<server>__<tool>`): the fix is disabling
  the MCP server/plugin behind them (check `enabledPlugins` in
  settings.json, or run `/mcp` to identify which server owns a given tool),
  not denying each tool individually — a server usually exposes several
  tools that all disappear together once the server is off.
- Everything else (e.g. `DesignSync`, `Cron*`, `Task*`, `EnterWorktree`/
  `ExitWorktree`, `ScheduleWakeup`, `LSP`, `ReportFindings`, `SendMessage`):
  no dedicated flag found in Claude Code's docs — bare-name
  `permissions.deny` is the mechanism.

The script fires a live verification probe (a second `claude -p` call with
a `--settings` override setting `permissions.deny` on the flagged tools) and
tags each suggestion `[VERIFIED removable]` if the tool actually disappeared
from that second request's tool list — don't trust the suggestion blindly
if it's *not* tagged verified.

**Trade-off to flag to the user, not just cost**: these are real features
(scheduled tasks, worktree isolation, workflows, cross-agent messaging,
design sync). Denying a tool removes the *capability*, not just its idle
token cost — confirm the user doesn't rely on it before applying a
suggested deny rule.

## Usage-history check: is this actually safe to disable?

For every heavy tool flagged above, the script scans every local session
transcript (`~/.claude/projects/*/*.jsonl`) for actual `tool_use` calls to
that tool — count and most-recent timestamp — and splits the final
recommendation into two buckets:

- **Safe-to-disable now** — tools with zero calls across all local session
  history. The script prints a ready-to-paste `permissions.deny` snippet
  for just this bucket, with the total tokens it would save.
- **Used recently — confirm first** — tools that were actually called
  (with count + "N days ago"). Still real token cost, but disabling one of
  these removes a capability the user has actively relied on — flag it,
  don't auto-recommend it.

This is a best-effort local scan (skips unparseable lines/files rather than
failing), and it can only see history recorded on this machine — a tool
unused here might still be used in other environments/machines the user
has. Say that caveat out loud rather than treating "never called locally"
as certainty.

## MCP SERVERS and SKILLS sections: every server/skill, not just the heavy ones

Individual MCP servers and skills are usually cheap (tens to a few hundred
tokens each for their catalog entry/instructions block) — too small to
clear the >1%-of-total bar the tool-level SUGGESTED FIXES section uses. But
across a dozen+ registered skills or several MCP servers, that adds up, and
"cheap per-item" isn't the same as "worth keeping." So these two sections
check every one of them against usage history unconditionally, independent
of token weight:

- **MCP SERVERS** — the same `mcp_usage` scan (aggregated per server, since
  that's the actual disable granularity — a server's tools disappear
  together when the plugin is turned off) drives a `never used` /
  `used Nx, last <recency>` label per connected server, alongside its
  actual token cost (its instructions block, split out from the catalog
  section above). `never used` servers get a concrete fix pointing at the
  matching `enabledPlugins` key in settings.json (resolved automatically
  where possible from the `plugin:<name>:<name>` header format) or `/mcp`.
- **SKILLS** — same idea, keyed by the `skill` argument passed to the
  `Skill` tool in transcript history (so `plugin-name:skill-name` and
  bare `skill-name` are both matched correctly). Recency is bucketed into
  never / within 7 days / 8-30 days / 30+ days ("stale") rather than just a
  raw day count, since "used once 45 days ago" is a different signal than
  "used yesterday."

Important nuance for skills specifically: a skill's *listed* cost here is
tiny (just its one-line catalog entry — name + description — since the
full `SKILL.md` body only loads into context on invocation). Don't
overstate the savings from disabling an individual skill; the real lever
is disabling the *plugin* that bundles several unused skills together, or
trimming an unusually long description in a skill's frontmatter (that one
line is what's actually costing tokens on every request).

## Known quirk this script works around

Some LiteLLM deployments that route through Vertex AI / Bedrock passthrough
(rather than native Anthropic passthrough) have a `count_tokens` endpoint
that silently ignores the `system` and `tools` fields and only tokenizes
`messages` — returning a constant regardless of system/tool content. The
script detects this at startup (pads `system` and checks if the count
changes) and, if detected, counts every section by wrapping its raw text as
a standalone user message instead (subtracting a measured per-request
overhead constant). This is still an exact real-tokenizer count — just
measured through a workaround path — not a heuristic estimate. It prints a
note to stderr when this fallback is active.

## Required final step: your own recommendation

The script's output is raw data plus mechanical suggestions (threshold cuts,
usage lookups) — it doesn't weigh trade-offs. **Always end your response
with your own synthesized recommendation**, not a repeat of the script's
printed suggestions. Concretely:

1. Pick the **2-4 highest-impact, lowest-risk actions** across everything
   the script surfaced — heavy unused tools, unused/stale MCP servers,
   unused skills/plugins. Prioritize by token impact, but downgrade
   anything in the "used recently" bucket even if it's large — that's a
   capability trade-off for the user to make, not a free win.
2. State the **combined token/percentage savings** of your top picks
   together, not just per-item numbers — that's what makes the
   recommendation actionable ("do these 3 things, save 45% total").
3. Explicitly separate **"just do this" (never used, verified removable,
   no downside)** from **"consider this" (some usage, or judgment call —
   e.g. a stale-but-not-dead skill, or a small plugin bundling a few
   unused skills alongside ones actually used)**. Don't collapse this
   distinction — the user has acted on "safe-to-disable now" suggestions
   before without hesitation, but wants recently-used items flagged for
   their own decision.
4. If nothing meaningful is left to cut (e.g. after a previous round of
   fixes already applied), say so plainly rather than manufacturing a
   recommendation — "your setup is now lean, no further action needed" is
   a valid and correct answer.

## Interpreting results / follow-up actions

- If **tools** dominates (commonly 70-85% of a fresh session's first-turn
  tokens): that's what the SUGGESTED FIXES block above is for — walk the
  user through the specific deny rules or plugin toggles it verified,
  starting with the heaviest entries.
- If **system** is large: check for CLAUDE.md bloat or oversized memory
  files (`~/.claude/projects/*/memory/`).
- If a specific **catalog** entry stands out: the agent-types prose row is
  fixed overhead from having the Agent tool enabled at all — not
  per-message trimmable. But a heavy `mcp:*` or `skill:*` row IS
  actionable — check it against the MCP SERVERS / SKILLS sections' usage
  labels before suggesting a fix.
- Walk the **MCP SERVERS** and **SKILLS** sections even when nothing there
  crossed the tool-level 1% threshold — a server or skill marked
  `never used` or `30+ days ago (stale)` is a plugin worth asking the user
  about, even at a modest token cost, since it compounds across every
  request.
- Every count here is *input* tokens for a **fresh** session with no cache.
  Cross-reference against `rtk gain` (the user's token-savings CLI) for
  actual historical spend across real sessions, since real sessions benefit
  from prompt caching on the system+tools block after turn 1.
