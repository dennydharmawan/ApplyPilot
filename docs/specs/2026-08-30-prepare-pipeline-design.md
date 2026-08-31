# Prepare pipeline migration

## Done predicate

The migration is done when all of these statements are true:

1. `prepare-queue` lists only Profile jobs with `fit_score >= 6` and a full job description.
2. `prepare-select` accepts only an explicit non-empty URL list. It records one Profile-scoped selection and never infers approval from score.
3. `prepare-selected` returns only jobs in that exact selection. `prepare-write` rejects jobs outside it.
4. Each selected job can record one Application Bundle with an editable resume, a two-page PDF when the content fits, an evidence report, and a conditional cover letter.
5. Apply reads the Application Bundle. Prepare and verification never submit an application.
6. The repository has no Tailor, Cover, or PDF pipeline stage and no API-era material generator.
7. The full test suite, static checks, and the Denny Profile verification recipe pass. Verification reads the generated files and database state from `.verify/verify-applypilot/<RUN_ID>/`.

## Scope and rigor

This is a high-rigor migration across the CLI, pipeline, database, Apply, repository skills, tests, and documentation. The work changes about twelve tracked files and deletes two obsolete generators. The main risks are accidental bulk preparation, Profile mixing, unsupported candidate claims, broken Apply uploads, and a resume PDF that drifts from the golden two-page standard.

## Workflow

1. Capture the old CLI, database fields, tests, and output conventions.
2. Design the selection and Application Bundle types before changing callers.
3. Add failing tests for queue eligibility, exact selection, write authorization, bundle validation, and Apply bundle loading.
4. Implement the preparation state and CLI helpers.
5. Migrate Apply and remove Tailor, Cover, and PDF pipeline paths in one change.
6. Replace the interactive resume-tailoring instructions with one autonomous Prepare Pipeline Skill.
7. Extend `verify-applypilot` and run it through Denny's Profile without submission.

## Throughput checkpoint

- Blocking first steps. Finish code-flow grounding and choose the state model before editing shared callers.
- Independent workstreams. Read-only code and skill exploration can run in parallel. All repository writes stay with one owner.
- Shared mutable state. Serialize database, Profile, and verification writes. Give every Application Bundle its own directory.
- Smallest safe decomposition. Use one preparation module behind a small CLI interface. Do not add a service layer or preserve the API-era generators.

## State model decision

Two shapes were considered after tracing the CLI, pipeline, database, and Apply callers:

1. Store an approved URL list in a Profile JSON file and add bundle paths directly to jobs. This is easy to inspect, but selection and job writes cannot share a transaction. A crash can leave two sources of truth.
2. Store selection headers and their ordered jobs in SQLite, then put the validated bundle path on the job. This makes exact-list approval, membership checks, and bundle registration transactional. The bundle manifest keeps artifact paths and validation evidence together.

Use the second shape. `preparation_selections` records approval and completion. `preparation_selection_jobs` records the exact ordered list. `jobs.application_bundle_path` is the only handoff to Apply. One partial unique index permits at most one active selection per Profile database.

The public boundary is four commands:

- `prepare-queue` reads eligible jobs. It cannot approve them.
- `prepare-select --url ...` records the exact non-empty approved list.
- `prepare-selected` reads only the active selection.
- `prepare-write --url ... --bundle ...` validates and records one bundle for a selected job.

Bundle paths are Profile-contained. `bundle.json` uses relative artifact paths, declares the cover-letter trigger, and records that the final rewrite and later read-only provenance validation both completed. Apply loads this manifest instead of reconstructing PDF siblings from legacy Tailor fields.
