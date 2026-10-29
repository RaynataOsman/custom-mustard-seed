# My custom Mustard Seed: setup to-do and what is switched off

This copy is based on Jay's latest code (187jjay187/mustard-seed, branch Own_JP, 27 Oct 2026). It is separate from
your working job engine (`mustard-seed-Own_JP`): its own folder, its own database, its own settings, and it is **not**
scheduled. Nothing here touches the other one.

- Folder: `C:\Users\rayna\Downloads\mustard-seed-custom`
- Your repo: github.com/RaynataOsman/mustard-seed-custom (private). Jay's repo is the remote called `upstream`.
- Open the dashboard: double-click `start.bat`. It uses **port 8777** so it can run beside the other engine (8766).
- Pull Jay's future changes: `git fetch upstream` then `git merge upstream/Own_JP` (resolve any clashes with your edits).
- Icon: olive-green capital R (`ui/seed.svg`, `web/public/*`).

## To-do (in this order)

### 1. Make it yours (10 min)
- [ ] Open the dashboard (`start.bat`) > **Settings > Profile**: name, email, phone, LinkedIn, portfolio, rates per level.
- [ ] Drop your resume masters into `masters\` (the dashboard Settings page lists what it expects). Without a master nothing can be tailored.
- [ ] **Settings > Career paths**: `config.json` only has one path (admin). Add the others from the presets (dev, design, ai, cse, ecommerce, admin, sales, bookkeeping) with *Add family*, or copy the tech and marketing families from the working engine's `config.json`.
- [ ] Edit `search.queries` (only 4 are set: virtual assistant, executive assistant, customer support, data entry).
- [ ] Review `search.title_exclude`: it blocks many dev and ML titles (python, php, laravel, machine learning...). Loosen it if you want tech roles.
- [ ] Review `submit.answers` (standing answers for application forms) and `submit.years_by_tier`. Keep every answer true.

### 2. Free keys (Settings > Keys) so the AI parts work (15 min)
- [ ] **GEMINI_API_KEY** (aistudio.google.com). Required for tailoring and cover letters.
- [ ] Optional backups: GROQ_API_KEY, CEREBRAS_API_KEY, OPENROUTER_API_KEY. Press *Test free AI providers*.
- [ ] Rotate the keys that were pasted earlier in chat before reusing them here.

### 3. Optional extras
- [ ] **Email job alerts**: GMAIL_ADDRESS plus a Gmail App Password (needs 2-Step Verification). Subscribe to alerts on Indeed, LinkedIn, Glassdoor.
- [ ] **Notion tracker**: NOTION_TOKEN and tracker link, or switch `features.notion` off.
- [ ] **Referral search**: runs SearXNG on localhost:8888 (`searxng.bat`). Without it, referral finding falls back to browser search.
- [ ] **Phone dashboard**: your own Supabase project (`cloud\supabase.sql`, then `cloud\2026_10_16_lite_list.sql`) and a Vercel deploy of `web\`. Not connected yet, so `cloud` is empty in `config.json`.
- [ ] **Sign in once** (Boards tab > *Open login browser*): Google, LinkedIn, Indeed, Wellfound.
- [ ] **PDF resumes**: needs LibreOffice (already installed on this PC).
- [ ] `paths.resume_copies` can point at Google Drive for Desktop.
- [ ] **Schedule**: run `schedule.bat` only when you want this copy to scan every 3 hours. Do not turn it on while the other engine's "Job Engine" task is running, or the two will fight over Chrome.

## What is on, off, or inert right now

| Area | State | How to change |
|---|---|---|
| `features.scan_boards` | On | `config.json > features` |
| `features.ai_tailoring` | On, but **does nothing until a Gemini key is added** | Keys tab |
| `features.email_alerts` | On, but **inert** (no Gmail address or app password) | Keys tab |
| `features.notion` | On, but **inert** (no token or database) | Keys tab, or switch off |
| `features.referrals` | On, but SearXNG is **not running** | `searxng.bat` |
| `features.auto_fill` | On (fills forms only after you press *Submit approved*) | `features` |
| Auto-submit without approval | **Off** by design | not available |
| `submit.auto_tick_consent` | **Off** (never ticks consent boxes for you) | `submit` |
| Scheduled scans | **Off** (`schedule.bat` not run) | `schedule.bat` |
| Phone dashboard / cloud sync | **Off** (no Supabase or Vercel) | see to-do 3 |
| Ollama (local AI) | **Off** | `llm.providers` > `enabled` |
| `geo.international_only` | **Off** (SA companies allowed) | `geo` |
| `geo.strict_timezone` | **On** (US Pacific full-day roles filtered; work window 07:00-23:00 SAST) | `geo` |
| `resume.min_score_to_prepare` | 45 (roles below this are not tailored) | `resume` |
| `schedule.prepare_max_per_run` | 25 roles per run | `schedule` |
| Career paths | **Only "admin"** | to-do 1 |
| Masters, profile, cover letter example | **Empty** | to-do 1 |

### Boards switched off (13) in the shipped config
| Board | Why |
|---|---|
| PNet, CareerJunction, Careers24 | South Africa-local jobs, off by design |
| CareerHound, JobBoardAI, micro1 experts | Not working or not useful (Jay's notes) |
| Canada Job Bank | Relocation only |
| Remote 100K, Mercor, NaukriGulf, OnlineJobs.ph, Ruby on Remote, WORK180 | Off in Jay's file with no reason recorded. Turn on and test one by one (Boards tab > run) |

To turn a board on: set `"enabled": true` on it in `config.json` (or use the Boards tab).

### Known limits (from Jay's handoff)
- Ashby custom dropdowns are not filled, so those roles land in **Needs you**.
- Reddit mostly returns 429/403. Wellfound and LinkedIn Easy Apply need you signed in.
- Site layouts change: if the Boards tab shows "0 seen" or "error", that board's selector needs fixing.
- The engine never solves CAPTCHAs. It stops and leaves the tab for you.

## Where to customise
| I want to change | Edit |
|---|---|
| Which jobs are searched | `config.json > search.queries` |
| Which job titles are skipped | `search.title_exclude` |
| Job boards | `config.json > boards` |
| Career paths, titles, headline | `config.json > families` (and `presets/families.json`) |
| Role-type categories in the dropdown | `categories.py` |
| Cover letter structure | `coverletter.py`, `docs/COVER_LETTER_STANDARD.md` |
| Scoring and levels | `triage.py` |
| Resume rewriting rules | `tailor.py` |
| Dashboard look | `ui/index.html` (PC), `web/public/index.html` (phone) |
| Brand colour and icons | `ui/seed.svg`, `web/public/` (olive `#6b7a2a`) |

Guides in `docs/`: SETUP_GUIDE.md (step by step), HANDOFF.md (how it works), PROJECT_SCOPE.md.
