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

Reads a real request/response pair captured by Claude Code's own
`OTEL_LOG_RAW_API_BODIES` logging (from a fresh session where the user typed
one message), and breaks the true, real token cost down section by section:
system prompt blocks, every tool/MCP schema, message history, per-MCP-server
and per-skill catalog cost.

**Why this doesn't call `/v1/messages/count_tokens` per section anymore**
(an earlier version of this script did): the configured endpoint's
`count_tokens` was found to silently ignore `system` and `tools` and return
a constant no matter their content — confirmed 2026-08 by padding both
fields and seeing zero change in the returned count. There is no reliable
way to get a real per-section tokenizer count from this endpoint, and
routing every tool through it individually (~100+ HTTP round-trips) was also
just slow for no accuracy benefit.

**What it uses instead**: the one number that IS real and exact — the
response's `usage.cache_creation_input_tokens`. That's the true, one-time
cost of writing the whole system+tools+messages payload into the prompt
cache on a session's first turn (this is also the number Claude Code's own
`/context` command shows as total context-window usage — see "Known quirk
#4" below). The script prorates that real total across every system block,
tool schema, and message *by character count* — character count and token
count are near-perfectly correlated for JSON/English text (measured
~2.6-2.9 chars/token across several real sessions), so this lands within a
few percent of a true per-item count, anchored to an exact real *total*
rather than guessed from scratch. This was verified directly: on a real
88,622-token session, summing chars across system+tools+messages and
prorating against that real total reproduced 88,622 exactly (by
construction — the point is the *distribution* across rows is what's
approximate, not the total).

## Running it

The script can't reliably capture its own probe: launching `claude` as a
child process of a running Claude Code session (which is what happens if
this script tries to shell out to `claude` itself, e.g. from inside this
skill) gets treated as a child session and silently degrades — and in
testing, a response body simply never got logged for such a child process,
even after long waits. Only a `claude` process started directly from a
real terminal reliably produces both a `.request.json` and a
`.response.json`.

So **the user runs the probe themselves**, in a new terminal, not this one:

```bash
mkdir -p ~/rtk-debug-logs
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_LOG_RAW_API_BODIES=file:$HOME/rtk-debug-logs
claude
```

Then inside that session: type one message (e.g. `hey`), wait for the
reply, and exit (Ctrl-C twice, or `/exit`). Tell the user exactly this when
they ask for a token audit — don't try to run `claude` yourself first; the
script will tell you the same thing if the log directory is empty or
incomplete, but it's faster to say it up front.

Once that's done, run:

```bash
uv run /home/lhelle/repos/personal/agent-harness/lors-plugin/skills/token-audit/scripts/analyze.py
```

It reads the most recent `*.request.json`/`*.response.json` pair from
`~/rtk-debug-logs` (no API calls, no `ANTHROPIC_*` env vars needed — it's
pure local JSON parsing) and prints the report in well under a second.

**Run this with the Bash tool directly** — it's fast enough that
backgrounding or Monitor add no value.

The probe session should be launched from whichever directory you want
audited (its project `CLAUDE.md`, local `.claude/settings.json`, and
project-scoped skills/MCP config get picked up from wherever `claude` was
actually started) — ask the user to `cd` there first if auditing a specific
project rather than global config.

## What it reports

A breakdown into five sections, each sorted heaviest-first:

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
  user message (memory recall, `currentDate`, etc.) is split into one row
  per top-level header inside it, plus a separate row for the actual
  user-typed text. The `claudeMd` header specifically is pulled out into its
  own **context** section instead (see below) rather than staying one lump
  row here. The mid-conversation agent catalog reminder is split out
  separately too (see **catalog** below) so it doesn't get counted as one
  opaque blob either.
- **context** — every CLAUDE.md-family file Claude Code actually loaded for
  this probe, one row per file (by its path), instead of one opaque
  `claudeMd` blob. Since the probe now runs in the invoking directory (see
  "Running it" above), this typically includes both **global** config
  (`~/.claude/CLAUDE.md`, plus any `@`-imported file like `RTK.md`) and, when
  run from inside a project, that **project's own `CLAUDE.md`** — each gets
  its own row and token count, so you can see e.g. "the project CLAUDE.md
  alone is 600 tokens" instead of folding it into a single global number.
  Run the audit from different directories to compare a project's
  CLAUDE.md cost against another project's, or against no project at all
  (run from `~`).
- **catalog** — the mid-conversation "Available agent types..."
  system-reminder Claude Code injects whenever the Agent tool is present,
  broken into its three independently-toggleable parts: the fixed
  agent-types prose, **one row per connected MCP server** (its per-server
  instructions block), and **one row per registered skill** (its one-line
  catalog entry — name + description). This split is what makes the MCP
  SERVERS and SKILLS sections below possible.

All of this splitting (system prompt, system-reminder wrapper, claudeMd
files, MCP/skill catalog) uses the same underlying technique: find every
top-level `# `/`## ` header (or, for claudeMd, every "Contents of `<path>`"
marker) in a block of text and cut it into one row per section between
markers. It's generic, so if Claude Code adds a new top-level section to
any of these blocks in a future version, it shows up as its own row
automatically — nothing in this skill needs updating for that.

Plus a grand total (with an inline note explaining the cold/uncached
vs. live context-window number distinction — see "Two totals" below),
a top-10 heaviest-items list across all sections, a **SUGGESTED FIXES**
block for heavy tools, **MCP SERVERS** / **SKILLS** sections (see below),
and a **TOOL SEARCH STATUS** block.

## The total: exactly `cache_creation_input_tokens`, not an estimate

The script's **TOTAL TOKENS** line is not computed from anything the script
measured itself — it's copied straight from the captured response's
`usage.cache_creation_input_tokens`, then the per-row numbers above it are
derived from that real total (char-proportional split). So the total always
matches what `/context` would show for that same session's first turn — see
"Known quirk #4" below for why `/context`'s own per-category breakdown can
still disagree with this report's per-row breakdown even though the totals
agree.

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

## Suggested fixes: cutting real token cost

Every request-level tool listed in the audit that isn't a core tool (Bash,
Read, Edit, Write, Agent, Skill, WebFetch, WebSearch, NotebookEdit,
AskUserQuestion, plan-mode tools) and contributes >1% of total tokens gets a
concrete fix suggestion.

**Key finding** (documented mechanism, established from an earlier round of
empirical verification by diffing two probe requests — not re-verified on
every run anymore, since that required spawning a second `claude` process,
which has the same child-session problem described in "Running it" above):
a **bare tool name** in `settings.json`'s `permissions.deny` array removes
that tool's schema from the request entirely — Claude never sees it, and
its tokens are gone from every request. This is different from a
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
- **`Artifact`**: disable via `"disableArtifact": true` in settings.json or
  `CLAUDE_CODE_DISABLE_ARTIFACT=1` — removes the Artifact tool (publishing
  session output as a private claude.ai page) entirely.
- **MCP-namespaced tools** (`mcp__<server>__<tool>`): the fix is disabling
  the MCP server/plugin behind them (check `enabledPlugins` in
  settings.json, or run `/mcp` to identify which server owns a given tool),
  not denying each tool individually — a server usually exposes several
  tools that all disappear together once the server is off.
  - **`mcp__claude_ai_*`** servers specifically (Gmail, Google Calendar/Drive,
    Notion, TickTick, etc. — the claude.ai-hosted connectors) have a single
    blanket flag beyond per-server disable: `"disableClaudeAiConnectors": true`
    in settings.json stops all of them from being auto-fetched/connected at
    once. Servers passed explicitly via `--mcp-config` are unaffected.
- **Bundled skills as a group**: if several *never-used* skills in the
  SKILLS section turn out to be Anthropic's own bundled ones (`dataviz`,
  `review`, `init`, etc., not plugin or `.claude/skills/` skills),
  `"disableBundledSkills": true` in settings.json (or
  `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1`) removes the whole bundled catalog
  in one shot while keeping their slash commands typable — cheaper than
  fighting each one individually. Confirmed via
  [code.claude.com/docs/en/settings](https://code.claude.com/docs/en/settings),
  min version v2.1.169.
- Everything else (e.g. `DesignSync`, `Cron*`, `Task*`, `EnterWorktree`/
  `ExitWorktree`, `ScheduleWakeup`, `LSP`, `ReportFindings`, `SendMessage`):
  no dedicated flag found in Claude Code's docs — bare-name
  `permissions.deny` is the mechanism.

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

## Known quirk #1: why this script doesn't call `count_tokens` at all anymore

An earlier version of this script called the configured endpoint's
`/v1/messages/count_tokens` once per section, smuggling text through the
`messages` field as a workaround for a LiteLLM/Vertex/Bedrock-passthrough
quirk where that endpoint silently ignores `system`/`tools` and returns a
constant. That workaround was real-tokenizer-exact per call, but required
~100+ sequential HTTP round-trips per audit (slow — 1-2 minutes) and still
had its own ~4% measurement bias (measuring `description + "\n" +
schema_json` as loose text instead of the real serialized tool object,
dropping the `"name":`/`"description":`/`"input_schema":` key overhead and
braces).

This script no longer calls `count_tokens` at all. It calibrates against
the real `usage.cache_creation_input_tokens` from a captured response
instead (see Overview) — which is both faster (zero API calls, pure local
JSON parsing) and anchored to a real total rather than a per-call
tokenizer estimate. Per-tool char counting still uses each tool's full
compact-serialized JSON object (`json.dumps(tool, separators=(",", ":"))`),
matching real request bytes as closely as possible, since that's now what
gets prorated against the real total.

## Known quirk #4: Claude Code's own `/context` command misattributes the MCP tool cost it can't see

Claude Code's built-in `/context` slash command shows **every MCP tool as
"0 tokens"** in its per-category breakdown — verified empirically (2026-08)
across two different real sessions. It's very likely hitting the same
broken `count_tokens` endpoint described in "Known quirk #1" internally and
failing silently (0) instead of working around it the way this script now
does. **Don't let a low-looking `/context` MCP-tools listing talk you out of
this script's TOOLS numbers** — use this report's TOOLS section, not
`/context`'s MCP tools list, to see which tool schemas actually cost tokens.
The script prints a "NOTE ON /context COMPARISON" block whenever the probed
session has any MCP tools, specifically so this doesn't need
re-discovering per session.

**Why a bare "hey" still shows 70-130k tokens in `/context`'s *total*, even
though its MCP-tools rows are all 0** (confirmed 2026-08 via a real user
session's captured `.response.json`): it's not the message "hey" costing
that much — it's `cache_creation_input_tokens`, the one-time price of
writing the entire system prompt + every active MCP tool schema + the
skill/agent catalog into the prompt cache on a session's first turn. A real
response body looked like:

```json
"usage": {"input_tokens": 2, "cache_creation_input_tokens": 132199,
          "cache_read_input_tokens": 0, "output_tokens": 13}
```

`/context`'s total (132.2k in that session) is exactly
`cache_creation_input_tokens` — **the total is correct**, cache-creation
tokens do count toward the context window even though they're billed
differently from plain input tokens. The bug is only in `/context`'s
*category breakdown* below that total: since it can't attribute MCP tool
cost (the 0s described above), the real tool-schema cost that's genuinely
part of that cache-creation number gets dumped into "Messages" instead of
"MCP tools" in `/context`'s own UI. So the total isn't wrong or inflated —
it's real, one-time cache-build cost — `/context` just files it under the
wrong row internally. This script's per-row breakdown (calibrated against
that same real total, but prorated correctly per tool/system-block/message)
is what to use instead.

(An earlier version of this doc claimed the gap only "appears after the
first turn was answered" and gets misattributed at that point specifically —
that framing was based on comparing two `/context` snapshots without the
underlying response body and turned out to not survive a direct repro: a
bare "hey" is a single API call, not multiple turns, and the earlier
snapshot-diff coincidentally conflated a session that also gained several
new MCP servers between snapshots. The cache-creation explanation above is
the one confirmed against a real captured response body — trust that one.)

## Known quirk #2: tool search silently disabled — inflates the whole TOOLS section

The `TOOLS` section (usually the single biggest chunk, 60-85% of total) is
only this large because every tool's *full* schema is sent on *every*
request. Claude Code has an experimental **tool search** mode
(`ENABLE_TOOL_SEARCH` — must be set in the `env` block of settings.json, **not** as a top-level key; a top-level `ENABLE_TOOL_SEARCH` is rejected by the schema validator and silently ignored) meant to cut this dramatically by
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
- **`ENABLE_TOOL_SEARCH` must be in the `env` block**, not top-level:
  ```json
  { "env": { "ENABLE_TOOL_SEARCH": "true" } }
  ```
  A top-level `"ENABLE_TOOL_SEARCH": true` fails schema validation and is
  silently ignored — Claude Code never sees it. Confirmed empirically
  (2026-07): attempting to add it top-level raises
  `"Unrecognized field: ENABLE_TOOL_SEARCH"` from the settings validator,
  and the setting has no effect even if the validator is bypassed.
- Even with that env var unset, `ToolSearchTool` itself can be **disallowed
  at an org-managed policy level** (a `managed-settings.json` /
  growthbook/statsig feature-gate layer above `~/.claude` config) — the
  same mechanism that can org-wide-disable Fast mode. When this is the
  cause, `ENABLE_TOOL_SEARCH=true` in the user's own settings.json `env`
  block is a no-op: nothing fixable locally in `settings.json` or
  `.claude.json`, it needs to be enabled at the org/managed-policy level.
  If tool search stays off despite `ENABLE_TOOL_SEARCH=true` being set in
  `env` correctly and the env var above being unset, say this plainly
  rather than suggesting more local settings tweaks — flag it as an
  org-policy question for whoever manages the deployment.
- Real-world effect observed: fixing the env var alone took one session
  from a much higher context size down to 21,601 tokens (11% of context
  window) for a bare "hey". This script's total (`cache_creation_input_tokens`)
  and that number can still legitimately differ turn to turn — a later turn
  in the same session might show mostly `cache_read_input_tokens` instead
  (cheaper, since the cache from turn 1 is being reused) — this script
  always measures a session's **first** turn specifically, since that's
  the one number that's a pure one-time build cost with nothing reused.

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
- **NOT CONFIGURED** — `ENABLE_TOOL_SEARCH` not found in any settings.json
  (neither top-level nor in the `env` block). Fix: add `"ENABLE_TOOL_SEARCH":
  "true"` to the `env` block.
- **MISCONFIGURED (top-level)** — `ENABLE_TOOL_SEARCH` found as a top-level
  settings.json key, not inside `env`. Schema validator rejects it; Claude
  Code silently ignores it. Fix: move it into `"env": { "ENABLE_TOOL_SEARCH":
  "true" }`.
- **ENABLED (ToolSearchTool present in request)** — working correctly; the
  TOOLS section above reflects the reduced per-turn schema cost.
- **CONFIGURED but ToolSearchTool absent** — `ENABLE_TOOL_SEARCH=true` is set
  correctly in `env`, `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` is not truthy,
  but `ToolSearchTool` still didn't appear. Likely org-managed policy blocking
  it; not fixable locally.

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
  at oversized memory files (`~/.claude/projects/*/memory/`), and a heavy
  `system: Harness` or `system: preamble` row is fixed Claude Code overhead
  (not user-controllable).
- If **context** is large: check which specific file's row is driving it —
  a heavy global `~/.claude/CLAUDE.md` (or an `@`-imported file like
  `RTK.md`) row is a fixed cost across every project, while a heavy
  project-`CLAUDE.md` row is specific to whatever directory the audit was
  run from and only trimmable in that project's own file. Since the probe's
  cwd controls which project CLAUDE.md (if any) shows up here, re-run from a
  different project directory to compare.
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
- Every count here is the real, one-time cost of building a **fresh**
  session's prompt cache (turn 1 specifically). Later turns in the same
  session mostly hit `cache_read_input_tokens` instead — cheaper, since the
  same content is being reused rather than rebuilt. Cross-reference against
  `rtk gain` (the user's token-savings CLI) for actual historical spend
  across real sessions.
