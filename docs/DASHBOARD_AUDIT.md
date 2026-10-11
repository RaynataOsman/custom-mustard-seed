# Dashboard audit â€” 11 October 2026

## Implemented

- Settings forms load independently of slow service-health checks. Page requests carry a render version so old responses cannot overwrite a newer tab. Navigation has loading, error and retry states and follows browser back/forward.
- Referral copy buttons safely handle apostrophes and quotation marks. Board Run buttons correctly encode board names.
- Undo approval returns a prepared job to Review (`ready`), retaining its output files.
- Output file and folder access uses resolved path containment instead of string prefixes.
- Late AI-provider tests and log responses no longer update unrelated pages. Manual preparation's refresh is limited to the Add a job tab.
- Settings includes the `ONE` rate tier used by single-level resume families.
- Warm neutral / mustard palette, sprout-and-seed SVG mark and favicon, progress cards, descriptive page headings, keyboard focus styles, mobile navigation and persistent light/dark mode. The initial theme follows the OS.
- All CSS is local; the dashboard no longer requires the Tailwind CDN. This is a shadcn-inspired vanilla implementation, not a React/MUI/shadcn migration.

## Verification

- Existing employer/time-zone/schema tests and email parsing/IMAP tests pass.
- `python tests/test_app.py`: output path containment, Undo approval, cross-site POST rejection.
- `python tests/test_dashboard.py`: installed Chrome with synthetic API fixtures; all nine views, slow Settings data and health responses, navigation races, browser history, quoted button arguments, HTTP failures/retry, theme persistence, mobile overflow and JavaScript errors. No real applications or messages are submitted by these tests.
- Python compilation and `git diff --check` pass.
- Read-only HTTP smoke checks cover actual dashboard assets, overview, jobs, contacts, settings data, runs and service health (all returned HTTP 200). No configuration, credentials, master resumes or live job statuses were changed by the tests.
- Visual samples in `out/dashboard-light.png`, `out/dashboard-dark.png`, and `out/dashboard-mobile.png` use synthetic data.

The Python process inside the restricted test environment could not see user-installed dependencies. Verification outside that environment confirmed that all dependencies in requirements.txt were already installed; this was an environment difference, not evidence of a broken user installation.

## Remaining gaps / next priorities

1. **External workflows need a separate live integration pass.** Board scraping, AI tailoring, PDF generation, Notion writes and approved form submissions were not exercised end-to-end. Existing handoff claims are context, not fresh verification. Ashby dropdowns and fragile board selectors remain known limitations.
2. **Run coordination:** manual preparation changes a job before `start_run` checks whether another run is busy. Refused starts can leave a job's status changed. The busy check also relies on statuses last updated by polling `runs_snapshot`. A follow-up should make job reservation and process lifecycle handling consistent.
3. **Config validation:** saving raw JSON only checks JSON syntax. Missing sections or wrong types can still break backend operations. Add schema validation and atomic writes before expanding family use.
4. **Database lifecycle:** many request handlers open SQLite connections without explicitly closing them. Add scoped connections consistently and stress-test concurrent dashboard/pipeline use.
5. **Manual form drafts:** switching away from Add a job discards unfinished input; same-tab preparation polling can also replace form content. Preserve drafts before enabling more automatic refreshes.
6. **Readiness / recovery:** add clear controls for interrupted preparation/submission runs and missing output files. Current tests do not cover crash recovery.
7. **Product backlog:** interview/rejection inbox sync, seven-day follow-up reminders and a nontechnical screening-answer editor remain unimplemented, as described in the handoff.
8. **Dependency reproducibility:** requirements use minimum versions rather than a tested lock or constraints file. The UI has no npm build; the runtime is Python plus static HTML/CSS.

## Running the checks

```text
python tests/test_employer.py
python tests/test_email_alerts.py
python tests/test_app.py
python tests/test_dashboard.py
```

The browser suite needs Playwright and installed Google Chrome. It serves local UI files on a temporary port and mocks all API calls. No browser download is needed when Chrome is installed.

Restart the dashboard with `start.bat` after updating the server, then reload the page. The theme control is in the header; its preference is stored in that browser.

## Live-server asset regression fixed

The first update introduced CSS and logo routes that an already-running Python server did not know about. It served the new HTML but returned 404 for those assets, leaving the UI unstyled. The dashboard now embeds its theme CSS, SVG logo and favicon in the HTML, so a page refresh works with the existing server. Browser regression tests simulate missing asset routes; a read-only Chrome check against the actual running dashboard confirmed layout, logo and no JavaScript errors. Theme CSS is maintained directly in `ui/index.html`.
