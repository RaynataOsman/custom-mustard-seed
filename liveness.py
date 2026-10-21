"""Check whether roles waiting on the dashboard are still open.

A role is closed only on a clear signal from the site itself:
  - the employer's job system (Greenhouse, Lever, Ashby, SmartRecruiters) says the posting is gone
  - the posting page answers 404 / 410
  - the page says so ("no longer accepting applications", "this job has expired", ...)
  - the posting's own data says its closing date has passed
Bot checks, 403 / 429 and timeouts count as 'unknown': the role stays, and that site is left alone
for the rest of the run. Closed roles move to 'expired' with the reason, so they drop off the PC and
phone dashboards. Submitted roles are never touched.

  python pipeline.py checklive            check the next batch (search.liveness.per_run)
  python pipeline.py checklive dry        report only, change nothing
  python pipeline.py checklive 500        check up to 500 this time
"""
import re, json, time, datetime, urllib.parse, html as htmllib
from concurrent.futures import ThreadPoolExecutor
import db
from util import http, load_config, now_iso

CHECK_STATUSES = ("approved", "needs_you", "ready", "retry", "failed", "new")
DEFAULTS = {"enabled": True, "per_run": 300, "recheck_hours": 48, "per_host": 40, "delay_s": 1.5, "workers": 6, "max_minutes": 12,
            # sites whose job links answer 404 even while the role is open (jobs live inside an embedded list)
            "ignore_404_hosts": ["somewhere.com"]}

CLOSED_TEXT = re.compile(
    r"(no longer accepting (applications|candidates)"
    r"|(this|the) (job|position|role|vacancy|opening|posting|listing|job ad(vert)?) (is|has been|was) (no longer (available|open|active|online)|filled|closed|removed|deleted|expired|taken down)"
    r"|(job|posting|listing|vacancy|advert|job ad) (has )?expired"
    r"|applications? (are|is|have) (now )?closed"
    r"|(job|page|posting|position) you(?:'re| are) looking for (is no longer|does not exist|doesn't exist|could not be found|was not found|has been removed)"
    r"|\bjob not found\b|\bposting not found\b|\bvacancy not found\b"
    r"|we(?:'re| are) no longer (hiring|recruiting) for this)", re.I)
BLOCK_TEXT = re.compile(r"(captcha|are you a robot|verify you are human|unusual traffic|access denied|"
                        r"attention required|just a moment|checking your browser|request blocked)", re.I)


def settings(cfg=None):
    cfg = cfg or load_config()
    s = dict(DEFAULTS)
    s.update((cfg.get("search", {}).get("liveness") or {}))
    return s


def ensure_cols(c):
    cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
    for col in ("live_checked_at", "live_status"):
        if col not in cols:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
    c.commit()


# ------------------------------------------------------------------ employer job systems (exact answers)
_ashby_cache = {}


def _api(url):
    r = http().get(url, timeout=20, headers={"Accept": "application/json"})
    return r.status_code, (r.json() if r.status_code == 200 and "json" in (r.headers.get("content-type") or "") else None)


def ats_check(url):
    """('open'|'closed'|None, reason). None = not an employer system we can ask directly."""
    u = urllib.parse.urlparse(url or "")
    h, p = u.netloc.lower(), u.path
    try:
        m = re.match(r"/([^/]+)/jobs/(\d+)", p)
        if m and h in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
            st, _ = _api(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}")
            return ("closed", "Greenhouse says the posting is gone") if st == 404 else ("open", "Greenhouse") if st == 200 else (None, f"Greenhouse {st}")
        m = re.match(r"/([^/]+)/([0-9a-f-]{36})", p)
        if m and h in ("jobs.lever.co", "jobs.eu.lever.co"):
            api = "api.eu.lever.co" if ".eu." in h else "api.lever.co"
            st, _ = _api(f"https://{api}/v0/postings/{m.group(1)}/{m.group(2)}")
            return ("closed", "Lever says the posting is gone") if st == 404 else ("open", "Lever") if st == 200 else (None, f"Lever {st}")
        if m and h == "jobs.ashbyhq.com":
            org, jid = m.group(1), m.group(2)
            if org not in _ashby_cache:
                st, data = _api(f"https://api.ashbyhq.com/posting-api/job-board/{org}")
                _ashby_cache[org] = {j.get("id") for j in (data or {}).get("jobs", [])} if st == 200 and data else None
            ids = _ashby_cache[org]
            if ids is None:
                return None, "Ashby board unreadable"
            return ("open", "Ashby") if jid in ids else ("closed", "no longer on the employer's Ashby job board")
        m = re.match(r"/([^/]+)/(\d{6,})", p)
        if m and h == "jobs.smartrecruiters.com":
            st, data = _api(f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}")
            if st == 404:
                return "closed", "SmartRecruiters says the posting is gone"
            if st == 200:
                return ("open", "SmartRecruiters") if (data or {}).get("active", True) else ("closed", "SmartRecruiters marks it inactive")
            return None, f"SmartRecruiters {st}"
    except Exception as e:
        return None, f"{type(e).__name__}"
    return None, ""


# ------------------------------------------------------------------ any other page
def _linkedin_guest(url):
    m = re.search(r"linkedin\.com/jobs/view/(?:[^/?]*?-)?(\d{6,})", url or "") or re.search(r"currentJobId=(\d{6,})", url or "")
    return f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}" if m else None


def _text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"(?s)<[^>]+>", " ", raw)))


def _valid_through(raw):
    today = datetime.date.today().isoformat()
    for blob in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', raw)[:6]:
        for m in re.finditer(r'"validThrough"\s*:\s*"(\d{4}-\d{2}-\d{2})', blob):
            if m.group(1) < today:
                return m.group(1)
    return None


def page_check(url, trust_404=True, ignore_404=()):
    guest = _linkedin_guest(url)
    target = guest or url
    r = http().get(target, timeout=15, allow_redirects=True)
    if r.status_code in (403, 429, 999, 503) or r.status_code >= 500:
        return "blocked", f"site answered {r.status_code}"
    if r.status_code in (404, 410):
        host = urllib.parse.urlparse(target).netloc.lower().replace("www.", "")
        if not trust_404 or any(host == h or host.endswith("." + h) for h in ignore_404):
            return None, f"{host} answers {r.status_code}, but that alone does not prove the role closed"
        return "closed", f"posting page answers {r.status_code} (removed)"
    if r.status_code != 200:
        return None, f"site answered {r.status_code}"
    raw = r.text[:400000]
    vt = _valid_through(raw)
    if vt:
        return "closed", f"posting's closing date {vt} has passed"
    txt = _text(raw)[:20000]
    m = CLOSED_TEXT.search(txt)
    if m:
        return "closed", f'page says "{m.group(0)[:70]}"'
    if len(txt) < 2500 and BLOCK_TEXT.search(txt):
        return "blocked", "bot check"
    if r.history and re.search(r"[?&](error=true|gh_err)", r.url):
        return "closed", "employer page redirects to its job list with an error (posting removed)"
    return "open", "LinkedIn" if guest else "page looks live"


def check(job, ignore_404=()):
    """Prefer the employer's own posting, then the board page. A 404 on the employer link alone
    never closes a role whose board page is still live (some employers' links 404 while open)."""
    for u in [x for x in (job.get("apply_url"), job.get("url")) if x and x.startswith("http")]:
        st, why = ats_check(u)
        if st:
            return st, why, u
    u = job.get("apply_url") if (job.get("apply_url") or "").startswith("http") and job.get("apply_url") != job.get("url") else job.get("url")
    try:
        st, why = page_check(job.get("url") or u, ignore_404=ignore_404)
        if st == "open" and u and u != job.get("url"):
            st2, why2 = page_check(u, trust_404=False, ignore_404=ignore_404)
            if st2 == "closed":
                return st2, why2, u
        return st, why, job.get("url") or u
    except Exception as e:
        return None, f"could not read the page ({type(e).__name__})", job.get("url") or u


# ------------------------------------------------------------------ run
def _host(j):
    u = _linkedin_guest(j.get("url")) or j.get("apply_url") or j.get("url") or ""
    return urllib.parse.urlparse(u).netloc.lower().replace("www.", "")


def pick(c, s, limit):
    cut = (datetime.datetime.now() - datetime.timedelta(hours=s["recheck_hours"])).isoformat(timespec="seconds")
    rows = db.rows(c, f"""SELECT id, status, title, company, url, apply_url, score FROM jobs
                          WHERE status IN ({','.join('?' * len(CHECK_STATUSES))})
                          AND (live_checked_at IS NULL OR live_checked_at < ?)""", list(CHECK_STATUSES) + [cut])
    order = {st: i for i, st in enumerate(CHECK_STATUSES)}
    rows.sort(key=lambda j: (order.get(j["status"], 9), -(j.get("score") or 0)))
    per, out = {}, []
    for j in rows:
        h = _host(j)
        if per.get(h, 0) >= s["per_host"]:
            continue
        per[h] = per.get(h, 0) + 1
        out.append(j)
        if len(out) >= limit:
            break
    return out


def _run_host(jobs, delay, ignore_404=(), deadline=None):
    res, fails = [], 0
    for j in jobs:
        if deadline and time.time() > deadline:
            res += [(k, "skipped", "time limit for this run reached", None) for k in jobs[len(res):]]
            break
        st, why, u = check(j, ignore_404)
        res.append((j, st, why, u))
        fails = fails + 1 if (st is None and why.startswith("could not read")) else 0
        if st == "blocked" or fails >= 3:
            note = "site blocked an earlier check this run" if st == "blocked" else "site too slow or unreachable this run"
            res += [(k, "skipped", note, None) for k in jobs[len(res):]]
            break
        time.sleep(delay)
    return res


def run(log=print, dry=False, limit=None):
    cfg = load_config()
    s = settings(cfg)
    if not s.get("enabled", True) and limit is None:
        log("removed-role check is switched off (search.liveness.enabled)")
        return 0
    c = db.conn()
    ensure_cols(c)
    jobs = pick(c, s, int(limit or s["per_run"]))
    if not jobs:
        log("removed-role check: every waiting role was checked recently")
        return 0
    groups = {}
    for j in jobs:
        groups.setdefault(_host(j), []).append(j)
    log(f"checking {len(jobs)} waiting roles on {len(groups)} sites for removed postings{' (dry run)' if dry else ''}")
    with ThreadPoolExecutor(max_workers=s["workers"]) as ex:
        deadline = time.time() + 60 * float(s.get("max_minutes", 12))
        parts = list(ex.map(lambda g: _run_host(g, s["delay_s"], tuple(s.get("ignore_404_hosts") or ()), deadline),
                            groups.values()))
    results = []
    for host, part in zip(groups, parts):
        judged = [r for r in part if r[1] in ("open", "closed")]
        if len(judged) >= 4 and all(r[1] == "closed" and r[2].startswith("posting page answers 404") for r in judged):
            log(f"  {host}: answered 404 for every role checked - not trusted as proof of closing")
            part = [(j, None, f"{host} answers 404 for every role", u) if st == "closed" else (j, st, why, u)
                    for j, st, why, u in part]
        results += part
    counts, closed, now = {}, 0, now_iso()
    for j, st, why, u in results:
        counts[st or "unknown"] = counts.get(st or "unknown", 0) + 1
        if st == "closed":
            closed += 1
            log(f"  closed: {j['company']} - {j['title']} [{j['status']}] - {why}")
        if dry:
            continue
        if st == "closed":
            db.set_job(c, j["id"], status="expired", status_note=f"Posting removed - {why} (checked {now[:10]})")
            db.event(c, j["id"], "posting_closed", f"{why} | {u or ''}"[:400])
        if st == "skipped":
            continue  # not looked at this run - stays first in line for the next one
        c.execute("UPDATE jobs SET live_checked_at=?, live_status=? WHERE id=?",
                  (now if st != "blocked" else None, st or "unknown", j["id"]))
    if not dry:
        c.commit()
    log("removed-role check: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        + ("" if dry else f" - {closed} moved out of New/Review"))
    return closed

