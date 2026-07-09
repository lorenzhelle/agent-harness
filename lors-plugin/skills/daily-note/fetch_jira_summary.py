#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
fetch_jira_summary.py - Fetches active + backlog Jira tickets via `acli jira` and
prints a ready-to-paste "## Jira" markdown block for the daily note.

Usage:
    python fetch_jira_summary.py
"""

import json
import subprocess
import sys

PROJECT = "DATA"
BASE_URL = "https://libri-gmbh.atlassian.net/browse"
ACTIVE_JQL = (
    f'assignee = currentUser() AND project = {PROJECT} '
    f'AND status in ("In Arbeit", "Test", "In Review") AND issuetype != Epic'
)
BACKLOG_JQL = (
    f'assignee = currentUser() AND project = {PROJECT} '
    f'AND status in ("Backlog", "Ready for Dev") AND issuetype != Epic '
    f'ORDER BY created ASC'
)


def run_search(jql: str, limit: int) -> list[dict]:
    result = subprocess.run(
        [
            "acli", "jira", "workitem", "search",
            "--jql", jql,
            "--fields", "key,summary",
            "--limit", str(limit),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def ticket_line(item: dict, suffix: str = "") -> str:
    key = item["key"]
    summary = item["fields"]["summary"]
    return f"- [{key}]({BASE_URL}/{key}) {summary}{suffix}"


def main() -> None:
    try:
        active = run_search(ACTIVE_JQL, 20)
        backlog = run_search(BACKLOG_JQL, 3)
    except subprocess.CalledProcessError as e:
        print(f"acli error: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    lines = ["## Jira", ""]

    if active:
        lines.append("**In Arbeit / Test**")
        lines.extend(ticket_line(item) for item in active)
        lines.append("")

    if backlog:
        lines.append("> [!todo]- Backlog Erinnerung")
        for i, item in enumerate(backlog):
            suffix = " (ältestes)" if i == 0 else ""
            lines.append("> " + ticket_line(item, suffix))

    print("\n".join(lines))


if __name__ == "__main__":
    main()
