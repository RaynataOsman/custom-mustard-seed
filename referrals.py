"""Find the people behind a job: recruiter, likely hiring manager, a teammate.

How: public web search (your own SearXNG first, DuckDuckGo as backup) for
LinkedIn profile pages that mention the company - the same "X-ray" trick
recruiters use. Nothing logs in to LinkedIn and nothing is sent: the engine
drafts the connection note, you tap "Copy + open profile" and press Send
yourself. LinkedIn restricts accounts that automate messages, so sending stays
with you on purpose.
"""
import html, random, re, time, urllib.parse
from util import get, load_config, ascii_clean

KIND_RE = [
    ("recruiter", re.compile(r"recruit|talent acquisition|talent partner|sourcer|sourcing|people partner|people ops|\bhr\b|human resources", re.I)),
    ("hiring_manager", re.compile(r"head of|manager|lead\b|director|cto|ceo|founder|co-founder|vp\b|chief|owner", re.I)),
]

MANAGER_TITLES = {
    "dev": '("engineering manager" OR "head of engineering" OR CTO OR "tech lead" OR founder)',
    "design": '("head of design" OR "design lead" OR "design manager" OR "creative director" OR founder)',
    "admin": '("operations manager" OR "head of operations" OR "customer success manager" OR "head of support" OR founder)',
    "ecommerce": '("head of e-commerce" OR "e-commerce manager" OR "ecommerce manager" OR founder)',
    "ai": '("AI engineering manager" OR "head of AI" OR CTO OR founder)',
    "cse": '("head of customer success" OR "solutions engineering manager" OR "VP customer success")',
}


_SEARX_DOWN_UNTIL = [0.0]


def _searx(q, cfg):
    """SearXNG search. If it isn't running (Docker off) we find out once and skip it for 10 minutes,
    instead of paying util.get's 3 retries (~18 s) on every referral lookup."""
    import time as _t
    from util import http
    base = (cfg["referrals"].get("searxng_url") or "").replace("//localhost", "//127.0.0.1") or None
    if not base or _t.time() < _SEARX_DOWN_UNTIL[0]:
        return None
    try:
        r = http().get(base.rstrip("/") + "/search", params={"q": q, "format": "json", "language": "en"}, timeout=25)
        if r.status_code == 200:
            return [{"url": x.get("url", ""), "title": x.get("title", ""), "snippet": x.get("content", "")}
                    for x in r.json().get("results", [])]
    except Exception as e:
        if "refused" in str(e).lower() or "max retries" in str(e).lower() or "failed to establish" in str(e).lower():
            _SEARX_DOWN_UNTIL[0] = _t.time() + 600
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


_CAPTCHA_PAGE = re.compile(r"unusual traffic|are you a robot|not a robot|captcha|verify you are human|"
                           r"anomaly|bots use duckduckgo|select all (images|squares)|challenge", re.I)
_COOL = {}           # engine -> time it may be used again
_LAST = {"t": 0.0}   # last browser search


def _gap(cfg):
    lo, hi = (cfg.get("referrals", {}).get("browser_gap_s") or [25, 50])
    wait = _LAST["t"] + random.uniform(lo, hi) - time.time()
    if wait > 0:
        time.sleep(wait)
    _LAST["t"] = time.time()


def _browser_search(q, cfg=None):
    """Search like a person in a real Chrome window: DuckDuckGo, then Yahoo. Spaced 25-50 s apart.
    A CAPTCHA page rests that engine (3, 6, 12... up to 30 min) instead of skipping the query; the
    query is tried on the other engine, and waits for a rested engine when both are cooling down."""
    cfg = cfg or load_config()
    page = _browser_page()
    engines = [("duckduckgo", "https://duckduckgo.com/?" + urllib.parse.urlencode({"q": q, "ia": "web"})),
               ("yahoo", "https://search.yahoo.com/search?" + urllib.parse.urlencode({"p": q.replace('"', "")}))]
    for attempt in range(2):
        for name, url in engines:
            c = _COOL.get(name)
            if c and time.time() < c["until"]:
                continue
            _gap(cfg)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(random.randint(2500, 4500))
                txt = (page.title() + " " + page.inner_text("body")[:1500])
            except Exception:
                continue
            if _CAPTCHA_PAGE.search(txt) or re.search(r"/sorry/|captcha", page.url, re.I):
                n = (c or {}).get("n", 0) + 1
                rest = min(1800, 180 * 2 ** (n - 1))
                _COOL[name] = {"until": time.time() + rest, "n": n}
                print(f"    {name} showed a CAPTCHA - resting it for {rest // 60} min and trying another way")
                continue
            if c:
                _COOL[name]["n"] = max(0, c["n"] - 1)
            try:
                out = page.evaluate(_JS_COLLECT)
            except Exception:
                out = []
            return out
        # every engine is cooling down: wait for the first one to be ready (bounded), then try again
        soonest = min((c["until"] for c in _COOL.values()), default=time.time())
        wait = soonest - time.time()
        if attempt == 0 and 0 < wait <= 900:
            print(f"    all search engines are resting - waiting {int(wait // 60) + 1} min")
            time.sleep(wait + 5)
        else:
            break
    return []


def search(q, cfg):
    res = _searx(q, cfg)
    if res:
        time.sleep(random.uniform(2, 5))   # gentle on SearXNG's upstream engines too
        return res
    return _browser_search(q, cfg)


def _company_core(company):
    """'OneDayOnly.co.za' -> 'OneDayOnly'. A job board's own name (remote.co, jobbank.gc.ca) -> '' (unknown employer)."""
    try:
        from safeguards import board_hosts, norm_company
        n = norm_company(company)
        if not n or n in board_hosts() or re.fullmatch(r"(www\.)?[a-z0-9-]+\.(co|com|io|org|net)(\.[a-z]{2})?", (company or "").strip().lower()) and n in ("remote", "jobs", "careers"):
            return ""
    except Exception:
        pass
    c = re.sub(r"^(https?://)?(www\.)?", "", (company or "").strip(), flags=re.I)
    c = re.sub(r"\.(com|io|ai|co|net|org|app|dev|tech|jobs)(\.[a-z]{2})?$|\.[a-z]{2}$", "", c, flags=re.I)
    c = re.sub(r"\(.*?\)", "", c)
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


def find(company, role_title, family, log=print, exclude=frozenset()):
    """exclude: normalised profile URLs already lined up for another of your roles - each person gets
    one note from you, not one per role (Settings > Safeguards > referral dedup)."""
    from safeguards import norm_profile_url
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
    seen, people, skipped = set(), [], set()
    for q in queries:
        for res in search(q, cfg) or []:
            p = _parse_profile(res, core)
            if p and norm_profile_url(p["url"]) in exclude:
                skipped.add(p["url"])
                continue
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
    log(f"  referrals for {company}: {len(picked)} found ({', '.join(p['kind'] for p in picked) or 'none'})"
        + (f", {len(skipped)} skipped - already lined up for another of your roles" if skipped else ""))
    return picked


HOOKS = {
    "dev": "I build Shopify and React/Next.js e-commerce sites",
    "design": "I design Figma e-commerce and landing page experiences and can build them too",
    "admin": "I handle e-commerce admin, customer support and client operations",
    "ecommerce": "I run and build Shopify stores",
    "ai": "I build AI automations and Shopify / React / Next.js sites",
    "cse": "I connect APIs and CRMs and get customers live",
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
