# Enrich jobs

Enrich fills full descriptions and application URLs for jobs already stored in
the active Profile database.

## Sub-features

- `enrich-cascade` uses the Playwright JSON-LD and CSS cascade.
- `enrich-leftovers` lists pages that need agent extraction.
- `enrich-write` persists a recovered description and application URL.

## How to get to it (user POV)

- Run `applypilot run enrich` after Discover.
- Inspect unresolved pages with `applypilot enrich-leftovers`.
- Persist a recovered page with `applypilot enrich-write`.

## Driving it with the CLI

Preconditions:

- Doctor passed for the selected `APPLYPILOT_DIR`.
- Discover stored at least one job.

- **Capture pending state.** Query `SELECT COUNT(*) FROM jobs WHERE full_description IS NULL;` into `$EVIDENCE_DIR/enrich-before.txt`.
- **Run Enrich.** Run `APPLYPILOT_DIR="$APPLYPILOT_DIR" uv run applypilot run enrich >"$EVIDENCE_DIR/enrich.stdout.txt" 2>"$EVIDENCE_DIR/enrich.stderr.txt"`; record its exit code in `$EVIDENCE_DIR/enrich.exit.txt`.
- **List leftovers.** Run `APPLYPILOT_DIR="$APPLYPILOT_DIR" uv run applypilot enrich-leftovers >"$EVIDENCE_DIR/enrich-leftovers.txt" 2>&1`.
- **Prove state.** Query `SELECT url, application_url, LENGTH(full_description), detail_scraped_at FROM jobs WHERE full_description IS NOT NULL ORDER BY detail_scraped_at DESC LIMIT 20;` into `$EVIDENCE_DIR/enrich-after.txt`.

## Gotchas

- An application URL without `full_description` is not ready for Score.
- Retryable transport failures remain queued and are not Cursor leftovers.
- Browser-backed pages may require the active Profile's signed-in session.
