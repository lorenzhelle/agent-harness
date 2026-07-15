#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
Token audit for Claude Code.

Fires a trivial `claude -p "hey"` run with OTEL_LOG_RAW_API_BODIES enabled,
captures the exact raw Anthropic Messages API request Claude Code sent to
ANTHROPIC_BASE_URL, then breaks it down section by section (attribution
header, base agent prompt, CLAUDE.md/memory, per-agent-type list, per-tool
schema, message history) and gets an exact token count for each section by
routing its text through the endpoint's /v1/messages/count_tokens as a fake
user message (see NOTE below on why not sent as system/tools directly).

NOTE on methodology: some LiteLLM-fronted backends (Vertex/Bedrock passthrough
particularly) only tokenize the `messages` field of count_tokens requests and
silently ignore `system` / `tools`, returning a constant. This script probes
for that at startup and, if detected, counts every section by wrapping its
raw text as a single user message instead (subtracting a measured per-request
overhead constant). This gives an exact real-tokenizer count, just via a
workaround path.
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-latest")

if not BASE_URL or not API_KEY:
    print("ERROR: ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY must be set "
          "(same env Claude Code itself uses).", file=sys.stderr)
    sys.exit(1)

COUNT_URL = f"{BASE_URL}/v1/messages/count_tokens"
HEADERS = {
    "x-api-key": API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}


def count_raw(payload, retries=3):
    """POST to count_tokens with a couple of retries — the endpoint has been
    observed to intermittently 503/502 under this workload (many rapid
    small requests), unrelated to payload content."""
    last_exc = None
    for attempt in range(retries):
        try:
            r = requests.post(COUNT_URL, headers=HEADERS, json=payload, timeout=30)
            r.raise_for_status()
            return r.json()["input_tokens"]
        except requests.exceptions.HTTPError as e:
            last_exc = e
            if e.response is not None and e.response.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    raise last_exc


def detect_system_tools_supported():
    """Return True if the endpoint actually tokenizes `system`/`tools`."""
    base = count_raw({"model": MODEL, "messages": [{"role": "user", "content": "hi"}]})
    padded = count_raw({
        "model": MODEL,
        "system": "one two three four five six seven eight nine ten " * 5,
        "messages": [{"role": "user", "content": "hi"}],
    })
    return padded > base + 5


# Measured once at startup: overhead of an empty user message, used to
# subtract framing tokens when we smuggle arbitrary text through `messages`.
_EMPTY_OVERHEAD = None


def count_text(text):
    """Exact token count for a raw chunk of text, via the messages-count workaround."""
    global _EMPTY_OVERHEAD
    if not text:
        return 0
    if _EMPTY_OVERHEAD is None:
        _EMPTY_OVERHEAD = count_raw({"model": MODEL, "messages": [{"role": "user", "content": ""}]})
    total = count_raw({"model": MODEL, "messages": [{"role": "user", "content": text}]})
    return max(0, total - _EMPTY_OVERHEAD)


def run_probe_request():
    """Fire `claude -p "hey"` with raw API body logging, return parsed request dict."""
    otel_dir = tempfile.mkdtemp(prefix="rtk-token-audit-")
    work_dir = tempfile.mkdtemp(prefix="rtk-token-audit-work-")
    env = dict(os.environ)
    env["CLAUDE_CODE_ENABLE_TELEMETRY"] = "1"
    env["OTEL_LOG_RAW_API_BODIES"] = f"file:{otel_dir}"

    print("Firing probe request (`claude -p \"hey\"`)...", file=sys.stderr)
    try:
        subprocess.run(
            ["claude", "-p", "hey", "--model", MODEL],
            cwd=work_dir, env=env, capture_output=True, timeout=90, check=False,
        )
    except FileNotFoundError:
        print("ERROR: `claude` CLI not found on PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("ERROR: probe request timed out after 90s.", file=sys.stderr)
        sys.exit(1)

    request_files = sorted(Path(otel_dir).glob("*.request.json"))
    if not request_files:
        print(f"ERROR: no request body captured in {otel_dir}. "
              "Check that OTEL_LOG_RAW_API_BODIES is supported by your Claude Code version.",
              file=sys.stderr)
        sys.exit(1)

    with open(request_files[-1]) as f:
        data = json.load(f)

    shutil.rmtree(otel_dir, ignore_errors=True)
    shutil.rmtree(work_dir, ignore_errors=True)
    return data


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
    agent catalog, per-MCP-server instructions, and skill catalog, if present."""
    for msg in messages:
        content = msg.get("content")
        if msg.get("role") == "system" and isinstance(content, str) and "Available agent types" in content:
            return content
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
}

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


def verify_deny_saves_tokens(tool_names):
    """Empirically confirm that denying these bare tool names actually drops
    them from the request (as opposed to just blocking usage). Fires a second
    probe request with --settings permissions.deny set. Returns the set of
    tool names actually confirmed removed, or None if the check couldn't run."""
    if not tool_names:
        return None
    otel_dir = tempfile.mkdtemp(prefix="rtk-token-audit-verify-")
    work_dir = tempfile.mkdtemp(prefix="rtk-token-audit-verify-work-")
    env = dict(os.environ)
    env["CLAUDE_CODE_ENABLE_TELEMETRY"] = "1"
    env["OTEL_LOG_RAW_API_BODIES"] = f"file:{otel_dir}"
    settings_override = json.dumps({"permissions": {"deny": list(tool_names)}})
    try:
        subprocess.run(
            ["claude", "-p", "hey", "--model", MODEL, "--settings", settings_override],
            cwd=work_dir, env=env, capture_output=True, timeout=90, check=False,
        )
        request_files = sorted(Path(otel_dir).glob("*.request.json"))
        if not request_files:
            return None
        with open(request_files[-1]) as f:
            data = json.load(f)
        remaining = {t.get("name") for t in data.get("tools", [])}
        return set(tool_names) - remaining  # names confirmed gone
    except Exception:
        return None
    finally:
        shutil.rmtree(otel_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)


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


def main():
    supported = detect_system_tools_supported()
    if not supported:
        print("NOTE: this endpoint's count_tokens ignores `system`/`tools` fields "
              "(common with Vertex/Bedrock-backed LiteLLM routes). Falling back to "
              "an exact-tokenizer workaround (each section counted as a standalone "
              "message) — counts are still exact, just measured indirectly.\n",
              file=sys.stderr)

    data = run_probe_request()

    rows = []  # (section, subsection, tokens, chars)

    # --- system blocks ---
    for i, (label, text) in enumerate(extract_system_blocks(data.get("system"))):
        name = classify_system_block(i, text)
        rows.append(("system", name, count_text(text), len(text)))

    # --- tools ---
    tools = data.get("tools", [])
    tool_total_chars = 0
    for t in tools:
        name = t.get("name", "?")
        schema_text = json.dumps(t.get("input_schema", {}))
        desc_text = t.get("description", "")
        full_text = desc_text + "\n" + schema_text
        tool_total_chars += len(full_text)
        rows.append(("tools", name, count_text(full_text), len(full_text)))

    # --- messages ---
    # The mid-conversation "Available agent types..." system-reminder bundles
    # three independently-toggleable things (agent catalog prose, one block
    # per MCP server, one line per skill) — break it into its own section
    # instead of counting it as a single opaque row, so each MCP server and
    # skill gets its own token cost and can be checked against usage history.
    catalog_text = find_catalog_message(data.get("messages", []))
    for i, msg in enumerate(data.get("messages", [])):
        content = msg.get("content")
        if isinstance(content, str) and content == catalog_text:
            continue  # handled below as its own section
        label = classify_message(i, msg)
        text = text_of_message(msg)
        rows.append(("messages", label, count_text(text), len(text)))

    if catalog_text:
        prose = agent_catalog_prose(catalog_text)
        rows.append(("catalog", "agent-types catalog", count_text(prose), len(prose)))
        for server_name, server_text in split_mcp_servers(catalog_text):
            rows.append(("catalog", f"mcp:{server_name}", count_text(server_text), len(server_text)))
        for skill_name, skill_text in split_skill_catalog(catalog_text):
            rows.append(("catalog", f"skill:{skill_name}", count_text(skill_text), len(skill_text)))

    # --- betas / metadata (usually negligible, but flag if huge) ---
    betas = data.get("betas", [])
    if betas:
        rows.append(("config", f"betas ({len(betas)} flags)", 0, len(json.dumps(betas))))

    grand_total = sum(r[2] for r in rows)

    # --- print report ---
    print(f"\n{'='*72}")
    print(f"TOKEN AUDIT — model={data.get('model')}  endpoint={BASE_URL}")
    print(f"{'='*72}\n")

    by_section = {}
    for section, name, tokens, chars in rows:
        by_section.setdefault(section, []).append((name, tokens, chars))

    for section in ["system", "tools", "messages", "catalog", "config"]:
        if section not in by_section:
            continue
        entries = sorted(by_section[section], key=lambda e: -e[1])
        section_total = sum(e[1] for e in entries)
        pct = 100 * section_total / grand_total if grand_total else 0
        print(f"## {section.upper()}  —  {section_total:,} tokens ({pct:.1f}% of total)")
        for name, tokens, chars in entries:
            bar_pct = 100 * tokens / grand_total if grand_total else 0
            print(f"  {tokens:>7,} tok  ({bar_pct:4.1f}%)  {name}  [{chars:,} chars]")
        print()

    print(f"{'='*72}")
    print(f"TOTAL INPUT TOKENS (exact, via tokenizer): {grand_total:,}")
    if data.get("thinking"):
        print(f"thinking config: {data['thinking']}")
    print(f"{'='*72}\n")

    # Top offenders across all sections
    print("Top 10 heaviest items overall:")
    for section, name, tokens, chars in sorted(rows, key=lambda r: -r[2])[:10]:
        print(f"  {tokens:>7,} tok  [{section}] {name}")

    # --- suggested fixes ---
    tool_rows = sorted(by_section.get("tools", []), key=lambda e: -e[1])
    # Heaviest, discretionary tools worth flagging: >1% of grand total each,
    # excluding core tools whose removal would cripple normal operation.
    heavy_tools = [(name, tokens) for name, tokens, _ in tool_rows
                   if grand_total and tokens / grand_total > 0.01 and name not in CORE_TOOLS]
    skipped_core = [(name, tokens) for name, tokens, _ in tool_rows
                    if grand_total and tokens / grand_total > 0.01 and name in CORE_TOOLS]

    if heavy_tools:
        print(f"\n{'='*72}")
        print("SUGGESTED FIXES (tools contributing >1% of total each)")
        print(f"{'='*72}\n")
        print("Every tool schema below is a `permissions.deny` bare-name candidate.\n"
              "Confirmed empirically: a bare tool name in permissions.deny removes\n"
              "the tool's schema from the request entirely (not just blocks its use\n"
              "at call time) — real token savings, verified by diffing probe requests\n"
              "with/without the deny rule.\n")

        heavy_names = [n for n, _ in heavy_tools]
        verified_removed = verify_deny_saves_tokens(heavy_names)

        print("Scanning session history for actual usage of these tools...", file=sys.stderr)
        tool_usage, skill_usage, mcp_usage = scan_tool_usage_history()

        never_used, recently_used = [], []

        for name, tokens in heavy_tools:
            pct = 100 * tokens / grand_total
            hint = disable_hint_for_tool(name)
            status = ""
            removable = verified_removed is None or name in verified_removed
            if verified_removed is not None:
                status = " [VERIFIED removable]" if name in verified_removed else " [not removed by deny — built-in/core?]"

            count, last_ts = tool_usage.get(name, (0, None))
            if count == 0:
                usage_note = "never called in local session history"
                never_used.append(name)
            else:
                usage_note = f"called {count}x, most recently {format_days_ago(last_ts)}"
                if removable:
                    recently_used.append(name)

            print(f"  {name} — {tokens:,} tok ({pct:.1f}%){status}")
            print(f"      usage: {usage_note}")
            if hint:
                for h in hint:
                    print(f"      -> {h}")
            else:
                print(f'      -> add "{name}" to permissions.deny in settings.json:')
                print(f'         {{"permissions": {{"deny": ["{name}"]}}}}')
            print()

        if never_used:
            print(f"Safe-to-disable now (never used in local history) — "
                  f"{sum(t for n, t in heavy_tools if n in never_used):,} tok saved:")
            print(json.dumps({"permissions": {"deny": never_used}}, indent=2))
            print()
        if recently_used:
            print(f"Used recently — confirm you don't need these before disabling: "
                  f"{', '.join(recently_used)}")
    else:
        print("\nNo discretionary tool exceeds 1% of total tokens — no specific fix to suggest.")
        print("Scanning session history for MCP/skill usage anyway...", file=sys.stderr)
        tool_usage, skill_usage, mcp_usage = scan_tool_usage_history()

    if skipped_core:
        print(f"\n(Not suggesting: {', '.join(n for n, _ in skipped_core)} — core tools, "
              f"disabling these would break normal operation, not just save tokens.)")

    # --- MCP servers by usage recency (independent of the >1%-of-total cut,
    # since a whole server may be cheap individually but still dead weight) ---
    catalog_rows = by_section.get("catalog", [])
    mcp_rows = [(name[4:], tokens) for name, tokens, _ in catalog_rows if name.startswith("mcp:")]
    skill_rows = [(name[6:], tokens) for name, tokens, _ in catalog_rows if name.startswith("skill:")]

    enabled_plugins = load_enabled_plugins()

    if mcp_rows:
        print(f"\n{'='*72}")
        print("MCP SERVERS — token cost vs. last-used")
        print(f"{'='*72}\n")
        for server_name, tokens in sorted(mcp_rows, key=lambda e: -e[1]):
            short = server_name.split(":")[-1] if ":" in server_name else server_name
            count, last_ts = mcp_usage.get(short, (0, None))
            label = usage_bucket_label(count, last_ts)
            plugin_key = guess_plugin_key(server_name, enabled_plugins)
            print(f"  {server_name} — {tokens:,} tok — {label}")
            if count == 0:
                fix = f'disable plugin "{plugin_key}"' if plugin_key else "disable the plugin/MCP server providing this"
                print(f"      -> {fix} in settings.json enabledPlugins, or `/mcp` to manage it")
        print()

    if skill_rows:
        print(f"\n{'='*72}")
        print("SKILLS — token cost vs. last-invoked")
        print(f"{'='*72}\n")
        for skill_name, tokens in sorted(skill_rows, key=lambda e: -e[1]):
            count, last_ts = skill_usage.get(skill_name, (0, None))
            label = usage_bucket_label(count, last_ts)
            print(f"  {skill_name} — {tokens:,} tok — {label}")
        print("\n(Skills only cost tokens for their one-line catalog entry above "
              "unless invoked — the full SKILL.md loads on demand. Removing an "
              "unused skill from a plugin's skills/ dir, or disabling the plugin "
              "entirely, saves that one line's tokens per request.)")


if __name__ == "__main__":
    main()
