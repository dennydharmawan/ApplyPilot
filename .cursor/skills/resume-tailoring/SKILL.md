---
name: resume-tailoring
description: Build one factual, provenance-audited Application Bundle for a job already authorized by the active ApplyPilot Preparation selection.
---

# Resume tailoring

This is the material-generation engine used by the Prepare Pipeline Skill. It
processes one selected job without asking the applicant questions.

## Inputs

Load these sources before writing:

- The active job from `applypilot prepare-selected`.
- The active Profile's `profile.json` and `standing-notes.md`.
- Denny's golden resume at
  `/Users/denny.dharmawan/portfolios/personal-site/public/resume.pdf` and its
  editable source at
  `/Users/denny.dharmawan/portfolios/personal-site/resume.tex`.
- Every relevant artifact in `$APPLYPILOT_DIR/resumes/`. A prior application
  variant is evidence only for facts that trace to that variant.

Profile isolation is a hard boundary. When `$APPLYPILOT_DIR` is Denny, every
candidate fact must come from Denny's golden resume or Denny's resume bank.
Employer pages may supply vocabulary and context, never candidate facts.

## Evidence chain

Extract the job's requirements and themes. For each one, rank candidate
evidence by directness, recency, scale, and relevance. Record this chain in
`report.md`:

| JD requirement or theme | Ranked evidence | Source path and locator | Tailored wording | Status |
|---|---|---|---|---|

Use `supported`, `partial`, or `gap` for status. A gap stays a gap. Preserve
skills, titles, scope, causality, dates, companies, and metrics exactly as the
sources support them.

## Bundle

Create one stable directory under
`$APPLYPILOT_DIR/resumes/applications/<company-role>/`. Never overwrite the
golden resume. Re-running the same job updates its own bundle; a slug collision
with another URL gets a stable URL-hash suffix.

Produce:

- `resume.tex` or another editable source derived from the golden layout.
- `resume.txt` containing only the final rendered resume text used by Apply.
- `resume.pdf`, preserving the golden two-page standard when the sourced
  content fits. Explain a different page count in the manifest.
- `report.md` with the evidence chain, source inventory, unsupported gaps,
  cover-letter trigger, and validation result.
- Cover-letter source and PDF only when the posting requests a letter, the
  application exposes an upload field, or the application is by email.
- `bundle.json` matching the schema below.

Research the employer only as needed to choose accurate vocabulary. Read-only
inspection of the application page is allowed to detect an upload field.
Preparation authorization permits material generation only; it does not permit
form completion or submission.

```json
{
  "schema_version": 1,
  "job_url": "<exact selected URL>",
  "resume": {
    "source": "resume.tex",
    "text": "resume.txt",
    "pdf": "resume.pdf",
    "page_count": 2
  },
  "report": "report.md",
  "cover_letter": {"trigger": "none"},
  "provenance": [
    {
      "requirement": "<job requirement or theme>",
      "status": "supported",
      "sources": ["<Denny source path and locator>"]
    }
  ],
  "validation": {
    "unslop_applied": true,
    "factual_provenance": "passed"
  }
}
```

Allowed cover triggers are `none`, `posting_request`, `upload_field`, and
`email`. A triggered letter also has `source`, `text`, and `pdf` relative
paths; `text` contains only the final rendered letter used by Apply. A resume
outside two pages also has a non-empty `page_count_justification`.
Use one provenance entry per requirement or theme. Allowed statuses are
`supported`, `partial`, and `gap`; non-gap entries require at least one source.

## Completion gate

1. Apply `pstack:unslop` as the final text-changing pass to the resume and any
   cover letter.
2. Run a read-only comparison of every candidate claim against the cited
   golden-resume or resume-bank source. Validation may report defects; it may
   not rewrite text.
3. Set `factual_provenance` to `passed` only when every claim is supported and
   every unsupported requirement remains a documented gap.
4. Confirm the PDF opens, the declared page count is correct, `resume.txt`
   matches the rendered candidate content, and the golden resume is unchanged.
5. Register the result with `applypilot prepare-write --url <url> --bundle
   <absolute-bundle-json-path>`.

The job is complete only when `prepare-write` succeeds.
