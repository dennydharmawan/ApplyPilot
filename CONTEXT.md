# ApplyPilot Indonesia Edition

Job-search agent context for this fork: one Edition, many Profiles, one live Board, two Lanes.

## Language

**Edition**:
This fork of ApplyPilot, retargeted for Indonesia job search. Shared code, boards, and geography rules. Not a second product name and not upstream Pickle-Pixel ApplyPilot.
_Avoid_: region pack, locale, Indonesia mode

**Profile**:
One person's isolated ApplyPilot data and preferences: resume, searches, lane toggles, compensation, browser session, jobs database. The Profile is `APPLYPILOT_DIR`. For this Edition that is `~/.applypilot/profiles/<slug>/`. Two Profiles to start: `denny` (Denny) and `pipin` (Sekar Yupina). A Profile is not a Chrome Person (Default vs Profile 2).
_Avoid_: account, user, version, persona, sekar, yupina (those are the human / Chrome Person, not the Profile slug), `--profile`

**Init**:
A repo skill/command an agent runs with one human to reach shared understanding and write that person's Profile. It is the onboarding path. Not `applypilot init` unless a later decision says otherwise.
_Avoid_: wizard, setup, onboarding CLI

**Lane**:
A search geography a Profile can turn on or off independently. The Edition has exactly two: Jakarta and Indonesia-eligible remote. Discover currently searches both in one HiringCafe window: Jakarta place plus Asia and worldwide unrestricted remote.
_Avoid_: mode, track, market, APAC remote

**Jakarta lane**:
Jobs tied to DKI Jakarta: Onsite, Hybrid, or Remote at that place. Not Field. Not Bogor, Depok, Tangerang, or Bekasi.
_Avoid_: Jabodetabek, Greater Jakarta

**Indonesia-eligible remote**:
A remote posting that will hire someone working from Indonesia or SEA. Discover includes this by adding HiringCafe unrestricted remote from Asia and Worldwide (`anywhere_in_continent`, `anywhere_in_world`). Not Indonesia-wide unrestricted remote (`anywhere_in_country`). Do not treat the keyword "APAC" as a search term or a Lane name.
_Avoid_: APAC remote, APAC lane

**Board**:
A discovery source. This Edition's live Board is HiringCafe. LinkedIn, Glints Indonesia, Indeed Indonesia, and JobStreet are later Boards, not Discover now.
_Avoid_: site, portal, job board, JobSpy, Workday, smartextract

**Pipeline Skill**:
A repo skill under `.cursor/skills/` that is the human/agent entrypoint for a pipeline stage. Discover and Enrich skills drive mechanical engines; the Score skill is Cursor judgment. Not `applypilot run <stage>` as the primary UX, and not an API LLM provider (Codex, Gemini, OpenAI) for those stages.
_Avoid_: pipeline command, stage wrapper, codex score, gemini score

**Discover**:
Pipeline stage 1. HiringCafe only in this Edition. Entrypoint is the Discover Pipeline Skill; the engine still crawls and writes the Profile DB. Keywords come from the skill/CLI query for that run. Does not read `searches.yaml`.
_Avoid_: discover mode, crawl, JobSpy (as the stage)

**Enrich**:
Pipeline stage 2. Fills `full_description` and `application_url` for discovered jobs. Entrypoint is the Enrich Pipeline Skill. Easy pages use the Playwright cascade (JSON-LD, CSS); hard leftovers are extracted in Cursor, not by an API LLM.
_Avoid_: detail scrape (as the stage name), LLM enrich

**Score**:
Pipeline stage 3. A fit rating 1–10 plus reasoning written onto a job in the Profile DB. Done by Cursor (parent chat and/or parallel subagents), persisted via a write helper — not Codex, Gemini, or any API LLM scorer. Inputs are resume, full JD, Profile preferences, and that Profile's standing notes. Done means every pending enriched job is scored and the HTML dashboard is opened.
_Avoid_: run score, codex exec scoring, automated LLM score

**Standing notes**:
The Profile-scoped counterpart to personal `/remember`: durable preference and policy notes for one person, not repo `AGENTS.md` and not global user-context rules. Freeform prose lives in `standing-notes.md` under that Profile's `APPLYPILOT_DIR`. Enumerable rules that engines or skills enforce live in `profile.json`. An update skill works like `/remember` (interview → append/edit the right target); stable rules may be promoted from markdown into JSON. Not chat memory.
_Avoid_: preferences (when meaning freeform policy), scratchpad, AGENTS.md (for person policy), single junk-drawer profile.json notes blob

**HITL login**:
When a Board needs a signed-in browser, the human uses Chrome (via Chrome AXI) in that Profile's browser session. The agent does not invent credentials.
_Avoid_: auto-login, stored password login
