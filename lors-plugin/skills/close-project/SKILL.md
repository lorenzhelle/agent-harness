---
name: close-project
description: Use this skill when the user wants to close, wrap up, finish, complete, or archive a PARA project. Triggers on phrases like "close project", "wrap up project", "I'm done with", "archive project", "finish project", "project is done", "distill project", "clean up project". This skill guides the user through a structured closing ceremony — reviewing notes, extracting reusable knowledge into Areas/Resources, removing clutter, and archiving the project folder.
---

# Close Project

A structured walkthrough to properly close a PARA project. The goal is threefold:
1. **Distill** — extract lasting knowledge into Areas or Resources before it's buried in an archive
2. **Clean** — remove noise, drafts, and irrelevant artifacts
3. **Archive** — move the project to `6 - archive` with a clear closing note

---

## How to run this skill

Work through the phases below in order, but adapt to the project's size and complexity. For a small project with 3 notes, the whole thing can be done in a single conversation. For a large project with dozens of files, take it one phase at a time.

**Be conversational.** Ask questions, let the user think out loud, and make suggestions. Don't just execute silently — the value is in the reflection, not just the file moves.

---

## Phase 0: Orient

Before anything else, understand what you're working with.

1. Ask the user which project they want to close, or if it's already clear from context, confirm it.
2. List the files in the project folder (use `ls` or Glob).
3. Give the user a quick summary: how many files, rough topics covered, any obvious structure.
4. Ask: *"What was the outcome? Did you finish what you set out to do, or are you closing it for another reason (abandoned, superseded, on hold)?"*

Note the closure type — it matters for how you write the archive note later.

---

## Phase 1: Triage each file

Go through the files one by one (or group similar ones). For each file or group, ask the user to decide:

- **Keep as-is (archive)** — still useful for future reference, but no active home
- **Move to an Area** — ongoing responsibility this connects to (e.g., Freelance, Engineering and AI, Netlight Career)
- **Move to a Resource** — a topic or reference that could be useful again (e.g., AI & LLMs, Software Engineering, n8n)
- **Delete** — drafts, scratch notes, duplicates, dead ends that add no value

Read the file if the user is unsure what it is. Suggest a destination based on its content.

**Vault structure for reference:**
- Areas: `3 - areas/` (Engineering and AI, Freelance, Netlight Career, Personal Knowledge Management, Sport & Gesundheit, Kleingarten, Fahrrad - Graveln, Reisen, Startup Ideas)
- Resources: `4 - ressources/` (AI & LLMs, Software Engineering, n8n, Obsidian Templates, People, Reisen, Shopping, Geschenke)
- Archive: `6 - archive/`

If a file clearly belongs somewhere, suggest it confidently. If it's ambiguous, present 2 options and let the user choose.

---

## Phase 2: Distill key learnings

After triaging, ask: *"Before we archive this — what did you learn from this project that you want to remember?"*

Help the user think through:
- **Process learnings** — what worked, what didn't, what you'd do differently
- **Domain knowledge** — insights about the topic that are worth keeping
- **Contacts or relationships** — people met, context on them (goes to Resources/People)
- **Templates or reusable artifacts** — anything that could serve future projects

For each learning, decide together where it lives:
- A new note in a Resource folder
- An addition to an existing note
- A short entry in an Area note
- An `_index.md` or `_learnings.md` file in the archive folder

Offer to write these notes for the user if they talk through the content.

---

## Phase 3: Write the archive note

Create a brief closing note inside the project folder before archiving. Keep it short — just enough context for future-you to understand what this was.

Use this template:

```
# [Project Name] — Closed [Date]

**Outcome:** [Completed / Abandoned / Superseded / On hold]
**Summary:** [1-2 sentences on what was done]
**Key output:** [Main deliverable or result, if any]
**Distilled to:** [List of notes/areas/resources where knowledge was moved]
**Why closed:** [Brief context if not obvious]
```

Write the file as `_CLOSED.md` in the project folder.

---

## Phase 4: Execute the moves

Now actually move things. For each decision from Phase 1:
- Use Bash `mv` commands to move files to their new locations
- For Resources/Areas: confirm the destination subfolder exists, or create it
- Files being deleted: confirm with the user before deleting

Show the user what you're about to do before executing. A quick list like:
```
Moving:
  → notes/X.md  →  3 - areas/Engineering and AI/
  → draft.md    →  DELETE
  → research.md →  4 - ressources/AI & LLMs/
Archiving rest to:  6 - archive/[project-name]/
```

Then ask: *"Ready to execute?"*

---

## Phase 5: Archive

Move the entire project folder (now containing only the `_CLOSED.md` and anything being kept for reference) to `6 - archive/`.

```bash
mv "2 - projects/[project-name]" "6 - archive/[project-name]"
```

Confirm it's done and show the final archive structure.

---

## Closing

End with a brief summary of what happened:
- What was archived
- What was distilled (notes created/updated)
- What was deleted

Something like: *"Project closed. You moved 3 notes to Resources, wrote a learnings note on [topic], and archived the rest. The project folder is now in `6 - archive/`."*

---

## Tips

- Don't rush Phase 1. The triage is where most of the value is lost if done carelessly.
- If the user is unsure whether to keep something, default to archive (not delete). It's searchable later.
- If a file would fit multiple Resource folders, ask which topic is more likely to trigger a future search.
- Some projects are emotionally significant — be aware of this and don't be purely mechanical.
- If the project has sub-folders, recurse into them during Phase 1.
