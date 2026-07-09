---
name: close-day
description: >
  Spielt Infos aus der heutigen Daily Note automatisch in Projekte zurück.
  Extrahiert Meeting-Erkenntnisse, neue Personen, TODOs und ordnet sie
  interaktiv den richtigen Projektdateien zu.
  Trigger: "close day", "tag abschließen", "daily zurückspielen", "end of day",
  "was muss ich noch pflegen", "/close-day".
version: 1.0.0
---

# Close Day Skill

Liest die heutige Daily Note und spielt relevante Infos interaktiv in den Vault zurück.

## Vault-Struktur (Libri-Projekte)

```
2 - projects/Libri/
  People/              ← Person-Notes (eine pro Person)
  Plureos/
    Meeting Notes/
  AI Enablement/
    Meeting Notes/
  Kundenservice/
    Meeting Notes/
  [weiteres Projekt]/
    Meeting Notes/
```

## Workflow

### 1. Daily Note laden

Lade `/mnt/c/Users/lhelle/Documents/para-vault/Daily Notes/<heute>.md`.
Falls nicht vorhanden: "Keine Daily Note für heute gefunden."

### 2. Extraktion

Extrahiere aus der Daily Note automatisch:

**A) Personen**
Alle Namen die in Meeting-Sektionen (`## HH:MM-...`) auftauchen:
- Vorname + Nachname erkennbar
- Prüfe ob `2 - projects/Libri/People/<Name>.md` existiert
- Markiere als NEU oder BEKANNT

**B) Meeting-Sektionen**
Alle `## HH:MM-HH:MM <Meeting-Titel>` Blöcke:
- Ermittle Projekt-Zuordnung aus Titel/Inhalt (Plureos → `Plureos/Meeting Notes/`, Storno/Kundenservice → `Kundenservice/Meeting Notes/`, LiteLLM/AHT/Freshdesk → `AI Enablement/Meeting Notes/`)
- Prüfe ob Meeting-Note bereits existiert unter `Meeting Notes/YYYY-MM-DD <Titel>.md`

**C) TODOs**
Alle `- [ ]` die noch offen sind (kein Projekt-Kontext klar) + alle `TODO ...` im Fließtext.

**D) Erkenntnisse / Entscheidungen**
Bullet Points in Meetings die Entscheidungen, Architektur-Info oder wichtige Fakten enthalten (kein Action-Item, aber wissenswert).

### 3. Interaktive Review

Zeige Zusammenfassung aller Funde, dann gehe Kategorie für Kategorie durch:

#### 3a) Neue Personen

Für jede neue Person:
```
Neue Person: [Name]
Gefunden in: [Meeting-Titel]
Kontext: [kurzer Satz aus Meeting-Notizen]

→ People-Note anlegen? [j/n/skip]
  Welches Projekt? [Plureos / Kundenservice / AI Enablement / anderes]
```

Falls j: erstelle `People/<Name>.md` mit Template (siehe unten), befülle Kontext aus Meeting-Notizen.

#### 3b) Meeting-Notes

Jedes Projekt hat eine einzige Datei `Meeting Notes.md` die akkumuliert wird.

Für jede Meeting-Sektion:
```
Meeting: [Titel] ([Zeit])
Zuordnung erkannt: [Projekt]

→ In Meeting Notes.md eintragen? [j/n]
```

Falls j: hänge den **exakten Inhalt** des Meeting-Blocks aus der Daily Note an `[Projekt]/Meeting Notes.md` an.
Format:

```markdown
## YYYY-MM-DD – HH:MM-HH:MM [Meeting-Titel]

[exakter Inhalt aus Daily Note, unverändert]
```

Falls `Meeting Notes.md` noch nicht existiert: neu erstellen.
Inhalt wird nicht zusammengefasst oder umgeschrieben – 1:1 Kopie aus Daily.

#### 3c) TODOs ohne Projektzuordnung

Für jeden offenen TODO:
```
TODO: "[Task-Text]"
Kontext: [woher / welches Meeting]

→ Wo hin? [Projekt eingeben / skip / bleibt in Daily]
```

Falls Projekt gewählt: hänge Task als `- [ ]` an die entsprechende Projektübersicht an.

### 4. Ausführung

Nach allen Bestätigungen:
- Erstelle/update alle bestätigten Files
- Zeige Zusammenfassung was erstellt/geändert wurde

## People-Note Template

```markdown
---
name: [Name]
firma: Libri
rolle: 
bereich: [aus Kontext]
tags: [person, libri]
---

# [Name]

## Kontext

- **Rolle:** 
- **Bereich:** [aus Meeting]
- **Firma:** Libri

## Notizen

[Kontext aus Meeting-Notizen]

## Projekte & Themen

- [[Projekt]]

## Interaktionen

| Datum | Kontext | Notiz |
|-------|---------|-------|
| YYYY-MM-DD | [Meeting-Titel] | [kurze Notiz] |
```

## Meeting Notes Datei

Pro Projekt eine Datei `Meeting Notes.md`. Neue Einträge werden oben oder unten angehängt (unten = chronologisch). Header-Format:

```markdown
## YYYY-MM-DD – HH:MM-HH:MM [Meeting-Titel]

[Inhalt exakt aus Daily Note]
```

## Projekt-Mapping (Heuristik)

| Keywords in Meeting-Titel/Inhalt | Projekt |
|----------------------------------|---------|
| Plureos, Logistik, Move3, AKL | `Plureos/Meeting Notes/` |
| Storno, Mein Libri, ESB | `Kundenservice/Meeting Notes/` |
| LiteLLM, AHT, Freshdesk, Kundenservice Projekt | `AI Enablement/Meeting Notes/` |
| Codepilot, NL | `../NL - AI enablement/` |
| DCing, Tim | `DCing mit Tim` (eigene Note) |
| 1on1, Sync Bjarne, Weekly | `AI Enablement/Meeting Notes/` |

Wenn unklar: User fragen.
