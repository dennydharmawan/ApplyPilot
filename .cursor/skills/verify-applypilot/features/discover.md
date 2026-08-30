# Discover jobs

Discover searches HiringCafe with the active Profile's lane policy and stores
deduplicated jobs in that Profile's database.

## Sub-features

- `discover-profile` resolves lane settings from the active Profile.
- `discover-preview` prints the query and lanes without crawling.
- `discover-live` searches HiringCafe through the CLI.
- `discover-persist` stores new jobs and reports duplicates.
- `discover-invalid-lanes` rejects an invalid Profile before HTTP work.

## How to get to it (user POV)

- Preview with `applypilot run discover --dry-run --query <keywords>`.
- Run with `applypilot run discover --query <keywords>`.

## Driving it with the CLI

Preconditions:

- Doctor passed for the selected `APPLYPILOT_DIR`.
- `$EVIDENCE_DIR` exists.
- The selected Profile has an explicit non-empty Discover lane list.

- **Capture configuration.** Run `cp "$APPLYPILOT_DIR/profile.json" "$EVIDENCE_DIR/profile.json"`. The copy records the exact Profile input without changing it.
- **Capture the command.** Run `printf '%s\n' 'APPLYPILOT_DIR=<profile> uv run applypilot run discover --query "software engineer node.js typescript"' >"$EVIDENCE_DIR/discover.command.txt"`.
- **Preview resolution.** Run `APPLYPILOT_DIR="$APPLYPILOT_DIR" uv run applypilot run discover --dry-run --query "software engineer node.js typescript" >"$EVIDENCE_DIR/discover-dry-run.stdout.txt" 2>"$EVIDENCE_DIR/discover-dry-run.stderr.txt"`. Exit code `0`; stdout names the query and selected lanes.
- **Capture before state.** Run `sqlite3 "$APPLYPILOT_DIR/applypilot.db" "SELECT COUNT(*), COALESCE(MAX(discovered_at), '') FROM jobs WHERE strategy = 'hiringcafe';" >"$EVIDENCE_DIR/discover-before.txt"`.
- **Run live Discover.** Run `APPLYPILOT_DIR="$APPLYPILOT_DIR" uv run applypilot run discover --query "software engineer node.js typescript" >"$EVIDENCE_DIR/discover.stdout.txt" 2>"$EVIDENCE_DIR/discover.stderr.txt"`; then run `printf '%s\n' "$?" >"$EVIDENCE_DIR/discover.exit.txt"`. The exit code is `0`; stdout reports pages, fetched, inserted, and duplicates.
- **Prove persistence.** Run `sqlite3 -header -column "$APPLYPILOT_DIR/applypilot.db" "SELECT url, title, location, strategy, discovered_at FROM jobs WHERE strategy = 'hiringcafe' ORDER BY discovered_at DESC LIMIT 20;" >"$EVIDENCE_DIR/discover-after.txt"`. Rows retain HiringCafe URLs, titles, locations, strategy, and discovery timestamps.
- **Confirm proof survived.** Run `find "$EVIDENCE_DIR" -maxdepth 1 -type f -print | sort`. The configuration, commands, transcripts, exit code, and database reads remain present.

## Gotchas

- `APPLYPILOT_DIR` must be exported before Python imports ApplyPilot.
- A successful dry-run does not contact HiringCafe or write jobs.
- A second live run may insert zero rows because URL uniqueness deduplicates it.
- HiringCafe availability is an external boundary. Keep its failure transcript.
- Do not test invalid lanes by overwriting a human Profile. Use a disposable
  Profile directory in a focused test.
