"""Find the people behind a job: recruiter, likely hiring manager, a teammate.

How: public web search (your own SearXNG first, DuckDuckGo as backup) for
LinkedIn profile pages that mention the company - the same "X-ray" trick
recruiters use. Nothing logs in to LinkedIn and nothing is sent: the engine
drafts the connection note, you tap "Copy + open profile" and press Send
yourself. LinkedIn restricts accounts that automate messages, so sending stays
with you on purpose.
"""
import html, re, time, urllib.parse
from util import get, load_config, ascii_clean

KIND_RE = [
    ("recruiter", re.compile(r"recruit|talent acquisition|talent partner|sourcer|sourcing|people partner|people ops|\bhr\b|human resources", re.I)),
    ("hiring_manager", re.compile(r"head of|manager|lead\b|director|cto|ceo|founder|co-founder|vp\b|chief|owner", re.I)),
]

MANAGER_TITLES = {
    "dev": '("engineering manager" OR "head of engineering" OR CTO OR "tech lead" OR founder)',
    "design": '("head of design" OR "design lead" OR "design manager" OR "creative director" OR founder)',
    "admin": '("operations manager" OR "head of operations" OR "customer success manager" OR "head of support" OR founder)',
}


def _searx(q, cfg):
    base = cfg["referrals"].get("searxng_url")
    if not base:
        return None
    try:
        r = get(base.rstrip("/") + "/search", params={"q": q, "format": "json", "language": "en"}, timeout=25)
        if r.status_code == 200:
            return [{"url": x.get("url", ""), "title": x.get("title", ""), "snippet": x.get("content", "")}
                    for x in r.json().get("results", [])]
    except Exception:
        return None
    return None


def _ddg(q):
    try:
        r = get("https://html.duckduckgo.com/html/", params={"q": q}, timeout=25)
    except Exception:
        return []
    out = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
                         r.text, re.S):
        u = html.unescape(m.group(1))
        q2 = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("uddg")
        out.append({"url": q2[0] if q2 else u, "title": re.sub("<[^>]+>", "", html.unescape(m.group(2))),
                    "snippet": re.sub("<[^>]+>", "", html.unescape(m.group(3)))})
    return out


_BROWSER = {}


def _browser_page():
    """One real Chrome (engine profile) reused for all searches in this run."""
    if "page" not in _BROWSER:
        from playwright.sync_api import sync_playwright
        import render
        pw = sync_playwright().start()
        ctx = render.launch(pw, headless=False, profile=render.PROFILE.parent / "search-profile")
        try:
            ctx.pages[0].evaluate("() => { window.moveTo(0, 0); }")
        except Exception:
            pass
        _BROWSER.update(pw=pw, ctx=ctx, page=ctx.new_page())
    return _BROWSER["page"]


def close_browser():
    if "ctx" in _BROWSER:
        try:
            _BROWSER["ctx"].close()
            _BROWSER["pw"].stop()
        except Exception:
            pass
        _BROWSER.clear()


_JS_COLLECT = """() => {
  const seen = new Set(), out = [];
  for (const a of document.querySelectorAll('a[href*="linkedin.com/in/"]')) {
    const u = a.href.split('?')[0];
    if (seen.has(u)) continue; seen.add(u);
    const box = a.closest('article, li, div.algo, div[data-testid="result"], .dd') || a.parentElement;
    const h = box ? box.querySelector('h2, h3') : null;
    out.push({url: u, title: (h ? h.innerText : a.innerText) || '', snippet: box ? box.innerText.slice(0, 400) : ''});
  }
  return out; }"""


def _browser_search(q):
    """Search like a person would, in a real Chrome window: DuckDuckGo, then Yahoo."""
    page = _browser_page()
    out = []
    for url in ("https://duckduckgo.com/?" + urllib.parse.urlencode({"q": q, "ia": "web"}),
                "https://search.yahoo.com/search?" + urllib.parse.urlencode({"p": q.replace('"', "")})):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            out = page.evaluate(_JS_COLLECT)
        except Exception:
            out = []
        if out:
            break
    time.sleep(2)
    return out


def search(q, cfg):
    res = _searx(q, cfg)
    if res:
        return res
    return _browser_search(q)


def _company_core(company):
    c = re.sub(r"\(.*?\)", "", company or "")
    c = re.sub(r"\b(inc|llc|ltd|gmbh|pty|limited|corp|co|group|ab|bv|sa|plc)\b\.?", "", c, flags=re.I)
    return c.strip(" ,.-")


def _parse_profile(res, company):
    url = res["url"]
    if "linkedin.com/in/" not in url:
        return None
    url = re.sub(r"\?.*$", "", url)
    url = re.sub(r"https?://[a-z]{2,3}\.linkedin", "https://www.linkedin", url)
    title = ascii_clean(res["title"]).replace("| LinkedIn", "").replace("- LinkedIn", "").strip()
    parts = [p.strip() for p in re.split(r"\s[-|]\s", title) if p.strip()]
    if not parts:
        return None
    name = re.sub(r"^(dr|mr|mrs|ms|prof)\.?\s+", "", parts[0], flags=re.I).strip()
    headline = " - ".join(parts[1:])
    snippet = ascii_clean(res.get("snippet", ""))
    core = _company_core(company).lower()
    cre = re.compile(r"(?<![a-z0-9])" + re.escape(core) + r"(?![a-z0-9])", re.I)
    # the company must appear outside the person's name (avoids "Jami Swanky" for Swanky)
    rest = (headline + " " + snippet.replace(parts[0], " ")).lower()
    if not core or not cre.search(rest):
        return None
    # skip people who LEFT the company
    if re.search(r"(former|ex-|ex |previously|past:?)\s*(\w+\s+){0,4}(at\s+)?" + re.escape(core), rest, re.I) \
            and not re.search(r"(at|@)\s+" + re.escape(core), headline, re.I):
        return None
    score = 0
    if cre.search(headline):
        score += 3
    if re.search(r"(at|@|\|)\s*" + re.escape(core), rest, re.I):
        score += 2
    if re.search(r"experience:\s*" + re.escape(core), rest, re.I):
        score += 2
    kind = "team"
    for k, rx in KIND_RE:
        if rx.search(headline) or (not headline and rx.search(snippet[:120])):
            kind = k
            break
    if len(name.split()) > 5 or len(name) < 3 or re.search(r"jobs|hiring|careers", name, re.I):
        return None
    return {"name": name, "headline": headline[:160], "url": url, "kind": kind, "score": score}


def find(company, role_title, family, log=print):
    cfg = load_config()
    core = _company_core(company)
    if not core or core.lower().startswith("r/"):
        return []
    role_kw = re.sub(r"\b(senior|junior|mid|level|remote|sr|jr|ii|iii)\b", "", role_title, flags=re.I).strip()
    queries = [
        f'site:linkedin.com/in "{core}" (recruiter OR "talent acquisition" OR "people partner" OR "HR manager")',
        f'site:linkedin.com/in "{core}" {MANAGER_TITLES.get(family, MANAGER_TITLES["dev"])}',
        f'site:linkedin.com/in "{core}" "{role_kw[:40]}"',
    ]
    seen, people = set(), []
    for q in queries:
        for res in search(q, cfg) or []:
            p = _parse_profile(res, core)
            if p and p["url"] not in seen:
                seen.add(p["url"])
                people.append(p)
        time.sleep(1.5)
    order = {"recruiter": 0, "hiring_manager": 1, "team": 2}
    people.sort(key=lambda p: (-p["score"], order[p["kind"]]))
    people = [p for p in people if p["score"] >= 2] or [p for p in people if p["score"] >= 1]
    # keep a spread: up to 2 recruiters, 1-2 managers, 1 teammate
    picked, counts = [], {"recruiter": 0, "hiring_manager": 0, "team": 0}
    caps = {"recruiter": 2, "hiring_manager": 2, "team": 1}
    for p in people:
        if counts[p["kind"]] < caps[p["kind"]]:
            picked.append(p)
            counts[p["kind"]] += 1
        if len(picked) >= cfg["referrals"]["max_per_job"]:
            break
    for i, p in enumerate(picked):
        p["rank"] = i + 1
        p["note"], p["followup"] = draft_notes(p, company, role_title, family, cfg)
    if not picked and len(core) > 2:
        log(f"  referrals for {company}: nothing on LinkedIn search for this company name")
    log(f"  referrals for {company}: {len(picked)} found ({', '.join(p['kind'] for p in picked) or 'none'})")
    return picked


HOOKS = {
    "dev": "I build Shopify and React/Next.js e-commerce sites",
    "design": "I design Figma e-commerce and landing page experiences and can build them too",
    "admin": "I handle e-commerce admin, customer support and client operations",
}


def draft_notes(p, company, role, family, cfg):
    first = p["name"].split()[0].title()
    me = cfg["profile"]
    hook = cfg["referrals"].get("hooks", {}).get(family) or HOOKS.get(family, HOOKS["dev"])
    role = ascii_clean(role)
    if p["kind"] == "recruiter":
        note = (f"Hi {first}, I just applied for the {role} role at {company}. {hook}, working remotely from "
                f"Cape Town (UTC+2). Glad to send anything that helps your review. Thanks, {me['first_name']}")
    elif p["kind"] == "hiring_manager":
        note = (f"Hi {first}, I applied for {role} at {company}. {hook}. If useful I can walk you through a "
                f"relevant project in 15 minutes. Thanks, {me['first_name']}")
    else:
        note = (f"Hi {first}, I've applied for {role} at {company} and saw you're on the team. Would you be open "
                f"to a quick word on what the team values? Thanks, {me['first_name']}")
    limit = cfg["referrals"].get("note_max_chars", 280)
    if len(note) > limit:
        note = note[: limit - 3].rsplit(" ", 1)[0] + "..."
    follow = (f"Thanks for connecting, {first}. I applied for {role} on {_today()}. My resume is attached to the "
              f"application, and my portfolio is {me['portfolio']}. If my background fits, would you be open to "
              f"referring me or pointing me to the right person? Either way, thanks for your time.")
    return ascii_clean(note), ascii_clean(follow)


def _today():
    import datetime
    return datetime.date.today().strftime("%d %b")
