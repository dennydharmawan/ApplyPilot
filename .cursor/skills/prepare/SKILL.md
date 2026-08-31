---
name: prepare
description: Process one exact approved ApplyPilot Preparation selection into validated, Profile-scoped Application Bundles without submitting applications.
---

# Prepare Pipeline Skill

Prepare converts one human-approved selection into application materials. A
fit score of 6 or higher makes a job visible in the queue; only the exact list
recorded by `prepare-select` authorizes generation.

## Approval boundary

1. Export `APPLYPILOT_DIR` before invoking ApplyPilot.
2. Run `applypilot prepare-queue` and present the eligible jobs to Denny.
3. Receive one exact selection list from Denny.
4. Record only that list by repeating `--url`:

   ```bash
   applypilot prepare-select --url '<first exact URL>' --url '<second exact URL>'
   ```

Stop before step 4 when no exact list has been approved. Never translate score
eligibility, “all good jobs,” or silence into selection approval.

## Autonomous run

After `prepare-select` succeeds, do not ask intermediate or final questions.
Run `applypilot prepare-selected`, preserve its order, and process every row
through [resume-tailoring](../resume-tailoring/SKILL.md). Continue past missing
evidence by recording a gap. Continue past a per-job failure by preserving its
error with `applypilot prepare-fail --url '<url>' --reason '<concrete reason>'`
and processing the remaining selected jobs. A failure is terminal for that
selection; it does not prevent later approval of the same job.

The run owns one Application Bundle per selected job. A cover letter is part
of that same workflow only when its trigger is detected. Generated materials
do not authorize an application submission.

## Done

The run is complete when:

- every selected job has either a successful `prepare-write` registration or
  a recorded `prepare-fail` terminal result;
- `applypilot prepare-selected` prints no active rows after all registrations;
- every successful bundle contains editable resume source, an application-ready
  PDF, an evidence report, and a valid manifest;
- no browser form was completed and no application was submitted.

If a job still fails after diagnosis, record the concrete failure, finish the
remaining selected jobs, and report `completed_with_failures` without asking a
question. Report counts, bundle paths, and failures. Do not request approval
to submit.
