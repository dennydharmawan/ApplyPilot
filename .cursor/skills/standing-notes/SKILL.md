---
name: standing-notes
description: >-
  Update Profile standing notes like /remember: prose in standing-notes.md,
  enumerable rules in profile.json. Use when saving person preference notes for scoring/apply.
---

# Standing notes

Profile-scoped `/remember`. Not repo `AGENTS.md`. Not global user-context.

## Files

Under `APPLYPILOT_DIR`:

- `standing-notes.md` — freeform policy prose
- `profile.json` — enumerable rules engines/skills enforce

## Do

1. Confirm which Profile (`APPLYPILOT_DIR`).
2. Ask what to remember (or take the user’s stated note).
3. Classify:
   - Freeform policy → append/edit `standing-notes.md` (dated or bulleted entries).
   - Enumerable enforceables (title bans, min score, lane toggles already in schema) → update `profile.json` fields; do not dump essays into JSON.
4. If a prose rule has stabilized and should be enforced, promote it into `profile.json` and leave a short pointer in the markdown.
5. Show the diff or final snippet; stop.

## Do not

- Write person policy into repo `AGENTS.md`.
- Blind overwrite the whole notes file unless the human asks to replace.
