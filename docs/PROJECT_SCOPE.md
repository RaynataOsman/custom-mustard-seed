# Mustard Seed (job-engine) - Project Scope & Audit

Owner: WebDevJay (Cape Town, SAST). Code: `D:\job-engine` on the MSI PC. Repo: `github.com/187jjay187/mustard-seed`.
Online companion: https://mustard-seed-online.vercel.app (Supabase sync). Audit date: 16 Oct 2026.

This file is the single description of what the engine is meant to do, what it does today, what the
16 Oct deep test found, what was fixed, and what is still open. `docs/HANDOFF.md` remains the developer
guide (how the code fits together and how to ship changes).

---

## 1. Purpose

Find remote (and relocation-track) roles across 50+ job boards, pick the right resume family and level,
tailor a truthful ATS-clean copy, write a cover letter and interview prep, find referral contacts, fill
the application form **only after the owner approves**, and track everything in Notion. The owner reads
and approves; he never uses a terminal. Zero Claude credits at runtime (free LLM tiers only).

## 2. Hard requirements (unchanged)

| Area | Rule |
|---|---|
| Cost | Free LLM tiers only (Gemini, Groq, Cerebras, OpenRouter, Ollama). No Claude at runtime. |
| Control | Everything from the dashboard (localhost:8766) or the online dashboard. No terminal. |
| Resumes | Never edit masters. Plain ASCII, no AI cliches, real URLs, family headline. `tailor.guard()` blocks invented numbers/tools/employers. |
| Applying | Approval before submit. Never types passwords, creates accounts, solves CAPTCHAs or sends messages. Stops at **Needs you**. |
| Filtering | International employers only for the owner (weighted SA-local classification). Work window 07:00-23:00 SAST. |
| Pay | USD by family and tier, never SA rates. |
| Tracking | Notion "Application tracker 2.1". Referrals: up to 4 people per role, drafted notes only. |
| Sharing | Family-ready presets and feature switches; personal data never in git. |

## 3. Pipeline

```
boards (API/RSS adapters, real-Chrome render, company ATS feeds, Gmail alerts)
  -> scan -> triage (family, tier, geo, employer type, time zone, core skills, score, AI-ban, listing-page filter)
  -> expire stale (NEW)
  -> prepare (tailor copy + PDF + cover letter + interview prep + gaps + referrals)
  -> Review: approve / retry with note / skip
  -> submit approved (real Chrome, answer bank) -> submitted | needs_you | failed -> Notion
  -> reply watch (NEW): Gmail replies -> Interview / Rejected / Offered + Response date in Notion
  -> follow-ups due (NEW): 7+ days, no reply -> draft note on the Applied tab
```

Scheduled task (`schedule.bat`, every 3 h) runs `pipeline.py all` = scan + expire + prepare + replies. It never submits.

## 4. Feature matrix

| Feature | Status | Notes |
|---|---|---|
| Board scanning (API/RSS) | Built | Himalayas, Remotive, Remote OK, WWR, Working Nomads, Jobicy, Arbeitnow, LinkedIn guest API, Reddit |
| Board scanning (real Chrome) | Built | 28 render boards, one shared Chrome per scan |
| Company ATS feeds | Built | Greenhouse/Lever/Ashby/Workable via `ats_discover.py`, ~90 companies |
| Gmail alert emails as a board | Built | Read-only IMAP; now 30 s timeout + 1 retry (16 Oct) |
| nocodejobs / landing.jobs API adapters | **Built 16 Oct** | Replaced scraping that read 0 links |
| Per-board health words | **Built 16 Oct** | ok / quiet / needs sign-in / blocked / error / broken: page empty / broken: no job links / empty feed |
| Listing-page / alert-header filter | **Built 16 Oct** | `triage.is_listing_title` |
| Triage rules (family, tier, geo, employer, time zone) | Built | Weighted employer classes; `dev_first` titles |
| Safeguards v2 (one application per company and per recruiter, best role wins, one family per platform, version labels, referral dedup, Allow anyway) | **Built 17 Oct** | See section 9. Default is now skip; online app mirrors it |
| AI tailoring with truth guard | Built | Free LLM chain now self-heals retired models (16 Oct) |
| Cover letter + interview prep + gaps | Built | Example-driven voice, 250-350 words |
| Referral finder | Built | SearXNG -> real Chrome DDG/Yahoo. SearXNG down is now detected once per 10 min |
| Review UI (lenses, filters, approve/retry/skip) | Built | |
| Form filling after approval | Partial | Workable full; Greenhouse/Lever good; **Ashby custom dropdowns not filled** |
| Notion push + Tier used + Connections | Built | |
| Online dashboard + cloud sync | Built | Same filters as the PC since 16 Oct; all Review roles load; phone app icon |
| Auto-expire stale roles | **Built 16 Oct** | `lifecycle.expire_stale`, 21 days |
| Gmail reply watch -> Notion stage | **Built 16 Oct** | `lifecycle.watch_replies`, rules only, read-only |
| Follow-up reminders | **Built 16 Oct** | Applied tab card, "I followed up" -> Notion "Followed up" |
| Run allowlist on `/api/run` | **Built 16 Oct** | Unknown run names are refused |
| Answer-bank form for family members | Missing | Screening answers still live in `config.json` |
| Notion template creator per family member | Missing | Manual duplicate of the empty tracker for now |
| Hybrid hosting for family (Actions + Supabase) | Assessed only | See HANDOFF section 9 |

## 5. Board status after the 16 Oct test

| Board | Before (fetched per run) | Verdict now |
|---|---|---|
| Himalayas, Remotive, Remote OK, WWR, Working Nomads, Jobicy, Arbeitnow | healthy | ok |
| LinkedIn (guest API) | healthy but ~18 min per run | ok; details fetched only for new roles |
| Companies hiring Africans (ATS feeds) | ~8,900 roles/run | ok |
| EU Remote Jobs, Remote Rocketship, Jobgether, HireZar, NoDesk, Built In, Bayt, NaukriGulf, Tanqeeb, Jaabz, remote.co, Remote4Africa, Workable SA, Make it in Germany | healthy | ok (remote.co now retries HTTP/2 drops) |
| Remote Career Africa, remotiko, GulfTalent, Vacancy Mail, aitraining.jobs, Virtual Staff SA, Dynamite Jobs, Ruby on Remote, Flexa, Dubai Careers | low volume | quiet / ok |
| **Remote Africa** | 0 every run | Never broken: 28 job links read, only already-known roles. Now "quiet" |
| **nocodejobs** | 0 every run | **Fixed**: jobs.json adapter, 6 matches, 5 new |
| **landing.jobs** | 0 every run | **Fixed**: API adapter, 13 matches, 13 new (relocation track) |
| **relocate.me** | ~0 | Works: 20 job links read; roles rarely fit. Quiet |
| **Wellfound** | 0 every run | Sign-up wall. Now "needs sign-in" - owner signs in once |
| **Welcome to the Jungle** | 0 every run | Search hidden behind sign-up. **Off**; use WTTJ alert emails |
| **Remoters** | 0 every run | Site lists no jobs even to a person. **Off** |
| **GovAI (UK)** | 0 every run | Only research fellowships, never fits. **Off** |
| Indeed ZA | blocked 3 of 6 runs | Known limit (Cloudflare). Use Indeed alert emails |
| Zimbajob | blocked 1 of 6 | Known limit |
| Email job alerts (Gmail) | 1 timeout | Retry added; "quiet" when no new alert emails |
| Somewhere.com jobs | never run | Iframe reading added; first run pending |
| Off by design | PNet, CareerJunction, Careers24 (SA-local), CareerHound, JobBoardAI, micro1, Mercor, Remote 100K, OnlineJobs.ph, RAK Gov | - |

## 6. Audit findings and fixes (16 Oct 2026)

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | 75 `database is locked` crashes in cloud sync; a scan held the write lock for a whole board (LinkedIn: 18 min) | High | `db.conn()` autocommit, 60 s busy timeout; schema DDL once per process per DB |
| 2 | LLM chain had 1 working model: Groq, Cerebras, OpenRouter models retired (404), Gemini Flash over quota | High | Models updated; `llm.py` self-heals on 404 via the provider's /models list (cache `data/llm_models.json`). 3 providers verified |
| 3 | 3 of 4 failed preps were malformed AI JSON; 1 was a list | Medium | JSON repair, list->dict, one cooler retry |
| 4 | Boards reported "ok" with 0 results whether broken or quiet | High | Link and job-link counts per run; health word per run; shown on Boards tab |
| 5 | 29 category pages / alert headers stored as jobs; 12 prepared | Medium | Listing-title filter; the 29 rows set to skipped (event `auto_skip`, reversible) |
| 6 | Company = board hostname; safeguards grouped unrelated roles | Medium | Better company extraction; safeguards ignore board hostnames |
| 7 | Email alerts stored half-cut HTML as company; Gmail timeouts | Low | Context-line filter; IMAP timeout + retry |
| 8 | `/api/health` hung >25 s | Medium | Parallel single-try probes: 3.1 s |
| 9 | Referral lookups paid ~18 s each while SearXNG was down | Medium | Detected once, skipped 10 min |
| 10 | LinkedIn fetched details for every match incl. known roles | Medium | Details only for unseen roles |
| 11 | Prepared roles never expire | Medium | `lifecycle.expire_stale` (48 roles on a DB copy) |
| 12 | No reply tracking / follow-ups | Medium | `lifecycle.watch_replies`, `lifecycle.followups`, Applied tab card |
| 13 | `/api/run` accepted any word | Low | Allowlist on the PC and online |
| 14 | remote.co: 50 `ERR_HTTP2_PROTOCOL_ERROR` loads | Low | One retry in `render._goto` |

Tests: `tests/test_audit_fixes.py` (new). All suites pass: test_app, test_email_alerts, test_employer,
test_safeguards, test_audit_fixes. test_dashboard to re-run after the app.py restore.

## 7. Open items

**16 Oct follow-up (done):**
- `app.py` restored from the backup (owner approved), the audit's dashboard fixes re-applied, dashboard restarted;
  all test suites pass, including test_dashboard.
- Live DB: the scheduled 03:28 run had already cleared 48 roles older than 3 weeks with the new rule.
- LLM self-heal tightened: a busy Gemini (503 "high demand") had been switched to Gemma by mistake. Only real
  "model not found" errors switch models now; busy errors wait 8 s and retry.
- Referral run for Review roles without contacts (`pipeline.py referrals`, also a button online and on the PC):
  best scores first, resumable. Company names like "OneDayOnly.co.za" are searched without the web address;
  job-board names (remote.co, jobbank.gc.ca) are never searched as employers.
- Online dashboard rebuilt to match the PC: search, quick categories, resume / level / employer / board filters,
  sort, paging, Boards tab with health words, follow-ups on Applied, new run buttons, Run board.
  All 846 Review roles load: the list is light (`ms_list_jobs_lite`) and a role's text loads when opened
  (`ms_get_job`), see `cloud/2026_10_16_lite_list.sql`. Phone app icons + manifest (Add to Home Screen).
- Deploys: Vercel does NOT deploy on git push for this project. Run `data\deploy_web.bat`, which deploys from a
  clean copy holding only `web\` (the engine folder holds the database, keys and browser profiles).

**Still to build:**
1. Ashby / custom React dropdowns in `submit.py` (test with `dryfill`, never submit).
2. Answer-bank form in Settings for family members.
3. Notion template creator for new family members.
4. Banner when a board is "broken" 3 runs in a row.
5. Optional hybrid hosting (HANDOFF section 9).

**Owner actions:**
- Start Docker Desktop so SearXNG runs (395 prepared roles have no referral contacts while it is down).
- Sign in to Wellfound once (Boards > Sign-ins, scanning profile).
- Subscribe to job alerts (Indeed, LinkedIn, Glassdoor, WTTJ) into the Gmail inbox the engine reads.
- Review queue: 772 roles prepared and waiting. Expiry clears roles older than 3 weeks.
- Fix the masters: UX/UI headline, link labels, "Project Managment" typo.

## 8. Keeping it healthy

No scraper stays fixed: sites change layouts and add bot walls. The engine now reports that instead of
hiding it. Weekly: open Boards, look for red "Layout changed" or amber "Sign in once" badges, and run
`data/audit_boards2.py`, `data/audit_pipeline.py`, the test suites and the LLM health ping.

---

## 9. Safeguards v2 - one application per company and recruiter (17 Oct 2026)

Why: the over-employment method must never put two applications, or two resume versions, in front of the same
company or recruiter, and for multi-role adverts only the best-fitting role should go out.

| Rule | Behaviour |
|---|---|
| Company lock (`company_mode`, default **skip**) | Another role at the same company already approved / sent in the last 90 days: this role is held ("Already applied 3 Oct with HM_ Dev - one application per company"). Several roles only waiting in Review: the best fit wins, the rest are skipped ("Skipped - weaker match: ..."). Ties go to the newer role. `warn` still available in Settings |
| Platform rule | Unchanged: one resume family per agency / talent platform |
| Recruiter check (`recruiter_check`, default on) | Roles at different companies that name the same contact email, the same company email domain (free mail excluded), the same hiring account (Greenhouse / Lever / Ashby / Workable / SmartRecruiters / Recruitee slug) or the same LinkedIn recruiter profile count as one recipient. Keys are stored in `jobs.contact_keys` and refreshed when a description changes |
| Allow anyway | Button on any held or skipped role (PC and online). Sets `jobs.allow_override`; the safeguards never hold or skip that role again. A skipped role returns to Review (or to Found if it was never prepared) |
| Best role per company run | Runs > "Best role per company" (`pipeline.py sweep`, `sweep dry` only counts). Also runs automatically at the start of every prepare |
| Online app | Same banners, Allow anyway, a "Skipped by safeguards" list in Review and the run button. Command kind `job_action` with action `allow` |

Never grouped: hidden employers ("Confidential", "Stealth"...) and job-board hostnames.
Limits: matching is by normalised name, so "Acme Labs" and "Acme Corp" stay separate unless they share a recruiter key; roles whose ad names no email, hiring account or LinkedIn profile cannot be matched to a recruiter.
First live run (17 Oct): 350 of 993 roles in Review skipped (323 company, 26 recruiter, 1 platform); 643 remain. Backup before the change: `data\backup_2026-10-17\` (code, config, jobs.db).
Tests: `tests/test_safeguards_v2.py`.

## 10. Edit resume / cover letter by hand (18 Oct 2026)
- **Where:** an *Edit resume* and *Edit cover letter* button on every role in Review / Needs you, on the PC dashboard and the phone app. The role's resume text is now visible too (PC: "Resume (text)"; phone: "Show resume text", fetched from the PC).
- **What a save does:** rewrites the database text, the cover `.txt`, `.docx`, `.pdf` and the resume `.docx` + `.pdf` in Resume Copies. The form filler (`submit.py`) uses those files, so it sends your version.
- **Safety:** only the tailored copy is written (`editor._safe_copy` refuses anything outside Resume Copies, so masters are untouched). The truth guard (`tailor.guard` / `guard_cover`) checks your text; if it finds a new number, tool, name or unsupported figure it lists them and the button becomes *Save anyway*.
- **Resume editor rules:** one line per paragraph, same line count (clear a line to remove it). The contact line and paragraphs with line breaks, tabs or links (skills lists) are not shown and stay as they were.
- **Kept until Retry:** `jobs.resume_edited_at` / `cover_edited_at`. Retry on an edited role warns first (PC confirm / phone confirm), then discards the edits; a fresh prepare clears the flags.
- **Phone:** commands `edit_text` and `resume_text` go through the same queue as Approve (PC must be on). Resume text is not stored in Supabase; it is fetched on demand.
- Code: `editor.py`, `app.py` (`/api/job/<id>/texts`, `/api/job/<id>/edit`), `cloud_sync.py` (`edit_text`, `resume_text`, `refresh_job`), `web/api/command.js`. Test: `tests/test_editor.py` (22 checks, restores everything).

