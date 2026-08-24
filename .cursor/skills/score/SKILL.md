---
name: score
description: >-
  Score ApplyPilot jobs with parallel Cursor Task subagents (Composer), persist
  via score-write, open the dashboard. Use when scoring jobs or replacing run score.
---

# Score

## Setup

Export `APPLYPILOT_DIR` to the Profile dir before any `applypilot` command.

Load once:

- `<profile>/resume.txt`
- `<profile>/profile.json`
- `<profile>/standing-notes.md` (create empty if missing; or run standing-notes skill)

`applypilot run score` is removed. Do not call Codex/Gemini for fit scores.

## Rubric (pass to every subagent)

- 9–10: Perfect match — nearly all required skills/qualifications.
- 7–8: Strong match — most skills; minor gaps.
- 5–6: Moderate — some skills; missing key requirements.
- 3–4: Weak — significant gaps.
- 1–2: Poor — wrong field or level.

Weight skills heavily. Be realistic on seniority. Standing notes and profile prefs can veto (e.g. skip intern/talent-pool) even when skills match.

## Do

1. List pending:

```bash
APPLYPILOT_DIR=<profile> applypilot score-pending
```

Pending means enriched with no `fit_score`. Skip jobs without `full_description`.

2. Split into batches of ~8–12 URLs. For each batch, spawn a Task subagent with `model: composer-2.5-fast`. Give resume, profile prefs, standing notes, rubric, and that batch’s title/site/full_description (truncate long JDs sensibly).

3. Each subagent returns per job: `url`, `score` (1–10), `keywords`, `reasoning`.

4. Parent validates score in 1–10 and URL in the pending set. Persist:

```bash
APPLYPILOT_DIR=<profile> applypilot score-write \
  --url "<url>" \
  --score N \
  --keywords "<csv>" \
  --reasoning "<text>"
```

On write failure, note the URL and continue. Retry a failed batch once.

5. Done when pending is empty or only explicit failures remain:

```bash
APPLYPILOT_DIR=<profile> applypilot dashboard
```

Chat: scored count / still pending / how many ≥7. No score table in chat. Dashboard lists `fit_score >= 5`.
