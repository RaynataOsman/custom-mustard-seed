"""Find the employer's real application link for a posting - and refuse links that belong to another job.

Why: board pages (Remote Rocketship, remotiko, ...) show "similar jobs" with their own Apply buttons.
Taking the first "Apply" on the page sent roles to the wrong employer (ChainGPT -> Lyceum College,
Fathom Robotics -> REMAX Hawaii). Every link is now checked against the company and the job title.
"""
import re, urllib.parse
from util import get

GENERIC = {"inc", "llc", "ltd", "limited", "group", "global", "international", "solutions", "services", "company",
           "co", "corp", "corporation", "gmbh", "pty", "plc", "org", "the", "and", "remote", "careers", "jobs",
           "hiring", "technologies", "technology", "software", "labs", "agency", "partners", "holdings", "hq",
           "www", "com", "io", "ai", "uk", "za", "net", "app"}
APPLY_TEXT = re.compile(r"^\s*(apply( now| here| online| for this (job|position|role))?|i'?m interested|start (your )?application|"
                        r"apply on (company|employer)( site| website)?|apply to (this )?job|submit (your )?(application|cv|resume)|"
                        r"easy apply|quick apply|apply manually|autofill with (my )?(resume|cv)|apply with (your |my )?(resume|cv)|"
                        r"continue to (apply|application)|apply on (the )?company('s)? (site|website))\s*[!>→]*\s*$", re.I)
# containers whose Apply buttons belong to OTHER jobs
FOREIGN_BOX = re.compile(r"related|similar|recommend|more-jobs|other-jobs|also|footer|nav|carousel|latest", re.I)
ATS_HOST = re.compile(r"greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|smartrecruiters\.com|recruitee\.com|"
                      r"teamtailor\.com|bamboohr\.com|personio\.|applytojob\.com|zohorecruit\.com|rippling\.com|breezy\.hr|"
                      r"join\.com|softgarden\.io|myworkdayjobs\.com|successfactors|icims\.com|jobvite\.com|workday", re.I)
STOP = {"remote", "senior", "junior", "sr", "jr", "lead", "manager", "specialist", "the", "and", "for", "with", "of",
        "to", "in", "a", "an", "m", "f", "d", "x", "w", "full", "time", "part", "contract"}


def company_tokens(company):
    c = re.sub(r"^(https?://)?(www\.)?", "", (company or "").lower())
    c = re.sub(r"\.(com|io|ai|co|net|org|app|dev|tech)(\.[a-z]{2})?\b", " ", c)
    toks = [t for t in re.findall(r"[a-z0-9]+", c) if len(t) >= 3 and t not in GENERIC]
    joined = "".join(re.findall(r"[a-z0-9]+", c))
    return list(dict.fromkeys(toks + ([joined] if len(joined) >= 4 else [])))


def title_tokens(title):
    return [t for t in re.findall(r"[a-z0-9]+", (title or "").lower()) if len(t) >= 3 and t not in STOP]


def link_fits(href, company, title, board_host=""):
    """True when href plausibly is THIS job at THIS company."""
    if not href or not href.startswith("http"):
        return False
    u = urllib.parse.urlparse(href)
    hay = (u.netloc + u.path + "?" + u.query).lower().replace("-", "").replace("_", "")
    hay_dash = (u.netloc + u.path).lower()
    if board_host and board_host in u.netloc:
        return True  # same board - the board's own apply page for this job
    unknown = not company or bool(re.fullmatch(r"(www\.)?[a-z0-9.-]+\.[a-z]{2,}(\.[a-z]{2})?", company.strip().lower()))
    ct = [] if unknown else company_tokens(company)
    if ct and any(t.replace("-", "") in hay for t in ct):
        return True
    tt = title_tokens(title)
    if unknown:
        # employer name unknown (board stored its own domain): accept only a link that spells out this job title
        return bool(tt) and sum(1 for t in tt if t in hay_dash) >= max(2, round(len(tt) * 0.6))
    if ATS_HOST.search(u.netloc):
        return False  # hiring-system links carry the employer's account name - it must be this company
    tt = title_tokens(title)
    hits = sum(1 for t in tt if t in hay_dash)
    if tt and hits >= max(2, (len(tt) + 1) // 2):
        return True
    return False


_PICK_JS = """(boxRe) => {
  const re = new RegExp(boxRe, 'i'); const out = []; let i = 0;
  for (const e of document.querySelectorAll('a[href], button, [role=button], input[type=submit], input[type=button]')) {
    const t = (e.innerText || e.getAttribute('aria-label') || e.value || '').trim().slice(0, 80);
    if (!t) continue;
    let foreign = false, p = e.parentElement;
    for (let i = 0; i < 12 && p; i++, p = p.parentElement) {
      const k = ((p.className && p.className.baseVal !== undefined ? p.className.baseVal : p.className) || '') + ' ' + (p.id || '') + ' ' + p.tagName;
      if (re.test(k)) { foreign = true; break; }
    }
    const r = e.getBoundingClientRect(); const idx = i++;
    e.setAttribute('data-ms-apply', idx);
    const st = getComputedStyle(e);
    out.push({idx, tag: e.tagName, href: e.href || '', text: t, foreign,
              visible: !!(r.width && r.height) && st.visibility !== 'hidden' && st.display !== 'none'});
  }
  return out; }"""


def apply_candidates(page):
    try:
        return page.evaluate(_PICK_JS, FOREIGN_BOX.pattern)
    except Exception:
        return []


def pick_apply(page, company, title, board_host=""):
    """Best employer apply URL on a board's job page, or None. Never returns another job's link."""
    best = None
    for c in apply_candidates(page):
        if c["foreign"] or not APPLY_TEXT.match(c["text"]) or not c["href"].startswith("http"):
            continue
        h = c["href"]
        if link_fits(h, company, title, board_host):
            if not best or (ATS_HOST.search(h) and not ATS_HOST.search(best)):
                best = h
    return best


def _norm(t):
    return " ".join(title_tokens(t))


def title_match(a, b):
    ta, tb = set(title_tokens(a)), set(title_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def employer_lookup(company, title, log=print):
    """Look the job up in the company's own hiring system (Greenhouse/Lever/Ashby/Workable/SmartRecruiters/
    Recruitee) by company name + title. Returns the posting URL or None."""
    import ats_discover, boards
    if not company or not title:
        return None
    names = [company]
    core = re.sub(r"\b(org|inc|llc|ltd|limited|gmbh|pty|co|corp|group|hq|io|ai|com|global|international)\b\.?|\b\d+\b", " ", company, flags=re.I)
    core = re.sub(r"\s+", " ", core).strip()
    if core and core.lower() != company.lower():
        names.append(core)
    first = (core or company).split()[0] if (core or company).split() else ""
    if len(first) >= 4 and first.lower() not in [n.lower() for n in names]:
        names.append(first)
    info = None
    for n in names:
        try:
            info = ats_discover.resolve(n, log=lambda *a: None)
        except Exception:
            info = None
        if (info or {}).get("kind"):
            break
    kind, slug = (info or {}).get("kind"), (info or {}).get("slug")
    if not kind:
        return None
    try:
        if kind in ("greenhouse", "lever", "ashby", "workable"):
            jobs = getattr(boards, kind)({"companies": [slug], "name": f"{kind} ({company})", "kind": kind}, {}, lambda *a: None)
        else:
            jobs = ats_discover.fetch(kind, slug, company) or []
    except Exception as e:
        log(f"    employer lookup failed for {company}: {e}")
        return None
    scored = sorted(((title_match(title, j.get("title", "")), j) for j in jobs), key=lambda x: -x[0])
    if scored and scored[0][0] >= 0.6:
        j = scored[0][1]
        u = j.get("apply_url") or j.get("url") or ""
        m = re.search(r"gh_jid=(\d+)", u) or re.search(r"greenhouse\.io/[^/]+/jobs/(\d+)", u)
        if kind == "greenhouse" and m:
            # Greenhouse's own form page - company careers sites only wrap it in a slow iframe
            u = f"https://job-boards.greenhouse.io/embed/job_app?for={slug}&token={m.group(1)}"
        return u
    return None
