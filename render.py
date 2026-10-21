"""Playwright 'render and harvest' for JavaScript-heavy boards.

This is the part career-ops was missing. Instead of hand-writing a scraper per
site, it:
  1. opens the board in a real Chrome (your installed Chrome, separate profile),
  2. scrolls so lazy lists load,
  3. collects every link that looks like a job posting,
  4. keeps the ones whose title matches your role keywords,
  5. opens each kept posting and reads it - preferring the schema.org
     JobPosting data most boards embed for Google, and falling back to page text.

The browser profile lives in data/real-chrome (scanning) and data/apply-profile (applying).
Use Boards > Sign-ins in the dashboard once to sign in to the sites that need it; the engine
reuses those sign-ins and never types a password itself.

One Chrome is started per scan and shared by every browser board (it used to start one per
board, which left stray Chrome processes behind and locked the profile for the next board).
Its first tab shows a "Mustard Seed is reading job boards" page instead of about:blank.
"""
import json, os, re, sys, time, urllib.parse
from pathlib import Path
from util import DATA, ascii_clean, strip_html

PROFILE = DATA / "real-chrome"
APPLY_PROFILE = DATA / "apply-profile"
LOGIN_LOCK = DATA / "login_open.json"
STATUS_PAGE = DATA.parent / "ui" / "scanning.html"
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
        _kill_leftovers(profile)
        start = STATUS_PAGE.as_uri() if STATUS_PAGE.exists() else "about:blank"
        self.proc = subprocess.Popen(args + [start])
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
        _kill_tree(self.proc.pid)


def _kill_tree(pid):
    """Chrome starts several child processes; terminating only the parent left them running and
    the profile locked ("Opening in existing browser session")."""
    import subprocess
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            os.kill(pid, 9)
    except Exception:
        pass


def login_window_open():
    """True while the sign-in window from the dashboard is open (scans must not touch that profile)."""
    try:
        info = json.loads(LOGIN_LOCK.read_text())
    except Exception:
        return False
    if time.time() > info.get("until", 0):
        return False
    if sys.platform == "win32":
        import subprocess
        r = subprocess.run(["tasklist", "/FI", f"PID eq {info.get('pid')}", "/NH"], capture_output=True, text=True)
        return str(info.get("pid")) in r.stdout
    return True


def _kill_leftovers(profile):
    """Close any Chrome still running on this engine profile from an earlier, crashed run."""
    if sys.platform != "win32":
        return
    import subprocess
    prof = str(profile).replace("'", "''")
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { $_.CommandLine -like '*"
          + prof + "*' -and $_.CommandLine -notlike '*--type=*' } | ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


def launch(p, headless=True, profile=None):
    """Prefers your real Chrome (passes bot checks); falls back to Playwright's browser."""
    from util import load_config
    profile = Path(profile or PROFILE)
    profile.mkdir(parents=True, exist_ok=True)
    if login_window_open():
        try:
            busy = json.loads(LOGIN_LOCK.read_text()).get("profile")
        except Exception:
            busy = None
        if busy == profile.name:
            raise RuntimeError("the Sign-in window is open on this profile - close it first")
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


_SESSION = {"pw": None, "ctx": None}


def session(cfg):
    """One browser for the whole scan, started on first use."""
    if _SESSION["ctx"] is None:
        if login_window_open():
            raise RuntimeError("the Sign-in window is open on this PC - close it so browser boards can run")
        from playwright.sync_api import sync_playwright
        _SESSION["pw"] = sync_playwright().start()
        headless = cfg["search"].get("render_headless", True)
        _SESSION["ctx"] = launch(_SESSION["pw"], headless=headless)
    return _SESSION["ctx"]


def shutdown():
    ctx, pw = _SESSION["ctx"], _SESSION["pw"]
    _SESSION.update(ctx=None, pw=None)
    try:
        if ctx:
            ctx.close()
    except Exception:
        pass
    try:
        if pw:
            pw.stop()
    except Exception:
        pass


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


def _slug_title(href):
    """'/job-details/senior-shopify-developer-d08957a7-5e72' -> 'Senior Shopify Developer'."""
    path = urllib.parse.urlparse(href).path.rstrip("/")
    segs = [x for x in path.split("/") if x]
    while segs and re.fullmatch(r"[\d\-]+|[0-9a-f\-]{16,}", segs[-1]):
        segs.pop()  # /job/<slug>/11609701
    last = segs[-1] if segs else ""
    last = re.sub(r"\.\w{2,5}$", "", last)
    words = [w for w in re.split(r"[-_+]", last) if w]
    while words and re.search(r"\d", words[-1]):
        words.pop()  # trailing ids / uuids
    words = [w for w in words if not re.fullmatch(r"[0-9a-f]{6,}", w)]
    if len(words) < 2 or len(words) > 14:
        return ""
    return " ".join(words).title()


def _scroll(page, times):
    for _ in range(times):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(900)


_PASSIVE = re.compile(r"just a moment|attention required|checking your browser|radware|^loading https?://", re.I)


def _settle(page, tries=5, ms=4000):
    """Passive bot checks (Cloudflare 'Just a moment', Radware 'Loading...') clear on their own in a few seconds
    for a normal browser; wait for that like a person would. Stops as soon as the real page text is there."""
    for _ in range(tries):
        try:
            t = page.title() or ""
            n = len(page.inner_text("body") or "")
        except Exception:
            return
        if not _PASSIVE.search(t) or n > 1500:
            return
        page.wait_for_timeout(ms)


_BLOCK_TITLE = re.compile(r"radware|403 forbidden|access denied|request blocked|you have been blocked|error 1020|"
                          r"are you a robot|human verification|verify you are human|robot check|too many requests", re.I)
_BLOCK_BODY = re.compile(r"transaction id|access denied|403 forbidden|verify (that )?you are (a )?human|are you a robot|"
                         r"unusual traffic|captcha|not a robot|automated (access|requests)|you have been blocked", re.I)


# a human-check pop-up laid over an otherwise normal, long page (Make it in Germany: "Suspicious Activity Detected!")
_BLOCK_OVERLAY = re.compile(r"suspicious activity detected|validated for suspicious|suspicious bot activity|"
                            r"unusual activity from your|verify you are (a )?human", re.I)


def blocked_page(page, resp=None):
    """True when the site is showing a 403 / human-check page instead of its listings.
    We never try to solve or dodge these: the caller stops the board and it rests for a day or more."""
    try:
        if resp is not None and resp.status in (403, 429):
            return True
    except Exception:
        pass
    try:
        title = page.title() or ""
    except Exception:
        title = ""
    if _BLOCK_TITLE.search(title):
        return True
    try:
        full = page.inner_text("body") or ""
    except Exception:
        full = ""
    if _BLOCK_OVERLAY.search(full):
        return True
    body = full[:3000].strip()
    if len(body) < 1500:  # a real listing page is long; block / challenge pages are short
        if _BLOCK_BODY.search(body):
            return True
        try:
            if page.query_selector('iframe[src*="hcaptcha"], iframe[src*="recaptcha"][src*="bframe"], '
                                   'iframe[src*="challenges.cloudflare"]'):
                return True
        except Exception:
            pass
    return False


LAST = {}  # stats from the last harvest(): links on the pages, links matching the job pattern, sign-in wall


_LOGIN_WALL = re.compile(r"/(login|signin|sign-in|sign_in|auth|authenticate)\b|[?&]redirect", re.I)


def _goto(page, u, board):
    """page.goto with one retry - remote.co and others drop HTTP/2 streams now and then."""
    for attempt in range(2):
        try:
            return page.goto(u, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            if attempt or not re.search(r"ERR_HTTP2|ERR_CONNECTION|ERR_TIMED_OUT|Timeout|net::", str(e)):
                raise
            page.wait_for_timeout(3000)


def harvest(board, cfg, log, title_ok, known=frozenset()):
    """title_ok(title)->bool decides which links are worth opening."""
    LAST.clear()
    LAST.update(links=0, hits=0, signin=False)
    link_re = re.compile(board.get("link_pattern") or DEFAULT_LINK_RE, re.I)
    max_details = board.get("max_details", cfg["search"].get("render_max_details", 15))
    urls = board.get("urls") or [board["url"]]
    found, out = {}, []
    follow_re = re.compile(board["follow_pattern"], re.I) if board.get("follow_pattern") else None
    if True:
        ctx = session(cfg)
        try:
            page = ctx.new_page()
        except Exception:  # browser died (closed by hand?) - start a fresh one
            shutdown()
            ctx = session(cfg)
            page = ctx.new_page()
        try:
            queue = []
            for start in urls:
                if "{q}" in start:
                    enc = (lambda q: re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")) if board.get("q_slug") \
                        else urllib.parse.quote_plus
                    queue += [start.replace("{q}", enc(q))
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
                    resp = _goto(page, u, board)
                    page.wait_for_timeout(board.get("wait_ms", 2500))
                    _settle(page)  # let a Cloudflare / Radware / Indeed check clear, like a person waiting
                    _scroll(page, board.get("scrolls", 3))
                except Exception as e:
                    log(f"  {board['name']}: could not open {u}: {e}")
                    continue
                if blocked_page(page, resp) or re.search(r"just a moment|attention required|blocked|could not be satisfied",
                                                         page.title(), re.I):
                    try:
                        page.goto("about:blank")  # leave the human-check page so it stops reloading
                    except Exception:
                        pass
                    log(f"  {board['name']}: the site is showing a 403 / human-check page ({urllib.parse.urlparse(u).netloc}) - "
                        "stopping this board now (not retrying, not solving it)")
                    raise RuntimeError("blocked by bot protection (403 / human check)")
                # some boards list JobPosting JSON-LD right on the index page
                for d in _jsonld_jobs(page):
                    j = _from_jsonld(d)
                    if j["title"] and title_ok(j["title"]):
                        j["url"] = d.get("url") or u
                        found.setdefault(j["url"], j)
                links = page.eval_on_selector_all("a[href]", """els => els.map(a => [a.href,
                    (a.innerText || a.getAttribute('aria-label') || a.title || '').trim()])""")
                if board.get("frames"):
                    # job lists embedded in an iframe (e.g. somewhere.com/jobs): scroll + read every child frame
                    for fr in page.frames[1:]:
                        try:
                            for _ in range(board.get("frame_scrolls", 10)):
                                fr.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                page.wait_for_timeout(900)
                            fl = fr.eval_on_selector_all("a[href]", """els => els.map(a => [a.href,
                                (a.innerText || a.getAttribute('aria-label') || a.title || '').trim()])""")
                            log(f"  {board['name']}: frame {fr.url[:80]} -> {len(fl)} links"
                                + (f" e.g. {fl[0][0][:90]}" if fl else ""))
                            links += fl
                        except Exception as e:
                            log(f"  {board['name']}: could not read frame {fr.url[:80]}: {e}")
                host = urllib.parse.urlparse(u).netloc
                LAST["links"] += len(links)
                LAST["hits"] += sum(1 for h, _ in links if link_re.search(h or ""))
                if _LOGIN_WALL.search(page.url) and not _LOGIN_WALL.search(u):
                    LAST["signin"] = True
                    log(f"  {board['name']}: redirected to a sign-in page ({page.url[:80]})")
                for href, text in links:
                    text = ascii_clean(text.split("\n")[0]).strip()
                    if not href.startswith("http") or len(text) < 3 or len(text) > 140:
                        continue
                    href = href.split("#")[0]
                    if board.get("url_strip"):
                        href = re.sub(board["url_strip"], "", href)
                    if follow_re and follow_re.search(href) and followed < board.get("max_follow", 8) \
                            and href not in visited and href not in queue \
                            and (board.get("follow_all") or title_ok(re.sub(r"(?i)\bjobs?\b.*$", "", text).strip() or text)):
                        queue.append(href)
                        followed += 1
                        continue
                    if not link_re.search(href):
                        continue
                    if board.get("any_link_text"):
                        # link text isn't the title on this board (Job Bank cards) - read every matching
                        # posting and let the page's own title decide
                        if not (follow_re and follow_re.search(href)) and href.rstrip("/") != u.rstrip("/"):
                            found.setdefault(href, {"title": ""})
                        continue
                    if len(text) < 6 or _JUNK_TEXT.match(text) or not title_ok(text):
                        # link text is "Apply" / "7 days ago" etc. - the job title is often in the URL itself
                        st = _slug_title(href)
                        if not st or not title_ok(st):
                            continue
                        text = st
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
                    resp = _goto(page, href, board)
                    page.wait_for_timeout(1800)
                    _settle(page, 3, 3000)
                    if blocked_page(page, resp):
                        try:
                            page.goto("about:blank")
                        except Exception:
                            pass
                        log(f"  {board['name']}: the site started showing a 403 / human-check page - "
                            "stopping here, keeping what was read so far")
                        break
                    lds = _jsonld_jobs(page)
                    if lds:
                        jj = _from_jsonld(lds[0])
                        jj["title"] = (j["title"] if board.get("link_title") and j["title"] else None) or jj["title"] or j["title"]
                    else:
                        body = page.inner_text("body")[:20000]
                        h1 = page.eval_on_selector("h1", "e => e.innerText") if page.query_selector("h1") else ""
                        site = page.eval_on_selector('meta[property="og:site_name"]', "e => e.content") \
                            if page.query_selector('meta[property="og:site_name"]') else ""
                        if board.get("any_link_text") and not h1:
                            h1 = page.title().split("|")[0].split(" - ")[0]
                        title = (j["title"] if board.get("link_title") and j["title"] else None) or h1 or j["title"]
                        jj = {"title": ascii_clean(title).strip(), "company": "", "location": "",
                              "description": body, "site": site}
                        m = re.search(r"(?im)^\s*(?:company|employer|hiring company)\s*[:\-]\s*(.+)$", body)
                        if m:
                            jj["company"] = m.group(1).strip()[:80]
                        m = re.search(r"(?im)^\s*(?:location|region|candidate location)\s*[:\-]\s*(.+)$", body)
                        if m:
                            jj["location"] = m.group(1).strip()[:120]
                    # the employer's own apply link - checked against company + title, so a "similar jobs"
                    # box can never hand us another employer's link (see applylinks.py)
                    import applylinks
                    co = jj.get("company") or _company_guess(dict(jj, url=href, title=jj.get("title") or ""), board)
                    apply = applylinks.pick_apply(page, co, jj.get("title") or "", "")
                    jj.update(url=href, apply_url=apply or href)
                    out.append(jj)
                except Exception as e:
                    log(f"    skip {href}: {e}")
                time.sleep(board.get("delay_s", 1.5))
        finally:
            try:
                page.close()
            except Exception:
                pass
    for j in out:
        j.update(board=board["name"], source="render")
        if not j.get("company"):
            j["company"] = _company_guess(j, board)
    return out


def _company_guess(j, board):
    """Company when the posting page didn't state one: board-specific URL rule, 'Title at Company',
    a /company/<slug>/ path - and only then the site's own name (safeguards ignore board hostnames)."""
    url, title = j.get("url") or "", j.get("title") or ""
    if board.get("company_url_re"):
        m = re.search(board["company_url_re"], url, re.I)
        if m:
            return m.group(1).replace("-", " ").title()
    m = re.search(r"\s(?:at|@)\s+([A-Z][\w&.' -]{1,50})$", title)
    if m:
        j["title"] = title[:m.start()].strip(" -|")
        return m.group(1).strip()
    m = re.search(r"/(?:company|companies|employer|o)/([a-z0-9\-]+)/", url, re.I)
    if m:
        return m.group(1).replace("-", " ").title()
    return board.get("company_fallback") or urllib.parse.urlparse(url).netloc


def open_login_browser(arg="https://www.linkedin.com/login"):
    """Visible Chrome on an engine profile so you can sign in to sites. One tab per site.
    arg: a URL, or JSON {"urls": [...], "profile": "scan"|"apply"}. Closes itself after 20 minutes."""
    from playwright.sync_api import sync_playwright
    try:
        spec = json.loads(arg) if str(arg).strip().startswith("{") else {"urls": [arg]}
    except Exception:
        spec = {"urls": [arg]}
    urls = [u for u in spec.get("urls", []) if str(u).startswith("http")] or ["https://www.linkedin.com/login"]
    profile = APPLY_PROFILE if spec.get("profile") == "apply" else PROFILE
    try:
        with sync_playwright() as p:
            ctx = launch(p, headless=False, profile=profile)
            LOGIN_LOCK.write_text(json.dumps({"pid": os.getpid(), "until": time.time() + 1200, "profile": profile.name}))
            pages = list(getattr(ctx, "pages", []) or [])
            first = pages[0] if pages else ctx.new_page()
            first.goto(urls[0])
            for u in urls[1:]:
                ctx.new_page().goto(u)
            print(f"Opened {len(urls)} sign-in tab(s) on the {'applying' if profile == APPLY_PROFILE else 'scanning'} "
                  "profile. Sign in where you want to, then close the Chrome window.", flush=True)
            stop = time.time() + 1200
            try:
                while time.time() < stop:
                    if not ctx.pages:
                        break
                    time.sleep(1)
            except Exception:
                pass
            try:
                ctx.close()
            except Exception:
                pass
        _mark_signins(urls, profile)
        print("Sign-in window closed. Your sign-ins are saved.", flush=True)
    finally:
        try:
            LOGIN_LOCK.unlink()
        except Exception:
            pass


def _mark_signins(urls, profile):
    f = DATA / "signins.json"
    try:
        d = json.loads(f.read_text())
    except Exception:
        d = {}
    for u in urls:
        d[f"{profile.name}|{urllib.parse.urlparse(u).netloc}"] = time.strftime("%Y-%m-%d %H:%M")
    f.write_text(json.dumps(d, indent=1))
