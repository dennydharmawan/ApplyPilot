# Score and dashboard

Score judges enriched jobs against one Profile, persists fit scores, and opens
the HTML dashboard that lists every job scoring at least five.

## Sub-features

- `score-pending` lists enriched jobs without a score.
- `score-write` persists one validated score and reasoning.
- `score-complete` leaves no eligible pending jobs except recorded failures.
- `dashboard` writes and opens the Profile's `dashboard.html`.

## How to get to it (user POV)

- Run `applypilot score-pending` to list work.
- Follow `.cursor/skills/score/SKILL.md` to judge and persist every job.
- Run `applypilot dashboard` to produce the deliverable.

## Driving it with the CLI

Preconditions:

- Doctor passed for the selected `APPLYPILOT_DIR`.
- At least one job has `full_description`.
- The active Profile resume, preferences, and standing notes are loaded.

- **Capture pending.** Run `APPLYPILOT_DIR="$APPLYPILOT_DIR" uv run applypilot score-pending >"$EVIDENCE_DIR/score-pending-before.txt" 2>&1`.
- **Drive Score.** Follow `.cursor/skills/score/SKILL.md`. Capture each `score-write` command and result under `$EVIDENCE_DIR`.
- **Prove scores.** Query `SELECT fit_score, COUNT(*) FROM jobs WHERE fit_score IS NOT NULL GROUP BY fit_score ORDER BY fit_score DESC;` into `$EVIDENCE_DIR/score-counts.txt`.
- **Build dashboard.** Run `APPLYPILOT_DIR="$APPLYPILOT_DIR" uv run applypilot dashboard >"$EVIDENCE_DIR/dashboard.stdout.txt" 2>"$EVIDENCE_DIR/dashboard.stderr.txt"`.
- **Prove deliverable.** Run `test -s "$APPLYPILOT_DIR/dashboard.html"` and copy it to `$EVIDENCE_DIR/dashboard.html`. Open the Profile dashboard and confirm every listed job has `fit_score >= 5`.

## Gotchas

- `applypilot run score` is removed. Use the Score Pipeline Skill.
- Jobs without a full description are not Score-pending.
- Chat output reports counts only. The dashboard is the job-by-job deliverable.
- A generated file alone is insufficient. Open the dashboard before reporting
  Score complete.
