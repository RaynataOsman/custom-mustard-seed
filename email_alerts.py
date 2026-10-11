"""Job-alert emails -> job records, read from Gmail over IMAP (free, no API, no LLM).

Credentials (keys.env / Settings): GMAIL_ADDRESS, GMAIL_APP_PASSWORD (Google app password).
Board config: {"name": "Email job alerts (Gmail)", "kind": "email_alerts", "enabled": true, "days": 3}
Optional: "senders": [...], "folder": "Label name".
"""
import email, email.header, email.utils, html as _html, imaplib, json, re, time
import urllib.parse
import util
from util import strip_html

SEEN_FILE = util.DATA / "email_alerts_seen.json"
MAX_LINKEDIN_DETAILS = 15

DEFAULT_SENDERS = ["indeed", "linkedin", "glassdoor", "careers24", "welcometothejungle",
                   "wellfound", "otta", "pnet", "careerjunction", "substack", "beehiiv",
                   "jobgether", "himalayas", "weworkremotely", "remoteok", "workingnomads",
                   "dynamitejobs", "builtin", "remotive"]

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# anchor texts that are never a job title
_GENERIC = re.compile(
    r"^(?:un-?subscribe|unsubscribe.*|view all.*|see all.*|see more.*|view more.*|more jobs.*|"
    r"manage (?:your )?(?:alerts?|settings|preferences|subscriptions?).*|email preferences|"
    r"privacy.*|terms.*|help(?: center)?|contact us|apply(?: now| here)?|view (?:job|in browser|online|email.*)|"
    r"read (?:more|online|in browser).*|learn more|get the app|download.*|subscribe.*|share.*|"
    r"forward.*|sign ?in|log ?in|sign ?up|create.*alert.*|edit.*alert.*|turn off.*|"
    r"why am i receiving.*|update.*(?:preferences|profile).*|leave feedback|report.*|"
    r"view this email.*|open in .*|upgrade.*|become a .*|advertise.*|sponsor.*|pledge.*|"
    r"like|comment|reply|restack|tweet|follow.*|jobs?|click here|here|this link)$", re.I)
_BAD_URL = re.compile(r"unsubscribe|optout|opt-out|/preferences|manage[-_]?(?:alert|sub)|privacy|"
                      r"/terms|mailto:|^tel:|twitter\.com|x\.com/|facebook\.com|instagram\.com|"
                      r"youtube\.com|apps\.apple\.com|play\.google\.com|substack\.com/(?:app|subscribe|share)|"
                      r"/signin|/login|/help", re.I)
_JOB_URL = re.compile(
    r"indeed\.[a-z.]+/(?:rc/clk|viewjob|pagead/clk)|[?&]jk=|"
    r"linkedin\.com/(?:comm/)?jobs/view/|"
    r"glassdoor\.[a-z.]+/(?:partner/jobListing|job-listing/)|"
    r"careers24\.com/jobs/adverts/|"
    r"welcometothejungle\.com/.*/jobs/|wellfound\.com/(?:company/[^/]+/)?jobs/", re.I)
_REDIRECT_PARAMS = ("url", "u", "redirect", "dest", "redirect_url", "target")
_A_RE = re.compile(r'<a\b([^>]*?)href\s*=\s*(?:"([^"]*)"|\'([^\']*)\')[^>]*>(.*?)</a\s*>', re.I | re.S)


def _unwrap(url, depth=0):
    """Resolve tracking redirects whose real destination sits in a query param."""
    url = _html.unescape(url or "").strip()
    if depth > 3 or not url.startswith("http"):
        return url
    # a job URL that is already direct needs no unwrapping
    if _JOB_URL.search(urllib.parse.urlparse(url).path + "?" + urllib.parse.urlparse(url).query) \
            and not re.search(r"[?&](?:url|u|redirect|dest)=https?", url, re.I):
        return url
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    for k in _REDIRECT_PARAMS:
        for v in q.get(k, []):
            v = urllib.parse.unquote(v) if v.startswith("http%3A") or v.startswith("https%3A") else v
            if v.startswith("http"):
                return _unwrap(v, depth + 1)
    return url


def _normalise(url):
    """Canonical URL: LinkedIn -> /jobs/view/<id>; others unchanged."""
    m = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*-)?(\d{6,})", url, re.I)
    if m:
        return "https://www.linkedin.com/jobs/view/" + m.group(1)
    return url


def _clean_text(s):
    return re.sub(r"\s+", " ", strip_html(s or "")).strip()


def _context_lines(chunk):
    text = strip_html(chunk)
    out = []
    for ln in text.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip(" \t|-·•")
        if not ln or len(ln) > 90 or _GENERIC.match(ln):
            continue
        out.append(ln)
        if len(out) == 2:
            break
    return out


def parse_alert_html(board, html_text, sender="", date=""):
    """Pure function: alert-email HTML -> list of job dicts. No network."""
    import boards
    cands = []
    for m in _A_RE.finditer(html_text or ""):
        raw_href = m.group(2) if m.group(2) is not None else m.group(3)
        href = _unwrap(raw_href)
        if not href.startswith("http") or _BAD_URL.search(href):
            continue
        text = _clean_text(m.group(4))
        generic = bool(_GENERIC.match(text))
        title_like = 6 <= len(text) <= 120 and not generic
        shape = bool(_JOB_URL.search(href) or _JOB_URL.search(_html.unescape(raw_href)))
        if not (title_like or shape):
            continue
        cands.append({"url": _normalise(href), "title": text if title_like else "",
                      "start": m.start(), "end": m.end()})
    jobs, by_url = [], {}
    for i, c in enumerate(cands):
        nxt = cands[i + 1]["start"] if i + 1 < len(cands) else len(html_text)
        if c["url"] in by_url:
            j = by_url[c["url"]]
            if not j["title"] and c["title"]:
                j["title"] = c["title"]
            continue
        lines = _context_lines(html_text[c["end"]:min(nxt, c["end"] + 900)])
        j = {"url": c["url"], "title": c["title"],
             "company": lines[0] if lines else "", "location": lines[1] if len(lines) > 1 else ""}
        by_url[c["url"]] = j
        jobs.append(j)
    out = []
    for j in jobs:
        if not j["title"]:
            continue
        rec = boards._job(board, url=j["url"], apply_url=j["url"], title=j["title"],
                          company=j["company"], location=j["location"], description="",
                          posted_at=date or None)
        rec["source_email"] = sender
        out.append(rec)
    return out


def _text_to_html(text):
    """Plain-text fallback: wrap bare URLs, using the preceding line as anchor text."""
    out, prev = [], ""
    for ln in (text or "").splitlines():
        m = re.search(r"https?://\S+", ln)
        if m:
            label = ln[:m.start()].strip(" :-<([") or prev
            out.append(f'<div><a href="{m.group(0).rstrip(">)].,")}">{label}</a></div>')
        elif ln.strip():
            out.append(f"<div>{_html.escape(ln.strip())}</div>")
            prev = ln.strip()
    return "\n".join(out)


def _decode(h):
    try:
        return "".join(p.decode(c or "utf-8", "replace") if isinstance(p, bytes) else p
                       for p, c in email.header.decode_header(h or ""))
    except Exception:
        return h or ""


def _body(msg):
    htmls, texts = [], []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ("text/html", "text/plain"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            s = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        (htmls if ct == "text/html" else texts).append(s)
    if htmls:
        return "\n".join(htmls)
    return _text_to_html("\n".join(texts))


def parse_message(board, raw_bytes):
    """Raw RFC822 bytes -> (message_id, sender, jobs)."""
    msg = email.message_from_bytes(raw_bytes)
    sender = _decode(msg.get("From", ""))
    try:
        date = email.utils.parsedate_to_datetime(msg.get("Date")).date().isoformat()
    except Exception:
        date = util.today()
    return (msg.get("Message-ID") or "").strip(), sender, parse_alert_html(board, _body(msg), sender, date)


# ---------------------------------------------------------------- IMAP
def _creds():
    k = util.load_keys()
    addr = (k.get("GMAIL_ADDRESS") or "").strip()
    pw = (k.get("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
    if not addr or not pw:
        raise RuntimeError("Gmail not connected: add GMAIL_ADDRESS and GMAIL_APP_PASSWORD in Settings")
    return addr, pw


def _connect():
    addr, pw = _creds()
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(addr, pw)
    return M


def _since(days):
    import datetime
    d = datetime.date.today() - datetime.timedelta(days=int(days))
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def _load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_seen(seen):
    try:
        SEEN_FILE.write_text(json.dumps(sorted(seen)[-5000:]), encoding="utf-8")
    except Exception:
        pass


def _iter_folder(M, folder, days, senders, seen, log=None):
    """Yield (message_id, sender, raw_bytes) for matching, unseen messages. Read-only."""
    typ, _ = M.select(f'"{folder}"' if " " in folder else folder, readonly=True)
    if typ != "OK":
        if log:
            log(f"  cannot open folder {folder}")
        return
    typ, data = M.search(None, "SINCE", _since(days))
    if typ != "OK" or not data or not data[0]:
        return
    for num in data[0].split():
        typ, d = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID)])")
        if typ != "OK" or not d or not isinstance(d[0], tuple):
            continue
        hdr = email.message_from_bytes(d[0][1])
        frm = _decode(hdr.get("From", "")).lower()
        mid = (hdr.get("Message-ID") or "").strip() or f"{folder}:{num.decode()}"
        if mid in seen or not any(s.lower() in frm for s in senders):
            continue
        typ, d = M.fetch(num, "(BODY.PEEK[])")
        if typ == "OK" and d and isinstance(d[0], tuple):
            yield mid, d[0][1]


def fetch(board, cfg, log):
    senders = board.get("senders") or DEFAULT_SENDERS
    days = board.get("days", 3)
    M = _connect()
    seen, jobs, urls = _load_seen(), [], set()
    folders = ["INBOX"] + ([board["folder"]] if board.get("folder") else [])
    n_mail = 0
    try:
        for folder in folders:
            for mid, raw in _iter_folder(M, folder, days, senders, seen, log):
                _, sender, found = parse_message(board, raw)
                n_mail += 1
                seen.add(mid)
                for j in found:
                    if j["url"] not in urls:
                        urls.add(j["url"])
                        jobs.append(j)
    finally:
        try:
            M.logout()
        except Exception:
            pass
        _save_seen(seen)
    log(f"  {n_mail} new alert emails -> {len(jobs)} job links")
    import boards
    done = 0
    for j in jobs:
        if done >= MAX_LINKEDIN_DETAILS:
            break
        if "linkedin.com/jobs/view/" in j["url"] and not j.get("description"):
            try:
                boards.linkedin_detail(j)
                done += 1
                time.sleep(2)
            except Exception:
                pass
    return jobs


def test_connection(board=None):
    """Short status string for the dashboard."""
    board = board or {}
    try:
        M = _connect()
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"error - {type(e).__name__}: {e}"
    try:
        days = board.get("days", 3)
        senders = board.get("senders") or DEFAULT_SENDERS
        n = sum(1 for _ in _iter_folder(M, "INBOX", days, senders, set()))
        return f"ok - {n} alert emails in last {days} days"
    except Exception as e:
        return f"error - {type(e).__name__}: {e}"
    finally:
        try:
            M.logout()
        except Exception:
            pass
