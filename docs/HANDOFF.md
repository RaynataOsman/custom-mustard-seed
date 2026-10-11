# Mustard Seed - handoff

For whoever picks this up next (a developer or another Claude session). This has the owner's
requirements, how the code fits together, how to run and ship it, what works, what's broken and what's next.
Last updated 11 Oct 2026.

---

## 1. What this is

A free job-hunting engine that runs on the owner's Windows PC. Owner: WebDevJay, a self-taught
full-stack developer and UX/UI designer in Cape Town (SAST, UTC+2).

The goal is to stack several remote contract roles. The owner should only have to **read and approve**.
The engine finds roles, picks and tailors the right resume, writes the cover letter, finds people to ask
for referrals, fills the forms after he approves, and tracks everything in Notion.

- Code on the PC: `D:\job-engine`, dashboard at http://localhost:8766 (`start.bat`).
- Repo: private, `github.com/187jjay187/mustard-seed` (branch `main`).
- Family members (bookkeeping, e-commerce, admin/VA, sales) will run their own copies with
  [SETUP_GUIDE.md](SETUP_GUIDE.md).

## 2. Owner requirements (treat as hard rules)

**Cost and setup**
- **Zero Claude credits at runtime.** Only free LLM tiers: Gemini, Groq, Cerebras, OpenRouter, Ollama.
- **Runs on his PC** using his real Chrome. Hosted or serverless versions were judged not workable (section 9).
- **He doesn't use the terminal.** Every control goes in the dashboard, a simple shadcn/MUI-style UI.

**Resumes**
- **Never edit the master resumes.** Tailor a copy into `paths.resume_copies`.
- **Resumes must pass ATS and read as human-written.** That means:
  - plain ASCII;
  - no AI boilerplate words (passionate, leverage, results-driven...);
  - no embedded fonts;
  - real URLs, not link labels;
  - a headline matching the resume family.
- **Truthful edits only.** `tailor.guard()` rejects any edit that adds a number, tool, employer or name
  that isn't already in the master or the job title.

**Applying**
- **Approval before submit.** The Review tab offers Approve, Retry (with a note) or Skip. The
  "silence means submit" idea was declined.
- **The engine never:**
  - types passwords or creates accounts;
  - solves CAPTCHAs;
  - sends LinkedIn or other messages.

  It stops and moves the role to **Needs you**. Referral notes are drafts that he sends himself.

**Which roles to keep**
- **International employers only (for him).** A role is dropped only when the employer is a South African
  local company or an SA agency or middleman paying in rands. Overseas companies and global platforms are
  kept (Deel, Remote.com, Toptal, Andela, Turing, Proxify, Pavago, Hire Overseas...). This is a weighted
  classification, not a single trigger.
- **Time zone, digital-nomad style.** The work window is 07:00-23:00 SAST, so UK, EU and US Eastern fit.
  The setting is `geo.strict_timezone`.
- **Pay is quoted in USD by family and level, never SA rates.** Context: a local Mid-Senior interview went
  from R60k to R75k to R85k cost-to-contract against a R120k benchmark, so local rates undersell him.

**Tracking and referrals**
- **Notion tracker:** "Application tracker 2.1". It was reset to empty on 11 Oct 2026 ("day one"); the
  backup is `data/notion_backup_2026-10-11.json`.
- **Referrals on every prepared role:** up to 4 people (recruiters first, then the hiring manager, then
  team members), each with a 280-character connection note and a follow-up message.

**Coverage and sharing**
- **Board coverage is the point.** The tool it replaced (career-ops) only read about 11 of 35+ boards. When
  a board blocks the engine, find another way in: real Chrome, company job feeds, alert emails, the
  bookmarklet, or pasting the job in by hand.
- **Family-ready:** presets, feature switches and a plain-language guide. Personal data stays out of git.

## 3. Architecture

```
boards.py / render.py / ats_discover.py / email_alerts.py   -> raw postings
        |
pipeline.scan -> db.upsert_job -> pipeline._triage_one
        |          (family_of, tier_of, geo, employer, timezone_fit, core_ok, fit_score, AI_BAN)
        v
status new|filtered  --(score >= resume.min_score_to_prepare)-->  pipeline.prepare
        |   tailor.tailor (LLM edits + guard) -> pdf.to_pdf -> cover letter docx/pdf
        |   referrals.find (SearXNG -> real Chrome DDG/Yahoo) -> contacts table
        v
status ready  -> dashboard Review: approve | retry(note) | skip
        v
pipeline.submit_approved -> submit.run (real Chrome, apply-profile, answer bank)
        -> submitted | needs_you | failed  -> pipeline.record_in_notion
```

Manual path: Add a job tab -> `manual.analyse` -> `prepare <id>` -> `manual.record_prepared`
(Notion Stage "Waiting for a referral", Text prefixed "PREPARED - submit manually") -> "I submitted it"
-> `record_in_notion` sets Stage to Applied and fills in the apply date.

### Files

| File | Responsibility | Key functions |
|---|---|---|
| `util.py` | paths, config, keys, HTTP, ASCII clean, feature switches | `load_config`, `save_config_text`, `load_keys/save_keys`, `get`, `job_key`, `feature`, `FEATURE_DEFAULTS` |
| `db.py` | SQLite `data/jobs.db`; adds new columns automatically | `conn`, `upsert_job`, `set_job`, `event`, `rows` |
| `llm.py` | free OpenAI-compatible provider chain; marks dead provider:model pairs | `chat`, `chat_json`, `available`, `health` |
| `boards.py` | API/RSS adapters + `ADAPTERS` dict; LinkedIn guest API; Greenhouse/Lever/Ashby/Workable feeds | `ADAPTERS`, `linkedin_detail` |
| `ats_discover.py` | finds each watched company's ATS feed, cached in `data/ats_cache.json` | `resolve`, `fetch`, `slugs` |
| `render.py` | browser boards. `RealChrome` launches installed chrome.exe with `--remote-debugging-port` and its own profile, then `connect_over_cdp` | `harvest`, `launch`, `open_login_browser` |
| `email_alerts.py` | Gmail IMAP, read-only, `BODY.PEEK`, parses alert emails into jobs | `fetch`, `parse_alert_html`, `test_connection` |
| `triage.py` | rules only, no LLM | `family_of`, `tier_of`, `geo`, `employer`, `timezone_fit`, `core_ok`, `fit_score`, `AI_BAN` |
| `tailor.py` | python-docx edits on a copy of the master | `master_path`, `vocab`, `guard`, `tailor`, `strip_fonts`, `fallback_cover` |
| `pdf.py` | LibreOffice, falling back to Word COM | `to_pdf`, `available` |
| `referrals.py` | people search + scoring + note drafting | `find`, `draft_notes`, `close_browser` |
| `submit.py` | fills forms after approval; answer bank; currency-aware rate | `run`, `_rate_for`, `_visible_captcha` |
| `notion_sync.py` | Notion API 2022-06-28 | `push_application(stage, text_prefix)`, `update_stage(applied_on)`, `rows_missing_connections`, `write_connections` |
| `manual.py` | Add a job tab | `analyse`, `record_prepared` |
| `pipeline.py` | CLI: `scan`, `board <name>`, `prepare [ids]`, `submit`, `backfill`, `all`, `retriage`, `dryfill <ids>`, `discover [names]` | |
| `app.py` + `ui/index.html` | stdlib HTTP server + Tailwind single page | see endpoints below |
| `presets/families.json` | bookkeeping, ecommerce, admin, sales, dev, design (title patterns, core regex, tiers, headline, queries) | |

### Dashboard endpoints (`app.py`)

The server binds to 127.0.0.1 only. It rejects any Host that isn't localhost. POST requests must be
`application/json` and come from a localhost Origin, which blocks other sites from triggering actions.
**Do not add wildcard CORS or Private-Network-Access headers.** An earlier attempt was blocked by a
safety review for exactly that.

- **GET:** `/api/overview`, `/api/health`, `/api/llm`, `/api/jobs?status=&board=&q=`, `/api/contacts`,
  `/api/runs`, `/api/run/<id>/log`, `/api/config`, `/api/keys`, `/api/features`, `/api/presets`,
  `/api/profile`, `/file?path=` (only under resume_copies or `out/`), `/open-folder`
- **POST:**
  - jobs and runs: `/api/job/<id>/action` (approve | retry | skip | reopen | done), `/api/contact/<id>/sent`,
    `/api/approve_all`, `/api/run` ({job, arg}), `/api/run/<id>/stop`;
  - settings: `/api/config`, `/api/keys`, `/api/features`, `/api/profile`;
  - families and resumes: `/api/family/add`, `/api/family/remove`, `/api/master/upload` (base64 .docx);
  - manual jobs: `/api/manual/analyse`, `/api/manual/prepare`.

Tabs: Add a job, Review, Needs you, Applied, Referrals, All found, Boards, Runs, Settings.

The bookmarklet opens `http://localhost:8766/#add&u=<url>&t=<page text>`. It is a top-level navigation and
the hash is never sent to any server.

### Data model (`data/jobs.db`)

- `jobs`:
  - identity and source: `id` = sha1(company+title)[:16], url, apply_url, board;
  - triage results: family, tier, geo_ok, geo_reason, employer_type, employer_reason, tz_reason, score,
    score_reasons, ai_ban;
  - progress: status, status_note, retry_note;
  - outputs: resume_docx, resume_pdf, cover_letter, interview_prep (JSON), gaps (JSON), edits_log (JSON,
    includes cover_letter_pdf);
  - tracking: notion_page_id, applied_at.
- Status values: `new | filtered | preparing | ready | approved | retry | submitting | submitted | needs_you | skipped | failed | expired`.
- `contacts` (job_id, name, headline, url, kind, rank, note, followup, sent), `board_runs`, `events`.

### Config (`config.json`; scrubbed template in `config.example.json`)

**About the person and their output**
- `profile`: personal details, `rate_by_tier`, `rate_by_family` (USD per month), `usd_zar`.
- `paths.resume_copies`: where tailored copies are saved.
- `families`: per family `title_patterns`, `tiers`, `headline`, `core` (regex). Masters are named
  `masters/{family}_{tier}.docx`. Jay has dev J/J-M/HM/M-S/S, design ONE, admin J/J-M/HM.
- `resume`: `max_bullet_edits` 6, `min_score_to_prepare` 45.

**Where jobs come from**
- `search`: queries, `title_exclude`, `browser_mode: real_chrome`, `render_max_details`, `max_age_days` 21.
- `boards` (49 total, 39 enabled; 28 browser-rendered).
- `companies_to_watch` (about 88 companies).

**Filtering**
- `geo`: `international_only`, `strict_timezone`, `work_window_sast`, `international_platforms`,
  `sa_aggregators`. Any board marked `"local": true` makes weak SA signals count.

**Services and switches**
- `llm.providers`: gemini-flash-latest, then gemini-flash-lite-latest, then groq, then cerebras, then
  openrouter (ollama is off).
- `referrals`: `searxng_url` (localhost:8888), `max_per_job` 4, `note_max_chars` 280.
- `notion`: `database_id`, `family_position`, `title_position_overrides`.
- `submit`: `max_per_run`, delays, `years_by_tier`, `answers` (regex -> answer; "A|B" means try options
  in order).
- `features`: scan_boards, email_alerts, ai_tailoring, referrals, notion, auto_fill.

**Keys** (`keys.env`, set from Settings): GEMINI_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY,
OPENROUTER_API_KEY, NOTION_TOKEN, GMAIL_ADDRESS, GMAIL_APP_PASSWORD.

## 4. Running and shipping changes

**On the PC**
- `setup.bat` (first time), `start.bat` (dashboard), `run_all.bat` (scan + prepare).
- `schedule.bat` registers a task that runs every 3 hours. **The owner must run it himself.** Claude's
  safety rules don't allow it to create scheduled or startup tasks.

**From a Claude cloud session** (the sandbox can't reach job sites; it gets proxy 403s):
1. Edit the code in the sandbox copy. Check it compiles (`python -m py_compile`) and run
   `tests/test_employer.py` and `tests/test_email_alerts.py`.
2. Zip only the changed files and send the zip to `D:\job-engine\upd.zip` with
   `device_commit_files`. Then run
   `Expand-Archive -Force upd.zip .; Remove-Item upd.zip` in PowerShell.
3. **Never overwrite the PC's `config.json`.** Ship a small merge script that adds missing keys with
   `setdefault` and backs the file up first (pattern: `data/merge_cfg.py`).
4. If there are rule changes, run `python pipeline.py retriage`.
5. Commit and push from the PC. `gh` there is logged in as 187jjay187; the sandbox GH token is invalid.

**PowerShell gotchas**
- `Start-Process ... -RedirectStandardOutput` often hangs the remote call. Use instead:
  `cmd /c 'start "Title" /min cmd /c "title Title && python x.py > logs\x.txt 2>&1"'`.
  The window title must not be empty: Node (Playwright's driver) asserts on an empty console title.
- Calls time out at about 60 seconds. Run long jobs with
  `Start-Process -WindowStyle Hidden python ... -RedirectStandardOutput logs\x.txt` and read the log
  afterwards. Starting the dashboard this way can itself hang the call, so check it with a separate call.
- `python -c "..."` with quotes breaks. Write a helper `.py` into `D:\job-engine\data\` and run that.
- Writing files with `Set-Content -Encoding utf8` adds a BOM. Strip it from commit messages.

## 5. Status as of 11 Oct 2026

**Working**
- Board coverage: 30+ boards produce roles.
  - Indeed ZA has been unblocked by RealChrome (about 73 links per run).
  - The company-feeds board added 718 roles from 45 company feeds.
- Open pool after filters: 373.
- Employer split across all roles: 1,238 overseas direct, 368 platforms, 30 SA local, 1 SA aggregator,
  351 unknown.
- AI tailoring is verified on the PC. Example (ReWorks Account Manager): 6 truthful edits, a grounded cover
  letter, interview prep and 4 real referral contacts.
- Notion integration is connected (health ok). The tracker is empty and ready.
- Add a job was tested on the PC. A bookkeeping job against Jay's resumes returned "low, 5%" from
  gemini-flash-lite with sensible red flags. The test row was removed.
- Form dry-run: Workable forms fill fully, including screening questions.

**Known issues / limits**
- **Ashby custom dropdowns** aren't filled, so those roles go to Needs you.
- **Reddit RSS** mostly returns 429/403.
- **Notion Stage options** can't be added through the API. Existing options used: Applied, Followed up,
  Interview, Waiting for a referral.
- **Disabled boards:**
  - PNet, CareerJunction and Careers24: SA-local by design.
  - CareerHound, JobBoardAI, micro1: not working or not useful.
  - Canada Job Bank: relocation only.
- **Email alerts:** company and location come from the first short lines after each link, so they can be
  wrong. Plain newsletters can create false jobs; the title filter is the backstop.
- **Time-zone filter:** US Pacific full-day roles are filtered while `strict_timezone` is on.
- **Board selectors** break whenever sites change. The Boards tab shows "0 seen" or "error".

**Owner to-dos**
- Run `schedule.bat`.
- Set up a Gmail app password (needs 2-Step Verification) and subscribe to job alerts on Indeed, LinkedIn,
  Glassdoor and PNet.
- Sign in to Wellfound and LinkedIn once in the login browser.
- Optionally add a Groq key as a backup AI.
- Fix the masters: the "Project Managment" typo in admin HM, the UX/UI headline, and link labels.
- Publish the empty tracker as a Notion template for family.
- Invite family to the repo.
- Optionally point resume_copies at Google Drive for Desktop.

## 5b. 12 Oct fixes

- **Locked scanning profile.** Browser boards failed with "Opening in existing browser session". Cause:
  sign-in windows left running and Chrome child processes surviving `terminate()`.
  - `render.py` now starts **one Chrome per scan**, shared by all browser boards (`session()` / `shutdown()`).
  - It kills the whole process tree on close and clears leftovers on start.
  - It skips browser boards while a sign-in window is open (`data/login_open.json`).
- **The blank window.** The scan Chrome's first tab is `ui/scanning.html` ("Mustard Seed is reading job boards")
  instead of about:blank.
- **Sign-ins.** The Boards tab has a Sign-ins panel built from `config.signins`.
  - Each site has a button for the scanning profile (`data/real-chrome`) and/or the applying profile
    (`data/apply-profile`), plus "open all".
  - Last-opened times are kept in `data/signins.json`, and the window closes itself after 20 minutes.
- **Review / All found filters.** Quick categories (`LENSES` in app.py): best, open_sa, fresh, contract, overseas,
  long_shot. Dropdowns for resume, level, employer and source; sort and search. `/api/jobs/facets` gives the counts.
  Filters are remembered per view.
- **Titles from URLs.** When link text isn't a title ("7 days ago", "Apply"), `render._slug_title` reads the title
  from the URL slug. This fixes remote.co, Built In and similar boards.
- **Board fixes.** New link patterns for relocate.me and landing.jobs. Mercor and Ruby on Remote are off: Mercor is
  sign-up only and Ruby isn't his stack.
- **Cover letters.**
  - They follow the structure and voice of `masters/cover_letter_example.txt` (Settings > Cover letter example),
    run 250-350 words, start "Dear <Company> team," and sign off "Kind regards".
  - `tailor.guard_cover` drops sentences stating figures not on the resume.
  - The .docx is laid out as a letter (name, contact line, date, "Re:").
- **Bug fixed.** Switching off AI tailoring no longer crashes `tailor()`: it raises `llm.NoLLM`, which falls back to
  keyword mode.

## 6. Backlog (suggested order)

1. Fill Ashby (and other custom React) dropdowns in `submit.py`.
2. A stage-sync job from the Gmail alerts inbox. Detect interview invites and rejections and update the
   Notion Stage. The owner asked for tracking of email feedback; this isn't built yet.
3. Follow-up reminders: after 7 days in Applied with no reply, suggest the follow-up note.
4. Family profile forms for the answer bank, so non-technical users can edit screening answers without
   touching JSON.
5. A per-person Notion template creator using the Notion API (create the database with the right properties).
6. Optional hybrid hosting (section 9) if family usage grows.

## 7. Decisions and rejected approaches

- **Playwright's own Chromium was replaced by RealChrome** over a debugging connection. Cloudflare flagged
  the automated profile. There are separate profiles for scan (`data/real-chrome`), search and apply.
- **Plain-HTTP search engines don't work for referrals.** DuckDuckGo, Bing and Brave over plain HTTP were
  blocked or returned junk, so search uses SearXNG or real Chrome.
- **Gemini 2.5 Flash was retired for new keys.** Use the `-latest` aliases.
- **The manual-tab agent design with wildcard CORS was rejected for safety.** The current design is a
  bookmarklet with hash navigation plus same-origin checks.
- **The first SA filter was a single trigger.** It was replaced by the weighted employer classification
  after the owner pointed out overseas employers paying him directly are fine.
- **The owner wanted resumes free of any AI watermark.** The answer is clean ASCII text, no AI-cliche
  wording, and stripped document metadata and fonts. The free LLM writes the content, not Claude.

## 8. Working with the owner

- He wants outcomes and live, working things, not plans. Ship to the PC and verify there.
- Keep everything in the dashboard. If something needs a terminal, wrap it in a .bat or a button.
- He runs a web agency too, so time is short. Batch questions and default to the sensible choice.
- When doing a big multi-part request he often uses the task-orchestrator skill (lead plus tiered
  subagents with a running log).

## 9. Hosting online (assessed)

A full move to Vercel or Netlify isn't viable. Browser-rendered boards, real Chrome, form filling, people
search, long runs, local SQLite and Word PDF export don't fit serverless.

A workable hybrid:
- a hosted dashboard on Supabase for auth and data;
- GitHub Actions on a schedule for the API/RSS boards and the company feeds;
- free-LLM tailoring in Actions;
- the browser-dependent parts staying on each person's PC as a small agent that syncs to Supabase.

Estimated a few days of work for about 60% of the features. The feature switches already let each person
run only the parts they need.
