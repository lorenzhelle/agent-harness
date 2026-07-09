#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["icalendar", "requests", "recurring-ical-events"]
# ///
"""
inject_meetings.py - Injects Outlook meetings from ICS feed into Obsidian Daily Notes

Usage:
    python inject_meetings.py                  # Today's note
    python inject_meetings.py --tomorrow       # Tomorrow's note
    python inject_meetings.py --date YYYY-MM-DD
"""

import argparse
import os
from datetime import date, timedelta, datetime

import requests
from icalendar import Calendar
import recurring_ical_events


VAULT_ROOT = "/mnt/c/Users/lhelle/Documents/para-vault/Daily Notes"
ICS_URLS = [
    "https://outlook.office365.com/owa/calendar/dc40573ee407482dab7bd1d3369f8a58@libri.de/332b20a1ab084aba9add674b25921b2c2431110006149550985/calendar.ics",
    "https://outlook.office365.com/owa/calendar/070b9b43f03648939e2577402922a5c9@netlight.com/2f09c0315ea74b729ac60711ec78a57d15135075663695882613/calendar.ics",
]


def fetch_events(ics_url: str, target_date: date) -> list[dict]:
    response = requests.get(ics_url, timeout=30)
    response.raise_for_status()

    cal = Calendar.from_ical(response.content)
    # recurring_ical_events expandiert Serientermine (RRULE) automatisch
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
            start_time = None  # All-day event

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


def format_meeting_block(event: dict) -> str:
    if event["start_time"] and event["end_time"]:
        time_str = f"{event['start_time']}-{event['end_time']}"
    elif event["start_time"]:
        time_str = event["start_time"]
    else:
        time_str = "ganztägig"
    return f"## {time_str} {event['summary']}\n"


def inject_into_note(note_path: str, events: list[dict], target_date: date) -> None:
    meetings_section = "Meetings:\n\n"
    if events:
        for e in events:
            meetings_section += format_meeting_block(e) + "\n"
    else:
        meetings_section += "*(keine Termine)*\n"

    # Read or create the note
    if os.path.exists(note_path):
        with open(note_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "Meetings:" in content:
            print(f"Meetings-Sektion bereits vorhanden in {note_path}. Überspringe.")
            return

        if "Heute:" in content:
            new_content = content.rstrip() + "\n\n" + meetings_section
        else:
            new_content = meetings_section + "\n" + content
    else:
        new_content = "Heute:\n\n---\n\n" + meetings_section

    with open(note_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"Meetings eingetragen in {note_path} ({len(events)} Termin(e)).")
    for e in events:
        print(f"  {format_meeting_block(e).strip()}")


def main():
    parser = argparse.ArgumentParser(description="Inject Outlook meetings into Obsidian Daily Note")
    parser.add_argument("--tomorrow", action="store_true", help="Use tomorrow's note instead of today")
    parser.add_argument("--ics-url", help="ICS feed URL (overrides env var)")
    parser.add_argument("--date", help="Specific date (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.date:
        target_date = date.fromisoformat(args.date)
    elif args.tomorrow:
        target_date = date.today() + timedelta(days=1)
    else:
        target_date = date.today()

    note_path = os.path.join(VAULT_ROOT, target_date.strftime("%Y-%m-%d") + ".md")
    urls = [args.ics_url] if args.ics_url else ICS_URLS

    print(f"Datum: {target_date}, Note: {note_path}")
    print("Lade ICS-Feeds...")

    events = []
    for url in urls:
        try:
            events.extend(fetch_events(url, target_date))
        except Exception as e:
            print(f"Warnung: Kalender konnte nicht geladen werden ({url[:60]}...): {e}")
    events.sort(key=lambda e: e["start_dt"] if isinstance(e["start_dt"], datetime) else datetime.combine(e["start_dt"], datetime.min.time()))
    inject_into_note(note_path, events, target_date)


if __name__ == "__main__":
    main()
