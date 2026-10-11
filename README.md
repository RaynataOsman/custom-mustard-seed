# Mustard Seed

> "If you have faith as small as a mustard seed..." - Matthew 17:20

A free job-hunting helper that runs on your own Windows PC. Every few hours it:

1. **Finds** remote roles on 40+ job boards, company career pages and your job-alert emails.
2. **Filters** out roles you can't take (wrong country, wrong hours, local agencies if you don't want them).
3. **Prepares** each good role: picks the right resume, tailors a copy to the job, writes a cover letter,
   gives you interview prep and finds the recruiter / hiring manager to message on LinkedIn.
4. **Waits for you.** You approve, retry or skip each role in a simple dashboard. Only approved roles are applied to.
5. **Tracks** everything in a Notion tracker (optional).

You can also paste any job you find yourself (WhatsApp, LinkedIn post, recruiter email) into the
**Add a job** tab and get your odds, a tailored resume and cover letter to download.

It costs nothing to run: it uses free AI keys (Google Gemini, Groq) and your own computer.
Every part can be switched on or off in **Settings > Features**.

## What it will never do

- Type your passwords, create accounts or solve "I'm not a robot" checks - it leaves those for you.
- Send LinkedIn messages for you - it writes the note, you press send.
- Apply to anything you didn't approve.
- Change your original resumes - it only edits copies.
- Invent experience - edits that add new numbers, tools or employers are blocked.

## Get started

Handing over to a developer or another Claude session: **[docs/HANDOFF.md](docs/HANDOFF.md)**.

Non-technical step-by-step guide: **[docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md)** (about an hour, once).

Short version for the technical: Windows, Python 3.11+, `setup.bat`, `start.bat`, open http://localhost:8766,
fill in Settings. `schedule.bat` registers the 3-hourly run. Personal data lives only in `config.json`,
`keys.env`, `masters/`, `data/` and `out/`, all git-ignored.

## Folder map

| File | What it does |
|---|---|
| `app.py`, `ui/index.html` | The dashboard (runs only on your PC, port 8766) |
| `pipeline.py` | scan / prepare / submit / backfill / retriage |
| `boards.py`, `render.py`, `ats_discover.py`, `email_alerts.py` | Reading job boards, company pages and alert emails |
| `triage.py` | Which resume family + level, location, employer and time-zone checks, fit score |
| `tailor.py`, `pdf.py` | Tailored resume copies and cover letters |
| `manual.py` | The "Add a job" tab |
| `referrals.py` | Finding recruiters / hiring managers and drafting notes |
| `submit.py` | Filling application forms after you approve |
| `notion_sync.py` | The Notion tracker |
| `presets/families.json` | Ready-made job families: admin/VA, bookkeeping, e-commerce, sales, web dev, UX/UI |
| `config.example.json` | Starting settings (copied to `config.json` by setup) |
