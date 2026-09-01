#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["icalendar", "requests", "recurring-ical-events"]
# ///
"""
create_focus_blocks.py - Fokusblock-Planung (Libri-only) für daily-note-libri.

Kein Netlight-Kontext, keine Kontext-Zonen — jeder freie Slot >= MIN_SLOT
zwischen den Libri-Meetings wird ein 🟢 Libri Fokus Block. Mittagspause wird
rausgeschnitten. Output: chronologisch sortierte Blöcke als Markdown.

Usage:
    python create_focus_blocks.py                   # Heute
    python create_focus_blocks.py --date YYYY-MM-DD
    python create_focus_blocks.py --dry-run
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, time

import requests
from icalendar import Calendar
import recurring_ical_events

N8N_WEBHOOK_URL = os.environ.get("N8N_FOCUS_WEBHOOK_URL", "http://localhost:5678/webhook/focus-blocks")
N8N_DELETE_WEBHOOK_URL = os.environ.get("N8N_FOCUS_DELETE_WEBHOOK_URL", "http://localhost:5678/webhook/focus-blocks-delete")

ICS_SOURCES = [
    ("Libri", "https://outlook.office365.com/owa/calendar/dc40573ee407482dab7bd1d3369f8a58@libri.de/332b20a1ab084aba9add674b25921b2c2431110006149550985/calendar.ics"),
]

WORK_START      = time(8, 0)
WORK_END        = time(17, 30)
MIN_SLOT        = 20   # Minuten — kleinster nützlicher freier Slot
LUNCH_START     = time(12, 0)
LUNCH_END       = time(13, 0)

SLACK_CHECK_TITLE      = "💬 Teams / Outlook Check"
SLACK_MORNING_DEADLINE = time(9, 15)   # Check muss vor diesem Meeting sein
SLACK_EVENING_START    = time(17, 0)
SLACK_DURATION_MIN     = 15


def fetch_events(target_date: date) -> list[dict]:
    """Gibt alle Libri-Events des Tages zurück."""
    events = []
    day_start = datetime.combine(target_date, WORK_START)
    day_end   = datetime.combine(target_date, WORK_END)

    for context, url in ICS_SOURCES:
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            cal = Calendar.from_ical(resp.content)
            for component in recurring_ical_events.of(cal).at(target_date):
                if component.name != "VEVENT":
                    continue
                dtstart = component.get("DTSTART")
                dtend   = component.get("DTEND")
                if not dtstart or not dtend:
                    continue

                start_dt = dtstart.dt
                end_dt   = dtend.dt
                if not isinstance(start_dt, datetime):
                    continue  # All-day

                if start_dt.tzinfo:
                    start_dt = start_dt.astimezone().replace(tzinfo=None)
                if end_dt.tzinfo:
                    end_dt = end_dt.astimezone().replace(tzinfo=None)

                if end_dt <= day_start or start_dt >= day_end:
                    continue

                summary = str(component.get("SUMMARY", ""))
                if summary.startswith("Blocker for"):
                    continue

                events.append({
                    "summary": summary,
                    "start":   max(start_dt, day_start),
                    "end":     min(end_dt,   day_end),
                })
        except Exception as e:
            print(f"Warnung: {context}-Kalender nicht geladen: {e}", file=sys.stderr)

    events.sort(key=lambda e: e["start"])
    return events


def merge_events(events: list[dict]) -> list[dict]:
    """Überlappende Events mergen."""
    if not events:
        return []
    merged = [events[0].copy()]
    for ev in events[1:]:
        last = merged[-1]
        if ev["start"] < last["end"]:
            last["end"] = max(last["end"], ev["end"])
        else:
            merged.append(ev.copy())
    return merged


def build_timeline(target_date: date, events: list[dict]) -> list[dict]:
    """Events + freie Slots als chronologische Timeline."""
    day_start = datetime.combine(target_date, WORK_START)
    day_end   = datetime.combine(target_date, WORK_END)

    timeline = []
    cursor = day_start

    for ev in events:
        if ev["start"] > cursor:
            timeline.append({"type": "free", "start": cursor, "end": ev["start"]})
        timeline.append({"type": "meeting", "summary": ev["summary"],
                         "start": ev["start"], "end": ev["end"]})
        cursor = ev["end"]

    if cursor < day_end:
        timeline.append({"type": "free", "start": cursor, "end": day_end})

    return timeline


def timeline_to_blocks(timeline: list[dict], target_date: date) -> list[dict]:
    """Freie Slots >= MIN_SLOT → 🟢 Libri Fokus Blöcke, Mittagspause rausgeschnitten."""
    lunch_start = datetime.combine(target_date, LUNCH_START)
    lunch_end   = datetime.combine(target_date, LUNCH_END)

    raw = []
    for slot in timeline:
        if slot["type"] != "free":
            continue
        s, e = slot["start"], slot["end"]
        if s < lunch_end and e > lunch_start:
            if s < lunch_start:
                raw.append({"start": s, "end": lunch_start})
            if e > lunch_end:
                raw.append({"start": lunch_end, "end": e})
            continue
        raw.append({"start": s, "end": e})

    blocks = []
    for r in raw:
        duration = (r["end"] - r["start"]).seconds // 60
        if duration < MIN_SLOT:
            continue
        blocks.append({
            "title": "🟢 Libri Fokus",
            "start": r["start"],
            "end":   r["end"],
            "tasks": [],
        })
    return blocks


def serialize_blocks(blocks: list[dict]) -> list[dict]:
    return [{**b, "start": b["start"].strftime("%H:%M"), "end": b["end"].strftime("%H:%M")}
            for b in blocks]


def plan_slack_blocks(target_date: date, timeline: list[dict], now: datetime) -> list[dict]:
    """
    Teams/Outlook-Checks als fixe Blöcke:
    - Morgens: erster freier Slot >= 15min vor 09:15, frühestens jetzt.
    - Abends: 17:00-17:15.
    """
    slack_blocks = []
    deadline = datetime.combine(target_date, SLACK_MORNING_DEADLINE)
    evening  = datetime.combine(target_date, SLACK_EVENING_START)

    def first_free_slot_before(deadline_dt: datetime) -> datetime | None:
        for slot in timeline:
            if slot["type"] != "free":
                continue
            s = max(slot["start"], now)
            e = min(slot["end"], deadline_dt)
            if (e - s).seconds // 60 >= SLACK_DURATION_MIN:
                return s
        return None

    morning_slot = first_free_slot_before(deadline)
    slack_start = morning_slot if morning_slot else now

    slack_blocks.append({
        "title": SLACK_CHECK_TITLE,
        "start": slack_start,
        "end":   slack_start + timedelta(minutes=SLACK_DURATION_MIN),
        "tasks": [],
    })

    if now < evening:
        slack_blocks.append({
            "title": SLACK_CHECK_TITLE,
            "start": evening,
            "end":   evening + timedelta(minutes=SLACK_DURATION_MIN),
            "tasks": [],
        })

    return slack_blocks


def send_to_n8n(date_str: str, blocks: list[dict], webhook_url: str) -> None:
    resp = requests.post(webhook_url, json={"date": date_str, "blocks": blocks}, timeout=30)
    resp.raise_for_status()


def delete_existing(date_str: str, webhook_url: str, titles: list[str]) -> None:
    """Löscht bestehende Fokus- und Check-Blöcke via Delete-Webhook."""
    for title in titles:
        try:
            requests.post(webhook_url, json={"date": date_str, "title": title}, timeout=30)
        except Exception as e:
            print(f"Warnung: Löschen fehlgeschlagen für '{title}': {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD, default: heute")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-md", action="store_true",
                         help="Blöcke als Markdown-Überschriften ausgeben (kein Kalender-Push)")
    parser.add_argument("--webhook-url")
    parser.add_argument("--no-delete", action="store_true", help="Bestehende Blöcke nicht löschen")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else date.today()
    now         = datetime.now().replace(second=0, microsecond=0)
    webhook_url = args.webhook_url or N8N_WEBHOOK_URL

    if not args.dry_run and not args.print_md and not webhook_url:
        print("Fehler: N8N_FOCUS_WEBHOOK_URL nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    print(f"Datum: {target_date}, jetzt: {now.strftime('%H:%M')}")
    print("Lade Kalender (Libri)...")

    events   = fetch_events(target_date)
    merged   = merge_events(events)
    timeline = build_timeline(target_date, merged)
    blocks   = timeline_to_blocks(timeline, target_date)
    slack    = plan_slack_blocks(target_date, timeline, now)

    all_blocks = sorted(blocks + slack, key=lambda b: b["start"])
    serialized = serialize_blocks(all_blocks)

    print("\nTagesplan:")
    for slot in timeline:
        tag = "[frei]" if slot["type"] == "free" else f"  {slot.get('summary','')[:40]}"
        print(f"  {slot['start'].strftime('%H:%M')}-{slot['end'].strftime('%H:%M')} {tag}")

    print(f"\n{len(all_blocks)} Blöcke:")
    for b in serialized:
        print(f"  {b['start']}-{b['end']} {b['title']}")

    if args.dry_run:
        print("\n[dry-run] Payload:")
        print(json.dumps({"date": str(target_date), "blocks": serialized}, indent=2, ensure_ascii=False))
        return

    if args.print_md:
        print("\n[markdown]")
        for b in serialized:
            print(f"## {b['start']}-{b['end']} {b['title']}")
        return

    if not args.no_delete:
        print("Lösche bestehende Blöcke...")
        delete_existing(str(target_date), N8N_DELETE_WEBHOOK_URL, [
            "🟢 Libri Fokus", "💬 Teams / Outlook Check"
        ])

    send_to_n8n(str(target_date), serialized, webhook_url)
    print("Fertig.")


if __name__ == "__main__":
    main()
