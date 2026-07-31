---
name: daily-note
description: >
  Use this skill when the user asks to "create a daily note", "neue daily note erstellen",
  "start the day", "/daily", "daily note anlegen", "tagesnotiz erstellen", or wants to
  set up their daily Obsidian note. Always use this skill when the user wants to create
  or open today's daily note in their Obsidian vault.
version: 4.0.0
---

# Daily Note Skill

Erstellt eine neue Daily Note fur heute im Obsidian-Vault unter `$VAULT_DIR/Daily Notes/`.

**Pfade in diesem Skill:**
- `$SKILL_DIR` = Ordner dieses Skills (wo diese SKILL.md liegt) — dort liegen die Python-Scripts
- `$VAULT_DIR` = Obsidian-Vault-Root. Env-Var `VAULT_DIR` nutzen falls gesetzt, sonst Standardpfad je Maschine (z.B. WSL: `/mnt/c/Users/lhelle/Documents/para-vault`, Mac: `~/.../para-vault`). Falls unklar: User fragen oder Obsidian-Vault-Pfad im Dateisystem suchen.

## Backlog-Format

Die Backlog-Datei liegt unter `$VAULT_DIR/1 - inbox/backlog.md`.

Spalten:
- **Task**: Task-Text
- **Wiedervorlage**: Datum YYYY-MM-DD ab dem der Task wieder angezeigt wird
- **Mal verschoben**: wie oft wurde dieser Task schon auf Wiedervorlage gelegt (erhöht sich jedes Mal wenn der User "Wiedervorlage" wählt)
- **Kategorie**: optional

## Workflow

### 1. Heutiges Datum bestimmen

Das heutige Datum ist im System-Kontext verfügbar (`currentDate`). Format für den Dateinamen: `YYYY-MM-DD.md`.

### 2. Prüfen ob die heutige Note schon existiert

Lies `$VAULT_DIR/Daily Notes/<heute>.md`. Wenn sie schon existiert, teile dem User mit dass sie schon vorhanden ist und zeige den Inhalt.

### 3. Letzte Daily Note finden

Suche die vorherige Daily Note unter `$VAULT_DIR/Daily Notes/`. Format: `YYYY-MM-DD.md`. Nutze:
```bash
ls "$VAULT_DIR/Daily Notes/"20*.md | sort | tail -5
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

Lies gleichzeitig den Backlog `$VAULT_DIR/1 - inbox/backlog.md` und sammle alle Tasks deren Wiedervorlage-Datum ≤ heute ist.

Lies außerdem `$VAULT_DIR/1 - inbox/Inbox.md`. Trenne den Inhalt an `---` Trennlinien auf und behandle jeden nicht-leeren Block als einen Inbox-Eintrag. Zeige jeden Eintrag als kompakte Vorschau (erste Zeile oder erste 80 Zeichen).

### 5. Top-10-Vorschlag + interaktive Triage

**Tageslimit: max. 10 Tasks in `Heute:`.** Ziel ist ein fokussierter Tag, nicht eine vollständige Liste.

Sammle alle Kandidaten (Backlog fällig, offene Vortags-Todos, Inbox-Einträge, implizite Meeting-Tasks) und priorisiere sie:

1. **Deadline** — Tasks mit explizitem Datum/Fälligkeit heute oder überfällig zuerst
2. **Verschoben-Zähler** — ⚠️ Tasks mit "Mal verschoben" ≥ 3 als nächstes (Backlog-Spalte)
3. **Meeting-Kontext** — Tasks die aus einem heutigen/aktuellen Meeting oder ONGOING-Arbeit stammen
4. Rest nach ursprünglicher Reihenfolge (Backlog → Vortag → Meeting-implizit → Inbox)

Markiere die Top 10 aus dieser Sortierung als **Vorschlag**, alles danach als **Rest-Pool**. Zeige beides:

```
Guten Morgen! Vorschlag für heute (max. 10):

**Vorschlag:**
1. ⚠️ Powerpoint Agent: mehr Slide-Layouts unterstützen (3x verschoben!)
2. SSH Key friction auflösen (Deadline heute)
3. LiteLLM Präsentation erstellen (1x verschoben)
4. AHT - Ticket zum testen
...
10. Präsentation bis Freitag schicken [implizit] (aus: 11:00 FollowUp KI)

**Rest-Pool (nicht im Vorschlag, bei Kapazität nachziehen):**
11. Neuer Task XY
12. Vera fragen wegen Storno-Prozess [implizit] (aus: 14:00 Storno-Prozess)
13. Will einen plan machen wie wir service accounts unterstützen können... (Inbox)

Vorschlag übernehmen? Sag **ja**, oder gib pro Task an:
**h** = heute (auch für Rest-Pool-Tasks, um sie reinzuziehen), **w<N>** = Wiedervorlage in N Tagen, **s** = skip/löschen, **k** = (nur Inbox) in Inbox lassen
z.B.: ja  ODER  h,h,s,w3,...,k
```

Tasks mit "Mal verschoben" ≥ 3 bekommen **⚠️** Präfix und `(Xx verschoben!)` Suffix - sowohl in der Liste als auch später in der `Heute:` Sektion der Note.

Warte auf die Antwort des Users. Bei "ja": Vorschlag 1-10 werden **h**, Rest-Pool bleibt unangetastet (Backlog-Tasks im Backlog, Inbox-Einträge in Inbox, Vortags-Todos/implizite Tasks werden **nicht** automatisch weiterverschoben — sie stehen einfach nicht in der neuen Note und bleiben in der alten).

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
uv run $SKILL_DIR/fetch_jira_summary.py
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
uv run $SKILL_DIR/inject_meetings.py --date <YYYY-MM-DD>
```

Das Script trägt die Outlook-Meetings als `Meetings:` Sektion in die Note ein. Jedes Meeting wird als `## HH:MM-HH:MM Meeting Name` Überschrift eingetragen. Meetings deren Name mit "Blocker for" beginnt, werden ignoriert. Falls die Note noch nicht existiert, erstellt das Script sie. Falls sie bereits eine `Meetings:` Sektion hat, überspringt es sie.

### Meetings neu laden (refetch)

Falls der User Meetings aktualisieren will (z.B. "Meetings neu laden", "Kalender aktualisieren", "refetch meetings"), nutze:

```bash
uv run $SKILL_DIR/refetch_meetings.py --date <YYYY-MM-DD>
```

Unterschied zu `inject_meetings.py`:
- Überschreibt die bestehende `Meetings:` Sektion komplett mit dem aktuellen Kalender
- Bestehende Notizen unter einem Meeting-Block werden **beibehalten** und an die neue Zeitposition verschoben (Matching via Titel)
- Meetings die nicht mehr im Kalender sind: Warnung ausgegeben, Notizen verworfen
- Neue Meetings aus dem Kalender: werden ohne Notizen eingefügt

Nach dem Ausführen des Scripts: Lies die Note erneut ein.

### 9. Daily Note schreiben

#### Kategorie-Erkennung (Libri vs. Netlight)

Für jeden mit **h** markierten Task Kategorie bestimmen:

1. **Backlog-Kategorie**: Falls Task aus Backlog kommt und Kategorie-Spalte "Libri" oder "Netlight" enthält → diese nutzen
2. **Keyword-Erkennung** (wenn keine Backlog-Kategorie):
   - → **Libri**: Task-Text enthält `DATA-`, `Libri`, `libri`, `JIRA`, `Plureo`, `AHT`, `Storno`, `DWH`, `Pipeline`
   - → **Netlight**: Task-Text enthält `NL-`, `Netlight`, `netlight`, `EdgeEx`, `Staffing`, `CV`, `Proposal`
   - → **Allgemein**: kein Keyword matcht
3. **Nachfragen** (wenn Kategorie immer noch unklar zwischen Libri/Netlight): Nach der h/w/s-Runde fragen: `Task X: Libri (L), Netlight (N) oder Allgemein (A)?` - nur für Tasks die mit h markiert wurden und nicht eindeutig erkannt wurden. Tasks ohne klaren Kontext landen in **Allgemein**.

#### Note-Format

Erstelle `$VAULT_DIR/Daily Notes/<heute>.md` mit den Tasks die der User mit **h** markiert hat, aufgeteilt in Sektionen:

```
Top 3 Ziele:
- [ ]
- [ ]
- [ ]

Heute:

### Netlight
- [ ] Task C

### Libri
- [ ] Task A
- [ ] ⚠️ Task B (3x verschoben!)

---

## Jira

**In Arbeit / Test**
- [DATA-XXXX](https://libri-gmbh.atlassian.net/browse/DATA-XXXX) Ticket-Titel

> [!todo]- Backlog Erinnerung
> - [DATA-XXXX](https://libri-gmbh.atlassian.net/browse/DATA-XXXX) Ticket-Titel (ältestes)

## HH:MM-HH:MM Meeting Name

```

**Regeln:**
- `Top 3 Ziele:` steht ganz oben in der Note, vor `Heute:`, immer mit genau 3 leeren `- [ ]` Checkboxen — wird nicht automatisch befüllt, der User trägt sie manuell ein
- Tasks in `### Netlight`, `### Libri`, `### Allgemein` aufteilen — kein Präfix im Task-Text, Sektionsüberschrift reicht
- Reihenfolge der Sektionen: Netlight → Libri → Allgemein
- ⚠️-Markierung bei ≥3x verschoben kommt **nach** dem Präfix
- Einrückung/Sub-Tasks beibehalten; Sub-Tasks erben die Kategorie des Parent
- Sektion weglassen wenn leer (keine Libri-Tasks → kein `### Libri`)
- Direkt nach `Heute:` Block kommt `---` Divider
- Danach `## Jira`, dann Meetings
- Wenn keine Tasks ausgewählt: `Heute:` bleibt leer (nur Überschrift, ohne Sektionen)
- Keine `Später:` Sektion

### 10. Fokus-Blöcke in die Note eintragen

Kein Kalender-Push mehr — Fokus-Blöcke werden nur als Markdown-Überschriften in der Note eingetragen (analog zu Meetings), damit sie in Obsidians Agenda/Day-Planner View auftauchen.

```bash
uv run $SKILL_DIR/create_focus_blocks.py --date <YYYY-MM-DD> --print-md
```

Das Script berechnet freie Slots und plant:
- 🔵 **Netlight Fokus**: 1-2 Blöcke (45-90min), morgens vor 12 Uhr + nachmittags ab 13 Uhr
- 🟢 **Libri Fokus**: größter verbleibender freier Block

Bei ≥4 Meetings: nur 1 Netlight-Block (morgens).

`--print-md` gibt die Blöcke als `## HH:MM-HH:MM 🔵/🟢 Titel` Zeilen aus (nach der `[markdown]` Markierung in stdout). Diese Zeilen in die Meetings-Sektion der Note einfügen, chronologisch nach Uhrzeit zwischen die bestehenden Meeting-Überschriften einsortiert.

Falls der User explizit einen Task als Zeitblock haben will (z.B. "DATA-1234 als Zeitblock"), frag nach Dauer und füge eine passende `## HH:MM-HH:MM Titel` Zeile manuell hinzu.

### 11. Bestätigung

Teile dem User kurz mit:
- Datum der neuen Note
- Welche Tasks heute mitgenommen wurden (nach Libri/Netlight aufgeteilt), Anzahl (max. 10)
- Welche im Rest-Pool geblieben sind (bei Kapazität nachziehbar)
- Welche auf Wiedervorlage in X Tagen liegen
- Welche Fokus-Blöcke in die Note eingetragen wurden
