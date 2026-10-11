# Mustard Seed - setup guide (no tech skills needed)

This takes about an hour, once. After that you only open the dashboard, read, and press buttons.

**You need:** a Windows laptop or PC that is on for a few hours a day, a Google (Gmail) account,
your resume as a Word file (.docx), and a LinkedIn account. A Notion account is optional.

Tick each box as you go.

---

## Part 1 - Install (15 minutes)

- [ ] **1. Install Python.** Go to **python.org/downloads**, press the yellow *Download Python* button and run it.
  On the first screen **tick "Add python.exe to PATH"** at the bottom, then press *Install Now*.
- [ ] **2. Install Google Chrome** if you don't have it (google.com/chrome).
- [ ] **3. Get the Mustard Seed folder.** Jerome will either invite you on GitHub (open the invite email,
  then on the project page press the green **Code** button > **Download ZIP**) or send you the zip.
- [ ] **4. Unzip it** to `C:\mustard-seed` (right-click the zip > *Extract All* > type `C:\mustard-seed`).
- [ ] **5. Double-click `setup.bat`** in that folder. A black window installs what's needed. It can take
  10 minutes. If Windows asks "Do you want to allow...", press *Yes*. When it says *Setup finished*, press any key.
- [ ] **6. Double-click `start.bat`.** Your browser opens the dashboard. Keep the black window open while
  you use it - closing it closes the dashboard.

> If the dashboard didn't open, type `localhost:8766` into Chrome's address bar.

---

## Part 2 - Tell it about you (15 minutes)

Everything here is in the dashboard **Settings** tab.

- [ ] **7. About you.** Fill in your name, email, phone, location and LinkedIn link.
  Fill in your **asking rate per level** in US dollars per month (example: `USD 1,200/month`).
  Remote companies overseas pay in dollars - don't type rand amounts here.
  - Leave *Only overseas employers* **off** unless you only want companies outside South Africa.
  - *Hours you can work* - the hours (SA time) you are willing to work, e.g. `07:00-22:00`.
    US companies usually want you from 15:00 to 23:00 SA time.
  - Press **Save my details**.
- [ ] **8. Resume families.** A "family" is a kind of job: *Admin & virtual assistant*, *Accounting &
  bookkeeping*, *E-commerce management*, *Sales*, *Web developer*, *UX/UI designer*.
  Admin is there already. Pick another from the list and press **Add family**. Press *remove* on any
  family you don't want.
- [ ] **9. Upload your resume(s).** Under *Upload a master resume*: choose the family, choose the level,
  choose your .docx and press **Upload**.
  - Levels: **J** = junior/entry, **J-M** = junior-to-mid, **HM** = mid, **M-S** = mid-to-senior, **S** = senior.
  - One resume per family is fine to start - upload it under the level that fits you. The engine uses it for
    every level until you add more.
  - Use a plain resume: no tables, no text boxes, no photos. Word or Google Docs > *Download as .docx*.
- [ ] **10. Free AI key (needed for tailoring and cover letters).** Go to **aistudio.google.com/apikey**,
  sign in with Google, press *Create API key*, copy it. In Settings > Keys paste it into
  **GEMINI_API_KEY** and press *Save keys*. Press *Test free AI providers* - Gemini should say ok.
  - Optional backup: a free key from **console.groq.com/keys** into GROQ_API_KEY.
- [ ] **11. Features.** Switch off what you won't use. Common choices:
  - Just want tailored resumes for jobs you find yourself? Keep only *AI resume tailoring* and use the **Add a job** tab.
  - Don't use Notion? Switch *Update Notion tracker* off.
  - Prefer to submit every application yourself? Switch *Fill application forms* off.

---

## Part 3 - Optional extras (20 minutes)

### Job-alert emails (finds jobs from sites that block robots: Indeed, LinkedIn, Glassdoor, PNet...)
- [ ] Turn on **2-Step Verification** on your Google account (myaccount.google.com > Security).
- [ ] Go to **myaccount.google.com/apppasswords**, type `Mustard Seed`, press *Create*, copy the 16 letters.
- [ ] In Settings > Keys paste your Gmail address into **GMAIL_ADDRESS** and the 16 letters into
  **GMAIL_APP_PASSWORD**. Save.
- [ ] On each job site, search your job title + "remote" and press **Create job alert / Get emails**:
  Indeed, LinkedIn Jobs, Glassdoor, and any you like. The engine reads those emails (it never deletes or marks them read).

### Notion tracker
- [ ] Ask Jerome for the **tracker template link**, open it and press **Duplicate** (top right).
- [ ] Go to **notion.so/my-integrations** > *New integration* > name it `Mustard Seed` > *Save*.
  Copy the **Internal Integration Secret**. Paste it into Settings > Keys > **NOTION_TOKEN**.
- [ ] Open your duplicated tracker in Notion > press **...** (top right) > *Connections* > add `Mustard Seed`.
- [ ] Copy the tracker's link (*Share > Copy link*) and paste it in Settings > *Notion tracker link*. Save.
- [ ] Settings > Health should say Notion **ok**.

### Run it automatically every 3 hours
- [ ] Double-click **`schedule.bat`** once. It finds and prepares jobs every 3 hours while your PC is on.
  It **never applies** on its own. To stop it later, open *Task Scheduler* and delete "Job Engine".

### Sign in to boards that need it
- [ ] Dashboard > **Boards** tab > *Open login browser*. Sign in to Wellfound and LinkedIn in that window,
  then close it. You type your own password; the engine only keeps the signed-in session.

---

## Your daily routine (10-20 minutes)

1. Open the dashboard (`start.bat`). The top line tells you what's waiting.
2. **Review** tab - for each role read the job, the resume changes and the cover letter.
   - **Approve** - looks good. **Retry...** - type what to change ("make it shorter", "use the admin resume").
     **Skip** - not for you.
3. Press **Submit approved**. A Chrome window fills in the forms. If a site wants a sign-in, a CAPTCHA or
   an odd question, the role moves to **Needs you** - finish it in that window and press *I submitted it*.
4. **Referrals** tab - send 10-20 LinkedIn notes: *Copy note + open profile* > on LinkedIn press
   *Connect* > *Add a note* > paste > *Send*. Then press *Mark sent*.
5. Found a job yourself? **Add a job** tab: paste the link and/or text > *Check my odds* >
   *Prepare...* > download the resume and cover letter > apply > press *I submitted it*.
   Tip: drag the **+ Send to Job Engine** button to your bookmarks bar - then one click on any job page fills this in.

---

## Staying safe

- **Never pay** to get a job, for "training", "equipment" or a "starter kit". The Add-a-job tab warns you about this.
- Real companies don't interview only on Telegram or WhatsApp.
- Paid in dollars? Payoneer and Wise accounts receive USD; platforms like Deel pay into them.
  You still declare that income to SARS - speak to a tax practitioner once you have your first contract.

## If something goes wrong

| What you see | What to do |
|---|---|
| Black window flashes and closes on setup | Python wasn't added to PATH. Reinstall Python and tick the box (step 1). |
| Dashboard won't open | Is the `start.bat` window still open? Then type `localhost:8766` in Chrome. |
| "Test free AI" shows an error | Re-copy the Gemini key; make sure there are no spaces. |
| Nothing in Review | Press *Find + prepare now*, wait for the Runs tab to say done. Check you uploaded a resume (Settings > Health > Masters). |
| A board shows "error" on the Boards tab | Normal now and then - sites change. The rest keep working. Tell Jerome if it stays red for days. |
| Notion says "not shared" | Step: tracker > ... > Connections > add Mustard Seed. |
