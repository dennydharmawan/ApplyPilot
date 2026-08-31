# ApplyPilot

> **ApplyPilot** is the original open-source project, created by
> [Pickle-Pixel](https://github.com/Pickle-Pixel) and first published on GitHub
> on February 17, 2026. This project is not affiliated with applypilot.app,
> useapplypilot.com, or any other product using the ApplyPilot name.

ApplyPilot is a Profile-scoped job pipeline. The CLI handles deterministic
discovery, enrichment, persistence, approval state, and application handoff.
Repository Pipeline Skills handle judgment-heavy Score and Prepare work.

## Pipeline

1. **Discover** searches HiringCafe with the active Profile's lane policy.
2. **Enrich** collects full descriptions and application URLs.
3. **Score** uses `.cursor/skills/score/SKILL.md` and writes fit judgments to
   the Profile database.
4. **Prepare** turns one exact human-approved selection into validated
   Application Bundles.
5. **Apply** may submit a prepared job only when separately invoked.

A score of 6 or higher makes a job eligible for the Preparation queue. It is
not approval. Preparation approval authorizes material generation only and
never authorizes submission.

## Profile setup

Set the Profile before importing or invoking ApplyPilot:

```bash
export APPLYPILOT_DIR=/absolute/path/to/profiles/denny
uv sync --dev
uv run applypilot --help
```

Each Profile owns its profile JSON, standing notes, resume bank, database,
dashboard, selections, and generated bundles. Do not mix Profile material.

## Discover, Enrich, and Score

```bash
uv run applypilot run discover --query "software engineer node.js typescript"
uv run applypilot run enrich
uv run applypilot score-pending
uv run applypilot dashboard
```

Use `.cursor/skills/discover/SKILL.md`, `.cursor/skills/enrich/SKILL.md`, and
`.cursor/skills/score/SKILL.md` for the complete workflows. `run score` exists
only to fail loudly and route the operator to the Score Pipeline Skill.

## Prepare

Use `.cursor/skills/prepare/SKILL.md`. The approval boundary is explicit:

```bash
uv run applypilot prepare-queue
uv run applypilot prepare-select \
  --url 'https://example.com/jobs/approved-one' \
  --url 'https://example.com/jobs/approved-two'
uv run applypilot prepare-selected
uv run applypilot prepare-write \
  --url 'https://example.com/jobs/approved-one' \
  --bundle "$APPLYPILOT_DIR/resumes/applications/acme-role/bundle.json"
```

If one selected job cannot be prepared after diagnosis, close it explicitly
and continue the approved list:

```bash
uv run applypilot prepare-fail \
  --url 'https://example.com/jobs/approved-two' \
  --reason 'candidate evidence cannot support a required claim'
```

Every bundle lives under
`$APPLYPILOT_DIR/resumes/applications/<company-role>/` and contains editable
resume source, an application-ready PDF, an evidence report, a manifest, and a
cover letter only when the posting, upload field, or email application requires
one.

## Apply

Apply consumes registered Application Bundles. It does not infer readiness
from scores or loose files.

```bash
uv run applypilot apply --dry-run --url 'https://example.com/jobs/approved-one'
```

Omit `--dry-run` only when application submission is explicitly authorized.

## Tests

```bash
uv run pytest -q
```

User-facing verification lives in
`.cursor/skills/verify-applypilot/SKILL.md`. Verification evidence is stored
under `.verify/verify-applypilot/<RUN_ID>/`.

## License

AGPL-3.0-only.
