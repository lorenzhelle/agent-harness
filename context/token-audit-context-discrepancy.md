# Token-Audit: Warum das Skript andere Zahlen zeigt als `/context`

Untersuchung vom 2026-08-07 zur Frage: warum weicht `token-audit`s gemeldeter
Token-Verbrauch von der Zahl ab, die Claude Codes eigener `/context`-Befehl
in einer frischen interaktiven Session zeigt?

## Ausgangsbefund

- `/context` in einer frischen Session (Modell `sonnet[1m]`, 967k Fenster) zeigte:
  **16,5k / 967k Tokens (2%)**, aufgeschlüsselt in System-Prompt 6,2k, Skills 9,9k,
  Custom Agents 129, Memory 258, Messages 8.
  **Jedes einzelne MCP-Tool wurde mit `0 tokens` gelistet** (alle ~65 GitLab-/
  Atlassian-Tools ohne Ausnahme).
- `token-audit`s Skript-Output für dieselbe Umgebung: 34.985–46.216 Tokens,
  davon 88–91% (~30–42k) allein in der TOOLS-Sektion.

## Root Cause #1 — der `count_tokens`-Endpoint ist für `system`/`tools` taub

Der LiteLLM-Proxy-Endpoint (`https://llmproxy.ai.libri.cloud`) gibt bei
`/v1/messages/count_tokens` **konstant `8` Input-Tokens** zurück, unabhängig
vom Inhalt oder der Größe von `system` und `tools` — verifiziert durch direkten
Vergleich:

```
count_tokens(system=leer, tools=leer, messages=[hi])        -> 8
count_tokens(system=500 Wörter, tools=echte 94 Tools, ...)   -> 8  (identisch)
```

Das ist ein bekanntes Muster bei Vertex/Bedrock-Passthrough-Routen (bereits
in `SKILL.md` als "Known quirk" dokumentiert). Folge: **Claude Codes eigener
`/context`-Befehl nutzt vermutlich denselben oder einen strukturell ähnlichen
Zählweg** — und fällt bei MCP-Tools auf `0` zurück, statt einen Fehler zu
zeigen. Die `0 tokens` in `/context` sind kein echter Messwert, sondern ein
stiller Ausfall derselben Zählkette.

**Konsequenz:** `/context` unterschätzt den echten Tool-Overhead bei diesem
Endpoint massiv (0 statt ~28-30k Tokens für MCP-Tools). Das Skript ist hier
die einzige Quelle mit tatsächlichem Aussagewert, weil es einen Workaround
fährt (jede Tool-Definition als eigene Fake-User-Message durch den
Tokenizer schicken) statt sich auf `system`/`tools`-Felder zu verlassen.

## Root Cause #2 — das Skript selbst hatte einen ~4% Messfehler

Der Workaround zählte pro Tool `description + "\n" + json.dumps(input_schema)`
als Text — das lässt die tatsächliche JSON-Objekt-Struktur weg (Feldnamen
`"name":`, `"description":`, `"input_schema":`, umschließende `{}`), die im
echten `tools`-Array mitgezählt wird.

Empirisch verifiziert an 94 echten Tool-Schemas aus einer echten Session
(`d937786b-...request.json`):

| Methode | Ergebnis | Fehler vs. Ground Truth |
|---|---|---|
| Ground Truth: ganzes `tools[]`-Array als ein JSON-Blob gezählt | 28.443 tok | — |
| **Alt** (Skript bis 2026-08-07): `desc + "\n" + schema_json` pro Tool | 29.588 tok | **+4,0%** |
| **Neu** (Fix): `json.dumps(tool_object)` komplett pro Tool | 28.447 tok | **+0,0%** |

Ground Truth = das gesamte `tools`-Array in einem Request gezählt (simuliert
über den Text-Workaround, da direkte `tools`-Übergabe wegen Root Cause #1 nicht
funktioniert). Die Methode "ganzes Tool-JSON-Objekt statt lose Text-Teile"
trifft dieses Ziel praktisch exakt.

Der Fix ist in `analyze.py`s Tools-Sektion umgesetzt: statt
`desc_text + "\n" + schema_text` wird nun `json.dumps(t, separators=(",", ":"))`
pro Tool gezählt (kompakte JSON-Serialisierung ohne Leerzeichen, wie sie auch
im echten API-Request vorläge).

## Root Cause #3 (Nebenbefund, noch nicht gefixt) — Modell-Inkonsistenz im Probe

Das Skript probt immer mit `--model claude-latest` (Fallback in
`MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-latest")`), unabhängig
davon, welches Modell in `~/.claude/settings.json` konfiguriert ist
(hier: `"model": "sonnet[1m]"`). Das kann zu einem anderen Beta-Flag-Set,
anderem Kontextfenster oder anderer Tool-Filterung führen als eine echte
Session tatsächlich sieht. Betas im geprobten Request:

```
claude-code-20250219, interleaved-thinking-2025-05-14,
thinking-token-count-2026-05-13, context-management-2025-06-27,
prompt-caching-scope-2026-01-05, mid-conversation-system-2026-04-07,
advisor-tool-2026-03-01, effort-2025-11-24
```

Noch nicht geprüft, ob `sonnet[1m]` andere Betas/Tools laden würde. Offener
Punkt für eine Folge-Untersuchung.

## Nachtrag #1 (widerlegt) — erste Hypothese zum "Messages"-Sprung

Ursprünglich vermutet: nach dem ersten `/context`-Snapshot (16,5k, vor jeder
Nachricht) sprang ein zweiter Snapshot nach einer "Hey"-Nachricht auf 81k,
mit dem kompletten Zuwachs (+64,5k) in der Kategorie "Messages", während alle
MCP-Tools weiterhin bei 0 blieben. Daraus wurde geschlossen, `/context` würde
den fehlenden Tool-Overhead nach dem ersten Turn pauschal "Messages"
zuschlagen.

**Diese Hypothese wurde durch einen eigenen Nachbau widerlegt.** Sowohl im
`-p`-Modus als auch per echtem interaktiven PTY-Test (Skript sendet "hey",
liest die reale Request-Datei aus) zeigte sich: ein einfaches "hey" erzeugt
**nur einen einzigen API-Request**, keine mehreren Turns. Die Zahlen in
diesem einen Request (System ~7k, Tools ~36-45k Tokens, Messages nur ein
paar hundert Tokens) reichten nicht aus, um einen +64,5k-Sprung ausschließlich
in "Messages" zu erklären. Die erste Erklärung war eine zu früh gezogene
Korrelation zweier Zahlen, keine verifizierte Kausalität.

## Root Cause #4 (verifiziert) — `/context` zeigt `cache_creation_input_tokens`, nicht `input_tokens`

Die tatsächliche Ursache wurde gefunden, indem eine echte Live-Session des
Nutzers mit `OTEL_LOG_RAW_API_BODIES` mitgeloggt wurde — dabei fiel neben der
`.request.json` erstmals auch eine `.response.json` an (in reinen `-p`-Probes
taucht diese nie auf, weil das Logging dort offenbar nur Requests erfasst).
Die echte API-Response auf ein einzelnes "hey" in einer frischen Session:

```json
"usage": {
  "input_tokens": 2,
  "cache_creation_input_tokens": 132199,
  "cache_read_input_tokens": 0,
  "output_tokens": 13,
  "cache_creation": { "ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 132199 }
}
```

`input_tokens` ist winzig (2 — nur das Wort "hey" plus Rahmen). Der riesige
Wert steckt in **`cache_creation_input_tokens: 132.199`** — und das deckt
sich exakt mit dem, was `/context` in derselben Session als Gesamt-
Kontextfensternutzung zeigte (132,2k von 967k, 14%).

**`/context` zeigt also korrekt `cache_creation_input_tokens` (bzw. die Summe
aus Cache-Read + Cache-Creation) als Kontextfenster-Füllstand an — das ist
kein Bug.** Cache-Creation-Tokens zählen zum Kontextfenster, auch wenn sie
separat (günstiger) abgerechnet werden als normale Input-Tokens. Der einzige
Bug ist die *Kategorie-Aufschlüsselung darunter*: weil `/context` die
MCP-Tool-Kosten aus Root Cause #1 nicht ermitteln kann (0 statt echter
Werte), landet der komplette nicht zuordenbare Rest — der reale
Tool-Definitions-Overhead, der ja tatsächlich Teil dieses
`cache_creation_input_tokens`-Blocks ist — in der Sammelkategorie "Messages".

Gegengerechnet an der zugehörigen Request-Datei (131 Tools aktiv, u.a.
GitLab, Atlassian, drawio, aws-mcp, cloudwatch-mcp-server, context7, ide):

| Komponente | Zeichen | ≈ Tokens |
|---|---|---|
| `tools[]` (131 Tools) | 240.375 | ~60k |
| `system` | 29.083 | ~7k |
| `messages` (inkl. Skill-/Agent-Katalog-Reminder im ersten Turn) | 71.641 | ~18k |

Summe in der Größenordnung von `cache_creation_input_tokens: 132.199` —
schlüssig, wenn man Tokenizer-Overhead (JSON-Struktur, Sonderzeichen) und
die eigentliche Antwort (`output_tokens: 13`) mit einrechnet.

## Take-away

Die Ausgangsfrage ("warum kostet ein bloßes 'Hey' schon 70-130k Tokens?")
hat eine einfache, jetzt belegte Antwort: **es ist nicht die Nachricht "Hey",
sondern der einmalige Preis, den jede erste Nachricht einer neuen Session
zahlt, um den kompletten Kontext (System-Prompt + alle aktiven Tool-
Definitionen + Skill-/Agent-Katalog) erstmals in den Prompt-Cache zu
schreiben** (`cache_creation_input_tokens`). Bei ~100-130 gleichzeitig
aktiven MCP-Tools macht allein das Tools-Array ~50-60k Tokens aus. Das ist
kein Mess-Artefakt und keine falsche Zuordnung — der Gesamtwert war real,
die ganze Zeit.

Die zwei tatsächlichen, unabhängigen Bugs sind:
1. **`/context`s Kategorie-Aufschlüsselung** kann MCP-Tool-Kosten nicht
   ermitteln (Root Cause #1, der taube `count_tokens`-Endpoint) und zeigt
   pauschal 0 statt eines Fehlers — der reale Betrag verschwindet dadurch
   nicht, er wird nur falsch der Kategorie "Messages" statt "MCP tools"
   zugeschlagen.
2. **Dieses Skripts eigener Workaround** hatte bis 2026-08-07 einen ~4%
   Messfehler durch Text-Konkatenation statt echter JSON-Objekt-Serialisierung
   (Root Cause #2, jetzt gefixt).

Das Skript-Ergebnis (kalter, kein-Cache Wert nach dem 4%-Fix, typischerweise
30-46k für System+Tools+Skills+Messages zusammen) ist konsistent mit der
`cache_creation_input_tokens`-Größenordnung, sobald man berücksichtigt, dass
die tatsächliche Session hier mehr aktive MCP-Server (131 statt 87-94 Tools)
hatte als die zuvor geprobten Skript-Läufe.
