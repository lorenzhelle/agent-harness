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

**Run this with the Bash tool directly — not as a background task and not
with Monitor.** The script sets `PYTHONUNBUFFERED=1` in its shebang so
stdout lines appear live in the Bash tool output. A background task +
Monitor adds no value here and causes duplicate/lost output.

**Handling the API key/token — never expose the value, only check presence.**
`analyze.py` itself never prints or logs the key: it's read once from the
environment and used only inside the `x-api-key` HTTP header sent directly
to the endpoint, never echoed to stdout/stderr. Keep it that way when
working on or around this skill:
- To confirm the credentials are set before running the audit, use:
  ```bash
  uv run /Users/lors/Repos/claude-plugin/lors-plugin/skills/token-audit/scripts/check_env.py
  ```
  It only prints `set`/`unset` per variable and exits non-zero if anything
  required is missing — never the actual value. Prefer this over
  `echo $ANTHROPIC_AUTH_TOKEN`, `env`, or `printenv`, none of which should
  be run here since they'd put the raw secret into context.
- If inspecting `~/.claude/settings.json`'s `env` block for troubleshooting,
  redact the token's value before showing it to the user or including it in
  your own output — show the key name and `"<redacted>"`, not the string.
- This applies to any new debug output added to the script too: don't add
  a print/log line that includes `API_KEY`/`HEADERS` (which contains the
  key) — log config presence/shape, never secret values.

## What it reports

A breakdown into four sections, each sorted heaviest-first:

- **system** — the base agent system prompt is never counted as one lump
  sum: it's split on its own top-level `# Header` lines into one row per
  section — typically **Harness**, **Session-specific guidance**,
  **Memory**, **Environment**, **Context management**, plus a leading
  **preamble** row for anything before the first header (the "you are an
  interactive agent..." identity line). Also reported separately: the
  billing/attribution header and the SDK identity line (each their own
  system block, not part of the main prompt). This is what lets you see,
  e.g., "Memory is 500 tokens because of an oversized memory file" instead
  of just "system is 1,450 tokens."
- **tools** — every tool and MCP tool schema individually, by name. This is
  usually the biggest chunk — each enabled plugin/MCP server adds its full
  tool schema to every request regardless of whether it's used that turn.
- **messages** — same per-header splitting applied to the conversation
  turn: the `<system-reminder>` wrapper Claude Code prepends to the first
  user message (memory recall, CLAUDE.md/RTK.md contents, `currentDate`,
  etc.) is split into one row per top-level header inside it, plus a
  separate row for the actual user-typed text. The mid-conversation agent
  catalog reminder is split out separately (see **catalog** below) so it
  doesn't get counted as one opaque blob either.
- **catalog** — the mid-conversation "Available agent types..."
  system-reminder Claude Code injects whenever the Agent tool is present,
  broken into its three independently-toggleable parts: the fixed
  agent-types prose, **one row per connected MCP server** (its per-server
  instructions block), and **one row per registered skill** (its one-line
  catalog entry — name + description). This split is what makes the MCP
  SERVERS and SKILLS sections below possible.

All of this splitting (system prompt, system-reminder wrapper, MCP/skill
catalog) uses the same underlying technique: find every top-level `# `/`## `
header in a block of text and cut it into one row per section between
headers. It's generic, so if Claude Code adds a new top-level section to
any of these blocks in a future version, it shows up as its own row
automatically — nothing in this skill needs updating for that.

Plus a grand total (with an inline note explaining the cold/uncached
vs. live context-window number distinction — see "Two totals" below),
a top-10 heaviest-items list across all sections, a **SUGGESTED FIXES**
block for heavy tools, **MCP SERVERS** / **SKILLS** sections (see below),
and a **TOOL SEARCH STATUS** block.

## Two totals — why the script's "Grand total" differs from live context-window %

The script's **TOTAL INPUT TOKENS** line counts a *cold, uncached* probe
request — every token priced at full input rate, no cache read. This is
the right number for "what does my setup cost per fresh session."

The live `claude -p` context-window percentage (and the Monitor event line
"Grand total: N tokens") can show a *larger* number because it includes
**cache-read tokens**, which count toward the context window but are billed
at a much lower rate. These are not the same metric. The script prints an
inline note below its grand total explaining this so you don't have to
look it up when the numbers don't match.

## Full overview file — every message/part sent in the probe request

Besides the terminal summary, the script writes a complete Markdown
overview to `output/<timestamp>.md` (next to `SKILL.md`, gitignored like
`ai-briefing`'s `output/` — see its `.gitkeep`) and prints the path at the
end of the run. Point the user at this file when they want to inspect
individual entries rather than just the aggregate percentages.

Unlike the terminal report (which only shows token/char counts per row),
the Markdown file adds a **content preview** column for every single
row — one table per section (SYSTEM, TOOLS, MESSAGES, CATALOG, CONFIG),
each row showing tokens, % of total, chars, name, and a truncated
single-line preview of the actual text/schema sent (e.g. the first ~200
chars of a tool's description, or the base system prompt's opening
lines). This is the artifact to open when the user asks "what exactly is
in this," not just "how many tokens" — the terminal report answers the
latter, this file answers the former. The same SUGGESTED FIXES / MCP
SERVERS / SKILLS sections from the terminal report are appended at the
end of the file too, so it's a self-contained record of one audit run.

Since it never truncates *which* rows are shown (every system block, every
tool, every message, every catalog/skill/MCP entry gets its own row), this
file is also the right thing to diff between two audit runs (e.g.
before/after applying a suggested `permissions.deny` fix) to see exactly
which rows disappeared or shrank.

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

## Known quirk #2: tool search silently disabled — inflates the whole TOOLS section

The `TOOLS` section (usually the single biggest chunk, 60-85% of total) is
only this large because every tool's *full* schema is sent on *every*
request. Claude Code has an experimental **tool search** mode
(`ENABLE_TOOL_SEARCH` in settings.json) meant to cut this dramatically by
letting the model search for relevant tools on demand instead of always
paying the full-schema cost — so before recommending per-tool
`permissions.deny` rules, check whether tool search is actually active,
since fixing *that* is a much bigger lever than denying individual tools.

Confirmed via a live debugging session (2026-07, Slack thread with Jonas
Brandes) — **this is not a LiteLLM/backend issue**, it's purely local
Claude Code client behavior:

- **`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`**, if set to any truthy value
  (`1`, `true`, ...), makes Claude Code silently ignore
  `ENABLE_TOOL_SEARCH` and force its internal tool-search mode to
  "standard" (i.e. full schemas, every request) — regardless of what's
  configured in settings.json. Check with:
  ```bash
  env | grep CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS
  ```
  If set truthy and you want tool search, unset it or set it to `0`/`false`.
- Even with that env var unset, `ToolSearchTool` itself can be **disallowed
  at an org-managed policy level** (a `managed-settings.json` /
  growthbook/statsig feature-gate layer above `~/.claude` config) — the
  same mechanism that can org-wide-disable Fast mode. When this is the
  cause, `ENABLE_TOOL_SEARCH=true` in the user's own settings.json is a
  no-op: nothing fixable locally in `settings.json` or `.claude.json`, it
  needs to be enabled at the org/managed-policy level. If tool search stays
  off despite `ENABLE_TOOL_SEARCH=true` being read correctly and the env
  var above being unset, say this plainly rather than suggesting more local
  settings tweaks — flag it as an org-policy question for whoever manages
  the deployment.
- Real-world effect observed: fixing the env var alone took one session
  from a much higher context size down to 21,601 tokens (11% of context
  window) for a bare "hey" — still high, because **most of that remainder
  was cache read**, not fresh cost. Cache-read tokens count toward the
  CLI's live context-window percentage but are not part of this script's
  grand total (which measures a cold, uncached request) — don't be
  surprised if the two numbers don't match; that's expected, not a bug in
  either measurement.

Run the normal token audit and per-tool `permissions.deny` suggestions
first, as always — those are real, immediate savings. Then, when `TOOLS`
dominates, also check tool search as an additional, higher-ceiling lever:
(1) is tool search even enabled and not silently overridden by the env var
above, (2) is `ToolSearchTool` actually available or blocked by org policy.
Tool search fixes the shape of the whole problem rather than trimming it
tool-by-tool, so surface it as a complementary option alongside the deny
suggestions, not a gate before them.

## TOOL SEARCH STATUS block (end of report)

The script now emits a **TOOL SEARCH STATUS** block at the end of every
run with one of four outcomes:

- **BLOCKED** — `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` is set truthy;
  tool search silently disabled regardless of settings. Fix: unset or set
  to `0`/`false`.
- **NOT CONFIGURED** — `ENABLE_TOOL_SEARCH` not found in any settings.json.
  Fix: add it.
- **ENABLED (ToolSearchTool present in request)** — working correctly; the
  TOOLS section above reflects the reduced per-turn schema cost.
- **CONFIGURED but ToolSearchTool absent** — likely org-managed policy
  blocking it; not fixable locally.

Surface this block to the user whenever TOOLS dominates. It's a bigger
lever than any per-tool deny rule.

## MCP SERVERS — active server, inactive specific tools

When a server is actively used (non-zero calls in history), the script now
checks whether any of that server's *individual tools* are never called and
flags them for per-tool `permissions.deny`. This is the right level of
granularity for servers like Atlassian where you may use Jira daily but
never use `createConfluenceInlineComment` or `createConfluencePage` etc.
The output prints each never-called tool with a ready-to-copy deny hint.

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
  tokens): run the audit and walk the user through the SUGGESTED FIXES
  block's specific deny rules or plugin toggles as usual, starting with
  the heaviest entries. Alongside those per-tool fixes, also check tool
  search status (see "Known quirk #2" above) as a separate, bigger lever —
  it's easy to misdiagnose as a LiteLLM/backend problem when it's actually
  local env config or org policy, so mention it even when the per-tool
  deny suggestions already look sufficient.
- If **system** is large: check which specific sub-row is driving it rather
  than treating "system" as one thing — a heavy `system: Memory` row points
  at oversized memory files (`~/.claude/projects/*/memory/`), a heavy
  `system: Harness` or `system: preamble` row is fixed Claude Code overhead
  (not user-controllable), and a heavy `message[N]: system-reminder:
  claudeMd` row (in MESSAGES) points at CLAUDE.md bloat specifically.
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
