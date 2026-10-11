# Job Engine - how it works (no Claude credits used)

Everything lives in `D:\job-engine`. Double-click the `.bat` files. The dashboard runs at http://localhost:8766 (this PC only).

## The loop
1. **Find** - every 3 hours the scheduled task reads all enabled boards (`Boards` tab shows each one's result, so a board that silently returns nothing shows up as "0 seen" or "error" instead of disappearing).
2. **Filter** - keeps only titles in your three families, drops US/UK/EU/LATAM-only roles, drops anything older than 21 days. Roles that just say "Remote" are checked against the employer's own apply page before any work is done.
3. **Prepare** - for the best new roles: picks the family + tier from the title and years asked, tailors a copy of that master (keywords and sentence order only - any edit that adds a tool, number or name your master doesn't have is blocked and shown to you), makes the PDF, writes the cover letter and interview prep, lists what the posting asks for that your resume doesn't show, and finds the recruiter / hiring manager / a teammate with a LinkedIn note ready to paste.
4. **Review** - `Review` tab. Approve, Retry (tell it what to change), or Skip. "Approve all" approves every SA-open role above a fit score.
5. **Submit** - press **Submit approved**. A Chrome window opens and applies one by one. It stops and leaves the tab open when it hits a CAPTCHA, a login, or a question only you can answer truthfully; those land in `Needs you`. Press "I submitted it" when you finish one by hand.
6. **Track** - every submitted role becomes a row in Notion Application tracker 2.1: Stage Applied, apply date, resume file, cover letter, interview prep, gaps, and the referral contacts in Connections.
7. **Referrals** - `Referrals` tab: "Copy note + open profile", paste into LinkedIn's Connect > Add a note, Send, then Mark sent (updates "connections sent" in Notion). `Runs > Backfill referrals` fills contacts for every older tracker row whose Connections is blank.

## One-off setup
1. `setup.bat` - installs the Python packages and LibreOffice (for PDFs).
2. `start.bat` - opens the dashboard. In **Settings** paste:
   - one free AI key (Gemini from aistudio.google.com/apikey is the best free one; add Groq too as a backup),
   - your Notion integration token (notion.so/my-integrations), then in Notion open Application tracker 2.1 > ... > Connections > add that integration.
3. Start Docker Desktop so the same SearXNG your lead qualifier uses (port 8888) handles referral searches. Without it the engine falls back to DuckDuckGo.
4. `Boards` tab > **Open login browser** - sign in once to Wellfound / We Work Remotely / Indeed in that window. The engine keeps those sign-ins in its own profile; it never types passwords.
5. `schedule.bat` - registers the 3-hourly find + prepare. It never submits on its own.

## Where files go
Tailored resumes and cover letters: `paths.resume_copies` in config (default `D:\job-engine\out\Resume Copies`). Install Google Drive for Desktop and point this at a Drive folder to have them land in Drive automatically.
Masters: `masters\` - copies of your Drive masters (fonts stripped). If you edit a master in Drive, download it as .docx and replace the matching file: `dev_J, dev_J-M, dev_HM, dev_M-S, dev_S, design_ONE, admin_J, admin_J-M, admin_HM`.

## Free AI options (in order the engine tries them)
Gemini (free tier), Groq (free tier), Cerebras (free tier), OpenRouter free models, then Ollama on this PC (offline, slower; `ollama pull llama3.2:3b`). With none of them it still works in keyword mode: skills reordered to match the posting, header fixed, template cover letter.

## Adding a board
Settings > config.json > `boards`. For any website: `{"name": "...", "kind": "render", "url": "https://..."}`. Use `{q}` in the URL to search each of your search terms. Then press Run next to it in the Boards tab and check it finds postings.
