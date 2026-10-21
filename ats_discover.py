"""Find which hiring system (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee)
a company posts its jobs on, so the engine can read them straight from the source.

Used by the "companies" board: you list company names in config.json -> companies_to_watch,
the engine works out each one's job feed once, caches it in data/ats_cache.json, and
reads every role from there on each scan.
"""
import json, re, time
from util import DATA, get, strip_html, ascii_clean

CACHE = DATA / "ats_cache.json"


def _load():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(c):
    CACHE.write_text(json.dumps(c, indent=1), encoding="utf-8")


def slugs(name):
    base = re.sub(r"\(.*?\)", "", name).strip()
    base = re.sub(r"\b(inc|llc|ltd|group|technologies|technology|software|solutions|hq|\.com|\.io|\.tech)\b\.?", "",
                  base, flags=re.I).strip()
    words = re.findall(r"[a-z0-9]+", base.lower())
    if not words:
        return []
    full = re.findall(r"[a-z0-9]+", re.sub(r"\(.*?\)", "", name).lower())
    out = ["".join(words), "-".join(words)] + (["".join(full), "-".join(full)] if full and full != words else [])
    out += [s + "hq" for s in out[:1]] + [s + "careers" for s in out[:1]]
    return list(dict.fromkeys(out))


def _try(kind, slug):
    try:
        if kind == "greenhouse":
            r = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=15)
            return len(r.json().get("jobs", [])) if r.status_code == 200 else None
        if kind == "lever":
            r = get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, timeout=15)
            if r.status_code == 200 and isinstance(r.json(), list):
                return len(r.json())
            r = get(f"https://api.eu.lever.co/v0/postings/{slug}", params={"mode": "json"}, timeout=15)
            return len(r.json()) if r.status_code == 200 and isinstance(r.json(), list) else None
        if kind == "ashby":
            r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=15)
            return len(r.json().get("jobs", [])) if r.status_code == 200 else None
        if kind == "workable":
            r = get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", timeout=15)
            return len(r.json().get("jobs", [])) if r.status_code == 200 else None
        if kind == "smartrecruiters":
            r = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 1}, timeout=15)
            n = r.json().get("totalFound") if r.status_code == 200 else None
            return n if n else None
        if kind == "recruitee":
            r = get(f"https://{slug}.recruitee.com/api/offers/", timeout=15)
            return len(r.json().get("offers", [])) if r.status_code == 200 else None
    except Exception:
        return None
    return None


KINDS = ["greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee"]


def resolve(name, log=print, force=False):
    cache = _load()
    if name in cache and not force and (cache[name].get("kind") or cache[name].get("v") == 2):
        return cache[name]  # "not found" results from before the wider name variants are re-checked once
    found = None
    for slug in slugs(name):
        for kind in KINDS:
            n = _try(kind, slug)
            if n:
                found = {"kind": kind, "slug": slug, "jobs": n}
                break
        if found:
            break
        time.sleep(0.3)
    cache[name] = found or {"kind": None, "checked": time.strftime("%Y-%m-%d"), "v": 2}
    _save(cache)
    log(f"  {name}: " + (f"{found['kind']}/{found['slug']} ({found['jobs']} open)" if found else "no public job feed found"))
    return cache[name]


def fetch(kind, slug, company):
    """All postings for one company feed, in the engine's job format."""
    out = []
    if kind == "smartrecruiters":
        offset = 0
        while offset < 400:
            r = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 100, "offset": offset})
            if r.status_code != 200:
                break
            items = r.json().get("content", [])
            for it in items:
                loc = it.get("location") or {}
                out.append({"url": f"https://jobs.smartrecruiters.com/{slug}/{it['id']}", "title": it["name"],
                            "company": company, "location": ("Remote " if loc.get("remote") else "") +
                            ", ".join(x for x in (loc.get("city"), loc.get("country")) if x),
                            "posted_at": (it.get("releasedDate") or "")[:10], "description": ""})
            if len(items) < 100:
                break
            offset += 100
        return out
    if kind == "recruitee":
        r = get(f"https://{slug}.recruitee.com/api/offers/")
        for it in r.json().get("offers", []) if r.status_code == 200 else []:
            out.append({"url": it.get("careers_url"), "title": it["title"], "company": company,
                        "location": ("Remote " if it.get("remote") else "") + (it.get("location") or ""),
                        "description": strip_html(it.get("description")), "posted_at": (it.get("published_at") or "")[:10]})
        return out
    return None  # greenhouse/lever/ashby/workable use the existing adapters in boards.py
