"""Board adapters. Each returns a list of raw job dicts:
   {board, source, url, apply_url, title, company, location, description,
    posted_at, salary, employment_type, countries(list|None)}

Kinds:
  himalayas, remotive, remoteok, wwr_rss, workingnomads, arbeitnow, jobicy,
  rss, greenhouse, lever, ashby, workable, linkedin, reddit, render
The 'render' kind (Playwright, for JS-heavy boards) lives in render.py.
"""
import datetime, html, json, re, time, urllib.parse
import xml.etree.ElementTree as ET
from util import get, strip_html, ascii_clean


def _iso(ts):
    if ts in (None, ""):
        return None
    try:
        if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit()):
            v = float(ts)
            if v > 1e12:
                v /= 1000
            return datetime.datetime.fromtimestamp(v, datetime.timezone.utc).date().isoformat()
        s = str(ts)
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
            try:
                return datetime.datetime.strptime(s, fmt).date().isoformat()
            except Exception:
                pass
        return s[:10]
    except Exception:
        return None


def _job(board, **kw):
    j = {"board": board["name"], "source": board["kind"], "countries": None}
    j.update(kw)
    for k in ("title", "company", "location"):
        if j.get(k):
            j[k] = ascii_clean(html.unescape(str(j[k]))).strip()
    return j


def search_terms(board, cfg):
    return board.get("queries") or cfg["search"]["queries"]


# ---------------------------------------------------------------- APIs
def himalayas(board, cfg, log):
    out, seen = [], set()
    for q in search_terms(board, cfg):
        cursor, pages = None, 0
        while pages < board.get("pages", 2):
            params = {"q": q, "limit": 20}
            if cursor:
                params["cursor"] = cursor
            r = get("https://himalayas.app/jobs/api/search", params=params)
            r.raise_for_status()
            data = r.json()
            for it in data.get("jobs", []):
                if it["guid"] in seen:
                    continue
                seen.add(it["guid"])
                sal = ""
                if it.get("minSalary"):
                    sal = f'{it.get("currency") or ""} {it["minSalary"]}-{it.get("maxSalary") or ""} {it.get("salaryPeriod") or ""}'
                out.append(_job(board, url=it["applicationLink"], apply_url=it["applicationLink"],
                                title=it["title"], company=it["companyName"],
                                location=", ".join(it.get("locationRestrictions") or []) or "Worldwide",
                                countries=it.get("locationRestrictions") or [],
                                description=strip_html(it.get("description")),
                                posted_at=_iso(it.get("pubDate")), salary=sal.strip(),
                                employment_type=it.get("employmentType"),
                                seniority=", ".join(it.get("seniority") or [])))
            cursor = data.get("nextCursor")
            pages += 1
            if not cursor:
                break
            time.sleep(1)
    return out


def remotive(board, cfg, log):
    out = []
    for q in search_terms(board, cfg):
        r = get("https://remotive.com/api/remote-jobs", params={"search": q, "limit": 100})
        r.raise_for_status()
        for it in r.json().get("jobs", []):
            out.append(_job(board, url=it["url"], apply_url=it["url"], title=it["title"],
                            company=it["company_name"], location=it.get("candidate_required_location"),
                            description=strip_html(it.get("description")),
                            posted_at=_iso(it.get("publication_date")), salary=it.get("salary"),
                            employment_type=it.get("job_type")))
        time.sleep(1)
    return out


def remoteok(board, cfg, log):
    r = get("https://remoteok.com/api")
    r.raise_for_status()
    out = []
    for it in r.json():
        if not isinstance(it, dict) or not it.get("position"):
            continue
        sal = f'USD {it["salary_min"]}-{it.get("salary_max")}' if it.get("salary_min") else ""
        out.append(_job(board, url=it.get("url"), apply_url=it.get("apply_url") or it.get("url"),
                        title=it["position"], company=it.get("company"), location=it.get("location") or "",
                        description=strip_html(it.get("description")), posted_at=_iso(it.get("date")),
                        salary=sal, tags=it.get("tags")))
    return out


def _rss_items(xml_text):
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    for item in root.iter("item"):
        d = {}
        for ch in item:
            tag = ch.tag.split("}")[-1]
            d[tag] = (ch.text or "").strip() if ch.text else ch.attrib.get("url", "")
        yield d


def wwr_rss(board, cfg, log):
    out = []
    for feed in board["feeds"]:
        r = get(feed)
        r.raise_for_status()
        for it in _rss_items(r.text):
            title = it.get("title", "")
            company, _, role = title.partition(": ")
            if not role:
                company, role = "", title
            desc = strip_html(it.get("description"))
            countries = [ascii_clean(c).strip() for c in re.split(r",| and ", it.get("country", "")) if c.strip()]
            loc = it.get("region", "")
            hq = re.search(r"Headquarters:\s*([^\n]+)", desc)
            out.append(_job(board, url=it.get("link") or it.get("guid"), apply_url=it.get("link"),
                            title=role, company=company, location=loc + (f" (HQ: {hq.group(1).strip()})" if hq else ""),
                            countries=countries or None, description=desc,
                            posted_at=_iso(it.get("pubDate")), employment_type=it.get("type")))
        time.sleep(1)
    return out


def rss(board, cfg, log):
    out = []
    for feed in board["feeds"]:
        r = get(feed)
        r.raise_for_status()
        for it in _rss_items(r.text):
            title = it.get("title", "")
            company = it.get("company") or it.get("creator") or ""
            if not company and " at " in title:
                title, company = title.rsplit(" at ", 1)
            out.append(_job(board, url=it.get("link") or it.get("guid"), apply_url=it.get("link"),
                            title=title, company=company, location=it.get("location") or it.get("region") or "",
                            description=strip_html(it.get("description") or it.get("encoded")),
                            posted_at=_iso(it.get("pubDate"))))
    return out


def workingnomads(board, cfg, log):
    r = get("https://www.workingnomads.com/api/exposed_jobs/")
    r.raise_for_status()
    return [_job(board, url=it["url"], apply_url=it["url"], title=it["title"], company=it.get("company_name"),
                 location=it.get("location") or "", description=strip_html(it.get("description")),
                 posted_at=_iso(it.get("pub_date")), tags=it.get("tags"))
            for it in r.json()]


def arbeitnow(board, cfg, log):
    out = []
    for page in range(1, board.get("pages", 3) + 1):
        params = {"page": page}
        if board.get("visa_sponsorship"):
            params["visa_sponsorship"] = "true"
        r = get("https://www.arbeitnow.com/api/job-board-api", params=params)
        r.raise_for_status()
        for it in r.json().get("data", []):
            out.append(_job(board, url=it["url"], apply_url=it["url"], title=it["title"],
                            company=it.get("company_name"),
                            location=("Remote, " if it.get("remote") else "") + (it.get("location") or ""),
                            description=strip_html(it.get("description")), posted_at=_iso(it.get("created_at")),
                            employment_type=", ".join(it.get("job_types") or []),
                            visa=bool(it.get("visa_sponsorship"))))
        time.sleep(1)
    return out


def jobicy(board, cfg, log):
    out = []
    for tag in board.get("tags", ["dev", "design", "support"]):
        r = get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "tag": tag})
        if r.status_code != 200:
            continue
        for it in r.json().get("jobs", []):
            sal = ""
            if it.get("annualSalaryMin"):
                sal = f'{it.get("salaryCurrency", "")} {it["annualSalaryMin"]}-{it.get("annualSalaryMax", "")} year'
            out.append(_job(board, url=it["url"], apply_url=it["url"], title=it["jobTitle"],
                            company=it.get("companyName"), location=it.get("jobGeo") or "",
                            description=strip_html(it.get("jobDescription")), posted_at=_iso(it.get("pubDate")),
                            salary=sal, employment_type=", ".join(it.get("jobType") or [])
                            if isinstance(it.get("jobType"), list) else it.get("jobType")))
        time.sleep(1)
    return out


# ------------------------------------------------- company ATS feeds
def greenhouse(board, cfg, log):
    out = []
    for slug in board["companies"]:
        data = None
        for host in ("boards-api.greenhouse.io", "boards-api.eu.greenhouse.io"):
            try:
                r = get(f"https://{host}/v1/boards/{slug}/jobs", params={"content": "true"})
            except Exception:
                continue
            if r.status_code == 200:
                data = r.json()
                break
        if not data:
            log(f"  greenhouse/{slug}: not found")
            continue
        for it in data.get("jobs", []):
            out.append(_job(board, url=it["absolute_url"], apply_url=it["absolute_url"], title=it["title"],
                            company=data.get("name") or it.get("company_name") or slug,
                            location=(it.get("location") or {}).get("name", ""),
                            description=strip_html(html.unescape(it.get("content") or "")),
                            posted_at=_iso(it.get("first_published") or it.get("updated_at"))))
    return out


def lever(board, cfg, log):
    out = []
    for slug in board["companies"]:
        for host in ("api.lever.co", "api.eu.lever.co"):
            r = get(f"https://{host}/v0/postings/{slug}", params={"mode": "json"})
            if r.status_code == 200 and isinstance(r.json(), list):
                for it in r.json():
                    cat = it.get("categories") or {}
                    out.append(_job(board, url=it["hostedUrl"], apply_url=it.get("applyUrl") or it["hostedUrl"],
                                    title=it["text"], company=slug,
                                    location=f'{cat.get("location", "")} {it.get("workplaceType", "")}'.strip(),
                                    description=it.get("descriptionPlain") or strip_html(it.get("description")),
                                    posted_at=_iso(it.get("createdAt")), employment_type=cat.get("commitment")))
                break
    return out


def ashby(board, cfg, log):
    out = []
    for slug in board["companies"]:
        r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"})
        if r.status_code != 200:
            log(f"  ashby/{slug}: HTTP {r.status_code}")
            continue
        for it in r.json().get("jobs", []):
            loc = it.get("location") or ""
            if it.get("isRemote"):
                loc = f"Remote {loc}".strip()
            out.append(_job(board, url=it["jobUrl"], apply_url=it.get("applyUrl") or it["jobUrl"],
                            title=it["title"], company=slug, location=loc,
                            description=it.get("descriptionPlain") or strip_html(it.get("descriptionHtml")),
                            posted_at=_iso(it.get("publishedAt")), employment_type=it.get("employmentType")))
    return out


def workable(board, cfg, log):
    out = []
    for slug in board["companies"]:
        r = get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", params={"details": "true"})
        if r.status_code != 200:
            log(f"  workable/{slug}: HTTP {r.status_code}")
            continue
        data = r.json()
        for it in data.get("jobs", []):
            locs = it.get("locations") or [{"country": it.get("country"), "city": it.get("city")}]
            loc = "; ".join(", ".join(x for x in (l.get("city"), l.get("country")) if x) for l in locs)
            if it.get("telecommuting"):
                loc = f"Remote ({loc})" if loc else "Remote"
            out.append(_job(board, url=it.get("url") or it.get("shortlink"),
                            apply_url=it.get("application_url") or it.get("url"),
                            title=it["title"], company=data.get("name") or slug, location=loc,
                            countries=[l.get("country") for l in locs if l.get("country")] or None,
                            description=strip_html(it.get("description")),
                            posted_at=_iso(it.get("published_on") or it.get("created_at")),
                            employment_type=it.get("employment_type")))
    return out


# --------------------------------------------------- LinkedIn (public)
def linkedin(board, cfg, log):
    """Logged-out public job search. Uses no account, so it cannot get your
    LinkedIn restricted. Kept slow on purpose."""
    out, seen = [], set()
    tpr = board.get("posted_within", "r86400")
    for loc in board.get("locations", ["South Africa"]):
        for q in search_terms(board, cfg):
            for start in range(0, 25 * board.get("pages", 1), 25):
                params = {"keywords": q, "location": loc, "f_WT": "2", "f_TPR": tpr,
                          "sortBy": "DD", "start": start}
                r = get("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search", params=params)
                if r.status_code != 200 or not r.text.strip():
                    break
                cards = re.findall(r'<li>(.*?)</li>', r.text, re.S)
                for c in cards:
                    m = re.search(r'href="(https://[a-z]+\.linkedin\.com/jobs/view/[^"?]+)', c)
                    if not m:
                        continue
                    url = m.group(1)
                    jid = re.search(r"(\d{6,})", url)
                    if not jid or jid.group(1) in seen:
                        continue
                    seen.add(jid.group(1))
                    t = re.search(r'base-search-card__title[^>]*>\s*(.*?)\s*<', c, re.S)
                    co = re.search(r'base-search-card__subtitle[^>]*>\s*(?:<a[^>]*>)?\s*([^<]*\S)\s*<', c, re.S)
                    lo = re.search(r'job-search-card__location[^>]*>\s*(.*?)\s*<', c, re.S)
                    dt = re.search(r'datetime="([^"]+)"', c)
                    out.append(_job(board, url=url, apply_url=url, title=t.group(1) if t else "",
                                    company=co.group(1) if co else "", location=lo.group(1) if lo else loc,
                                    posted_at=dt.group(1) if dt else None, linkedin_id=jid.group(1)))
                time.sleep(board.get("delay_s", 4))
    return out


def linkedin_detail(job):
    """Fetch the public description for one LinkedIn job (called only for kept jobs)."""
    jid = job.get("linkedin_id") or (re.search(r"(\d{6,})", job.get("url", "")) or [None, None])[1]
    if not jid:
        return job
    r = get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}")
    if r.status_code == 200:
        m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', r.text, re.S)
        if m:
            job["description"] = strip_html(m.group(1))
        ext = re.search(r'href="(https?://[^"]+)"[^>]*apply-button', r.text) or \
            re.search(r'<code id="applyUrl"[^>]*><!--"(.*?)"--></code>', r.text)
        if ext:
            u = html.unescape(ext.group(1))
            q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("url")
            job["apply_url"] = q[0] if q else u
    return job


# ------------------------------------------------------------ Reddit
def reddit(board, cfg, log):
    out = []
    for sub in board["subreddits"]:
        r = get(f"https://www.reddit.com/r/{sub}/new/.rss", headers={"User-Agent": "job-engine/1.0 (personal job search)"})
        if r.status_code != 200:
            log(f"  reddit/{sub}: HTTP {r.status_code}")
            continue
        root = ET.fromstring(r.content)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for e in root.findall("a:entry", ns):
            t = (e.findtext("a:title", "", ns) or "")
            if not re.search(board.get("title_must", r"\[?hiring\]?"), t, re.I):
                continue
            link = e.find("a:link", ns)
            out.append(_job(board, url=link.get("href") if link is not None else "", apply_url=None,
                            title=re.sub(r"\[[^\]]*\]", "", t).strip(), company=f"r/{sub} poster",
                            location="see post", description=strip_html(e.findtext("a:content", "", ns))[:8000],
                            posted_at=(e.findtext("a:updated", "", ns) or "")[:10]))
        time.sleep(2)
    return out


def companies(board, cfg, log):
    """Every company in companies_to_watch: find its job feed once (cached), then read all roles."""
    import ats_discover
    groups = {"greenhouse": [], "lever": [], "ashby": [], "workable": []}
    out = []
    for name in cfg.get("companies_to_watch", []):
        info = ats_discover.resolve(name, log=log)
        kind = info.get("kind")
        if not kind:
            continue
        if kind in groups:
            groups[kind].append((name, info["slug"]))
        else:
            for j in ats_discover.fetch(kind, info["slug"], name) or []:
                out.append(_job(board, apply_url=j["url"], **j))
    for kind, items in groups.items():
        if not items:
            continue
        sub = dict(board, companies=[s for _, s in items])
        names = {s: n for n, s in items}
        try:
            for j in ADAPTERS[kind](sub, cfg, log):
                slug = next((s for s in names if s in (j.get("url") or "").lower()), None)
                if slug and (not j.get("company") or j["company"].lower() == slug):
                    j["company"] = names[slug]
                out.append(j)
        except Exception as e:
            log(f"  {kind} feeds failed: {e}")
    return out


def nocodejobs(board, cfg, log):
    """nocodejobs.org publishes its whole board as JSON (/jobs.json) - no browser needed."""
    r = get(board.get("feed", "https://nocodejobs.org/jobs.json"))
    r.raise_for_status()
    d = r.json()
    out = []
    for it in (d.get("jobs") if isinstance(d, dict) else d) or []:
        url = it.get("url") or it.get("applyUrl") or f"https://nocodejobs.org/jobs/{it.get('slug', '')}"
        sal = it.get("compensation") or ""
        out.append(_job(board, url=url, apply_url=it.get("applyUrl") or url, title=it.get("title"),
                        company=it.get("company"), location=it.get("location") or it.get("workplaceType") or "Remote",
                        description=strip_html(it.get("description") or ""), salary=sal,
                        employment_type=(it.get("employmentType") or "").replace("_", " ").title(),
                        posted_at=_iso(it.get("datePosted") or it.get("publishedAt") or it.get("createdAt"))))
    return out


def landingjobs(board, cfg, log):
    """landing.jobs public API (EU tech roles, many with relocation / visa support)."""
    out, offset, limit = [], 0, 50
    for _ in range(board.get("pages", 6)):
        r = get("https://landing.jobs/api/v1/jobs", params={"limit": limit, "offset": offset})
        r.raise_for_status()
        rows = r.json() or []
        for it in rows:
            locs = it.get("locations") or []
            if isinstance(locs, str):
                locs = []
            where = ", ".join(f"{l.get('city', '')} {l.get('country_code', '')}".strip() for l in locs if isinstance(l, dict))
            remote = str(it.get("remote")).lower() == "true"
            sal = ""
            if it.get("gross_salary_low"):
                sal = f"{it.get('currency_code', 'EUR')} {it['gross_salary_low']}-{it.get('gross_salary_high') or ''}/yr"
            desc = " ".join(strip_html(it.get(k) or "") for k in ("role_description", "main_requirements", "nice_to_have", "perks"))
            if str(it.get("relocation_paid")).lower() == "true":
                desc += " Relocation paid."
            out.append(_job(board, url=it.get("url"), apply_url=it.get("url"), title=it.get("title"),
                            company=(it.get("url") or "").split("/at/")[-1].split("/")[0].replace("-", " ").title(),
                            location=("Remote, " if remote else "") + where, description=desc, salary=sal,
                            employment_type=it.get("type") or "", posted_at=_iso(it.get("published_at"))))
        if len(rows) < limit:
            break
        offset += limit
        time.sleep(1)
    return out


ADAPTERS = {
    "companies": companies,
    "himalayas": himalayas, "remotive": remotive, "remoteok": remoteok, "wwr_rss": wwr_rss,
    "rss": rss, "workingnomads": workingnomads, "arbeitnow": arbeitnow, "jobicy": jobicy,
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workable": workable,
    "linkedin": linkedin, "reddit": reddit, "nocodejobs": nocodejobs, "landingjobs": landingjobs,
    "email_alerts": lambda b, c, l: __import__("email_alerts").fetch(b, c, l),
}
