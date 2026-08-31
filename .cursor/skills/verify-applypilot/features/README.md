# ApplyPilot verification map

This map covers the user-facing Discover, Enrich, Score, and Prepare pipeline. Start
from the Doctor section in the parent skill and keep all proof under the active
`$EVIDENCE_DIR`.

## Baseline preconditions

- Run from `/Users/denny.dharmawan/ApplyPilot`.
- Export `APPLYPILOT_DIR` before invoking `applypilot` because configuration is
  resolved at import time.
- Use one human Profile at a time. Its database is shared mutable state.
- Export a unique `VERIFY_RUN_ID` and `EVIDENCE_DIR` before the first write.
- Run the parent skill's Doctor command and require exit code `0`.

## Driving conventions

- Capture stdout, stderr, command text, and exit code for each command.
- Query the Profile database read-only before and after mutations.
- Use the CLI command a person uses. Internal helper calls are supplemental.
- Preserve the Profile database and evidence during cleanup.

## Proof and skip reporting

- A dry-run proves validation and printed intent. It does not prove network or
  persistence behavior.
- Discover proof needs a live HiringCafe request and a database read afterward.
- Enrich proof needs a description or explicit leftover state in the database.
- Score proof needs persisted scores plus an opened `dashboard.html`.
- Prepare proof needs an exact recorded selection, registered bundle files, and
  unchanged application status in a disposable Denny Profile copy.
- Record any unreachable external URL with the command and error transcript.

## Features

- [Discover jobs](discover.md) covers Profile lane resolution, HiringCafe, and
  database persistence.
- [Enrich jobs](enrich.md) covers description and application URL enrichment.
- [Score and dashboard](score-dashboard.md) covers pending jobs, persisted fit
  scores, and the HTML deliverable.
- [Prepare bundles](prepare.md) covers the approval boundary, Profile isolation,
  bundle validation, and the database handoff to Apply.
