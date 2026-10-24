"""Stops one company, hiring platform or recruiter seeing two applications (or two versions of your resume) from you.

Five rules, all set in Settings > Safeguards (config "safeguards"):

1. Company lock (default: skip). Before a role is prepared, and again before it is approved or submitted,
   look for other roles at the same company (normalised name) in the last `lookback_days` (90) that are in
   Review, approved or sent.
     - one was already approved / sent  -> this role is held ("Already applied 3 Oct with HM_ Dev")
     - others are only waiting in Review -> the best match wins, the weaker ones are skipped
       ("Skipped - weaker match: ..."). Ties go to the newer role.
   `company_mode`: "skip" (default) holds / skips; "warn" only shows a warning in Review.
   A role you press "Allow anyway" on is never held or skipped by these rules.

2. Platform rule. Agencies and talent platforms (Pavago, Huzzle, Somewhere, Toptal...) keep one
   candidate pool, so they get ONE resume family. Once a family has been sent to a platform, roles
   from other families there are skipped. While nothing has been sent yet, the strongest match
   (highest fit score) wins and the weaker roles are skipped.

3. Recruiter check. Roles at different companies that name the same recruiter - the same contact
   email (or company domain in the email), the same hiring account (Greenhouse / Lever / Ashby ... slug)
   or the same LinkedIn recruiter profile - are treated like one company: only the best match goes out.

4. Version used. Every application records the version sent ("HM_ Dev") so Notion's "Tier used"
   column shows exactly what the recruiter is holding.

5. Referral dedup. A person already lined up for one of your roles is never given a second note
   for another role (see referrals.find(exclude=...)).
"""
import datetime, re
from util import load_config

# statuses where the company has seen, or is about to see, a resume from you
ACTIVE = ("ready", "approved", "submitting", "submitted", "needs_you")
SENT = ("approved", "submitting", "submitted", "needs_you")
WAITING = ("ready", "retry")  # in Review, nothing sent yet

DEFAULT_PLATFORMS = [
    "somewhere", "pavago", "huzzle", "hire overseas", "pearl talent", "virtuhire", "assist world",
    "persona talent", "bruntwork", "freeup", "20four7va", "prialto", "time etc", "cherry assistant",
    "sagan recruitment", "sagan", "toptal", "lemon.io", "turing", "andela", "proxify", "arc.dev", "x-team",
    "bairesdev", "storetasker", "mindrift", "telus digital", "invisible technologies", "outlier", "alignerr",
    "micro1", "mercor", "contra", "supportyourapp", "modsquad", "virtual staff sa", "remote career africa",
    "gebeya", "cloudstaff", "wing assistant", "athena", "belay", "boldly", "magic", "offerzen",
]

DEFAULTS = {"enabled": True, "lookback_days": 90, "company_mode": "skip", "platform_rule": True,
            "referral_dedup": True, "recruiter_check": True}

_SUFFIX = re.compile(r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|gmbh|ag|pty|corp|corporation|co|company|group|"
                     r"holdings|ab|bv|b\.v|sa|sas|srl|plc|oy|as|aps|kk|pte|sarl|nv|careers?|jobs|hiring|hq|"
                     r"remote|global|international|the)\b\.?", re.I)
FAMILY_LABEL = {"dev": "Dev", "design": "Design", "admin": "Admin", "bookkeeping": "Bookkeeping",
                "ecommerce": "E-commerce", "sales": "Sales", "ai": "AI", "cse": "CSE"}

# "company" values that mean the employer is hidden - two of these are NOT the same company
UNKNOWN_COMPANIES = {"confidential", "confidentialcompany", "confidentialemployer", "stealth", "stealthstartup",
                     "undisclosed", "anonymous", "private", "privateemployer", "unknown", "na", "none", "tbd",
                     "employer", "recruiter", "recruitment", "jobseeker", "notspecified", "notdisclosed"}


def settings(cfg=None):
    cfg = cfg or load_config()
    s = dict(DEFAULTS)
    s.update(cfg.get("safeguards") or {})
    s["platforms"] = [p.lower() for p in (s.get("platforms") or DEFAULT_PLATFORMS)]
    return s


def norm_company(name):
    """'Pavago, LLC' / 'pavago.com' / 'Pavago (Remote)' -> 'pavago'."""
    c = (name or "").lower()
    c = re.sub(r"\(.*?\)", " ", c)
    c = re.sub(r"https?://|www\.", "", c)
    c = re.sub(r"\.(com|io|ai|co|net|org|app|dev|tech|careers|jobs)(\.[a-z]{2})?\b", " ", c)
    c = _SUFFIX.sub(" ", c)
    c = re.sub(r"[^a-z0-9]+", "", c)
    return c


_BOARD_HOSTS = None


def board_hosts():
    """Normalised names of every configured job board's website (remote.co -> 'remote', jobbank.gc.ca ...).
    A role whose 'company' is one of these has an unknown employer, so the company lock must not group them."""
    global _BOARD_HOSTS
    if _BOARD_HOSTS is None:
        import urllib.parse
        from util import load_config
        hs = set()
        for b in load_config().get("boards", []):
            for u in [b.get("url") or ""] + list(b.get("urls") or []):
                h = urllib.parse.urlparse(u.replace("{q}", "x")).netloc
                if h:
                    hs.add(norm_company(h))
                    hs.add(norm_company(re.sub(r"^(www|jobs|app|uae|za|de)\.", "", h)))
        _BOARD_HOSTS = {h for h in hs if h}
    return _BOARD_HOSTS


def comparable(n):
    """True when a normalised company name can be compared with another (known employer, not a job board)."""
    return bool(n) and len(n) >= 2 and n not in board_hosts() and n not in UNKNOWN_COMPANIES


# ---------------------------------------------------------------- recruiter / contact keys
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_FREE_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com", "icloud.com",
              "proton.me", "protonmail.com", "aol.com", "msn.com", "mail.com", "gmx.com", "zoho.com", "yandex.com"}
_NOISE_DOMAINS = {"linkedin.com", "indeed.com", "glassdoor.com", "greenhouse.io", "lever.co", "ashbyhq.com",
                  "workable.com", "smartrecruiters.com", "recruitee.com", "breezy.hr", "bamboohr.com",
                  "teamtailor.com", "personio.de", "personio.com", "example.com", "example.org", "sentry.io",
                  "wixpress.com", "googlegroups.com", "google.com", "facebook.com", "twitter.com", "x.com",
                  "instagram.com", "wellfound.com", "angel.co", "ziprecruiter.com", "monster.com", "jooble.org",
                  "remoteok.com", "weworkremotely.com", "himalayas.app", "remotive.com", "jobicy.com",
                  "arbeitnow.com", "workingnomads.com", "nodesk.co", "jobgether.com", "naukri.com", "bayt.com",
                  "gulftalent.com", "careerjunction.co.za", "pnet.co.za", "careers24.com", "w3.org", "schema.org",
                  "cloudflare.com", "amazonaws.com", "mailchimp.com", "sendgrid.net", "mandrillapp.com"}
_BAD_TLD = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "pdf", "ico", "woff", "woff2", "html"}
_GENERIC_LOCAL = re.compile(r"^(no-?reply|do-?not-?reply|donotreply|privacy|legal|abuse|unsubscribe|postmaster|"
                            r"webmaster|support|help|billing|press|media|security|dpo|gdpr|notifications?|alerts?|"
                            r"newsletter|mailer-daemon)$", re.I)
_ATS_RX = [
    re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]{2,})", re.I),
    re.compile(r"jobs(?:\.eu)?\.lever\.co/([a-z0-9_-]{2,})", re.I),
    re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.%-]{2,})", re.I),
    re.compile(r"apply\.workable\.com/([a-z0-9_-]{2,})", re.I),
    re.compile(r"jobs\.smartrecruiters\.com/([a-z0-9_-]{2,})", re.I),
    re.compile(r"https?://([a-z0-9-]{2,})\.(?:recruitee|breezy|bamboohr|teamtailor|applytojob|freshteam)\.(?:com|hr|io)", re.I),
]
_ATS_BAD = {"www", "jobs", "apply", "careers", "embed", "boards", "api", "app"}
_LINKEDIN = re.compile(r"linkedin\.com/in/([A-Za-z0-9%_-]{3,})", re.I)
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}
_BOARD_DOMAINS = None


def _reg_domain(dom):
    parts = dom.lower().strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else dom


def _board_domains():
    global _BOARD_DOMAINS
    if _BOARD_DOMAINS is None:
        import urllib.parse
        ds = set(_NOISE_DOMAINS)
        try:
            for b in load_config().get("boards", []):
                for u in [b.get("url") or ""] + list(b.get("urls") or []):
                    h = urllib.parse.urlparse(u.replace("{q}", "x")).netloc
                    if h:
                        ds.add(_reg_domain(h))
        except Exception:
            pass
        _BOARD_DOMAINS = ds
    return _BOARD_DOMAINS


def contact_keys(*texts):
    """Who an application would reach, as a space-padded token string such as ' dom:acme.com em:jo@acme.com '.
    Tokens: em: contact email, dom: the email's company domain (free mail excluded), ats: hiring-account slug of
    the apply link (Greenhouse, Lever, Ashby ...), li: LinkedIn recruiter profile. '' when the ad names none."""
    text = " ".join(t for t in texts if t)
    if not text:
        return ""
    keys = set()
    skip = _board_domains()
    for m in _EMAIL.finditer(text):
        addr = m.group(0).lower().strip(".")
        local, _, dom = addr.rpartition("@")
        if len(dom) < 4 or dom.rsplit(".", 1)[-1] in _BAD_TLD or _GENERIC_LOCAL.match(local):
            continue
        reg = _reg_domain(dom)
        if reg in skip:
            continue
        keys.add("em:" + addr)
        if dom not in _FREE_MAIL and reg not in _FREE_MAIL:
            keys.add("dom:" + reg)
    for rx in _ATS_RX:
        for m in rx.finditer(text):
            slug = m.group(1).lower()
            if slug not in _ATS_BAD:
                keys.add("ats:" + slug)
    for m in _LINKEDIN.finditer(text):
        keys.add("li:" + m.group(1).lower())
    return (" " + " ".join(sorted(keys)) + " ") if keys else ""


def job_contact_keys(j):
    return contact_keys(j.get("apply_url"), j.get("url"), j.get("description"))


def _key_label(k):
    kind, _, v = k.partition(":")
    return {"em": f"email {v}", "dom": f"@{v}", "ats": f"hiring account {v}", "li": f"LinkedIn {v}"}.get(kind, k)


def norm_profile_url(url):
    """LinkedIn profile URL in one canonical form, so the same person matches across roles."""
    u = (url or "").strip().lower()
    m = re.search(r"linkedin\.com/in/([^/?#]+)", u)
    if m:
        return "li:" + m.group(1)
    return re.sub(r"^https?://(www\.)?|[?#].*$|/+$", "", u)


def version_label(family, tier):
    """('dev', 'HM') -> 'HM_ Dev'  (matches the resume file prefixes HM_, J-M_, ...)."""
    if not family:
        return tier or "?"
    try:
        from util import MASTERS
        if (MASTERS / f"{family}.docx").exists():
            return FAMILY_LABEL.get(family, family.title())
    except Exception:
        pass
    return f"{tier or 'ONE'}_ {FAMILY_LABEL.get(family, family.title())}"


def is_platform(job, s=None):
    s = s or settings()
    n = job.get("company_norm") or norm_company(job.get("company"))
    if not n:
        return False
    for p in s["platforms"]:
        pn = norm_company(p)
        if pn and (n == pn or (len(pn) >= 7 and n.startswith(pn))):
            return True
    return False


def _when(row):
    d = (row.get("applied_at") or row.get("updated_at") or row.get("found_at") or "")[:10]
    try:
        return datetime.date.fromisoformat(d)
    except Exception:
        return None


def _day(d):
    return f"{d.day} {d:%b}" if d else "recently"


_COLS = ("id, title, company, company_norm, family, tier, status, score, applied_at, updated_at, found_at, "
         "version_sent, allow_override, contact_keys")


def _since(s):
    return (datetime.date.today() - datetime.timedelta(days=int(s["lookback_days"]))).isoformat()


def history(c, job, s=None):
    """Other roles at the same company that are in Review, approved or sent within the look-back window."""
    s = s or settings()
    n = job.get("company_norm") or norm_company(job.get("company"))
    if not comparable(n):
        return []  # unknown employer (only the job board's own name) - nothing to compare against
    rows = c.execute(f"""SELECT {_COLS} FROM jobs WHERE company_norm=? AND id<>? AND status IN ({','.join('?' * len(ACTIVE))})
                         AND coalesce(applied_at, updated_at, found_at) >= ?""",
                     [n, job["id"], *ACTIVE, _since(s)]).fetchall()
    return [dict(r) for r in rows]


def recruiter_history(c, job, s=None):
    """Roles at OTHER companies that share a recruiter key (email / email domain / hiring account / LinkedIn).
    Returns [(row, [shared keys])]."""
    s = s or settings()
    keys = (job.get("contact_keys") or "").split()
    if not keys:
        return []
    n = job.get("company_norm") or norm_company(job.get("company"))
    conds = " OR ".join(["contact_keys LIKE ?"] * len(keys))
    rows = c.execute(f"""SELECT {_COLS} FROM jobs WHERE id<>? AND coalesce(company_norm,'')<>? AND status IN ({','.join('?' * len(ACTIVE))})
                         AND coalesce(applied_at, updated_at, found_at) >= ? AND ({conds})""",
                     [job["id"], n or "", *ACTIVE, _since(s), *[f"% {k} %" for k in keys]]).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        shared = [k for k in keys if f" {k} " in (r.get("contact_keys") or "")]
        if shared:
            out.append((r, shared))
    return out


def _describe(o):
    label = o.get("version_sent") or version_label(o.get("family"), o.get("tier"))
    if o["status"] == "submitted":
        return f"Already applied {_day(_when(o))} with {label} ({o['title']})"
    if o["status"] in ("approved", "submitting"):
        return f"Already approved {_day(_when(o))} with {label} ({o['title']})"
    if o["status"] == "needs_you":
        return f"Started {_day(_when(o))} with {label} ({o['title']}) - check whether you finished it"
    return f"Also in Review with {label} ({o['title']}) - send only one version"


def _rank(o):
    """Higher wins: fit score first, then the newer role (ids are hashes - only a stable tie-break)."""
    return (float(o.get("score") or 0), o.get("found_at") or "", o.get("id") or "")


def _fit(o):
    return int(o.get("score") or 0)


def _why(win, lose):
    """'fits better (fit 85 vs 70)' - or, on an equal score, the newer role is kept."""
    a, b = _fit(win), _fit(lose)
    return f"fits better (fit {a} vs {b})" if a != b else f"was kept (same fit {a}, newer role)"


def _decide(job, others, s, rule, who, company_label):
    """Shared decision for one company or one recruiter. `others` = the other roles competing for the same
    recipient; `who` is text for messages ('' for company, '(email x)' for recruiter)."""
    mine = (job.get("family"), job.get("tier"))
    sent = [o for o in others if o["status"] in SENT]
    if s.get("company_mode") != "skip":  # warn mode - never blocks, only tells you
        other_version = [o for o in others if (o["family"], o["tier"]) != mine]
        pool = other_version or []
        if rule == "recruiter":
            pool = others
        if pool:
            o = sorted(pool, key=lambda o: (o["status"] not in SENT, -(o.get("score") or 0)))[0]
            more = f" (+{len(pool) - 1} more)" if len(pool) > 1 else ""
            return {"level": "warn", "rule": rule, "message": (f"Same recruiter {who}: " if rule == "recruiter" else "") + _describe(o) + more}
        o = others[0]
        return {"level": "info", "rule": rule, "message": f"Same version ({version_label(o['family'], o['tier'])}) also used for {o['title']}"}
    if sent:
        o = sorted(sent, key=lambda o: -(o.get("score") or 0))[0]
        extra = f" (+{len(sent) - 1} more)" if len(sent) > 1 else ""
        pre = f"Same recruiter {who}: " if rule == "recruiter" else ""
        return {"level": "block", "rule": rule,
                "message": f"{pre}{_describe(o)}{extra} - one application per {'recruiter' if rule == 'recruiter' else 'company'}"}
    protected = [o for o in others if o.get("allow_override")]
    best = max(others, key=_rank)
    if _rank(job) > _rank(best) and not protected:
        losers = [o["id"] for o in others if o["status"] in WAITING]
        names = ", ".join(sorted({o["title"] for o in others}))[:120]
        scope = f"at {company_label}" if rule == "company" else f"for the same recruiter {who}"
        return {"level": "wins", "rule": rule, "losers": losers,
                "message": f"Best match {scope} (fit {_fit(job)} vs {_fit(best)}) - weaker role(s) skipped: {names}",
                "loser_note": f"Skipped - weaker match: {job.get('title')} at {job.get('company')} {_why(job, best)}"
                              + (f", same recruiter {who}" if rule == "recruiter" else "")}
    if protected and _rank(job) > _rank(best):
        return {"level": "info", "rule": rule,
                "message": f"Also in Review: {protected[0]['title']} (allowed by you) - you decide which to send"}
    pre = f"same recruiter {who}, " if rule == "recruiter" else ""
    return {"level": "block", "rule": rule,
            "message": f"Skipped - weaker match: {best['title']} ({pre}{best['company']}) is already lined up "
                       f"(fit {_fit(best)} vs {_fit(job)})"}


def _check(c, job, s):
    others = history(c, job, s)
    mine = (job.get("family"), job.get("tier"))
    if others:
        if s.get("platform_rule", True) and is_platform(job, s):
            other_fam = [o for o in others if o["family"] != job.get("family")]
            if other_fam:
                sent = [o for o in other_fam if o["status"] in SENT]
                if sent:
                    o = sent[0]
                    return {"level": "block", "rule": "platform",
                            "message": f"Platform rule: {job.get('company')} already has your "
                                       f"{FAMILY_LABEL.get(o['family'], o['family'])} profile - {_describe(o)}. "
                                       "One family per platform."}
                best = max(other_fam, key=lambda o: o.get("score") or 0)
                if (job.get("score") or 0) > (best.get("score") or 0):
                    return {"level": "wins", "rule": "platform", "losers": [o["id"] for o in other_fam],
                            "loser_note": f"Platform rule: a stronger match at {job.get('company')} was chosen ({job.get('title')})",
                            "message": f"Platform rule: strongest match at {job.get('company')} "
                                       f"(fit {int(job.get('score') or 0)} vs {int(best.get('score') or 0)}) - the "
                                       f"{', '.join(sorted({version_label(o['family'], o['tier']) for o in other_fam}))} "
                                       f"role(s) there ({len(other_fam)}) are skipped so they only see one profile."}
                return {"level": "block", "rule": "platform",
                        "message": f"Platform rule: a stronger {version_label(best['family'], best['tier'])} match is "
                                   f"already lined up at {job.get('company')} ({best['title']}, fit "
                                   f"{int(best.get('score') or 0)}). One family per platform."}
        res = _decide(job, others, s, "company", "", job.get("company"))
        if res:
            return res
    if s.get("recruiter_check", True):
        rec = recruiter_history(c, job, s)
        if rec:
            shared_all = sorted({k for _, ks in rec for k in ks}, key=lambda k: (not k.startswith("em:"), k))
            who = "(" + _key_label(shared_all[0]) + ")"
            return _decide(job, [r for r, _ in rec], s, "recruiter", who, job.get("company"))
    return None


def check(c, job, cfg=None):
    """Returns None when the role is clear, otherwise a dict:
         level   "block"   - do not send (platform / company / recruiter already covered by a better or sent role)
                 "warn"    - show in Review; you decide (company_mode=warn)
                 "info"    - nothing to do
                 "wins"    - this role is the strongest match, `losers` are the weaker roles that should be skipped
                 "allowed" - a rule would have held this role but you pressed Allow anyway
         message text for Review / Notion / the run log
         rule    "platform" | "company" | "recruiter"
         loser_note (wins only) the text each skipped role gets
    """
    s = settings(cfg)
    if not s.get("enabled", True) or not job.get("family"):
        return None
    res = _check(c, job, s)
    if res and job.get("allow_override") and res["level"] in ("block", "warn"):
        return {"level": "allowed", "rule": res["rule"], "message": "Allowed by you - " + res["message"]}
    return res


def lock_for(c, job, cfg=None):
    """The lock shown on a role in either dashboard (same logic for the PC app and the online sync)."""
    if job["status"] in ("new", "ready", "approved", "retry", "needs_you"):
        return check(c, job, cfg)
    note = job.get("lock_note")
    if note:
        return {"level": "skipped" if job["status"] == "skipped" else "info", "rule": "safeguard", "message": note}
    return None


def note_for(res):
    return res["message"] if res and res["level"] in ("warn", "block", "info", "wins", "allowed") else None


def skip_losers(c, res, winner, log=print):
    """Apply a 'wins' result: every weaker waiting role is skipped with the reason."""
    for lid in res.get("losers") or []:
        note = res.get("loser_note") or f"Skipped - weaker match: {winner.get('title')} at {winner.get('company')} was chosen"
        c.execute("UPDATE jobs SET status='skipped', status_note=?, lock_note=?, updated_at=datetime('now','localtime') "
                  "WHERE id=? AND status IN ('ready','retry') AND coalesce(allow_override,0)=0", (note, note, lid))


def sweep(c, log=print, cfg=None):
    """Apply the platform rule to roles already waiting in Review (prepared before the rule existed):
    per platform, keep the family with the best fit (or the one already sent) and skip the others."""
    s = settings(cfg)
    if not (s.get("enabled", True) and s.get("platform_rule", True)):
        return 0
    rows = [dict(r) for r in c.execute(f"""SELECT id, title, company, company_norm, family, tier, status, score
                FROM jobs WHERE status IN ({','.join('?' * len(ACTIVE))}) AND family IS NOT NULL""", ACTIVE).fetchall()]
    by = {}
    for r in rows:
        if is_platform(r, s):
            by.setdefault(r["company_norm"] or norm_company(r["company"]), []).append(r)
    skipped = 0
    for name, group in by.items():
        fams = {r["family"] for r in group}
        if len(fams) < 2:
            continue
        sent = [r for r in group if r["status"] in SENT]
        keep = sent[0]["family"] if sent else max(group, key=lambda r: r["score"] or 0)["family"]
        company = group[0]["company"]
        for r in group:
            if r["family"] != keep and r["status"] in ("ready", "retry"):
                msg = (f"Platform rule: {company} gets your {FAMILY_LABEL.get(keep, keep)} profile only "
                       f"({'already sent' if sent else 'strongest match'}) - this {version_label(r['family'], r['tier'])} role was skipped")
                c.execute("UPDATE jobs SET status='skipped', status_note=?, lock_note=?, updated_at=datetime('now','localtime') "
                          "WHERE id=? AND coalesce(allow_override,0)=0", (msg, msg, r["id"]))
                skipped += 1
        log(f"  {company}: keeping {FAMILY_LABEL.get(keep, keep)}, skipped "
            f"{sum(1 for r in group if r['family'] != keep and r['status'] in ('ready', 'retry'))} other-family role(s)")
    c.commit()
    return skipped


def _plan_company(rows, s):
    """Pure planning step for sweep_company: returns [(job_id, note, group_label)] for every role to skip.
    Company groups first, then recruiter groups over the roles that survived."""
    gone = {}
    plan = []

    def run_group(label, members, who):
        live = [m for m in members if m["id"] not in gone]
        if len(live) < 2:
            return
        sent = [m for m in live if m["status"] in SENT]
        waiting = [m for m in live if m["status"] in WAITING]
        if not waiting:
            return
        if sent:
            o = sorted(sent, key=lambda m: -(m.get("score") or 0))[0]
            for m in waiting:
                if m.get("allow_override"):
                    continue
                note = (f"Skipped - already applied: {_describe(o)}" + (f" (same recruiter {who})" if who else ""))
                gone[m["id"]] = note
                plan.append((m["id"], note, label))
            return
        win = max(waiting, key=_rank)
        for m in waiting:
            if m is win or m.get("allow_override"):
                continue
            note = (f"Skipped - weaker match: {win['title']} at {win['company']} {_why(win, m)}"
                    + (f", same recruiter {who}" if who else ""))
            gone[m["id"]] = note
            plan.append((m["id"], note, label))

    by_co = {}
    for r in rows:
        n = r.get("company_norm") or norm_company(r.get("company"))
        if comparable(n):
            by_co.setdefault(n, []).append(r)
    for n, members in sorted(by_co.items()):
        run_group(members[0]["company"], members, "")
    if s.get("recruiter_check", True):
        by_key = {}
        for r in rows:
            for k in (r.get("contact_keys") or "").split():
                by_key.setdefault(k, []).append(r)
        for k, members in sorted(by_key.items()):
            live = [m for m in members if m["id"] not in gone]
            if len({m.get("company_norm") for m in live}) < 2:
                continue  # one company only - the company pass already handled it
            run_group(_key_label(k), members, "(" + _key_label(k) + ")")
    return plan


def sweep_company(c, log=print, cfg=None, dry_run=False):
    """Best role per company / recruiter among roles already in Review (and a sent role beats any waiting one).
    Returns the number of roles skipped (or that would be skipped when dry_run)."""
    s = settings(cfg)
    if not (s.get("enabled", True) and s.get("company_mode") == "skip"):
        return 0
    rows = [dict(r) for r in c.execute(f"""SELECT {_COLS} FROM jobs WHERE status IN ({','.join('?' * len(ACTIVE))})
                AND family IS NOT NULL""", ACTIVE).fetchall()]
    plan = _plan_company(rows, s)
    if dry_run:
        return len(plan)
    for jid, note, label in plan:
        c.execute("UPDATE jobs SET status='skipped', status_note=?, lock_note=?, updated_at=datetime('now','localtime') "
                  "WHERE id=? AND status IN ('ready','retry') AND coalesce(allow_override,0)=0", (note, note, jid))
        c.execute("INSERT INTO events (ts, job_id, event, detail) VALUES (datetime('now','localtime'),?,?,?)",
                  (jid, "safeguard_skip", note))
    by_label = {}
    for _, _, label in plan:
        by_label[label] = by_label.get(label, 0) + 1
    for label, n in sorted(by_label.items(), key=lambda kv: -kv[1])[:25]:
        log(f"  {label}: skipped {n} weaker role(s)")
    c.commit()
    return len(plan)


def sweep_all(c, log=print, cfg=None, dry_run=False):
    """Platform rule, then best-role-per-company / per-recruiter. Returns (platform_skipped, company_skipped)."""
    p = 0 if dry_run else sweep(c, log=log, cfg=cfg)
    return p, sweep_company(c, log=log, cfg=cfg, dry_run=dry_run)
