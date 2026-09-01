---
name: daily-note-libri
description: >
  Use this skill when the user asks to "create a daily note libri", "daily-libri",
  "/daily-libri", or explicitly wants a Libri-only daily Obsidian note without any
  Netlight content (meetings, tasks, focus blocks) — e.g. for a demo or presentation.
  Do not use for the regular daily note (that's the "daily-note" skill); this skill
  never touches Netlight data at all.
version: 1.0.0
---

# Daily Note Skill (Libri-only)

Erstellt eine neue Daily Note fur heute im Obsidian-Vault unter `$VAULT_DIR/Daily Notes/`, ausschließlich mit Libri-Inhalten. Es gibt keinen Netlight-Kalenderzugriff, keine Netlight-Kategorie und keine Netlight-Fokusblöcke — die Scripts in diesem Skill kennen Netlight schlicht nicht.

**Pfade in diesem Skill:**
- `$SKILL_DIR` = Ordner dieses Skills (wo diese SKILL.md liegt) — dort liegen die Python-Scripts
- `$VAULT_DIR` = Obsidian-Vault-Root. Env-Var `VAULT_DIR` nutzen falls gesetzt, sonst Standardpfad je Maschine (z.B. WSL: `/mnt/c/Users/lhelle/Documents/para-vault`, Mac: `~/.../para-vault`). Falls unklar: User fragen oder Obsidian-Vault-Pfad im Dateisystem suchen.

## Kommunikationsstil

Keine Zwischenkommentare pro Schritt (kein "Ich prüfe jetzt...", "Ich lese..."). Arbeite die Schritte still ab und melde dich erst am Ende mit der kompakten Zusammenfassung aus Schritt 10 (Bestätigung). Eine kurze Meldung mitten im Ablauf ist nur bei einer echten Entscheidung/Warnung angebracht (z.B. Note existiert schon, Kalender nicht ladbar), nicht als Statusanzeige für jeden einzelnen Schritt.

## Backlog-Format

Die Backlog-Datei liegt unter `$VAULT_DIR/1 - inbox/backlog.md`.

Spalten:
- **Task**: Task-Text
- **Wiedervorlage**: Datum YYYY-MM-DD ab dem der Task wieder angezeigt wird
- **Mal verschoben**: wie oft wurde dieser Task schon auf Wiedervorlage gelegt (erhöht sich jedes Mal wenn der User "Wiedervorlage" wählt)
- **Erstellt am**: Datum YYYY-MM-DD, an dem der Task zum ersten Mal angelegt wurde. Wird beim Anlegen einer neuen Backlog-Zeile gesetzt und danach nie mehr verändert. Für Zeilen, die vor Einführung dieser Spalte angelegt wurden, bleibt das Feld leer (kein Alter anzeigbar/kein Alter=0 annehmen).
- **Kategorie**: optional

**Zeilen mit Kategorie "Netlight" komplett ignorieren** — beim Lesen des Backlogs überspringen, nicht einlesen/zitieren, nicht als Kandidat aufnehmen. Netlight-Inhalte sollen nie ins Modell-Kontextfenster dieses Skills gelangen.

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

**An jeder dieser Quellen (Vortags-Checkboxen, implizite Meeting-Tasks, Backlog-Zeilen, Inbox-Einträge) jeden Kandidaten verwerfen, der erkennbar zu Netlight gehört** — Backlog-Kategorie "Netlight", oder Text der Netlight-Keywords enthält (`NL-`, `Netlight`, `netlight`, `EdgeEx`, `Staffing`, `CV`, `Proposal`), oder sonst klar Netlight-Kontext hat (Personennamen/Themen die erkennbar zu Netlight gehören, auch ohne Keyword-Treffer). Verworfene Kandidaten **nicht** in die Note aufnehmen — sie fallen komplett weg, so als hätte es sie nie gegeben. Im Zweifel (Task könnte Netlight-Bezug haben) verwerfen statt raten.

### 5. Alle Kandidaten übernehmen, sortiert nach Priorität + Alter

Keine Triage-Rückfrage mehr. Alle verbleibenden Kandidaten (Backlog fällig, offene Vortags-Todos, Inbox-Einträge, implizite Meeting-Tasks — nach Netlight-Filterung aus Schritt 4) kommen automatisch in die `Heute:` Sektion der neuen Note — kein Tageslimit, keine Bestätigung nötig.

**Alter berechnen:** Für Backlog-Tasks mit gesetztem "Erstellt am" ist das Alter = heute − Erstellt am (in Tagen). Tasks ohne "Erstellt am" (Alt-Zeilen, oder Vortags-Todos/Meeting-Tasks/Inbox-Einträge, die neu in den Backlog wandern) bekommen beim ersten Auftauchen in diesem Lauf "Erstellt am" = heute gesetzt und starten bei Alter 0. Damit wächst das Alter ab jetzt korrekt mit, auch wenn die Historie davor nicht bekannt ist.

**Sortierung** (bestimmt die Reihenfolge in der Note):

1. **Deadline** — Tasks mit explizitem Datum/Fälligkeit heute oder überfällig zuerst
2. **Alter** — absteigend nach Tagen auf der Liste (Langläufer zuerst); Tasks mit Alter ≥ 7 Tagen bekommen **⚠️** Präfix und `(seit X Tagen)` Suffix
3. **Verschoben-Zähler** — als weiteres Tie-Break-Signal, absteigend
4. Rest nach ursprünglicher Reihenfolge (Backlog → Vortag → Meeting-implizit → Inbox)

Jeder in die Note übernommene Task wird aus Backlog/Inbox entfernt (Backlog-Zeile gelöscht, Inbox-Block gelöscht). Vortags-Todos und implizite Meeting-Tasks werden **nicht** in den Backlog zurückgeschrieben — sie stehen einfach nur in der neuen Note.

Zeige dem User nach dem Schreiben der Note kurz die Liste inkl. Alter-Anzeige, z.B.:

```
Heute übernommen (sortiert nach Alter):
1. ⚠️ Powerpoint Agent: mehr Slide-Layouts unterstützen (seit 12 Tagen)
2. SSH Key friction auflösen (Deadline heute)
3. LiteLLM Präsentation erstellen (seit 4 Tagen)
...
```

### 6. Backlog und Inbox aktualisieren

Schreib den aktualisierten Backlog zurück: übernommene Tasks entfernt, neu angelegte Zeilen (aus Vortag/Meeting/Inbox, die zwar noch nicht fällig sind, aber im Vault als Backlog-Eintrag weitergeführt werden sollen) mit "Erstellt am" = heute. Verworfene Netlight-Kandidaten (aus Schritt 4) werden **nicht** zurückgeschrieben, weder in den Backlog noch sonstwo.

Schreib die aktualisierte Inbox.md zurück (nur verbleibende, nicht übernommene Einträge, getrennt durch `---`, ohne führende/nachfolgende Leerzeilen).

### 7. Meetings eintragen

Führe das Script aus, bevor die Note geschrieben wird:

```bash
uv run $SKILL_DIR/inject_meetings.py --date <YYYY-MM-DD>
```

Das Script trägt die Libri-Outlook-Meetings als `Meetings:` Sektion in die Note ein (kein Netlight-Kalender wird abgefragt). Jedes Meeting wird als `## HH:MM-HH:MM Meeting Name` Überschrift eingetragen. Meetings deren Name mit "Blocker for" beginnt, werden ignoriert. Falls die Note noch nicht existiert, erstellt das Script sie. Falls sie bereits eine `Meetings:` Sektion hat, überspringt es sie.

### Meetings neu laden (refetch)

Falls der User Meetings aktualisieren will (z.B. "Meetings neu laden", "Kalender aktualisieren", "refetch meetings"), nutze:

```bash
uv run $SKILL_DIR/refetch_meetings.py --date <YYYY-MM-DD>
```

Unterschied zu `inject_meetings.py`:
- Überschreibt die bestehende `Meetings:` Sektion komplett mit dem aktuellen Libri-Kalender
- Bestehende Notizen unter einem Meeting-Block werden **beibehalten** und an die neue Zeitposition verschoben (Matching via Titel)
- Meetings die nicht mehr im Kalender sind: Warnung ausgegeben, Notizen verworfen
- Neue Meetings aus dem Kalender: werden ohne Notizen eingefügt

Nach dem Ausführen des Scripts: Lies die Note erneut ein.

### 8. Daily Note schreiben

Erstelle `$VAULT_DIR/Daily Notes/<heute>.md` mit allen übernommenen Tasks, nach Priorität/Alter sortiert (siehe Schritt 5):

```
Top 3 Ziele:
- [ ]
- [ ]
- [ ]

Heute:
- [ ] Task A
- [ ] ⚠️ Task B (seit 9 Tagen)

---

## HH:MM-HH:MM Meeting Name

```

**Regeln:**
- `Top 3 Ziele:` steht ganz oben in der Note, vor `Heute:`, immer mit genau 3 leeren `- [ ]` Checkboxen — wird nicht automatisch befüllt, der User trägt sie manuell ein
- Kein Sektions-Split nach Kategorie (kein `### Libri`/`### Netlight`/`### Allgemein`) — es gibt nur Libri-Inhalte, eine flache Liste reicht
- Nach Priorität/Alter sortiert (siehe Schritt 5), Langläufer oben
- ⚠️-Markierung + `(seit X Tagen)`-Suffix bei Alter ≥ 7 Tagen kommt **nach** dem Task-Text
- Einrückung/Sub-Tasks beibehalten
- Direkt nach `Heute:` Block kommt `---` Divider
- Danach Meetings
- Wenn keine Kandidaten vorhanden: `Heute:` bleibt leer (nur Überschrift)
- Keine `Später:` Sektion

### 9. Fokus-Blöcke in die Note eintragen

Kein Kalender-Push — Fokus-Blöcke werden nur als Markdown-Überschriften in der Note eingetragen (analog zu Meetings), damit sie in Obsidians Agenda/Day-Planner View auftauchen.

```bash
uv run $SKILL_DIR/create_focus_blocks.py --date <YYYY-MM-DD> --print-md
```

Das Script berechnet freie Slots zwischen den Libri-Meetings und plant für jeden Slot ≥ 20 Minuten einen 🟢 **Libri Fokus** Block (Mittagspause 12–13 Uhr wird ausgespart), plus zwei fixe 💬 **Teams / Outlook Check** Blöcke (morgens vor 09:15, abends um 17:00).

`--print-md` gibt die Blöcke als `## HH:MM-HH:MM Titel` Zeilen aus (nach der `[markdown]` Markierung in stdout). Diese Zeilen in die Meetings-Sektion der Note einfügen, chronologisch nach Uhrzeit zwischen die bestehenden Meeting-Überschriften einsortiert.

Falls der User explizit einen Task als Zeitblock haben will (z.B. "DATA-1234 als Zeitblock"), frag nach Dauer und füge eine passende `## HH:MM-HH:MM Titel` Zeile manuell hinzu.

### 10. Bestätigung

Teile dem User kurz mit:
- Datum der neuen Note
- Welche Tasks heute übernommen wurden, sortiert nach Alter, Langläufer (⚠️ ≥7 Tage) hervorgehoben
- Welche Fokus-Blöcke in die Note eingetragen wurden
