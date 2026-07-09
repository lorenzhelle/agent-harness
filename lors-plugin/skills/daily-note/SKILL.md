---
name: daily-note
description: >
  Use this skill when the user asks to "create a daily note", "neue daily note erstellen",
  "start the day", "/daily", "daily note anlegen", "tagesnotiz erstellen", or wants to
  set up their daily Obsidian note. Always use this skill when the user wants to create
  or open today's daily note in their Obsidian vault.
version: 3.0.0
---

# Daily Note Skill

Erstellt eine neue Daily Note fur heute im Obsidian-Vault unter `/mnt/c/Users/lhelle/Documents/para-vault/Daily Notes/`.

## Backlog-Format

Die Backlog-Datei liegt unter `/mnt/c/Users/lhelle/Documents/para-vault/1 - inbox/backlog.md`.

Spalten:
- **Task**: Task-Text
- **Wiedervorlage**: Datum YYYY-MM-DD ab dem der Task wieder angezeigt wird
- **Mal verschoben**: wie oft wurde dieser Task schon auf Wiedervorlage gelegt (erhöht sich jedes Mal wenn der User "Wiedervorlage" wählt)
- **Kategorie**: optional

## Workflow

### 1. Heutiges Datum bestimmen

Das heutige Datum ist im System-Kontext verfügbar (`currentDate`). Format für den Dateinamen: `YYYY-MM-DD.md`.

### 2. Prüfen ob die heutige Note schon existiert

Lies `/mnt/c/Users/lhelle/Documents/para-vault/Daily Notes/<heute>.md`. Wenn sie schon existiert, teile dem User mit dass sie schon vorhanden ist und zeige den Inhalt.

### 3. Letzte Daily Note finden

Suche die vorherige Daily Note unter `/mnt/c/Users/lhelle/Documents/para-vault/Daily Notes/`. Format: `YYYY-MM-DD.md`. Nutze:
```bash
ls "/mnt/c/Users/lhelle/Documents/para-vault/Daily Notes/"20*.md | sort | tail -5
```
Nimm die neueste Datei vor dem heutigen Datum.

### 4. Offene Todos aus Vortag + Backlog-Kandidaten bestimmen

Lies die vorherige Daily Note vollständig. Extrahiere Tasks aus zwei Quellen:

**Quelle A - Explizite Checkboxen:**
- Alle offenen `- [ ]` Top-Level-Einträge aus der `Heute:` Sektion
- Alle offenen `- [ ]` Einträge aus Meeting-Sektionen (`## HH:MM-...`) und sonstigen Sektionen
- Erledigte (`- [x]`) ignorieren
- Sub-Tasks (eingerückt) werden nicht separat gelistet - sie kommen automatisch mit wenn der Top-Level-Task mitgezogen wird

**Quelle B - Implizite Tasks aus Meeting-Notizen:**
Scanne alle Meeting-Sektionen und sonstigen Notizen auf Bullet Points die wie ein Folgeauftrag aussehen, auch wenn sie keine Checkbox haben. Kriterien:
- Enthält ein Aktionsverb (klären, prüfen, schicken, erstellen, fragen, ansprechen, nachverfolgen, ...)
- Enthält eine Zuweisung ("Lorenz:", "ich:", "-> Lorenz", "TODO:", "AP:")
- Klingt wie eine konkrete nächste Aktion

Diese als `[implizit]` markieren damit der User weiß dass es keine explizite Checkbox war.

Falls `# wo war ich` Sektion existiert: alle Bullet Points ebenfalls als Tasks behandeln.

Lies gleichzeitig den Backlog `/mnt/c/Users/lhelle/Documents/para-vault/1 - inbox/backlog.md` und sammle alle Tasks deren Wiedervorlage-Datum ≤ heute ist.

Lies außerdem `/mnt/c/Users/lhelle/Documents/para-vault/1 - inbox/Inbox.md`. Trenne den Inhalt an `---` Trennlinien auf und behandle jeden nicht-leeren Block als einen Inbox-Eintrag. Zeige jeden Eintrag als kompakte Vorschau (erste Zeile oder erste 80 Zeichen).

### 5. Interaktive Triage - User fragen

Zeige dem User eine nummerierte Liste aller Tasks die zu entscheiden sind:
- Zuerst: Backlog-Tasks mit Wiedervorlage ≤ heute (mit Hinweis wie oft bereits verschoben)
- Dann: offene Todos aus dem Vortag (die noch nicht im Backlog sind)
- Dann: Inbox-Einträge aus Inbox.md
- Zuletzt: implizite Tasks aus Meeting-Notizen

Format:

```
Guten Morgen! Hier sind deine Tasks für heute:

**Aus dem Backlog (Wiedervorlage heute):**
1. Powerpoint Agent: mehr Slide-Layouts unterstützen (2x verschoben)
2. LiteLLM Präsentation erstellen (1x verschoben)

**Offen vom Vortag:**
3. AHT - Ticket zum testen
4. Neuer Task XY

**Aus Meeting-Notizen [implizit]:**
5. Vera fragen wegen Storno-Prozess (aus: 14:00 Storno-Prozess)
6. Präsentation bis Freitag schicken (aus: 11:00 FollowUp KI)

**Aus Inbox:**
7. Will einen plan machen wie wir service accounts unterstützen können...
8. https://youtu.be/gv0WHhKelSE — Video über best practices Claude Code

Tasks (1-6): **h** = heute, **w<N>** = Wiedervorlage in N Tagen, **s** = skip/löschen
Inbox (7-8): **h** = heute als Task, **k** = in Inbox lassen, **s** = löschen aus Inbox
Antworte mit einer Liste, z.B.: h, w3, h, w7, s, h, k, s
```

Warte auf die Antwort des Users.

### 6. Triage auswerten

Verarbeite die Antwort des Users:

**Für Tasks (Backlog / Vortag / Meeting):**
- **h** (heute): Task kommt in die `Heute:` Sektion der neuen Note. Task wird aus dem Backlog entfernt falls er dort war.
- **w<N>** (Wiedervorlage): Task kommt **nicht** in die Note. Im Backlog:
  - Falls bereits vorhanden: Wiedervorlage-Datum auf heute+N setzen, "Mal verschoben" um 1 erhöhen
  - Falls neu: neue Zeile anlegen mit Wiedervorlage=heute+N, Mal verschoben=1
- **s** (skip): Task wird weder in die Note noch in den Backlog aufgenommen. Falls im Backlog vorhanden: entfernen.

Schreib den aktualisierten Backlog zurück.

**Für Inbox-Einträge:**
- **h** (heute): Eintrag kommt als Task in `Heute:` (erste Zeile als Task-Text). Eintrag wird aus Inbox.md entfernt.
- **k** (keep): Eintrag bleibt unverändert in Inbox.md.
- **s** (skip/löschen): Eintrag wird aus Inbox.md entfernt.

Nach der Triage: Schreib die aktualisierte Inbox.md zurück (nur verbleibende Einträge, getrennt durch `---`, ohne führende/nachfolgende Leerzeilen).

### 7. Jira-Tickets abfragen

Nutze `acli jira` (nicht MCP) über das Script - es macht beide Abfragen, formatiert das `## Jira` Markdown fertig und gibt nur den fertigen Block aus (kein rohes JSON im Kontext):

```bash
uv run /mnt/c/Users/lhelle/Documents/para-vault/.claude/skills/daily-note/fetch_jira_summary.py
```

Das Script fragt aktive Tickets (In Arbeit/Test/In Review) und die 3 ältesten Backlog/Ready-for-Dev-Tickets ab (`assignee = currentUser()`, Projekt `DATA`, `issuetype != Epic`) und gibt direkt fertiges Markdown zurück, z.B.:

```
## Jira

**In Arbeit / Test**
- [DATA-3553](https://libri-gmbh.atlassian.net/browse/DATA-3553) Ticket-Titel

> [!todo]- Backlog Erinnerung
> - [DATA-3079](https://libri-gmbh.atlassian.net/browse/DATA-3079) Ticket-Titel (ältestes)
> - [DATA-3078](https://libri-gmbh.atlassian.net/browse/DATA-3078) Ticket-Titel
```

Output 1:1 in die Note übernehmen. Script lässt "In Arbeit / Test" automatisch weg wenn leer.

Die `## Jira` Sektion kommt **nach** dem `---` Divider und **vor** den Meetings.

### 8. Meetings eintragen

Führe das Script aus, bevor die Note geschrieben wird:

```bash
uv run /mnt/c/Users/lhelle/Documents/para-vault/.claude/skills/daily-note/inject_meetings.py --date <YYYY-MM-DD>
```

Das Script trägt die Outlook-Meetings als `Meetings:` Sektion in die Note ein. Jedes Meeting wird als `## HH:MM-HH:MM Meeting Name` Überschrift eingetragen. Meetings deren Name mit "Blocker for" beginnt, werden ignoriert. Falls die Note noch nicht existiert, erstellt das Script sie. Falls sie bereits eine `Meetings:` Sektion hat, überspringt es sie.

### Meetings neu laden (refetch)

Falls der User Meetings aktualisieren will (z.B. "Meetings neu laden", "Kalender aktualisieren", "refetch meetings"), nutze:

```bash
uv run /mnt/c/Users/lhelle/Documents/para-vault/.claude/skills/daily-note/refetch_meetings.py --date <YYYY-MM-DD>
```

Unterschied zu `inject_meetings.py`:
- Überschreibt die bestehende `Meetings:` Sektion komplett mit dem aktuellen Kalender
- Bestehende Notizen unter einem Meeting-Block werden **beibehalten** und an die neue Zeitposition verschoben (Matching via Titel)
- Meetings die nicht mehr im Kalender sind: Warnung ausgegeben, Notizen verworfen
- Neue Meetings aus dem Kalender: werden ohne Notizen eingefügt

Nach dem Ausführen des Scripts: Lies die Note erneut ein.

### 9. Daily Note schreiben

Erstelle `/mnt/c/Users/lhelle/Documents/para-vault/Daily Notes/<heute>.md` mit den Tasks die der User mit **h** markiert hat:

```
Heute:

- [ ] Task A
- [ ] Task B
	- [ ] Sub-Task (falls vorhanden)

---

## Jira

**In Arbeit / Test**
- [DATA-XXXX](https://libri-gmbh.atlassian.net/browse/DATA-XXXX) Ticket-Titel

> [!todo]- Backlog Erinnerung
> - [DATA-XXXX](https://libri-gmbh.atlassian.net/browse/DATA-XXXX) Ticket-Titel (ältestes)

## HH:MM-HH:MM Meeting Name

```

**Regeln:**
- Nur mit **h** markierte Tasks kommen in `Heute:`
- Einrückung/Sub-Tasks von mitgezogenen Tasks beibehalten
- Direkt nach `Heute:` Block kommt `---` Divider
- Danach `## Jira`, dann Meetings
- Wenn keine Tasks ausgewählt: `Heute:` bleibt leer (nur Überschrift)
- Keine `Später:` Sektion

### 10. Bestätigung

Teile dem User kurz mit:
- Datum der neuen Note
- Welche Tasks heute mitgenommen wurden
- Welche auf Wiedervorlage in X Tagen liegen
