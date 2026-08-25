#!/usr/bin/env -S PYTHONUNBUFFERED=1 uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
Token audit for Claude Code.

Reads a real request/response pair captured by Claude Code's own
OTEL_LOG_RAW_API_BODIES logging (the user runs a fresh `claude` session,
types one message, and exits — see main() for the exact instructions this
script prints) and breaks the real cost down section by section (system
prompt, per-tool schema, message history, mid-conversation agent/skill
catalog).

Why this replaces the old count_tokens-based approach: the configured
endpoint's `/v1/messages/count_tokens` was found to silently ignore `system`
and `tools` and return a constant no matter their content (common on
Vertex/Bedrock-passthrough LiteLLM routes) — verified 2026-08 by padding
`system` and `tools` and seeing no change in the returned count. There is no
reliable per-section exact-tokenizer count available from this endpoint.

Instead, this script uses the one number that IS real and exact: the
response's `usage.cache_creation_input_tokens` — the true token cost of
writing the entire system+tools+messages payload into the prompt cache on a
session's first turn (confirmed 2026-08 via a real captured response body;
this is also the number Claude Code's own `/context` command shows as the
total context-window usage after a first turn — see SKILL.md "Known quirk
#4"). It then prorates that real total across every system block, tool
schema, and message *by character count*, on the basis that character count
and token count are near-perfectly correlated for JSON/English text
(measured ratio ~2.6-2.9 chars/token across several real sessions — close
enough that char-proportional allocation lands within a few percent of a
per-item real count, without needing ~100+ additional API calls to get
there). This is an approximation of the *distribution*, anchored to an
exact, real *total* — not a heuristic guess at the total itself.

Besides the terminal report, this also writes a Markdown overview of every
message/part sent in the probe request (one row per system block, tool
schema, message, and catalog entry, with token count and a content preview)
to output/<timestamp>.md next to this script's skill directory - see
write_markdown_report().
"""
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
GROUND_TRUTH_LOG_DIR = os.path.expanduser("~/rtk-debug-logs")

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-latest")


def preview_text(text, limit=200):
    """Collapse whitespace and truncate to a single-line preview, for the
    overview table (both terminal top-10 and the markdown report)."""
    if not text:
        return ""
    flat = " ".join(str(text).split())
    if len(flat) > limit:
        return flat[:limit].rstrip() + "…"
    return flat


def load_ground_truth_pair(log_dir):
    """Load the most recent request/response pair from a directory populated
    by Claude Code's OTEL_LOG_RAW_API_BODIES logging (file:<dir> mode).

    Returns (request_dict, cache_creation_input_tokens). Exits with a clear
    error if the directory is missing, empty, or has a request with no
    matching response yet (the user needs to actually send one message and
    wait for the reply before exiting the session)."""
    if not os.path.isdir(log_dir):
        print(f"ERROR: {log_dir} does not exist yet.\n", file=sys.stderr)
        print_instructions(log_dir)
        sys.exit(1)

    request_files = sorted(Path(log_dir).glob("*.request.json"), key=os.path.getmtime)
    response_files = sorted(Path(log_dir).glob("*.response.json"), key=os.path.getmtime)

    if not request_files or not response_files:
        print(f"ERROR: {log_dir} has no complete request/response pair yet "
              f"({len(request_files)} request(s), {len(response_files)} response(s)).\n",
              file=sys.stderr)
        print_instructions(log_dir)
        sys.exit(1)

    with open(request_files[-1]) as f:
        request_data = json.load(f)
    with open(response_files[-1]) as f:
        response_data = json.load(f)

    usage = response_data.get("usage", {})
    ground_truth = usage.get("cache_creation_input_tokens")
    if not ground_truth:
        # No cache write happened (e.g. this was a cache-read turn, not the
        # session's first). Fall back to input_tokens + cache_read, which is
        # still the real total for that turn, just not a fresh-cache-build number.
        ground_truth = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        if not ground_truth:
            print("ERROR: response has no usable usage.cache_creation_input_tokens or "
                  "input_tokens — can't calibrate against it.", file=sys.stderr)
            sys.exit(1)
        print("NOTE: this response had no cache_creation_input_tokens (not a fresh-cache "
              "turn) — using input_tokens + cache_read_input_tokens as ground truth instead. "
              "For the 'cost of a session's first message' number, use a genuinely fresh "
              "session (no prior /context or messages).", file=sys.stderr)

    return request_data, ground_truth


def print_instructions(log_dir):
    print(
        "This script needs a real request+response pair from a fresh Claude Code\n"
        "session to calibrate against. It can't reliably launch one itself — a\n"
        "`claude` process started from inside another Claude Code session (like this\n"
        "script running under a skill/subagent) is treated as a child session and\n"
        "silently degrades, and doesn't always get its response logged.\n\n"
        "Run this in a NEW terminal (not this one):\n\n"
        f"  mkdir -p {log_dir}\n"
        "  export CLAUDE_CODE_ENABLE_TELEMETRY=1\n"
        f"  export OTEL_LOG_RAW_API_BODIES=file:{log_dir}\n"
        "  claude\n\n"
        "Then inside that session: type one message (e.g. \"hey\"), wait for the reply,\n"
        "and exit (Ctrl-C twice, or /exit). Then re-run this script.",
        file=sys.stderr,
    )


def extract_system_blocks(system_field):
    """system can be a string or a list of {type, text, cache_control} blocks."""
    if isinstance(system_field, str):
        return [("system[0]", system_field)]
    out = []
    for i, block in enumerate(system_field or []):
        text = block.get("text", "") if isinstance(block, dict) else str(block)
        label = f"system[{i}]"
        out.append((label, text))
    return out


def classify_system_block(idx, text):
    """Give human-readable names to the known Claude Code system block slots."""
    if idx == 0 and text.startswith("x-anthropic-billing-header"):
        return "billing/attribution header"
    if "Claude Agent SDK" in text and len(text) < 200:
        return "SDK identity line"
    if "interactive agent that helps users" in text:
        return "base agent system prompt (harness + CLAUDE.md + memory + env)"
    return f"system block #{idx}"


def split_by_h1_headers(text, label_prefix):
    """Split a block of text into (label, chunk) pairs on top-level markdown
    `# Header` lines, keeping any leading preamble before the first header as
    its own row. This is what turns opaque multi-thousand-char blobs (the
    base system prompt, the mid-conversation system-reminder wrapper) into
    per-section rows so e.g. "Harness" vs. "Memory" vs. "Environment" each
    get their own token count instead of one lump sum.

    Falls back to a single (label_prefix, text) row if there are no H1
    headers to split on (e.g. a plain user message) or fewer than 2 (nothing
    meaningful to break apart), so callers don't have to special-case that.
    """
    headers = list(re.finditer(r"(?m)^# (.+)$", text))
    if len(headers) < 2:
        return [(label_prefix, text)]
    out = []
    if headers[0].start() > 0:
        preamble = text[:headers[0].start()]
        if preamble.strip():
            out.append((f"{label_prefix}: preamble", preamble))
    for i, m in enumerate(headers):
        name = m.group(1).strip()
        start = m.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        out.append((f"{label_prefix}: {name}", text[start:end]))
    return out


def classify_message(i, msg):
    role = msg.get("role")
    content = msg.get("content")
    if role == "system" and isinstance(content, str) and "Available agent types" in content:
        return "mid-conversation system reminder: agent catalog"
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and "<system-reminder>" in block.get("text", ""):
                return f"message[{i}] ({role}): system-reminder wrapper + user turn"
    return f"message[{i}] ({role})"


def find_catalog_message(messages):
    """Locate the mid-conversation system-reminder message that carries the
    agent catalog, per-MCP-server instructions, and skill catalog, if present.

    Checked against every message regardless of role or content shape (string
    vs. content-block array) — some backends deliver this as a block-array
    user/system message wrapped in <system-reminder> tags rather than a bare
    system-role string, and skipping those silently drops a large chunk of
    real tokens from the audit."""
    for msg in messages:
        text = text_of_message(msg)
        if "Available agent types" in text:
            return text
    return None


def split_mcp_servers(catalog_text):
    """Split the '# MCP Server Instructions' block into (server_name, prose)
    pairs. server_name is the colon-form header, e.g. 'plugin:telegram:telegram'."""
    mcp_idx = catalog_text.find("# MCP Server Instructions")
    skills_idx = catalog_text.find("The following skills are available")
    if mcp_idx == -1 or skills_idx == -1 or skills_idx <= mcp_idx:
        return []
    mcp_text = catalog_text[mcp_idx:skills_idx]
    headers = list(re.finditer(r"(?m)^## (\S+)", mcp_text))
    out = []
    for i, m in enumerate(headers):
        name = m.group(1)
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(mcp_text)
        out.append((name, mcp_text[start:end]))
    return out


def split_skill_catalog(catalog_text):
    """Split the 'The following skills are available...' block into
    (skill_name, entry_text) pairs, one per bullet line."""
    skills_idx = catalog_text.find("The following skills are available")
    if skills_idx == -1:
        return []
    skills_text = catalog_text[skills_idx:]
    # Trim off any trailing sections appended after the skill list (e.g. a
    # subsequent "## Exited Plan Mode" block in longer conversations).
    cutoff = re.search(r"\n## \S", skills_text)
    if cutoff:
        skills_text = skills_text[:cutoff.start()]
    entries = list(re.finditer(r"(?m)^- ([\w.:-]+)", skills_text))
    out = []
    for i, m in enumerate(entries):
        name = m.group(1).rstrip(":")  # strip the ": description" separator colon
        start = m.start()
        end = entries[i + 1].start() if i + 1 < len(entries) else len(skills_text)
        out.append((name, skills_text[start:end]))
    return out


def agent_catalog_prose(catalog_text):
    """The fixed 'Available agent types...' preamble, excluding the MCP and
    skill sections that get split out separately."""
    mcp_idx = catalog_text.find("# MCP Server Instructions")
    end = mcp_idx if mcp_idx != -1 else catalog_text.find("The following skills are available")
    return catalog_text[:end] if end != -1 else catalog_text


def usage_bucket_label(count, last_ts):
    """Classify usage recency into never / 30+ days / 8-30 days / <=7 days."""
    if count == 0:
        return "never used"
    if not last_ts:
        return f"used {count}x, date unknown"
    try:
        dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - dt).days
    except Exception:
        return f"used {count}x, date unknown"
    if days <= 7:
        return f"used {count}x, last {format_days_ago(last_ts)} (within 7 days)"
    if days <= 30:
        return f"used {count}x, last {format_days_ago(last_ts)} (8-30 days ago)"
    return f"used {count}x, last {format_days_ago(last_ts)} (30+ days ago — stale)"


def guess_plugin_key(server_header_name, enabled_plugins):
    """Given a header like 'plugin:telegram:telegram', try to find the
    matching key in settings.json's enabledPlugins (e.g. 'telegram@...')."""
    parts = server_header_name.split(":")
    if len(parts) >= 2 and parts[0] == "plugin":
        short = parts[1]
        for key in enabled_plugins:
            if key.split("@")[0] == short:
                return key
    return None


def load_enabled_plugins():
    for path in ("~/.claude/settings.json", "~/.claude/settings.local.json"):
        p = os.path.expanduser(path)
        if os.path.exists(p):
            try:
                d = json.load(open(p))
                if d.get("enabledPlugins"):
                    return d["enabledPlugins"]
            except Exception:
                continue
    return {}


# Core tools essential to normal operation — never suggest disabling these
# even though they're technically removable via permissions.deny. Doing so
# would cripple the agent, not just save tokens.
CORE_TOOLS = {
    "Bash", "Read", "Edit", "Write", "Agent", "Skill", "WebFetch", "WebSearch",
    "NotebookEdit", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
}

# Tools with a specific, documented disable mechanism beyond generic
# permissions.deny. Verified against code.claude.com/docs and/or empirically
# (see SKILL.md). Each entry is a list of equivalent ways to disable it.
KNOWN_DISABLE_HINTS = {
    "Workflow": [
        '"disableWorkflows": true in settings.json (default: false)',
        "env var CLAUDE_CODE_DISABLE_WORKFLOWS=1",
        '/config → toggle "Dynamic workflows" off',
    ],
    "Artifact": [
        '"disableArtifact": true in settings.json',
        "env var CLAUDE_CODE_DISABLE_ARTIFACT=1",
    ],
}

# Confirmed via code.claude.com/docs/en/settings (2026-07). Bundled-skills and
# claude.ai-connector disables aren't single-tool hints (they remove whole
# catalog groups, not one named tool), so they're surfaced separately in the
# SKILLS / MCP SERVERS sections rather than through disable_hint_for_tool().
DISABLE_BUNDLED_SKILLS_HINT = (
    '"disableBundledSkills": true in settings.json (or '
    "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1) — removes all of Anthropic's "
    "bundled skills/workflows at once, keeps their slash commands typable. "
    "Does NOT remove plugin skills or .claude/skills/."
)
DISABLE_CLAUDE_AI_CONNECTORS_HINT = (
    '"disableClaudeAiConnectors": true in settings.json — stops claude.ai '
    "MCP connectors (e.g. Gmail, Google Calendar/Drive, Notion, TickTick "
    "under mcp__claude_ai_*) from being auto-fetched/connected. Servers "
    "passed explicitly via --mcp-config are unaffected."
)

MCP_TOOL_RE = re.compile(r"^mcp__(.+?)__(.+)$")


def disable_hint_for_tool(name):
    """Return a list of suggested fixes for a specific tool, or None for
    tools with no specific mechanism (falls back to generic deny)."""
    if name in KNOWN_DISABLE_HINTS:
        return KNOWN_DISABLE_HINTS[name]
    m = MCP_TOOL_RE.match(name)
    if m:
        server_id = m.group(1)
        return [f'disable the MCP server/plugin behind "{server_id}" '
                f'(check enabledPlugins in settings.json, or `/mcp` to find which server this is)']
    return None


def scan_tool_usage_history():
    """Scan every session transcript (~/.claude/projects/*/*.jsonl) for actual
    tool_use calls, so suggestions can be qualified by "have you even used
    this" rather than token weight alone. Returns three dicts:
      - tool_usage: tool_name -> [count, last_ts]   (every tool_use call)
      - skill_usage: skill_name -> [count, last_ts] (Skill tool calls, keyed
        by the `skill` input argument, e.g. "token-audit" or "jira-cli:jira-cli")
      - mcp_usage: server_id -> [count, last_ts]    (any mcp__<server>__* call,
        aggregated per server since that's the disable granularity)
    Best-effort — skips unparseable lines/files rather than failing the audit.
    """
    tool_usage = {}
    skill_usage = {}
    mcp_usage = {}
    files = glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
    for path in files:
        try:
            with open(path, errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("type") != "assistant":
                        continue
                    content = d.get("message", {}).get("content", [])
                    if not isinstance(content, list):
                        continue
                    ts = d.get("timestamp")
                    for block in content:
                        if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                            continue
                        name = block.get("name")
                        if not name:
                            continue

                        def bump(bucket, key):
                            entry = bucket.setdefault(key, [0, None])
                            entry[0] += 1
                            if ts and (entry[1] is None or ts > entry[1]):
                                entry[1] = ts

                        bump(tool_usage, name)

                        if name == "Skill":
                            skill_name = (block.get("input") or {}).get("skill")
                            if skill_name:
                                bump(skill_usage, skill_name)

                        m = MCP_TOOL_RE.match(name)
                        if m:
                            bump(mcp_usage, m.group(1))
        except Exception:
            continue
    return tool_usage, skill_usage, mcp_usage


def format_days_ago(iso_ts):
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - dt).days
        if days == 0:
            return "today"
        if days == 1:
            return "1 day ago"
        return f"{days} days ago"
    except Exception:
        return iso_ts


def text_of_message(msg):
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if "text" in block:
                    parts.append(block["text"])
                else:
                    parts.append(json.dumps(block))
        return "\n".join(parts)
    return ""


SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>(.*?)</system-reminder>", re.DOTALL)


def split_user_turn_message(i, msg):
    """Split a user-turn message into its constituent parts instead of one
    opaque row: the <system-reminder> wrapper (itself broken into its
    top-level `# Header` sections — memory recall, CLAUDE.md contents,
    currentDate, etc. each get their own row) plus the actual user-typed
    text as its own separate row. Falls back to a single whole-message row
    if there's no <system-reminder> block to split out (e.g. a later turn
    in the conversation with no reminder attached)."""
    text = text_of_message(msg)
    m = SYSTEM_REMINDER_RE.search(text)
    if not m:
        return None
    reminder_body = m.group(1)
    remainder = (text[:m.start()] + text[m.end():]).strip()
    out = []
    for sub_label, sub_text in split_by_h1_headers(reminder_body, f"message[{i}]: system-reminder"):
        out.append((sub_label, sub_text))
    if remainder:
        out.append((f"message[{i}] ({msg.get('role')}): user turn text", remainder))
    return out


CLAUDE_MD_FILE_RE = re.compile(r"(?m)^Contents of (\S+)")


def split_claude_md_files(claudemd_text):
    """Split the '# claudeMd' section's body into one row per loaded file.

    Claude Code concatenates every CLAUDE.md-family file it loaded (global
    ~/.claude/CLAUDE.md, any @-imported files like RTK.md, and — when the
    session's cwd has one — that project's own CLAUDE.md) into this single
    section, each announced by its own "Contents of <path> (...)" line. That
    makes "claudeMd" in the generic system/messages breakdown an opaque lump
    that conflates global config with whatever project the probe happened to
    run in. Splitting it out here gives each file its own row so project-
    loaded context is visible and comparable run-over-run as cwd changes.

    Falls back to a single (None, whole_text) pseudo-row if no "Contents of"
    marker is found (e.g. no CLAUDE.md loaded at all, or a future format
    change), so callers don't have to special-case an empty split."""
    markers = list(CLAUDE_MD_FILE_RE.finditer(claudemd_text))
    if not markers:
        return [(None, claudemd_text)]
    out = []
    for i, m in enumerate(markers):
        path = m.group(1)
        start = m.start()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(claudemd_text)
        out.append((path, claudemd_text[start:end]))
    return out


def md_escape(text):
    """Escape a preview string so it's safe inside a markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def write_markdown_report(data, by_section, grand_total, extra_sections):
    """Write a full overview of every message/part sent in the probe request
    to output/<timestamp>.md — one table per section (system/tools/messages/
    catalog/config), each row showing tokens, %, chars, and a content preview,
    plus the same SUGGESTED FIXES / MCP SERVERS / SKILLS sections as the
    terminal report. Returns the path written."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = OUTPUT_DIR / f"{timestamp}.md"

    lines = [
        f"# Token Audit — {timestamp}",
        "",
        f"- Model: `{data.get('model')}`",
        f"- **Total tokens (real cache_creation_input_tokens, char-prorated per row): {grand_total:,}**",
        "",
    ]

    for section in ["system", "tools", "messages", "context", "catalog", "config"]:
        entries = by_section.get(section)
        if not entries:
            continue
        entries = sorted(entries, key=lambda e: -e[1])
        section_total = sum(e[1] for e in entries)
        pct = 100 * section_total / grand_total if grand_total else 0
        lines.append(f"## {section.upper()} — {section_total:,} tokens ({pct:.1f}% of total)")
        lines.append("")
        lines.append("| Tokens | % of total | Chars | Name | Preview |")
        lines.append("|---|---|---|---|---|")
        for name, tokens, chars, preview in entries:
            bar_pct = 100 * tokens / grand_total if grand_total else 0
            lines.append(
                f"| {tokens:,} | {bar_pct:.1f}% | {chars:,} | {md_escape(name)} | {md_escape(preview)} |"
            )
        lines.append("")

    lines += extra_sections

    out_path.write_text("\n".join(lines))
    return out_path


def main():
    request_data, ground_truth_tokens = load_ground_truth_pair(GROUND_TRUTH_LOG_DIR)
    data = request_data

    char_rows = []  # (section, subsection, chars, preview) — tokens filled in after totaling chars

    # --- system blocks ---
    # The base agent system prompt is one multi-thousand-char blob (harness
    # instructions + CLAUDE.md + memory + environment block, all
    # concatenated) — split it on its own top-level `# Header` lines so
    # "Harness" vs. "Memory" vs. "Environment" etc. each get their own row
    # and char count instead of one opaque lump sum.
    for i, (label, text) in enumerate(extract_system_blocks(data.get("system"))):
        name = classify_system_block(i, text)
        if name.startswith("base agent system prompt"):
            for sub_label, sub_text in split_by_h1_headers(text, "system"):
                char_rows.append(("system", sub_label, len(sub_text), preview_text(sub_text)))
        else:
            char_rows.append(("system", name, len(text), preview_text(text)))

    # --- tools ---
    # Count each tool as its real, compact-serialized JSON object (matching
    # what actually sits in the API request's `tools` array), not as loose
    # concatenated description+schema text — this is what actually gets
    # prorated against the real cache_creation_input_tokens ground truth,
    # so it needs to match the real request bytes as closely as possible.
    tools = data.get("tools", [])
    for t in tools:
        name = t.get("name", "?")
        desc_text = t.get("description", "")
        full_json = json.dumps(t, separators=(",", ":"))
        char_rows.append(("tools", name, len(full_json), preview_text(desc_text or full_json)))

    # --- messages ---
    # The mid-conversation "Available agent types..." system-reminder bundles
    # three independently-toggleable things (agent catalog prose, one block
    # per MCP server, one line per skill) — break it into its own section
    # instead of counting it as a single opaque row, so each MCP server and
    # skill gets its own char cost and can be checked against usage history.
    catalog_text = find_catalog_message(data.get("messages", []))
    for i, msg in enumerate(data.get("messages", [])):
        if catalog_text is not None and text_of_message(msg) == catalog_text:
            continue  # handled below as its own section
        # The <system-reminder> wrapper bundles several independently-sized
        # things (memory recall, CLAUDE.md contents, currentDate, ...) — same
        # opaque-blob problem as the base system prompt, so split it the
        # same way instead of one lump "system-reminder wrapper" row.
        split = split_user_turn_message(i, msg)
        if split:
            for sub_label, sub_text in split:
                # The claudeMd sub-block bundles every loaded CLAUDE.md-family
                # file (global config + any project CLAUDE.md picked up from
                # the probe's cwd) into one opaque blob — break it out into
                # its own "context" section, one row per file, instead of
                # letting it hide inside "messages" as a single lump.
                if sub_label.endswith(": claudeMd"):
                    for file_path, file_text in split_claude_md_files(sub_text):
                        name = file_path or sub_label
                        char_rows.append(("context", name, len(file_text), preview_text(file_text)))
                else:
                    char_rows.append(("messages", sub_label, len(sub_text), preview_text(sub_text)))
        else:
            label = classify_message(i, msg)
            text = text_of_message(msg)
            char_rows.append(("messages", label, len(text), preview_text(text)))

    if catalog_text:
        prose = agent_catalog_prose(catalog_text)
        char_rows.append(("catalog", "agent-types catalog", len(prose), preview_text(prose)))
        for server_name, server_text in split_mcp_servers(catalog_text):
            char_rows.append(("catalog", f"mcp:{server_name}", len(server_text), preview_text(server_text)))
        for skill_name, skill_text in split_skill_catalog(catalog_text):
            char_rows.append(("catalog", f"skill:{skill_name}", len(skill_text), preview_text(skill_text)))

    # --- calibrate: prorate the real cache_creation_input_tokens ground truth
    # across every row proportionally to its share of total characters. Char
    # count and token count are near-perfectly correlated for JSON/English
    # text (measured ~2.6-2.9 chars/token across several real sessions), so
    # this lands within a few percent of a true per-item tokenizer count
    # without needing per-item API calls against an endpoint that can't
    # even do that (see module docstring).
    total_chars = sum(r[2] for r in char_rows)
    rows = []  # (section, subsection, tokens, chars, preview)
    running_tokens = 0
    for idx, (section, name, chars, preview) in enumerate(char_rows):
        if idx == len(char_rows) - 1:
            # last row absorbs any rounding remainder so the sum matches
            # ground_truth_tokens exactly, not just approximately
            tokens = ground_truth_tokens - running_tokens
        else:
            tokens = round(ground_truth_tokens * chars / total_chars) if total_chars else 0
        running_tokens += tokens
        rows.append((section, name, tokens, chars, preview))

    # betas/metadata contribute negligible bytes and aren't part of the
    # cache-creation payload in a way worth prorating a row for — reported
    # separately below, not mixed into the token-bearing rows.
    betas = data.get("betas", [])

    grand_total = sum(r[2] for r in rows)

    by_section = {}
    for section, name, tokens, chars, preview in rows:
        by_section.setdefault(section, []).append((name, tokens, chars, preview))

    # --- print report ---
    print(f"\n{'='*72}")
    print(f"TOKEN AUDIT — model={data.get('model')}  (calibrated against real cache_creation_input_tokens)")
    print(f"{'='*72}\n")

    for section in ["system", "tools", "messages", "context", "catalog"]:
        if section not in by_section:
            continue
        entries = sorted(by_section[section], key=lambda e: -e[1])
        section_total = sum(e[1] for e in entries)
        pct = 100 * section_total / grand_total if grand_total else 0
        print(f"## {section.upper()}  —  {section_total:,} tokens ({pct:.1f}% of total)")
        for name, tokens, chars, _preview in entries:
            bar_pct = 100 * tokens / grand_total if grand_total else 0
            print(f"  {tokens:>7,} tok  ({bar_pct:4.1f}%)  {name}  [{chars:,} chars]")
        print()

    print(f"{'='*72}")
    print(f"TOTAL TOKENS: {grand_total:,}")
    print(f"  (this equals the real usage.cache_creation_input_tokens from the captured")
    print(f"   response — the exact one-time cost of building this session's prompt")
    print(f"   cache. Per-row numbers above are that real total, prorated by each")
    print(f"   row's share of total characters — see module docstring for why.)")
    if betas:
        print(f"betas ({len(betas)} flags): {', '.join(betas)}")
    if data.get("thinking"):
        print(f"thinking config: {data['thinking']}")
    print(f"{'='*72}\n")

    # Top offenders across all sections
    print("Top 10 heaviest items overall:")
    for section, name, tokens, chars, preview in sorted(rows, key=lambda r: -r[2])[:10]:
        print(f"  {tokens:>7,} tok  [{section}] {name}")

    # --- suggested fixes ---
    extra_md = []  # markdown lines for SUGGESTED FIXES / MCP SERVERS / SKILLS, mirrored into the .md report

    tool_rows = sorted(by_section.get("tools", []), key=lambda e: -e[1])
    # Heaviest, discretionary tools worth flagging: >1% of grand total each,
    # excluding core tools whose removal would cripple normal operation.
    heavy_tools = [(name, tokens) for name, tokens, _, _ in tool_rows
                   if grand_total and tokens / grand_total > 0.01 and name not in CORE_TOOLS]
    skipped_core = [(name, tokens) for name, tokens, _, _ in tool_rows
                    if grand_total and tokens / grand_total > 0.01 and name in CORE_TOOLS]

    if heavy_tools:
        print(f"\n{'='*72}")
        print("SUGGESTED FIXES (tools contributing >1% of total each)")
        print(f"{'='*72}\n")
        print("Every tool schema below is a `permissions.deny` bare-name candidate.\n"
              "Documented mechanism (see SKILL.md): a bare tool name in permissions.deny\n"
              "removes the tool's schema from the request entirely, not just blocks its\n"
              "use at call time.\n")

        extra_md.append("## SUGGESTED FIXES (tools contributing >1% of total each)")
        extra_md.append("")

        print("Scanning session history for actual usage of these tools...", file=sys.stderr)
        tool_usage, skill_usage, mcp_usage = scan_tool_usage_history()

        never_used, recently_used = [], []

        for name, tokens in heavy_tools:
            pct = 100 * tokens / grand_total
            hint = disable_hint_for_tool(name)
            status = ""

            count, last_ts = tool_usage.get(name, (0, None))
            if count == 0:
                usage_note = "never called in local session history"
                never_used.append(name)
            else:
                usage_note = f"called {count}x, most recently {format_days_ago(last_ts)}"
                recently_used.append(name)

            print(f"  {name} — {tokens:,} tok ({pct:.1f}%){status}")
            print(f"      usage: {usage_note}")
            extra_md.append(f"- **{name}** — {tokens:,} tok ({pct:.1f}%){status} — {usage_note}")
            if hint:
                for h in hint:
                    print(f"      -> {h}")
                    extra_md.append(f"  - fix: {h}")
            else:
                print(f'      -> add "{name}" to permissions.deny in settings.json:')
                print(f'         {{"permissions": {{"deny": ["{name}"]}}}}')
                extra_md.append(f'  - fix: add `"{name}"` to `permissions.deny` in settings.json')
            print()

        if never_used:
            never_used_tokens = sum(t for n, t in heavy_tools if n in never_used)
            print(f"Safe-to-disable now (never used in local history) — "
                  f"{never_used_tokens:,} tok saved:")
            print(json.dumps({"permissions": {"deny": never_used}}, indent=2))
            print()
            extra_md.append("")
            extra_md.append(f"**Safe-to-disable now (never used locally)** — {never_used_tokens:,} tok saved:")
            extra_md.append("```json")
            extra_md.append(json.dumps({"permissions": {"deny": never_used}}, indent=2))
            extra_md.append("```")
        if recently_used:
            print(f"Used recently — confirm you don't need these before disabling: "
                  f"{', '.join(recently_used)}")
            extra_md.append("")
            extra_md.append(f"**Used recently — confirm before disabling:** {', '.join(recently_used)}")
    else:
        print("\nNo discretionary tool exceeds 1% of total tokens — no specific fix to suggest.")
        print("Scanning session history for MCP/skill usage anyway...", file=sys.stderr)
        tool_usage, skill_usage, mcp_usage = scan_tool_usage_history()
        extra_md.append("## SUGGESTED FIXES")
        extra_md.append("")
        extra_md.append("No discretionary tool exceeds 1% of total tokens — no specific fix to suggest.")

    if skipped_core:
        print(f"\n(Not suggesting: {', '.join(n for n, _ in skipped_core)} — core tools, "
              f"disabling these would break normal operation, not just save tokens.)")
        extra_md.append("")
        extra_md.append(f"_(Not suggesting: {', '.join(n for n, _ in skipped_core)} — core tools.)_")

    # --- MCP servers by usage recency (independent of the >1%-of-total cut,
    # since a whole server may be cheap individually but still dead weight) ---
    catalog_rows = by_section.get("catalog", [])
    mcp_rows = [(name[4:], tokens) for name, tokens, _, _ in catalog_rows if name.startswith("mcp:")]
    skill_rows = [(name[6:], tokens) for name, tokens, _, _ in catalog_rows if name.startswith("skill:")]

    enabled_plugins = load_enabled_plugins()

    if mcp_rows:
        print(f"\n{'='*72}")
        print("MCP SERVERS — token cost vs. last-used")
        print(f"{'='*72}\n")
        extra_md.append("")
        extra_md.append("## MCP SERVERS — token cost vs. last-used")
        extra_md.append("")
        extra_md.append("| Server | Tokens | Usage | Fix |")
        extra_md.append("|---|---|---|---|")
        for server_name, tokens in sorted(mcp_rows, key=lambda e: -e[1]):
            short = server_name.split(":")[-1] if ":" in server_name else server_name
            count, last_ts = mcp_usage.get(short, (0, None))
            label = usage_bucket_label(count, last_ts)
            plugin_key = guess_plugin_key(server_name, enabled_plugins)
            print(f"  {server_name} — {tokens:,} tok — {label}")
            fix = ""
            if count == 0:
                fix = f'disable plugin "{plugin_key}"' if plugin_key else "disable the plugin/MCP server providing this"
                print(f"      -> {fix} in settings.json enabledPlugins, or `/mcp` to manage it")
                if short.startswith("claude_ai_") or server_name.startswith("claude_ai_"):
                    print(f"      -> or blanket-disable all claude.ai connectors at once: "
                          f"{DISABLE_CLAUDE_AI_CONNECTORS_HINT}")
                    fix += f"; {DISABLE_CLAUDE_AI_CONNECTORS_HINT}"
            else:
                # Server is actively used — check if any of its individual tools
                # are never called (partial disable via per-tool permissions.deny).
                server_prefix = f"mcp__{short}__"
                server_tools_in_request = [
                    t.get("name") for t in data.get("tools", [])
                    if (t.get("name") or "").startswith(server_prefix)
                ]
                never_called_tools = [
                    t for t in server_tools_in_request
                    if tool_usage.get(t, (0, None))[0] == 0
                ]
                if never_called_tools:
                    print(f"      Server is used — but these specific tools are never called "
                          f"and could be denied individually:")
                    for nt in never_called_tools:
                        print(f"        -> add \"{nt}\" to permissions.deny")
                    fix = f"server used; consider per-tool deny for: {', '.join(never_called_tools)}"
            extra_md.append(f"| {md_escape(server_name)} | {tokens:,} | {md_escape(label)} | {md_escape(fix)} |")
        print()

    if skill_rows:
        print(f"\n{'='*72}")
        print("SKILLS — token cost vs. last-invoked")
        print(f"{'='*72}\n")
        extra_md.append("")
        extra_md.append("## SKILLS — token cost vs. last-invoked")
        extra_md.append("")
        extra_md.append("| Skill | Tokens | Usage |")
        extra_md.append("|---|---|---|")
        for skill_name, tokens in sorted(skill_rows, key=lambda e: -e[1]):
            count, last_ts = skill_usage.get(skill_name, (0, None))
            label = usage_bucket_label(count, last_ts)
            print(f"  {skill_name} — {tokens:,} tok — {label}")
            extra_md.append(f"| {md_escape(skill_name)} | {tokens:,} | {md_escape(label)} |")
        print("\n(Skills only cost tokens for their one-line catalog entry above "
              "unless invoked — the full SKILL.md loads on demand. Removing an "
              "unused skill from a plugin's skills/ dir, or disabling the plugin "
              "entirely, saves that one line's tokens per request.)")
        extra_md.append("")
        extra_md.append("_(Skills only cost tokens for their one-line catalog entry unless "
                         "invoked — the full SKILL.md loads on demand.)_")

        never_used_skills = [s for s, t in skill_rows if skill_usage.get(s, (0, None))[0] == 0]
        if len(never_used_skills) >= 2:
            print(f"\n  {len(never_used_skills)} skills never invoked locally: "
                  f"{', '.join(never_used_skills)}")
            print(f"  If most of these are Anthropic's bundled skills (dataviz, review, init, "
                  f"etc.), a single flag cuts all of them at once: {DISABLE_BUNDLED_SKILLS_HINT}")
            extra_md.append("")
            extra_md.append(f"**{len(never_used_skills)} skills never invoked:** "
                             f"{', '.join(md_escape(s) for s in never_used_skills)}  ")
            extra_md.append(DISABLE_BUNDLED_SKILLS_HINT)

    # --- /context comparison note ---
    # Claude Code's own `/context` command, on endpoints where count_tokens
    # ignores `system`/`tools` (see NOTE at startup), silently reports 0
    # tokens for every MCP tool instead of erroring or estimating — verified
    # empirically (2026-08) by comparing a real `/context` run against this
    # script's output on the same session: /context showed 16.5k total with
    # every mcp__* tool listed as "0 tokens", while this script measured the
    # same tools at ~30-42k tokens via the text-workaround tokenizer path.
    # /context is not a second opinion here — it's very likely hitting the
    # exact same broken count_tokens endpoint, just failing silently instead
    # of falling back like this script does.
    mcp_tool_count = sum(1 for t in data.get("tools", []) if MCP_TOOL_RE.match(t.get("name", "")))
    if mcp_tool_count:
        print(f"\n{'='*72}")
        print("NOTE ON /context COMPARISON")
        print(f"{'='*72}\n")
        note = (
            f"This session has {mcp_tool_count} MCP tools. Claude Code's own /context command\n"
            "shows every MCP tool as \"0 tokens\" in its category breakdown — that's a real\n"
            "bug in /context's attribution, not a sign this report is wrong. /context's TOTAL\n"
            "is correct (it's the same cache_creation_input_tokens this report is calibrated\n"
            "against), but the per-category rows below that total dump the whole real MCP-tool\n"
            "cost into \"Messages\" instead of \"MCP tools\", because it can't attribute it\n"
            "correctly. Use this report's TOOLS section, not /context's MCP tools list, to see\n"
            "which specific tool schemas are actually costing you tokens."
        )
        print(note)
        print()
        extra_md.append("## NOTE ON /context COMPARISON")
        extra_md.append("")
        extra_md.append(note.replace("\n", "  \n"))
        extra_md.append("")

    # --- tool search status ---
    print(f"\n{'='*72}")
    print("TOOL SEARCH STATUS")
    print(f"{'='*72}\n")
    ts_md = ["## TOOL SEARCH STATUS", ""]

    disable_betas = os.environ.get("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "")
    betas_blocking = disable_betas.strip().lower() not in ("", "0", "false")

    settings_paths = [
        os.path.expanduser("~/.claude/settings.json"),
        os.path.expanduser("~/.claude/settings.local.json"),
    ]
    tool_search_enabled = False
    tool_search_toplevel_only = False  # set in wrong location (top-level instead of env block)
    for sp in settings_paths:
        if os.path.exists(sp):
            try:
                d = json.load(open(sp))
                in_env = bool(d.get("env", {}).get("ENABLE_TOOL_SEARCH"))
                at_toplevel = bool(d.get("ENABLE_TOOL_SEARCH"))
                if in_env:
                    tool_search_enabled = True
                    tool_search_toplevel_only = False
                elif at_toplevel and not tool_search_enabled:
                    tool_search_toplevel_only = True
            except Exception:
                pass
    if tool_search_toplevel_only:
        tool_search_enabled = True  # "found" but in wrong place

    tool_search_tool_present = any(
        t.get("name") == "ToolSearch" or t.get("name") == "ToolSearchTool"
        for t in data.get("tools", [])
    )

    if betas_blocking:
        status = "BLOCKED"
        detail = (f"CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS={disable_betas!r} "
                  f"overrides ENABLE_TOOL_SEARCH — tool search silently disabled "
                  f"regardless of settings.json. Unset or set to '0'/'false' to re-enable.")
    elif not tool_search_enabled:
        status = "NOT CONFIGURED"
        detail = ('ENABLE_TOOL_SEARCH not found in settings.json. '
                  'Add it to the env block: {"env": {"ENABLE_TOOL_SEARCH": "true"}}')
    elif tool_search_toplevel_only:
        status = "MISCONFIGURED (top-level key, not in env block)"
        detail = ('ENABLE_TOOL_SEARCH is set as a top-level settings.json key — '
                  'schema validator rejects it and Claude Code silently ignores it. '
                  'Move it inside the env block: {"env": {"ENABLE_TOOL_SEARCH": "true"}}')
    elif tool_search_tool_present:
        status = "ENABLED (ToolSearchTool present in request)"
        detail = "Tool search active — the TOOLS section above reflects reduced per-turn schema cost."
    else:
        status = "CONFIGURED but ToolSearchTool absent from request"
        detail = ("ENABLE_TOOL_SEARCH set correctly in env block but ToolSearchTool not in probe "
                  "request's tool list. Likely blocked by org-managed policy "
                  "(managed-settings.json / feature gate). Not fixable locally — flag to whoever "
                  "manages the deployment.")

    print(f"  Status: {status}")
    print(f"  {detail}")
    print()
    ts_md.append(f"**Status: {status}**  ")
    ts_md.append(detail)
    ts_md.append("")
    ts_md.append("Tool search is the single biggest lever — it sends only relevant tool schemas per turn")
    ts_md.append("instead of all schemas on every request. If TOOLS dominates, fix this before per-tool deny rules.")
    extra_md += ts_md

    out_path = write_markdown_report(data, by_section, grand_total, extra_md)
    print(f"\nFull overview written to: {out_path}")


if __name__ == "__main__":
    main()
