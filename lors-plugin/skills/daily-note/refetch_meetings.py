#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["icalendar", "requests", "recurring-ical-events"]
# ///
"""
refetch_meetings.py - Aktualisiert die Meetings-Sektion in einer Obsidian Daily Note.

Holt den aktuellen Kalender, vergleicht mit bestehenden Meeting-Blöcken und:
- Fügt neue Meetings hinzu
- Entfernt gecancelte Meetings (Titel-Match)
- Verschiebt vorhandene Meeting-Notizen an die neue Zeitposition

Usage:
    python refetch_meetings.py              # Heute
    python refetch_meetings.py --tomorrow
    python refetch_meetings.py --date YYYY-MM-DD
"""

import argparse
import os
import re
from datetime import date, timedelta, datetime

import requests
from icalendar import Calendar
import recurring_ical_events


VAULT_ROOT = "/mnt/c/Users/lhelle/Documents/para-vault/Daily Notes"
ICS_URLS = [
    "https://outlook.office365.com/owa/calendar/dc40573ee407482dab7bd1d3369f8a58@libri.de/332b20a1ab084aba9add674b25921b2c2431110006149550985/calendar.ics",
    "https://outlook.office365.com/owa/calendar/070b9b43f03648939e2577402922a5c9@netlight.com/2f09c0315ea74b729ac60711ec78a57d15135075663695882613/calendar.ics",
]

# Matches: ## HH:MM-HH:MM Title  or  ## ganztägig Title
MEETING_HEADING_RE = re.compile(
    r"^## (?:(\d{2}:\d{2}(?:-\d{2}:\d{2})?|ganztägig)) (.+)$"
)


def fetch_events(ics_url: str, target_date: date) -> list[dict]:
    response = requests.get(ics_url, timeout=30)
    response.raise_for_status()

    cal = Calendar.from_ical(response.content)
    components = recurring_ical_events.of(cal).at(target_date)

    events = []
    for component in components:
        if component.name != "VEVENT":
            continue

        dtstart = component.get("DTSTART")
        dtend = component.get("DTEND")
        summary = str(component.get("SUMMARY", "Kein Titel"))

        if dtstart is None:
            continue
        if summary.startswith("Blocker for"):
            continue

        start_dt = dtstart.dt
        end_dt = dtend.dt if dtend else None

        if isinstance(start_dt, datetime):
            if start_dt.tzinfo is not None:
                start_dt = start_dt.astimezone().replace(tzinfo=None)
            start_time = start_dt.strftime("%H:%M")
        else:
            start_time = None

        if isinstance(end_dt, datetime):
            if end_dt.tzinfo is not None:
                end_dt = end_dt.astimezone().replace(tzinfo=None)
            end_time = end_dt.strftime("%H:%M")
        elif isinstance(end_dt, date):
            end_time = None
        else:
            end_time = None

        events.append({
            "summary": summary,
            "start_time": start_time,
            "end_time": end_time,
            "start_dt": start_dt,
        })

    return events


def format_meeting_heading(event: dict) -> str:
    if event["start_time"] and event["end_time"]:
        time_str = f"{event['start_time']}-{event['end_time']}"
    elif event["start_time"]:
        time_str = event["start_time"]
    else:
        time_str = "ganztägig"
    return f"## {time_str} {event['summary']}"


def parse_meeting_blocks(lines: list[str]) -> list[dict]:
    """
    Split content into blocks. Each block is either a meeting block or non-meeting content.
    Returns list of dicts: {type: 'meeting'|'other', heading: str|None, title: str|None, body_lines: list[str]}
    """
    blocks = []
    current_block = {"type": "other", "heading": None, "title": None, "body_lines": []}

    for line in lines:
        m = MEETING_HEADING_RE.match(line)
        if m:
            if current_block["body_lines"] or current_block["heading"]:
                blocks.append(current_block)
            current_block = {
                "type": "meeting",
                "heading": line,
                "title": m.group(2).strip(),
                "body_lines": [],
            }
        else:
            current_block["body_lines"].append(line)

    if current_block["body_lines"] or current_block["heading"]:
        blocks.append(current_block)

    return blocks


def refetch_meetings(note_path: str, events: list[dict]) -> None:
    if not os.path.exists(note_path):
        print(f"Note nicht gefunden: {note_path}")
        return

    with open(note_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines(keepends=True)
    stripped_lines = [l.rstrip("\n") for l in lines]

    # Find meetings start: either "Meetings:" label or first ## HH:MM heading
    meetings_start = None
    has_meetings_label = False
    for i, line in enumerate(stripped_lines):
        if line.strip() == "Meetings:":
            meetings_start = i
            has_meetings_label = True
            break
        if MEETING_HEADING_RE.match(line):
            meetings_start = i
            break

    if meetings_start is None:
        print("Keine Meetings gefunden. Nutze inject_meetings.py für erste Einbettung.")
        return

    # Split note: before meetings section, and from meetings section onward
    before_meetings = stripped_lines[:meetings_start]
    if has_meetings_label:
        meetings_content = stripped_lines[meetings_start + 1:]  # skip "Meetings:" line
        while meetings_content and meetings_content[0].strip() == "":
            meetings_content = meetings_content[1:]
    else:
        meetings_content = stripped_lines[meetings_start:]

    # Parse existing meeting blocks from the meetings section
    existing_blocks = parse_meeting_blocks(meetings_content)

    # Build title -> existing body map for meetings
    existing_notes: dict[str, list[str]] = {}
    for block in existing_blocks:
        if block["type"] == "meeting" and block["title"]:
            body = block["body_lines"]
            # Strip trailing blank lines from body
            while body and body[-1].strip() == "":
                body = body[:-1]
            if body:
                existing_notes[block["title"]] = body

    # Build new meetings section using fresh calendar events
    new_meetings_lines = []
    for event in events:
        heading = format_meeting_heading(event)
        new_meetings_lines.append(heading)
        title = event["summary"]
        if title in existing_notes:
            new_meetings_lines.append("")
            new_meetings_lines.extend(existing_notes[title])
            print(f"  Notizen beibehalten: {heading}")
        new_meetings_lines.append("")  # blank line after each block

    if not events:
        new_meetings_lines.append("*(keine Termine)*")
        new_meetings_lines.append("")

    # Report meetings whose notes existed but are no longer in calendar
    removed_titles = set(existing_notes.keys()) - {e["summary"] for e in events}
    for title in removed_titles:
        print(f"  WARNUNG: Meeting '{title}' nicht mehr im Kalender, Notizen verworfen:")
        for line in existing_notes[title]:
            print(f"    {line}")

    # Reconstruct full note
    while before_meetings and before_meetings[-1].strip() == "":
        before_meetings.pop()

    if has_meetings_label:
        separator = ["Meetings:", ""]
    else:
        separator = [""]

    new_content_lines = before_meetings + separator + new_meetings_lines

    # Remove trailing blank lines at end of file, add single newline
    while new_content_lines and new_content_lines[-1].strip() == "":
        new_content_lines.pop()

    with open(note_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_content_lines) + "\n")

    print(f"Meetings aktualisiert: {len(events)} Termin(e) in {note_path}")
    for e in events:
        print(f"  {format_meeting_heading(e)}")


def main():
    parser = argparse.ArgumentParser(description="Refetch and update meetings in Obsidian Daily Note")
    parser.add_argument("--tomorrow", action="store_true")
    parser.add_argument("--date", help="YYYY-MM-DD")
    args = parser.parse_args()

    if args.date:
        target_date = date.fromisoformat(args.date)
    elif args.tomorrow:
        target_date = date.today() + timedelta(days=1)
    else:
        target_date = date.today()

    note_path = os.path.join(VAULT_ROOT, target_date.strftime("%Y-%m-%d") + ".md")

    print(f"Datum: {target_date}, Note: {note_path}")
    print("Lade ICS-Feeds...")

    events = []
    for url in ICS_URLS:
        try:
            events.extend(fetch_events(url, target_date))
        except Exception as e:
            print(f"Warnung: Kalender konnte nicht geladen werden ({url[:60]}...): {e}")

    events.sort(key=lambda e: e["start_dt"] if isinstance(e["start_dt"], datetime) else datetime.combine(e["start_dt"], datetime.min.time()))

    refetch_meetings(note_path, events)


if __name__ == "__main__":
    main()
