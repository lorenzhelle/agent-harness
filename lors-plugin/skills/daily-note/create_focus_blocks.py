#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["icalendar", "requests", "recurring-ical-events"]
# ///
"""
create_focus_blocks.py - Kontext-bewusste Fokusblock-Planung via n8n Webhook

Logik:
  - Liest beide Kalender mit Kontext-Tag (Netlight / Libri)
  - Bildet Kontext-Zonen: kurze Lücken (<= CONTEXT_GAP_MIN) zwischen zwei
    gleichfarbigen Meetings bleiben in deren Kontext
  - Morgens vor erstem Meeting: NL bis 08:45, dann Libri bis Daily
  - Jeder freie Slot >= MIN_SLOT bekommt den Fokusblock des umgebenden Kontexts
  - Output: chronologisch sortierte Blöcke mit tasks-Liste (wird von Daily Note befüllt)

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

# (context, url) — Reihenfolge bestimmt Kontext-Tag
ICS_SOURCES = [
    ("Libri",    "https://outlook.office365.com/owa/calendar/dc40573ee407482dab7bd1d3369f8a58@libri.de/332b20a1ab084aba9add674b25921b2c2431110006149550985/calendar.ics"),
    ("Netlight", "https://outlook.office365.com/owa/calendar/070b9b43f03648939e2577402922a5c9@netlight.com/2f09c0315ea74b729ac60711ec78a57d15135075663695882613/calendar.ics"),
]

WORK_START      = time(8, 0)
WORK_END        = time(17, 30)
WORK_END_MAX    = time(17, 30)
MIN_SLOT        = 20   # Minuten — kleinster nützlicher freier Slot
CONTEXT_GAP_MIN = 45   # Minuten — Lücke zwischen gleichfarbigen Meetings bleibt im Kontext
NL_MORNING_END  = time(8, 45)  # Morgens NL bis hier, dann Libri bis Daily
LUNCH_START     = time(12, 0)
LUNCH_END       = time(13, 0)


def fetch_events_with_context(target_date: date) -> list[dict]:
    """Gibt alle Events des Tages mit context='Libri'/'Netlight' zurück."""
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
                    "context": context,
                    "summary": summary,
                    "start":   max(start_dt, day_start),
                    "end":     min(end_dt,   day_end),
                })
        except Exception as e:
            print(f"Warnung: {context}-Kalender nicht geladen: {e}", file=sys.stderr)

    events.sort(key=lambda e: e["start"])
    return events


def merge_events(events: list[dict]) -> list[dict]:
    """Überlappende Events gleichen Kontexts mergen; verschiedene Kontexte bleiben getrennt."""
    if not events:
        return []
    merged = [events[0].copy()]
    for ev in events[1:]:
        last = merged[-1]
        if ev["start"] < last["end"]:  # Überlappung
            last["end"] = max(last["end"], ev["end"])
            # Kontext: wenn verschieden, "Mixed" (wird nicht als Fokusblock genutzt)
            if last["context"] != ev["context"]:
                last["context"] = "Mixed"
        else:
            merged.append(ev.copy())
    return merged


def assign_context_to_gaps(
    target_date: date,
    events: list[dict],
) -> list[dict]:
    """
    Gibt eine vollständige Timeline zurück: Events + freie Slots mit zugewiesenem Kontext.
    Slots <= CONTEXT_GAP_MIN zwischen gleichfarbigen Events erben deren Kontext.
    Morgens: NL bis NL_MORNING_END, dann Libri bis erstem Meeting.
    """
    day_start = datetime.combine(target_date, WORK_START)
    day_end   = datetime.combine(target_date, WORK_END)
    nl_morning_cutoff = datetime.combine(target_date, NL_MORNING_END)

    timeline = []
    cursor = day_start

    for i, ev in enumerate(events):
        gap_start = cursor
        gap_end   = ev["start"]

        if gap_end > gap_start:
            gap_min = (gap_end - gap_start).seconds // 60

            # Kontext für Lücke bestimmen
            prev_ctx = events[i - 1]["context"] if i > 0 else None
            next_ctx = ev["context"]

            if prev_ctx and prev_ctx == next_ctx and gap_min <= CONTEXT_GAP_MIN:
                # Kurze Lücke zwischen gleichen Kontexten → selber Kontext
                gap_ctx = prev_ctx
            elif prev_ctx is None:
                # Morgendliche Lücke vor erstem Meeting → immer Netlight
                gap_ctx = "Netlight"
            elif prev_ctx and gap_min <= CONTEXT_GAP_MIN:
                # Kurze Lücke zwischen verschiedenen Kontexten → vorheriger Kontext gewinnt
                gap_ctx = prev_ctx
            else:
                # Lange Lücke zwischen verschiedenen Kontexten → nächster Kontext
                gap_ctx = next_ctx

            if gap_end > gap_start:
                timeline.append({"type": "free", "context": gap_ctx,
                                 "start": gap_start, "end": gap_end})

        timeline.append({"type": "meeting", "context": ev["context"],
                         "summary": ev["summary"],
                         "start": ev["start"], "end": ev["end"]})
        cursor = ev["end"]

    # Abschluss-Lücke nach letztem Meeting
    if cursor < day_end:
        last_ctx = events[-1]["context"] if events else "Libri"
        timeline.append({"type": "free", "context": last_ctx,
                         "start": cursor, "end": day_end})

    return timeline


LIBRI_MIN_HOURS = 6
NL_MIN_MINUTES  = 60
MAX_NL_BLOCKS   = 2


def timeline_to_blocks(timeline: list[dict], target_date: date) -> list[dict]:
    """
    Freie Slots >= MIN_SLOT → Fokusblöcke.
    Constraints:
      - Max MAX_NL_BLOCKS NL-Fokusblöcke (benachbarte NL-Slots werden gemergt)
      - Libri-Fokuszeit + Libri-Meetings >= LIBRI_MIN_HOURS
        → überschüssige NL-Fokusblöcke (längste zuerst) werden zu Libri umgewidmet
    """
    lunch_start = datetime.combine(target_date, LUNCH_START)
    lunch_end   = datetime.combine(target_date, LUNCH_END)

    # Rohe Blöcke aus freien Slots
    raw = []
    for slot in timeline:
        if slot["type"] != "free":
            continue
        # Mittagspause 12-13 rausschneiden
        s, e = slot["start"], slot["end"]
        if s < lunch_end and e > lunch_start:
            # Slot überlappt Mittagspause — aufteilen
            if s < lunch_start:
                raw.append({"start": s, "end": lunch_start, "context": slot["context"],
                            "duration": int((lunch_start - s).seconds // 60)})
            if e > lunch_end:
                raw.append({"start": lunch_end, "end": e, "context": slot["context"],
                            "duration": int((e - lunch_end).seconds // 60)})
            continue
        duration = (e - s).seconds // 60
        if duration < MIN_SLOT:
            continue
        raw.append({
            "start":   s,
            "end":     e,
            "context": slot["context"],
            "duration": duration,
        })
    raw = [r for r in raw if r["duration"] >= MIN_SLOT]

    # Benachbarte NL-Blöcke mergen (durch kurze Libri-Lücken getrennt <= CONTEXT_GAP_MIN)
    merged_nl = []
    i = 0
    while i < len(raw):
        if raw[i]["context"] != "Netlight":
            merged_nl.append(raw[i])
            i += 1
            continue
        # Schaue ob nächster NL-Block nah genug ist zum mergen
        j = i + 1
        while j < len(raw):
            gap = (raw[j]["start"] - raw[i]["end"]).seconds // 60
            if raw[j]["context"] == "Netlight" and gap <= CONTEXT_GAP_MIN:
                # Merge: extend i bis end von j, Lücke dazwischen wird NL
                raw[i] = {**raw[i], "end": raw[j]["end"],
                          "duration": int((raw[j]["end"] - raw[i]["start"]).seconds // 60)}
                j += 1
            else:
                break
        merged_nl.append(raw[i])
        i = j

    # NL-Blöcke auf MAX_NL_BLOCKS begrenzen: kleinste NL-Blöcke zu Libri umwidmen
    # Sandwiched Blöcke (zwischen zwei NL-Meetings) werden zuletzt konvertiert
    nl_blocks   = [b for b in merged_nl if b["context"] == "Netlight"]
    other_blocks = [b for b in merged_nl if b["context"] != "Netlight"]

    if len(nl_blocks) > MAX_NL_BLOCKS:
        def _is_sandwiched_quick(b: dict) -> bool:
            prev_nl = any(s["type"] == "meeting" and s["context"] == "Netlight"
                          and s["end"] == b["start"] for s in timeline)
            next_nl = any(s["type"] == "meeting" and s["context"] == "Netlight"
                          and s["start"] == b["end"] for s in timeline)
            return prev_nl and next_nl
        # Konvertiere zuerst nicht-sandwiched Blöcke, bevorzuge größte (mehr Libri-Gewinn)
        # Innerhalb nicht-sandwiched: größte zuerst, sandwiched niemals wenn vermeidbar
        nl_blocks.sort(key=lambda b: (_is_sandwiched_quick(b), -b["duration"]))
        to_convert = nl_blocks[:len(nl_blocks) - MAX_NL_BLOCKS]
        keep_nl    = nl_blocks[len(nl_blocks) - MAX_NL_BLOCKS:]
        for b in to_convert:
            b["context"] = "Libri"
        other_blocks.extend(to_convert)
        nl_blocks = keep_nl

    all_blocks = sorted(nl_blocks + other_blocks, key=lambda b: b["start"])

    # Libri-Quota prüfen: Libri-Meetings + Libri-Fokusblöcke >= LIBRI_MIN_HOURS
    libri_meeting_min = sum(
        int((s["end"] - s["start"]).seconds // 60)
        for s in timeline
        if s["type"] == "meeting" and s["context"] == "Libri"
    )
    libri_focus_min = sum(b["duration"] for b in all_blocks if b["context"] == "Libri")
    libri_total_min = libri_meeting_min + libri_focus_min
    libri_needed    = LIBRI_MIN_HOURS * 60 - libri_total_min

    if libri_needed > 0:
        # 1. Tag verlängern bis WORK_END_MAX
        day_end_max = datetime.combine(target_date, WORK_END_MAX)
        last_end = max((b["end"] for b in all_blocks), default=datetime.combine(target_date, WORK_END))
        if last_end < day_end_max:
            extension = min(libri_needed, int((day_end_max - last_end).seconds // 60))
            if extension >= MIN_SLOT:
                new_end = last_end + timedelta(minutes=extension)
                all_blocks.append({
                    "start":    last_end,
                    "end":      new_end,
                    "context":  "Libri",
                    "duration": extension,
                })
                libri_needed -= extension
                print(f"Info: Tag verlängert bis {new_end.strftime('%H:%M')}",
                      file=sys.stderr)

        # 2. Nur wenn immer noch nicht erfüllt: NL umwidmen, sandwiched zuletzt
        if libri_needed > 0:
            tl = list(timeline)

            def nl_is_sandwiched(b: dict) -> bool:
                """True wenn direkt vor und nach dem Block ein NL-Meeting liegt."""
                prev_nl = any(
                    s["type"] == "meeting" and s["context"] == "Netlight"
                    and s["end"] == b["start"]
                    for s in tl
                )
                next_nl = any(
                    s["type"] == "meeting" and s["context"] == "Netlight"
                    and s["start"] == b["end"]
                    for s in tl
                )
                return prev_nl and next_nl

            nl_focus_blocks = sorted(
                [b for b in all_blocks if b["context"] == "Netlight"],
                key=lambda b: (nl_is_sandwiched(b), -b["duration"])
            )
            nl_focus_total = sum(b["duration"] for b in nl_focus_blocks)
            # Nur soviel konvertieren wie nötig, NL_MIN_MINUTES muss übrig bleiben
            nl_convertable = max(0, nl_focus_total - NL_MIN_MINUTES)

            # Ganze Blöcke konvertieren (kein Split — verhindert Zeitüberschneidungen)
            for b in nl_focus_blocks:
                if libri_needed <= 0 or nl_convertable <= 0:
                    break
                if b["duration"] <= nl_convertable:
                    b["context"] = "Libri"
                    libri_needed   -= b["duration"]
                    nl_convertable -= b["duration"]
            print(f"Info: Libri-Quota durch Umwidmen angepasst", file=sys.stderr)

    # Finale Blöcke bauen (start/end als datetime für plan_slack_blocks)
    blocks = []
    for b in all_blocks:
        ctx = b["context"]
        title = "🔵 Netlight Fokus" if ctx == "Netlight" else "🟢 Libri Fokus" if ctx == "Libri" else "🔘 Fokus"
        blocks.append({
            "title":   title,
            "start":   b["start"],
            "end":     b["end"],
            "context": ctx,
            "tasks":   [],
        })
    return blocks


def serialize_blocks(blocks: list[dict]) -> list[dict]:
    return [{**b, "start": b["start"].strftime("%H:%M"), "end": b["end"].strftime("%H:%M")}
            for b in blocks]


SLACK_MORNING_DEADLINE = time(9, 15)   # Slack-Check muss vor diesem Meeting sein
SLACK_EVENING_START    = time(17, 0)
SLACK_DURATION_MIN     = 15


def plan_slack_blocks(target_date: date, timeline: list[dict], focus_blocks: list[dict], now: datetime) -> list[dict]:
    """
    Slack-Checks als fixe Blöcke:
    - Morgens: erster freier Slot >= 15min vor 09:15, frühestens jetzt.
      Falls kein freier Slot vor 09:15 → ersten NL-Fokusblock nutzen (am Anfang).
    - Abends: 17:00-17:15. Falls Libri-Fokusblock → ersten NL-Fokusblock ab 16:45 nutzen.
    """
    slack_blocks = []
    deadline = datetime.combine(target_date, SLACK_MORNING_DEADLINE)
    evening  = datetime.combine(target_date, SLACK_EVENING_START)
    evening_end = evening + timedelta(minutes=SLACK_DURATION_MIN)

    def first_free_slot_before(deadline_dt: datetime) -> datetime | None:
        for slot in timeline:
            if slot["type"] != "free":
                continue
            s = max(slot["start"], now)
            e = min(slot["end"], deadline_dt)
            if (e - s).seconds // 60 >= SLACK_DURATION_MIN:
                return s
        return None

    def first_nl_focus_start() -> datetime | None:
        for b in focus_blocks:
            if b["context"] == "Netlight" and b["start"] >= now:
                return b["start"]
        return None

    # Morgens
    morning_slot = first_free_slot_before(deadline)
    if morning_slot:
        slack_start = morning_slot
    else:
        # Kein freier Slot vor 09:15 → Anfang des ersten NL-Fokusblocks
        nl_start = first_nl_focus_start()
        slack_start = nl_start if nl_start else now

    slack_blocks.append({
        "title":   "📱 Slack Check",
        "start":   slack_start,
        "end":     slack_start + timedelta(minutes=SLACK_DURATION_MIN),
        "context": "Allgemein",
        "tasks":   [],
    })

    # Abends
    if now < evening:
        # Prüfe ob 17:00-17:15 in einem Libri-Fokusblock liegt
        evening_in_libri = any(
            b["context"] == "Libri"
            and b["start"] <= evening
            and b["end"] >= evening_end
            for b in focus_blocks
        )
        if evening_in_libri:
            # Ersten NL-Fokusblock ab 16:45 suchen
            window_start = evening - timedelta(minutes=15)
            nl_evening = next(
                (b for b in focus_blocks
                 if b["context"] == "Netlight" and b["start"] >= window_start),
                None
            )
            slack_start_e = nl_evening["start"] if nl_evening else evening
        else:
            slack_start_e = evening

        slack_blocks.append({
            "title":   "📱 Slack Check",
            "start":   slack_start_e,
            "end":     slack_start_e + timedelta(minutes=SLACK_DURATION_MIN),
            "context": "Allgemein",
            "tasks":   [],
        })

    return slack_blocks


def send_to_n8n(date_str: str, blocks: list[dict], webhook_url: str) -> None:
    resp = requests.post(webhook_url, json={"date": date_str, "blocks": blocks}, timeout=30)
    resp.raise_for_status()


def delete_existing(date_str: str, webhook_url: str, titles: list[str]) -> None:
    """Löscht bestehende Fokus- und Slack-Blöcke via Delete-Webhook."""
    delete_url = N8N_DELETE_WEBHOOK_URL
    for title in titles:
        try:
            requests.post(delete_url, json={"date": date_str, "title": title}, timeout=30)
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
    print("Lade Kalender...")

    events   = fetch_events_with_context(target_date)
    merged   = merge_events(events)
    timeline = assign_context_to_gaps(target_date, merged)
    blocks   = timeline_to_blocks(timeline, target_date)
    slack    = plan_slack_blocks(target_date, timeline, blocks, now)

    all_blocks = sorted(blocks + slack, key=lambda b: b["start"])
    serialized = serialize_blocks(all_blocks)

    print("\nTagesplan:")
    for slot in timeline:
        tag = f"[{slot['context']}]" if slot["type"] == "free" else f"  {slot.get('summary','')[:40]}"
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
        delete_existing(str(target_date), webhook_url, [
            "🔵 Netlight Fokus", "🟢 Libri Fokus", "🔘 Fokus", "📱 Slack Check"
        ])

    send_to_n8n(str(target_date), serialized, webhook_url)
    print("Fertig.")


if __name__ == "__main__":
    main()
