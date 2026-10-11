"""Submit APPROVED applications in a visible Chrome window.

Only jobs you approved in the dashboard are touched. For each one the engine:
  - follows board links (Himalayas, WWR, LinkedIn...) through to the employer's form,
  - fills name, email, phone, location, links, rate, notice, resume and cover letter,
  - stops and leaves the tab open for you ("Needs you") when it meets a CAPTCHA,
    a question it can't answer truthfully from your profile (work authorisation,
    custom essays, dropdowns it doesn't recognise), a login wall, or a posting
    that bans AI-assisted applications,
  - otherwise clicks submit, checks for a confirmation and saves a screenshot.
It never solves CAPTCHAs, never creates accounts and never types passwords.
"""
import json, random, re, time, urllib.parse
from pathlib import Path
from util import OUT, load_config, ascii_clean
import render

ATS = {
    "greenhouse": re.compile(r"greenhouse\.io|gh_jid=", re.I),
    "lever": re.compile(r"jobs\.(eu\.)?lever\.co", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com", re.I),
    "workable": re.compile(r"apply\.workable\.com", re.I),
    "smartrecruiters": re.compile(r"smartrecruiters\.com", re.I),
    "breezy": re.compile(r"breezy\.hr", re.I),
    "recruitee": re.compile(r"recruitee\.com", re.I),
    "teamtailor": re.compile(r"teamtailor\.com", re.I),
    "bamboohr": re.compile(r"bamboohr\.com", re.I),
    "personio": re.compile(r"jobs\.personio\.", re.I),
    "jazzhr": re.compile(r"applytojob\.com", re.I),
    "zoho": re.compile(r"zohorecruit\.com", re.I),
    "rippling": re.compile(r"ats\.rippling\.com", re.I),
}
BOARD_HOSTS = re.compile(r"himalayas\.app|weworkremotely\.com|remoteok\.com|remotive\.com|jobicy\.com|"
                         r"workingnomads\.com|euremotejobs\.com|linkedin\.com/jobs|remoterocketship\.com|jobgether\.com", re.I)
CAPTCHA = 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare"], div.g-recaptcha, [data-sitekey]'
SUCCESS = re.compile(r"(thank you for (applying|your application)|application (has been )?(received|submitted)|"
                     r"we('ve| have) received your application|successfully (applied|submitted))", re.I)
PROOFS = OUT / "proofs"
PROOFS.mkdir(parents=True, exist_ok=True)


def ats_of(url):
    for k, rx in ATS.items():
        if rx.search(url or ""):
            return k
    return None


def _answers(job, cfg):
    p = cfg["profile"]
    rate = _rate_for(job, cfg, "") or ""
    yrs = cfg["submit"].get("years_by_tier", {}).get(job.get("tier") or "HM", "3")
    bank = [(pat, ans.replace("{years}", yrs).replace("{rate}", rate))
            for pat, ans in cfg["submit"].get("answers", [])]
    # "A|B|C" = try these options in order on dropdowns/radios; text boxes get the first one
    return bank + [
        (r"first[\s_-]*name|given name|fname", p["first_name"]),
        (r"last[\s_-]*name|surname|family name|lname", p["last_name"]),
        (r"^(full[\s_-]*)?name\b|your name|legal name|^name$", p["name"]),
        (r"e-?mail", p["email"]),
        (r"phone|mobile|telephone|whatsapp", p["phone"]),
        (r"linkedin", p["linkedin"]),
        (r"github", p["github"]),
        (r"portfolio|website|personal site|url|link", p["portfolio"]),
        (r"\bcity\b|current location|where are you (located|based)|location|address", p["location"]),
        (r"country", p["country"]),
        (r"time ?zone", p["timezone"]),
        (r"salary|compensation|rate|expected pay|pay expectation|desired pay", rate),
        (r"notice|start date|when can you start|availability to start|available to start", p["notice"]),
        (r"how did you hear|source|where did you (find|hear|see)", job.get("board") or "Job board"),
    ]


def _label_for(page, el):
    try:
        return page.evaluate("""el => {
            const id = el.id; let t = '';
            if (id) { const l = document.querySelector('label[for="' + CSS.escape(id) + '"]'); if (l) t = l.innerText; }
            if (!t) { const l = el.closest('label'); if (l) t = l.innerText; }
            if (!t) { const w = el.closest('div,fieldset,li'); if (w) { const l = w.querySelector('label,legend,.label,.application-label'); if (l) t = l.innerText; } }
            return (t + ' | ' + (el.name||'') + ' | ' + (el.placeholder||'') + ' | ' + (el.getAttribute('aria-label')||'') + ' | ' + (el.autocomplete||'')).trim();
        }""", el)
    except Exception:
        return ""


def _go_to_form(page, url, ats):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    # board page -> find the employer apply link
    if BOARD_HOSTS.search(page.url):
        for sel in ['a:has-text("Apply on company")', 'a:has-text("Apply now")', 'a:has-text("Apply for this")',
                    'a:has-text("Apply")', 'button:has-text("Apply")']:
            el = page.query_selector(sel)
            if not el:
                continue
            href = el.get_attribute("href")
            if href and href.startswith("http") and not BOARD_HOSTS.search(href):
                page.goto(href, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
                break
            try:
                with page.context.expect_page(timeout=8000) as newp:
                    el.click()
                p2 = newp.value
                p2.wait_for_load_state("domcontentloaded")
                return p2
            except Exception:
                try:
                    el.click()
                    page.wait_for_timeout(3000)
                except Exception:
                    pass
                break
    ats = ats_of(page.url)
    u = page.url
    if ats == "lever" and not urllib.parse.urlparse(u).path.rstrip("/").endswith("/apply"):
        page.goto(u.rstrip("/") + "/apply", wait_until="domcontentloaded")
    elif ats == "ashby" and "/application" not in urllib.parse.urlparse(u).path:
        page.goto(u.rstrip("/") + "/application", wait_until="domcontentloaded")
    elif ats == "workable" and "/apply" not in urllib.parse.urlparse(u).path:
        page.goto(u.split("?")[0].rstrip("/") + "/apply/", wait_until="domcontentloaded")
    else:
        btn = page.query_selector('button:has-text("Apply for this job"), a:has-text("Apply for this job"), '
                                  'button:has-text("Apply now"), a:has-text("Apply now")')
        if btn and not page.query_selector("input[type=file]"):
            try:
                btn.click()
            except Exception:
                pass
    page.wait_for_timeout(2500)
    return page


def _rate_for(job, cfg, label):
    """International USD rate for this family + tier, converted to the currency/period the form asks for."""
    p = cfg["profile"]
    fam, tier = job.get("family") or "dev", job.get("tier") or "HM"
    m = p.get("rate_by_family", {}).get(fam, {}).get(tier) or p["rate_by_tier"].get(tier)
    if not m:
        return None
    num = re.search(r"([\d,]+)", m)
    if not num:
        return m
    usd = int(num.group(1).replace(",", ""))
    cur, amt, per = "USD", usd, "month"
    if re.search(r"\bzar\b|rand|\(r\)|in r\b", label, re.I):
        cur, amt = "ZAR", round(usd * float(p.get("usd_zar", 18)) / 1000) * 1000
    elif re.search(r"\beur\b|euro", label, re.I):
        cur, amt = "EUR", round(usd * 0.92 / 100) * 100
    elif re.search(r"\bgbp\b|pound|\u00a3", label, re.I):
        cur, amt = "GBP", round(usd * 0.79 / 100) * 100
    if re.search(r"annual|per year|yearly|per annum|\bpa\b", label, re.I):
        amt, per = amt * 12, "year"
    elif re.search(r"hour|hourly", label, re.I):
        amt, per = round(amt / 160), "hour"
    return f"{cur} {amt:,}/{per}"


def _visible_captcha(page):
    """True only for a challenge a person has to click (invisible reCAPTCHA v3 is ignored)."""
    for el in page.query_selector_all('iframe[src*="recaptcha"][src*="anchor"], iframe[src*="recaptcha"][src*="bframe"], '
                                      'iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare"]'):
        try:
            src = el.get_attribute("src") or ""
            if "size=invisible" in src:
                continue
            box = el.bounding_box()
            if el.is_visible() and box and box["height"] > 40 and box["width"] > 40:
                return True
        except Exception:
            pass
    return False


def _answer_choices(page, answers, log):
    """Answer required radio groups and selects from the answer bank (e.g. Yes/No questions)."""
    left = []
    groups = page.evaluate("""() => {
      const g = {};
      document.querySelectorAll('input[type=radio]').forEach(r => {
        if (r.offsetParent === null) return;
        const optLab = (r.labels && r.labels[0] ? r.labels[0].innerText : '').trim();
        let q = '';
        const rg = r.closest('[role=radiogroup]');
        if (rg && rg.getAttribute('aria-labelledby')) { const e = document.getElementById(rg.getAttribute('aria-labelledby').split(' ')[0]); if (e) q = e.innerText; }
        if (!q) { const fs = r.closest('fieldset'); const lg = fs && fs.querySelector('legend'); if (lg) q = lg.innerText; }
        if (!q) { let p = r.parentElement; for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
            const t = (p.innerText || '').trim().split('\\n')[0].trim();
            if (t && t !== optLab && !/^(yes|no)$/i.test(t)) { q = t; break; } } }
        q = (q || r.name).trim();
        const lab = (r.labels && r.labels[0] ? r.labels[0].innerText : (r.parentElement.innerText || r.value)).trim();
        (g[r.name] = g[r.name] || {q, opts: [], checked: false});
        g[r.name].opts.push([r.id, r.value, lab]); if (r.checked) g[r.name].checked = true;
      });
      return Object.entries(g).filter(([n, v]) => !v.checked).map(([n, v]) => ({name: n, q: v.q, opts: v.opts}));
    }""")
    for grp in groups:
        ans = next((a for p, a in answers if re.search(p, grp["q"], re.I)), None)
        picked = False
        for alt in (ans.split("|") if ans else []):
            w = alt.split()[0].strip(".,")
            for oid, val, lab in grp["opts"]:
                if re.match(re.escape(w), lab.strip(), re.I) or re.match(re.escape(w), (val or ""), re.I):
                    try:
                        sel = f'input[type=radio][name="{grp["name"]}"][value="{val}"]'
                        try:
                            page.check(sel, timeout=3000)
                        except Exception:
                            page.eval_on_selector(sel, "e => { (e.labels && e.labels[0] ? e.labels[0] : e).click(); }")
                        picked = page.eval_on_selector(sel, "e => e.checked")
                    except Exception:
                        pass
                    break
            if picked:
                break
        if not picked:
            left.append(grp["q"][:80] or grp["name"])
    return left


def _decline_cookies(page):
    for sel in ['button:has-text("Decline all")', 'button:has-text("Reject all")', 'button:has-text("Decline")',
                'button:has-text("Reject")', 'button:has-text("Only necessary")', 'button:has-text("Necessary only")']:
        try:
            b = page.query_selector(sel)
            if b and b.is_visible():
                b.click()
                page.wait_for_timeout(800)
                return
        except Exception:
            pass


def fill_and_submit(page, job, cfg, approved=True, log=print):
    """Returns (status, note). status: submitted | needs_you | failed"""
    _decline_cookies(page)
    if page.query_selector('input[type="password"]'):
        return "needs_you", "login or account required on this site - sign in once, then click Retry"
    answers = _answers(job, cfg)
    unanswered, filled = [], []

    # text-like inputs
    for el in page.query_selector_all('input:not([type=hidden]):not([type=file]):not([type=checkbox]):'
                                      'not([type=radio]):not([type=submit]):not([type=button]), textarea'):
        try:
            if not el.is_visible() or (el.input_value() or "").strip():
                continue
        except Exception:
            continue
        label = _label_for(page, el)
        lab = label.lower()
        tag = el.evaluate("e => e.tagName").lower()
        value = None
        if tag == "textarea" and re.search(r"cover|letter|why (do|are|would) you|why .{0,30}(us|role|company|position|team)|motivat|message|additional information|anything else|tell us about yourself", lab):
            value = job.get("cover_letter") or ""
        else:
            for pat, v in answers:
                if re.search(pat, lab):
                    value = v.split("|")[0]
                    break
        if value and re.search(r"salary|compensation|rate|pay", lab):
            value = _rate_for(job, cfg, lab) or value
        if value:
            try:
                v = ascii_clean(value)
                el.fill(v)
                try:
                    page.keyboard.press("Escape")  # close autocomplete popups
                    cur = el.input_value()
                    if len(v) > 4 and cur.count(v) > 1:
                        el.fill("")
                        el.type(v, delay=10)
                        page.keyboard.press("Escape")
                except Exception:
                    pass
                filled.append(label.split("|")[0].strip()[:40])
            except Exception:
                pass
        else:
            req = el.evaluate("e => e.required || e.getAttribute('aria-required') === 'true'")
            if req:
                unanswered.append(label.split("|")[0].strip()[:80] or "unnamed field")

    # resume / cover letter uploads
    files = page.query_selector_all('input[type="file"]')
    resume = job.get("resume_pdf") or job.get("resume_docx")
    spare = []
    for i, el in enumerate(files):
        lab = (_label_for(page, el) + " " + (el.get_attribute("accept") or "") + " " +
               (el.evaluate("e => (e.closest('section,fieldset,div[class*=field],div[class*=upload]') || e.parentElement).innerText.slice(0,120)") or "")).lower()
        try:
            if re.search(r"cover", lab):
                if job.get("cover_letter_pdf"):
                    el.set_input_files(job["cover_letter_pdf"])
            elif re.search(r"photo|avatar|image|picture|headshot|video", lab):
                continue
            elif resume and (re.search(r"resume|\bcv\b|curriculum", lab) or len(files) == 1):
                el.set_input_files(resume)
                filled.append("resume")
            elif not re.search(r"image/|\.jpe?g|\.png", lab):
                spare.append(el)
        except Exception as e:
            log(f"    upload failed: {e}")
    if resume and "resume" not in filled and spare:
        try:
            spare[0].set_input_files(resume)
            filled.append("resume")
        except Exception as e:
            log(f"    upload failed: {e}")
    page.wait_for_timeout(2000)

    # required selects / radios / checkboxes we cannot answer truthfully -> you
    for el in page.query_selector_all("select"):
        try:
            if el.is_visible() and not el.input_value() and el.evaluate(
                    "e => e.required || e.getAttribute('aria-required') === 'true'"):
                lab = _label_for(page, el).lower()
                if re.search(r"country", lab):
                    try:
                        el.select_option(label=cfg["profile"]["country"])
                        continue
                    except Exception:
                        pass
                ans = next((a for p, a in answers if re.search(p, lab, re.I)), None)
                if ans:
                    opts = el.evaluate("e => [...e.options].map(o => [o.value, o.text])")
                    want = [a.split()[0].strip(".,").lower() for a in ans.split("|")] + \
                           [(job.get("board") or "").split()[0].lower(), "job board", "other"]
                    hit = next((v for w in want if w for v, t in opts if v and t.lower().startswith(w)), None)
                    if hit:
                        el.select_option(value=hit)
                        continue
                unanswered.append(_label_for(page, el).split("|")[0].strip()[:80])
        except Exception:
            pass
    for el in page.query_selector_all('input[type="checkbox"]'):
        try:
            if not el.is_visible() or el.is_checked():
                continue
            lab = _label_for(page, el).lower()
            req = el.evaluate("e => e.required || e.getAttribute('aria-required') === 'true'")
            if re.search(r"privacy|consent|terms|agree|gdpr|data", lab) and cfg["submit"].get("auto_tick_consent"):
                el.check()
            elif req:
                unanswered.append(lab.split("|")[0].strip()[:80])
        except Exception:
            pass
    for q in _answer_choices(page, answers, log):
        unanswered.append(q)

    if _visible_captcha(page):
        return "needs_you", "CAPTCHA on the form - solve it and press submit yourself. Filled: " + ", ".join(filled)
    if unanswered:
        return "needs_you", "Questions only you can answer: " + "; ".join(dict.fromkeys(unanswered))[:600]
    if "resume" not in filled and files:
        return "needs_you", "could not attach the resume automatically"
    if not filled:
        return "needs_you", "no application form found on this page"
    if not approved:
        return "needs_you", "filled, waiting for your approval"

    btn = page.query_selector('button[type=submit], input[type=submit], button:has-text("Submit application"), '
                              'button:has-text("Submit Application"), button:has-text("Submit"), button:has-text("Send application")')
    if not btn:
        return "needs_you", "filled everything but could not find the submit button"
    btn.click()
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    shot = PROOFS / f'{job["id"]}.png'
    try:
        page.screenshot(path=str(shot), full_page=True)
    except Exception:
        pass
    body = page.inner_text("body")[:6000]
    if SUCCESS.search(body):
        return "submitted", f"confirmation seen; proof {shot.name}"
    if _visible_captcha(page):
        return "needs_you", "CAPTCHA appeared after submit - finish it in the open tab"
    err = re.search(r"(this field is required|is required|please (fill|complete|enter)[^.\n]{0,60})", body, re.I)
    if err:
        return "needs_you", f'form says: "{err.group(0)}" - finish in the open tab'
    return "needs_you", "submitted but no confirmation text seen - check the open tab, then mark it"


def run(jobs, log=print, dry=False):
    """jobs: list of approved job dicts (with resume paths). Yields (job_id, status, note)."""
    from playwright.sync_api import sync_playwright
    cfg = load_config()
    results = []
    with sync_playwright() as p:
        ctx = render.launch(p, headless=dry, profile=render.PROFILE.parent / "apply-profile")
        open_tabs = 0
        try:
            for job in jobs[: cfg["submit"]["max_per_run"]]:
                if job.get("ai_ban"):
                    results.append((job["id"], "needs_you", "posting bans AI-assisted applications - write this one yourself"))
                    continue
                page = ctx.new_page()
                try:
                    url = job.get("apply_url") or job.get("url")
                    page = _go_to_form(page, url, ats_of(url))
                    status, note = fill_and_submit(page, job, cfg, approved=not dry, log=log)
                    if dry:
                        page.screenshot(path=str(PROOFS / f'dry_{job["id"]}.png'), full_page=True)
                except Exception as e:
                    status, note = "needs_you", f"automation error: {str(e)[:200]} - tab left open"
                log(f"  {job['company']} - {job['title']}: {status} ({note[:120]})")
                results.append((job["id"], status, note))
                if status == "submitted" or dry:
                    page.close()
                else:
                    open_tabs += 1
                time.sleep(random.uniform(*cfg["submit"]["delay_between_s"]))
            if open_tabs and not dry:
                log(f"{open_tabs} tab(s) need you. Finish them in the browser window, then close it. "
                    "Mark them done in the dashboard.")
                deadline = time.time() + cfg["submit"].get("wait_for_you_minutes", 45) * 60
                while time.time() < deadline and len(ctx.pages) > 0:
                    time.sleep(2)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    return results
