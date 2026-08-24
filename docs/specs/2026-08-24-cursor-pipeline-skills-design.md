# Cursor Pipeline Skills (Discover → Enrich → Score)

**Date:** 2026-08-24
**Status:** Ready for review
**Edition:** ApplyPilot Indonesia Edition

## Problem

Score today is sequential API-LLM (`codex exec` / Gemini), slow and rate-limited. Discover/Enrich are CLI-centric while the human/agent UX should be Cursor skills. Enrich’s tier-3 extraction also calls an API LLM. The product decision is: **no Codex/Gemini (or other API LLM) on Discover → Enrich → Score**; judgment and hard extraction happen in Cursor; mechanical crawl/scrape stay in Python engines.

## Goals

1. Primary entrypoints for Discover, Enrich, and Score are repo Pipeline Skills under `.cursor/skills/`.
2. Score runs as parallel Composer 2.5 Task subagents; results persist to the Profile DB; deliverable is the HTML dashboard (chat: counts only).
3. Standing notes are the Profile-scoped `/remember`: prose in `standing-notes.md`, enumerable rules in `profile.json`, updated by a dedicated skill.
4. Audit/fix Enrich retry behavior and align docs with HiringCafe-only Discover.
5. **No backward compatibility** with API-LLM scoring or Enrich LLM tier-3.

## Non-goals

- Tailor, Cover Letter, Auto-Apply redesign (intent: Cursor-only later; not designed here).
- Rewiring JobSpy/Workday as live Boards.
- Driving Cursor from an external SDK so `applypilot run score` shells Composer.
- Preserving dual-mode “CLI LLM score if skill unavailable.”

## Domain terms

See root `CONTEXT.md`: **Pipeline Skill**, **Discover**, **Enrich**, **Score**, **Standing notes**, **Profile**, **Board**.

## Approach

**Skills-as-orchestrators:** Skills are UX and control flow. Discover/Enrich skills invoke Python engines. Score skill performs Cursor judgment and calls thin write helpers. No API LLM on these three stages.

## Components

### Pipeline Skills (`.cursor/skills/`)

| Skill dir (`.cursor/skills/<dir>/SKILL.md`) | Responsibility |
|--------|----------------|
| `discover` | Set `APPLYPILOT_DIR`, accept query, run HiringCafe engine, report new/duplicate counts. |
| `enrich` | Run Playwright cascade (JSON-LD → CSS only). Hard leftovers: Cursor extracts JD + apply URL; persist via `enrich-write`. Summarize ok/partial/error. |
| `score` | Load resume, `profile.json`, `standing-notes.md`, and the Score rubric (bands below, embedded in the skill). List pending. Fan out Task subagents by batch (`model`: `composer-2.5-fast` unless Denny specifies otherwise). Validate results; fold keywords into reasoning; `score-write`. Open dashboard; chat counts only. |
| `standing-notes` | Interview like `/remember`; append/edit `standing-notes.md` or promote enumerable rules into `profile.json`. |

### Engines / CLI

| Surface | Role |
|---------|------|
| HiringCafe discover engine | Unchanged Board crawl; invokable by Discover skill (and optionally thin `applypilot run discover`). |
| Playwright enrich (tiers 1–2) | Detail scrape without API LLM. |
| `applypilot score-write` | Persist `fit_score`, `score_reasoning`, `scored_at` for a URL (bulk variant allowed). `score_reasoning` is `keywords` newline `reasoning` (same shape as today). |
| `applypilot enrich-write` | Persist Cursor leftover extraction: set `full_description` and/or `application_url`, set `detail_scraped_at`, clear `detail_error`. |
| Pending list helper | List enriched jobs with `fit_score IS NULL` (CLI or library used by Score skill). |
| Enrich leftover list | Rows needing Cursor extraction after the Playwright pass (see Enrich leftovers). |

### Profile artifacts

```text
APPLYPILOT_DIR/
  profile.json           # structured / enumerable prefs
  standing-notes.md      # freeform policy prose
  resume.txt
  applypilot.db
  dashboard.html         # after dashboard command
```

## Data flow

```text
discover skill → jobs rows
enrich skill   → full_description, application_url
standing-notes → anytime (Score reads on run)
score skill    → parallel Cursor judgment → score-write → dashboard
```

Pending for Score: `full_description IS NOT NULL AND fit_score IS NULL`. Jobs without full JD are not scored (Score does not invent descriptions).

## Enrich leftovers

After the Playwright cascade (JSON-LD → CSS, no API LLM):

**Leftover selection** (Enrich skill / leftover list helper):

- Rows with no usable `full_description` after the engine pass, including `partial` (missing description), `error`, or blocked-site skips that never got a description — whatever the engine records so the skill can enumerate them.
- Retryable HTTP failures are re-queued for Playwright first (see Audit); they are not Cursor leftovers until non-retryable failure or empty extraction.

**Persist contract:** Cursor extracts text; parent calls `enrich-write` with `url`, `full_description` (required to become Score-eligible), optional `application_url`. Helper sets `detail_scraped_at`, clears `detail_error`. Partial Cursor success (apply URL only, still no description) may update `application_url` but the job remains Score-ineligible until `full_description` is set.

## Score rubric

Owned by the Score skill (not a Profile file). Embed these bands in the skill and pass them to every subagent (same criteria as the former `SCORE_PROMPT`):

- 9–10: Perfect match — direct experience in nearly all required skills/qualifications.
- 7–8: Strong match — most required skills; minor gaps easily bridged.
- 5–6: Moderate match — some relevant skills; missing key requirements.
- 3–4: Weak match — significant gaps; substantial ramp-up.
- 1–2: Poor match — different field or experience level.

Also instruct subagents to weigh skills heavily, consider transferable experience, and be realistic on seniority vs requirements. Profile prefs + standing notes can lower or veto a score (e.g. intern/talent-pool) even when skills match.

## Score fan-out

1. Parent loads Profile context once (resume, profile.json, standing-notes) and the Score rubric above.
2. Split pending into batches (default ~8–12 jobs per batch).
3. One Task subagent per batch; model `composer-2.5-fast` unless overridden.
4. Each subagent returns per job: `url`, `score` (1–10), `keywords`, `reasoning`.
5. Parent validates (in-range score, URL in pending set). Reject invalid rows; retry that job once or leave unscored.
6. Persist via `score-write`: store `fit_score`; set `score_reasoning` to `"{keywords}\n{reasoning}"` (preserve current DB shape; no new keywords column). On write failure: record URL, continue others.
7. Subagent crash: retry batch once; then leave those URLs unscored and report.
8. Done: no pending left, or only explicitly failed leftovers. Run dashboard; chat = scored / pending / count ≥7.

Optional later: explicit rescore (clear scores and re-queue). Not required for v1.

## Standing notes

- Analogous to personal `/remember`, scoped to one Profile (not repo `AGENTS.md`, not global user-context).
- Prose → `standing-notes.md`.
- Enumerable enforceable rules → `profile.json` (promote when the human asks or when a rule stabilizes).
- Score inputs: resume + full JD + profile.json + standing-notes.md.

## Deletes (no backward compat)

- Product LLM scorer path for fit (Codex/Gemini/HTTP) and sequential `run score` as the scoring UX.
- Enrich tier-3 API LLM extraction.
- Dual-mode flags preserving API LLM score/enrich.
- Stale docs that describe JobSpy multi-board Discover as live (rewrite to HiringCafe + skills).

Keep on disk if unused: JobSpy/Workday modules (no rewiring). Do not change Tailor/Cover/Apply in this cut.

## Audit fixes (same cut)

- Enrich: use `RETRYABLE_STATUSES` (408/429/5xx); do not permanently stamp `detail_scraped_at` on retryable failures so they re-queue.
- Enrich skill reports blocked sites / errors clearly.
- Discover skill documents hardcoded lanes, 3-day window, query source (not `searches.yaml`).
- Invalid scores are not persisted.
- `AGENTS.md` documents skill entrypoints and dashboard deliverable; no API-LLM `run score` instructions.

## Testing

**Automated**

- `score-write`: persists fields; folds keywords into `score_reasoning`; rejects out-of-range scores and unknown URLs.
- `enrich-write`: sets description/apply URL, stamps scraped-at, clears `detail_error`.
- Pending helper: only enriched unscored rows.
- Enrich retryable HTTP does not terminal-stamp scraped-at; non-retryable remains terminal.
- Existing HiringCafe tests remain green; update if contracts change.
- No Score tests that call live Codex/Gemini.

**Manual**

- Pipin (or fixture Profile): discover → enrich → score with parallel subagents; dashboard opens; chat counts only.
- standing-notes append visible to next Score context.
- Confirm no API LLM on Enrich leftovers or Score.

## Success criteria

1. Four skills under `.cursor/skills/` aligned with `CONTEXT.md`.
2. API LLM removed from Enrich and Score paths.
3. Enrich retry + docs/`AGENTS.md` aligned.
4. One real Profile dry-run through Score → dashboard.

## Implementation order (informative)

1. CLI helpers (`score-write`, `enrich-write`, pending/leftover lists) + tests.
2. Strip API LLM from Enrich + Score modules; enrich retry fix.
3. Author four skills + update `AGENTS.md` / README Discover section.
4. Manual dry-run on a Profile.

Implementation starts only after this spec is approved and Denny asks to implement.
