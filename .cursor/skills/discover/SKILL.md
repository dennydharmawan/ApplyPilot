---
name: discover
description: >-
  Run ApplyPilot Discover for a Profile via HiringCafe. Use when discovering
  jobs, running the discover stage, or the user asks to search/crawl listings.
---

# Discover

## Setup

Export `APPLYPILOT_DIR` to the Profile dir before any `applypilot` command (import-time; `.env` cannot relocate it).

Checkout example: `profiles/pipin/`.

## Do

1. Confirm query keywords with the human if missing.
2. Run:

```bash
APPLYPILOT_DIR=<profile> applypilot run discover --query "<keywords>"
```

3. Report counts from the command output (pages / fetched / inserted / duplicates). Do not invent board names.

## Facts

- Live Board is HiringCafe only (Jakarta + Indonesia-eligible remote lanes, ~3-day window). Hardcoded in the engine.
- Keywords come from `--query`, not `searches.yaml`.
- See root `CONTEXT.md` for Edition terms.
