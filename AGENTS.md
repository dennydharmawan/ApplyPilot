# ApplyPilot agents

Set `APPLYPILOT_DIR` to the Profile (`profiles/<slug>/` in this checkout, or `~/.applypilot/profiles/<slug>/`). Denny: `profiles/denny/`. Pipin: `profiles/pipin/`. Export it in the process env before `applypilot` (import-time).

## Pipeline Skills

Primary UX for Discover → Enrich → Score is `.cursor/skills/` (Codex: `.codex/skills` → same dir via symlink):

| Skill | Role |
|--------|------|
| `discover` | HiringCafe engine via `applypilot run discover --query` |
| `enrich` | Playwright cascade, then Cursor leftovers via `enrich-write` |
| `score` | Parallel Cursor judgment → `score-write` → `dashboard` |
| `standing-notes` | Profile `/remember` → `standing-notes.md` / `profile.json` |

`applypilot run score` is removed (API LLM scoring is gone).

Before creating, changing, or uploading a resume for a job application, read `.cursor/skills/resume-tailoring/SKILL.md`. Use `$APPLYPILOT_DIR/resumes/` as the resume bank and `/Users/denny.dharmawan/portfolios/personal-site/public/resume.pdf` as the golden resume.

## Scoring results

After the Score skill (or when the human asks for scores), the deliverable is the HTML dashboard, not a chat table or CSV.

```bash
APPLYPILOT_DIR=<profile> applypilot dashboard
```

Done when `<profile>/dashboard.html` exists and has been opened. Chat: counts only (scored / pending / how many at 7+). The file lists every job with `fit_score >= 5`. Raw scores stay in `<profile>/applypilot.db`.

Domain language: root `CONTEXT.md`. Design: `docs/specs/2026-08-24-cursor-pipeline-skills-design.md`.
