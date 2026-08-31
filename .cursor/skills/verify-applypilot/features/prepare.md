# Prepare bundles

Prepare records one exact approved job list and registers one validated,
Profile-scoped Application Bundle per selected job. It does not submit.

## Sub-features

- `prepare-queue` lists described jobs scoring at least 6.
- `prepare-select` records only repeated explicit `--url` values.
- `prepare-selected` preserves the approved order until every member completes.
- `prepare-write` validates selection membership, Profile containment, files,
  cover trigger, final unslop state, and factual provenance state.
- `prepare-fail` closes one selected job with a concrete terminal reason so a
  failed item cannot leave the approval list permanently active.
- Apply readiness comes from `jobs.application_bundle_path`.

## Driving it with the CLI

Use a disposable copy so verification exercises Denny's real Profile inputs
without changing Denny's human database:

1. Create `$EVIDENCE_DIR/profile-copy` and set `VERIFY_PROFILE` to it. Use
   SQLite `.backup` for `applypilot.db`. Copy only `profile.json`,
   `standing-notes.md`, `searches.yaml`, the active resume inputs, and the
   required files under `resumes/`. Exclude `chrome/`, `logs/`, `apply-workers/`,
   DB WAL/SHM files, and legacy generated directories. Record the source and
   copy paths.
2. Insert one fixture job with a full description and `fit_score = 6` into the
   copied database. Capture `prepare-queue` and prove the fixture is listed.
3. Run `prepare-select` with no `--url`; capture its non-zero exit. Then select
   only the fixture URL and capture `prepare-selected`.
4. Create a bundle under
   `$VERIFY_PROFILE/resumes/applications/<company-role>/` from Denny's golden
   resume or Denny's existing resume bank. Include editable source,
   `resume.txt`, a readable PDF, structured provenance, `report.md`, and
   `bundle.json`. Use no cover letter unless the fixture description declares
   a trigger.
5. Run `prepare-write`, then capture the manifest, file listing, PDF page count,
   selection status, job bundle path, and `apply_status`.
6. Run `apply --gen --url <fixture-url>` against the disposable Profile. This
   utility mode loads the bundle and writes a prompt without launching a browser
   or submitting. Capture the prompt path and prove the job lock was released.

The final database query must show a completed selection, the exact absolute
manifest path, and a null `apply_status`. The only permitted Apply command in
this recipe is `apply --gen --url`; do not open a form or submit anything.

Also prove the failure lifecycle with a second selected fixture: run
`prepare-fail`, then show its member status and concrete failure reason while
the selection closes as `completed_with_failures`.

## Gotchas

- Export the disposable `APPLYPILOT_DIR` in a fresh process because ApplyPilot
  resolves Profile paths at import time.
- A file tree alone is not proof; `prepare-write` must register it.
- A score is queue eligibility only. The failing empty-selection transcript is
  part of the approval-boundary proof.
- Keep the Profile copy under `$EVIDENCE_DIR`; it is evidence, not cleanup debris.
