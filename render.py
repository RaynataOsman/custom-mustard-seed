"""Playwright 'render and harvest' for JavaScript-heavy boards.

This is the part career-ops was missing. Instead of hand-writing a scraper per
site, it:
  1. opens the board in a real Chrome (your installed Chrome, separate profile),
  2. scrolls so lazy lists load,
  3. collects every link that looks like a job posting,
  4. keeps the ones whose title matches your role keywords,
  5. opens each kept posting and reads it - preferring the schema.org
     JobPosting data most boards embed for Google, and falling back to page text.

The browser profile lives in data/browser-profile. Use "Open login browser" in
the dashboard once to sign in to boards that need it (Wellfound, WWR, LinkedIn);
the engine reuses those sign-ins and never types a password itself.
"""
import json, os, re, sys, time, urllib.parse
from util import DATA, ascii_clean, strip_html

PROFILE = DATA / "real-chrome"
DEFAULT_LINK_RE = (r"/(job|jobs|remote-jobs|job-listing|vacanc|position|careers?/|opening|"
                   r"listing|posting|o/|j/|view/)")
_JUNK_TEXT = re.compile(r"^(apply|view|see|read|more|next|prev|login|sign|post a job|jobs?|remote jobs?)\b", re.I)


CHROME_PATHS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")]


class RealChrome:
    """Your installed Chrome, started normally (not as an automated browser) and steered over its
    debugging port. Sites like Indeed treat it as a normal visitor. Uses its own profile folder,
    so your personal Chrome, logins and history are never touched."""

    def __init__(self, p, profile, minimized=True):
        import socket, subprocess
        exe = next((c for c in CHROME_PATHS if os.path.exists(c)), None)
        if not exe:
            raise FileNotFoundError("Chrome not installed")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        args = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "--no-first-run",
                "--no-default-browser-check", "--window-size=1366,900"]
        if minimized:
            args.append("--start-minimized")
        self.proc = subprocess.Popen(args + ["about:blank"])
        last = None
        for _ in range(30):
            time.sleep(0.5)
            try:
                self.browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                break
            except Exception as e:
                last = e
        else:
            self.proc.terminate()
            raise RuntimeError(f"could not attach to Chrome: {last}")
        self.ctx = self.browser.contexts[0]

    def __getattr__(self, k):
        return getattr(self.ctx, k)

    def close(self):
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass


def launch(p, headless=True, profile=None):
    """Prefers your real Chrome (passes bot checks); falls back to Playwright's browser."""
    from util import load_config
    profile = profile or PROFILE
    profile.mkdir(parents=True, exist_ok=True)
    if load_config()["search"].get("browser_mode", "real_chrome") == "real_chrome" and sys.platform == "win32":
        try:
            return RealChrome(p, str(profile), minimized=headless)
        except Exception:
            pass
    args = ["--disable-blink-features=AutomationControlled"]
    try:
        return p.chromium.launch_persistent_context(str(profile), channel="chrome", headless=headless,
                                                    args=args, viewport={"width": 1366, "height": 900})
    except Exception:
        return p.chromium.launch_persistent_context(str(profile), headless=headless, args=args,
                                                    viewport={"width": 1366, "height": 900})


def _jsonld_jobs(page):
    out = []
    try:
        blobs = page.eval_on_selector_all('script[type="application/ld+json"]', "els => els.map(e => e.textContent)")
    except Exception:
        return out
    for b in blobs:
        try:
            data = json.loads(b)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                if "@graph" in d:
                    stack.extend(d["@graph"])
                t = d.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    out.append(d)
            elif isinstance(d, list):
                stack.extend(d)
    return out


def _from_jsonld(d):
    org = d.get("hiringOrganization") or {}
    loc_req = d.get("applicantLocationRequirements") or []
    if isinstance(loc_req, dict):
        loc_req = [loc_req]
    countries = [x.get("name") for x in loc_req if isinstance(x, dict) and x.get("name")]
    jl = d.get("jobLocation") or []
    if isinstance(jl, dict):
        jl = [jl]
    places = []
    for x in jl:
        a = (x or {}).get("address") or {}
        if isinstance(a, dict):
            places.append(", ".join(v for v in (a.get("addressLocality"), a.get("addressCountry")
                                                if isinstance(a.get("addressCountry"), str) else
                                                (a.get("addressCountry") or {}).get("name")) if v))
    remote = "Remote" if str(d.get("jobLocationType", "")).upper() == "TELECOMMUTE" else ""
    loc = " ".join(x for x in [remote, "; ".join(countries) or "; ".join(p for p in places if p)] if x)
    sal = ""
    bs = d.get("baseSalary") or {}
    if isinstance(bs, dict) and isinstance(bs.get("value"), dict):
        v = bs["value"]
        sal = f'{bs.get("currency", "")} {v.get("minValue", "")}-{v.get("maxValue", "")} {v.get("unitText", "")}'
    return {"title": d.get("title"), "company": org.get("name") if isinstance(org, dict) else str(org),
            "location": loc, "countries": countries or None, "description": strip_html(d.get("description", "")),
            "posted_at": (d.get("datePosted") or "")[:10] or None, "salary": sal.strip(),
            "employment_type": d.get("employmentType") if isinstance(d.get("employmentType"), str) else
            ", ".join(d.get("employmentType") or [])}


def _scroll(page, times):
    for _ in range(times):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(900)


def harvest(board, cfg, log, title_ok, known=frozenset()):
    """title_ok(title)->bool decides which links are worth opening."""
    from playwright.sync_api import sync_playwright
    link_re = re.compile(board.get("link_pattern") or DEFAULT_LINK_RE, re.I)
    max_details = board.get("max_details", cfg["search"].get("render_max_details", 15))
    urls = board.get("urls") or [board["url"]]
    found, out = {}, []
    follow_re = re.compile(board["follow_pattern"], re.I) if board.get("follow_pattern") else None
    with sync_playwright() as p:
        headless = cfg["search"].get("render_headless", True) and not board.get("headed")
        ctx = launch(p, headless=headless)
        page = ctx.new_page()
        try:
            queue = []
            for start in urls:
                if "{q}" in start:
                    queue += [start.replace("{q}", urllib.parse.quote_plus(q))
                              for q in (board.get("queries") or cfg["search"]["queries"])]
                else:
                    queue.append(start)
            visited, followed = set(), 0
            while queue:
                u = queue.pop(0)
                if u in visited:
                    continue
                visited.add(u)
                try:
                    page.goto(u, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(board.get("wait_ms", 2500))
                    for _ in range(5):  # let a Cloudflare / Indeed check clear, like a person waiting
                        if not re.search(r"just a moment|attention required|checking your browser", page.title(), re.I):
                            break
                        page.wait_for_timeout(4000)
                    _scroll(page, board.get("scrolls", 3))
                except Exception as e:
                    log(f"  {board['name']}: could not open {u}: {e}")
                    continue
                if re.search(r"just a moment|attention required|blocked|could not be satisfied", page.title(), re.I):
                    log(f"  {board['name']}: blocked by bot protection on {u} - skipping this board for this run")
                    raise RuntimeError("blocked by bot protection (Cloudflare/Indeed check)")
                # some boards list JobPosting JSON-LD right on the index page
                for d in _jsonld_jobs(page):
                    j = _from_jsonld(d)
                    if j["title"] and title_ok(j["title"]):
                        j["url"] = d.get("url") or u
                        found.setdefault(j["url"], j)
                links = page.eval_on_selector_all("a[href]", """els => els.map(a => [a.href,
                    (a.innerText || a.getAttribute('aria-label') || a.title || '').trim()])""")
                host = urllib.parse.urlparse(u).netloc
                for href, text in links:
                    text = ascii_clean(text.split("\n")[0]).strip()
                    if not href.startswith("http") or len(text) < 3 or len(text) > 140:
                        continue
                    href = href.split("#")[0]
                    if follow_re and follow_re.search(href) and followed < board.get("max_follow", 8) \
                            and href not in visited and href not in queue \
                            and (board.get("follow_all") or title_ok(re.sub(r"(?i)\bjobs?\b.*$", "", text).strip() or text)):
                        queue.append(href)
                        followed += 1
                        continue
                    if len(text) < 6 or _JUNK_TEXT.match(text) or not link_re.search(href):
                        continue
                    if follow_re and follow_re.search(href):
                        continue
                    if board.get("same_host", True) and urllib.parse.urlparse(href).netloc.split(":")[0] \
                            not in (host, "www." + host, host.replace("www.", "")):
                        continue
                    if href.rstrip("/") == u.rstrip("/"):
                        continue
                    if title_ok(text):
                        found.setdefault(href, {"title": text})
            fresh = [(h, j) for h, j in found.items() if h not in known]
            log(f"  {board['name']}: {len(found)} matching links, {len(fresh)} not seen before, reading up to {max_details}")
            for href, j in fresh[:max_details]:
                if j.get("description"):
                    out.append(dict(j, url=href, apply_url=href))
                    continue
                try:
                    page.goto(href, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(1800)
                    lds = _jsonld_jobs(page)
                    if lds:
                        jj = _from_jsonld(lds[0])
                        jj["title"] = jj["title"] or j["title"]
                    else:
                        body = page.inner_text("body")[:20000]
                        h1 = page.eval_on_selector("h1", "e => e.innerText") if page.query_selector("h1") else ""
                        site = page.eval_on_selector('meta[property="og:site_name"]', "e => e.content") \
                            if page.query_selector('meta[property="og:site_name"]') else ""
                        jj = {"title": ascii_clean(h1 or j["title"]).strip(), "company": "", "location": "",
                              "description": body, "site": site}
                        m = re.search(r"(?im)^\s*(?:company|employer|hiring company)\s*[:\-]\s*(.+)$", body)
                        if m:
                            jj["company"] = m.group(1).strip()[:80]
                        m = re.search(r"(?im)^\s*(?:location|region|candidate location)\s*[:\-]\s*(.+)$", body)
                        if m:
                            jj["location"] = m.group(1).strip()[:120]
                    apply = None
                    for sel in ['a:has-text("Apply")', 'a:has-text("apply")']:
                        el = page.query_selector(sel)
                        if el:
                            apply = el.get_attribute("href")
                            if apply and apply.startswith("http"):
                                break
                            apply = None
                    jj.update(url=href, apply_url=apply or href)
                    out.append(jj)
                except Exception as e:
                    log(f"    skip {href}: {e}")
                time.sleep(board.get("delay_s", 1.5))
        finally:
            ctx.close()
    for j in out:
        j.update(board=board["name"], source="render")
        if not j.get("company"):
            m = re.search(r"/(?:company|companies|employer|o)/([a-z0-9\-]+)/", j["url"], re.I)
            j["company"] = (m.group(1).replace("-", " ").title() if m else
                            board.get("company_fallback") or urllib.parse.urlparse(j["url"]).netloc)
    return out


def open_login_browser(url="https://www.linkedin.com/login"):
    """Headed browser on the engine profile so the user can sign in to boards."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = launch(p, headless=False)
        page = ctx.new_page()
        page.goto(url)
        print("Sign in to any boards you want the engine to use, then close the browser window.", flush=True)
        try:
            while ctx.pages:
                time.sleep(1)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
