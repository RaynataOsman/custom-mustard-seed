"""Stops one company (or one hiring platform) seeing two different versions of your resume.

Four rules, all set in Settings > Safeguards (config "safeguards"):

1. Company lock. Before a role is prepared, and again before it is approved or submitted, look for
   other roles at the same company (normalised name) in the last `lookback_days` (90) that are in
   Review, approved or sent. If they used a different resume version (family or tier), the role is
   either skipped or shown in Review with a warning such as "Already applied 3 Oct with HM_ Dev".
   `company_mode`: "warn" (default) or "skip".

2. Platform rule. Agencies and talent platforms (Pavago, Huzzle, Somewhere, Toptal...) keep one
   candidate pool, so they get ONE resume family. Once a family has been sent to a platform, roles
   from other families there are skipped. While nothing has been sent yet, the strongest match
   (highest fit score) wins and the weaker roles are skipped.

3. Version used. Every application records the version sent ("HM_ Dev") so Notion's "Tier used"
   column shows exactly what the recruiter is holding.

4. Referral dedup. A person already lined up for one of your roles is never given a second note
   for another role (see referrals.find(exclude=...)).
"""
import datetime, re
from util import load_config

# statuses where the company has seen, or is about to see, a resume from you
ACTIVE = ("ready", "approved", "submitting", "submitted", "needs_you")
SENT = ("approved", "submitting", "submitted", "needs_you")

DEFAULT_PLATFORMS = [
    "somewhere", "pavago", "huzzle", "hire overseas", "pearl talent", "virtuhire", "assist world",
    "persona talent", "bruntwork", "freeup", "20four7va", "prialto", "time etc", "cherry assistant",
    "sagan recruitment", "sagan", "toptal", "lemon.io", "turing", "andela", "proxify", "arc.dev", "x-team",
    "bairesdev", "storetasker", "mindrift", "telus digital", "invisible technologies", "outlier", "alignerr",
    "micro1", "mercor", "contra", "supportyourapp", "modsquad", "virtual staff sa", "remote career africa",
    "gebeya", "cloudstaff", "wing assistant", "athena", "belay", "boldly", "magic", "offerzen",
]

DEFAULTS = {"enabled": True, "lookback_days": 90, "company_mode": "warn", "platform_rule": True,
            "referral_dedup": True}

_SUFFIX = re.compile(r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|gmbh|ag|pty|corp|corporation|co|company|group|"
                     r"holdings|ab|bv|b\.v|sa|sas|srl|plc|oy|as|aps|kk|pte|sarl|nv|careers?|jobs|hiring|hq|"
                     r"remote|global|international|the)\b\.?", re.I)
FAMILY_LABEL = {"dev": "Dev", "design": "Design", "admin": "Admin", "bookkeeping": "Bookkeeping",
                "ecommerce": "Ecommerce", "sales": "Sales"}


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


def history(c, job, s=None):
    """Other roles at the same company that are in Review, approved or sent within the look-back window."""
    s = s or settings()
    n = job.get("company_norm") or norm_company(job.get("company"))
    if not n or len(n) < 2:
        return []
    since = (datetime.date.today() - datetime.timedelta(days=int(s["lookback_days"]))).isoformat()
    rows = c.execute(f"""SELECT id, title, company, family, tier, status, score, applied_at, updated_at, found_at,
                         version_sent FROM jobs WHERE company_norm=? AND id<>? AND status IN ({','.join('?' * len(ACTIVE))})
                         AND coalesce(applied_at, updated_at, found_at) >= ?""",
                     [n, job["id"], *ACTIVE, since]).fetchall()
    return [dict(r) for r in rows]


def _describe(o):
    label = o.get("version_sent") or version_label(o.get("family"), o.get("tier"))
    if o["status"] == "submitted":
        return f"Already applied {_day(_when(o))} with {label} ({o['title']})"
    if o["status"] in ("approved", "submitting"):
        return f"Already approved {_day(_when(o))} with {label} ({o['title']})"
    if o["status"] == "needs_you":
        return f"Started {_day(_when(o))} with {label} ({o['title']}) - check whether you finished it"
    return f"Also in Review with {label} ({o['title']}) - send only one version"


def check(c, job, cfg=None):
    """Returns None when the role is clear, otherwise a dict:
         level   "block"  - do not send (platform already has another family, or company_mode=skip)
                 "warn"   - show in Review; you decide
                 "info"   - same version already went to this company; nothing to do
                 "wins"   - platform rule: this role is the strongest match, `losers` are the weaker
                            roles from other families at the same platform that should be skipped
         message text for Review / Notion / the run log
         rule    "platform" | "company"
    """
    s = settings(cfg)
    if not s.get("enabled", True) or not job.get("family"):
        return None
    others = history(c, job, s)
    if not others:
        return None
    mine = (job.get("family"), job.get("tier"))
    other_version = [o for o in others if (o["family"], o["tier"]) != mine]

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
                        "message": f"Platform rule: this is your strongest match at {job.get('company')} "
                                   f"(fit {int(job.get('score') or 0)} vs {int(best.get('score') or 0)}), so "
                                   f"the {', '.join(sorted({version_label(o['family'], o['tier']) for o in other_fam}))} "
                                   "role(s) there were skipped."}
            return {"level": "block", "rule": "platform",
                    "message": f"Platform rule: a stronger {version_label(best['family'], best['tier'])} match is "
                               f"already lined up at {job.get('company')} ({best['title']}, fit "
                               f"{int(best.get('score') or 0)}). One family per platform."}

    if other_version:
        o = sorted(other_version, key=lambda o: (o["status"] not in SENT, -(o.get("score") or 0)))[0]
        level = "block" if s.get("company_mode") == "skip" else "warn"
        more = f" (+{len(other_version) - 1} more)" if len(other_version) > 1 else ""
        return {"level": level, "rule": "company", "message": _describe(o) + more}
    o = others[0]
    return {"level": "info", "rule": "company",
            "message": f"Same version ({version_label(o['family'], o['tier'])}) also used for {o['title']}"}


def note_for(res):
    return res["message"] if res and res["level"] in ("warn", "block", "info", "wins") else None
