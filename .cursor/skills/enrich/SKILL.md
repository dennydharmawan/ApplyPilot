---
name: enrich
description: >-
  Run ApplyPilot Enrich: Playwright JSON-LD/CSS, then Cursor leftover extraction
  via enrich-write. Use when enriching job details or filling full_description.
---

# Enrich

## Setup

Export `APPLYPILOT_DIR` to the Profile dir before any `applypilot` command.

## Do

1. Run the engine:

```bash
APPLYPILOT_DIR=<profile> applypilot run enrich [-w N]
```

2. List Cursor leftovers:

```bash
APPLYPILOT_DIR=<profile> applypilot enrich-leftovers
```

3. For each leftover, open the job URL (browser), extract full JD and apply URL, then:

```bash
APPLYPILOT_DIR=<profile> applypilot enrich-write \
  --url "<url>" \
  --full-description "<jd text>" \
  [--application-url "<apply url>"]
```

4. Summarize ok / leftovers fixed / still missing description. No API LLM.

## Facts

- Cascade is JSON-LD then CSS only. Failures may be `needs_cursor_extraction`.
- Retryable HTTP/timeouts leave `detail_scraped_at` null and re-queue for Playwright; they are not leftovers.
- Leftovers: `full_description IS NULL AND detail_scraped_at IS NOT NULL`.
- Score needs `full_description`. Apply URL alone is not enough.
