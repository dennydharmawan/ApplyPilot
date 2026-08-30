---
name: verify-applypilot
description: >-
  Drive ApplyPilot through its CLI and verify Discover, Enrich, Score, and
  dashboard behavior with command transcripts and database evidence.
---

# Verify ApplyPilot

Use the real CLI with one explicit Profile. Keep evidence after cleanup.

## Launch

ApplyPilot is a short-lived CLI. Prepare it once from the repository root:

```bash
uv sync --dev
uv run applypilot --help
```

The help command must exit `0` and list `run`, `score-pending`, `score-write`,
and `dashboard`. There is no background process to stop.

## Doctor

Set the Profile and evidence directory before the first write:

```bash
export APPLYPILOT_DIR=/Users/denny.dharmawan/ApplyPilot/profiles/denny
export VERIFY_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export EVIDENCE_DIR="/Users/denny.dharmawan/ApplyPilot/.verify/verify-applypilot/$VERIFY_RUN_ID"
mkdir -p "$EVIDENCE_DIR"
test -f "$APPLYPILOT_DIR/profile.json"
test -f "$APPLYPILOT_DIR/resume.txt"
uv run applypilot --help >"$EVIDENCE_DIR/doctor.stdout.txt" 2>"$EVIDENCE_DIR/doctor.stderr.txt"
```

Stop if the Profile path is wrong or the help command fails. Each concurrent
run needs its own `VERIFY_RUN_ID`. Profile databases are shared mutable state,
so only one verification run may write a given Profile at a time.

## Drive

Read [features/README.md](features/README.md), then open the feature recipe.
Run every command from `/Users/denny.dharmawan/ApplyPilot`.

The primary pipeline entry points are:

```bash
APPLYPILOT_DIR="$APPLYPILOT_DIR" uv run applypilot run discover --query "<keywords>"
APPLYPILOT_DIR="$APPLYPILOT_DIR" uv run applypilot run enrich
APPLYPILOT_DIR="$APPLYPILOT_DIR" uv run applypilot score-pending
APPLYPILOT_DIR="$APPLYPILOT_DIR" uv run applypilot dashboard
```

## Evidence

Store proof in `$EVIDENCE_DIR`. A passing CLI proof contains:

- The exact command and exit code.
- Separate stdout and stderr transcripts.
- The Profile lane configuration used by the run.
- Database counts before and after a state-changing command.
- A read-only query showing the resulting rows or generated dashboard path.

Exercise the CLI entry point. Unit-test helpers alone do not prove a feature.
Dry-run proves request resolution only. Pair it with a real command and its
database or file side effect. External HiringCafe HTTP remains live in the
Discover recipe. Do not replace it with a mock for final proof.

## Cleanup

No service cleanup is needed. Keep `$EVIDENCE_DIR`. Remove only disposable
Profile copies created by the run. Never delete or rewrite the selected human
Profile or its jobs database during cleanup.
