"""15 Oct 2026 config update. Safe to run more than once: it only adds what is missing.
Backs up config.json to data/config_backup_<time>.json first.

Adds: safeguards, cloud (online dashboard), new boards (Vacancy Mail, Zimbajob, Tanqeeb UAE,
Dubai Careers, RAK Government careers, Make it in Germany, GovAI, Canada Job Bank LMIA), turns on
Ruby on Remote and NaukriGulf with working link patterns, adds Ruby/Rails to the dev family,
lets Gulf boards count UAE/Saudi/Qatar roles as reachable, and fixes the Persona mix-up.
"""
import json, sys, time, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CFG = ROOT / "config.json"
DATA = ROOT / "data"

GULF = ["united arab emirates", "uae", "dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah", "saudi", "riyadh",
        "jeddah", "dammam", "qatar", "doha", "kuwait", "bahrain", "manama", "oman", "muscat"]
ZIM = ["zimbabwe", "harare", "bulawayo", "mutare", "gweru", "masvingo", "kwekwe", "victoria falls"]

NEW_BOARDS = [
    {"name": "Vacancy Mail (Zimbabwe)", "kind": "render", "enabled": True, "url": "https://vacancymail.co.zw/jobs/",
     "urls": ["https://vacancymail.co.zw/jobs/", "https://vacancymail.co.zw/jobs/?page=2", "https://vacancymail.co.zw/jobs/?page=3"],
     "link_pattern": r"vacancymail\.co\.zw/jobs/[a-z0-9-]+-\d+/?$", "accept_countries": ZIM, "max_details": 15},
    {"name": "Zimbajob (Zimbabwe)", "kind": "render", "enabled": True,
     "url": "https://www.zimbajob.com/job-vacancies-search-zimbabwe", "accept_countries": ZIM, "max_details": 12,
     "link_pattern": r"zimbajob\.com/(?!job-vacancies-search)[a-z0-9-]+/?[a-z0-9-]*\d{3,}"},
    {"name": "Tanqeeb UAE", "kind": "render", "enabled": True, "track": "relocation", "accept_countries": GULF,
     "url": "https://uae.tanqeeb.com/jobs/search?keywords={q}",
     "link_pattern": r"tanqeeb\.com/jobs-in-[a-z]+/all/jobs/\d+\.html$", "max_details": 12},
    {"name": "Dubai Careers (government)", "kind": "render", "enabled": True, "track": "relocation", "accept_countries": GULF,
     "url": "https://jobs.dubaicareers.ae/careersection/dubaicareers/jobsearch.ftl?lang=en",
     "link_pattern": r"jobdetail\.ftl\?job=\d+", "url_strip": r"&tz=.*$", "same_host": True, "max_details": 12},
    {"name": "RAK Government careers", "kind": "render", "enabled": True, "track": "relocation", "accept_countries": GULF,
     "url": "https://careers.rak.ae/search/?q={q}", "link_pattern": r"careers\.rak\.ae/job/", "max_details": 10},
    {"name": "Make it in Germany", "kind": "render", "enabled": True, "track": "relocation", "sponsor_board": True,
     "url": "https://www.make-it-in-germany.com/en/working-in-germany/job-listings?tx_solr%5Bq%5D={q}",
     "link_pattern": r"job-listings/job/job-[\w.-]+-S$", "max_details": 12},
    {"name": "GovAI (UK)", "kind": "render", "enabled": True, "track": "relocation", "sponsor_board": True,
     "url": "https://www.governance.ai/opportunities", "link_pattern": r"governance\.ai/opportunities/[a-z0-9-]+$",
     "max_details": 8},
]

UPDATES = {
    "Ruby on Remote": {"enabled": True, "why_off": None,
                       "urls": ["https://rubyonremote.com/remote-jobs-in-anywhere/",
                                "https://rubyonremote.com/remote-jobs-in-africa/",
                                "https://rubyonremote.com/remote-jobs-in-south-africa/"],
                       "link_pattern": r"rubyonremote\.com/jobs/\d+-", "max_details": 15},
    "NaukriGulf": {"enabled": True, "track": "relocation", "accept_countries": GULF, "q_slug": True,
                   "url": "https://www.naukrigulf.com/{q}-jobs", "link_pattern": r"naukrigulf\.com/.+-jid-\d+$",
                   "max_details": 12},
    "Canada Job Bank": {"name": "Canada Job Bank (LMIA)", "enabled": True, "track": "relocation",
                        "urls": ["https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring={q}&fskl=101010",
                                 "https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring={q}&fskl=101020"],
                        "link_pattern": r"/jobsearch/jobposting/\d+", "url_strip": r";jsessionid=[^?]*|\?source=searchresults$",
                        "max_details": 12, "why_off": None},
    "Bayt (Gulf)": {"accept_countries": GULF},
    "GulfTalent": {"accept_countries": GULF},
}

SIGNINS = [
    {"name": "Somewhere (candidate profile)", "url": "https://somewhere.com/candidates", "use": "apply",
     "why": "Somewhere has no public job list - roles come to your candidate profile and by email (the Gmail reader now picks up Somewhere emails)."},
    {"name": "Work in Austria Talent Hub", "url": "https://jobs.workinaustria.com/?lang=en&auth=a-login", "use": "apply",
     "why": "Austria's Talent Hub only shows its jobs after you sign in (free account)."},
]


def main():
    raw = CFG.read_text(encoding="utf-8-sig")
    cfg = json.loads(raw)
    DATA.mkdir(exist_ok=True)
    shutil.copy(CFG, DATA / f"config_backup_{time.strftime('%Y%m%d_%H%M')}.json")
    done = []

    import safeguards
    sg = cfg.setdefault("safeguards", {})
    for k, v in safeguards.DEFAULTS.items():
        if k not in sg:
            sg[k] = v
            done.append(f"safeguards.{k}")
    sg.setdefault("platforms", safeguards.DEFAULT_PLATFORMS)

    cl = cfg.setdefault("cloud", {})
    for k, v in {"enabled": True, "supabase_url": "https://dkjfqflzcuajrsbxrrhv.supabase.co",
                 "anon_key": "sb_publishable_dzTYW_gZaGsNmv_vDjsEbA_Dej7bx3F", "web_url": "", "found_limit": 150}.items():
        if k not in cl:
            cl[k] = v
            done.append(f"cloud.{k}")

    names = {b["name"] for b in cfg["boards"]}
    email_idx = next((i for i, b in enumerate(cfg["boards"]) if b.get("kind") == "email_alerts"), len(cfg["boards"]))
    for b in NEW_BOARDS:
        if b["name"] not in names:
            cfg["boards"].insert(email_idx, b)
            email_idx += 1
            done.append(f"board {b['name']}")
    for b in cfg["boards"]:
        up = UPDATES.get(b["name"])
        if up:
            for k, v in up.items():
                if v is None:
                    b.pop(k, None)
                else:
                    b[k] = v
            done.append(f"updated {b['name']}")
        if b.get("kind") == "email_alerts" and b.get("senders"):
            for s in ("substack", "beehiiv", "somewhere"):
                if s not in b["senders"]:
                    b["senders"].append(s)

    dev = cfg["families"].get("dev")
    if dev and not any("ruby" in p for p in dev["title_patterns"]):
        dev["title_patterns"] += [r"\bruby\b", r"\brails\b"]
        done.append("dev family: ruby / rails")
    qs = cfg["search"].setdefault("queries", [])
    if "ruby on rails developer" not in qs:
        qs.append("ruby on rails developer")
        done.append("query: ruby on rails developer")

    w = cfg.get("companies_to_watch", [])
    for i, n in enumerate(w):
        if isinstance(n, str) and n == "Persona":
            w[i] = "Persona Talent"
            done.append("companies_to_watch: Persona -> Persona Talent")

    si = cfg.setdefault("signins", [])
    have = {s.get("url") for s in si}
    for s in SIGNINS:
        if s["url"] not in have:
            si.append(s)
            done.append(f"sign-in {s['name']}")

    CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # the 'Persona' feed was Persona (identity verification), not Persona Talent - drop it and its unprepared roles
    cache = DATA / "ats_cache.json"
    try:
        ac = json.loads(cache.read_text())
        if "Persona" in ac:
            ac.pop("Persona")
            ac["Persona Talent"] = {"kind": None, "checked": time.strftime("%Y-%m-%d"), "note": "no public ATS feed found"}
            cache.write_text(json.dumps(ac, indent=1))
            done.append("ats_cache: removed wrong Persona feed")
    except Exception:
        pass
    import db
    c = db.conn()
    n = c.execute("""UPDATE jobs SET status='filtered', geo_reason='wrong company: Persona (identity verification), not Persona Talent'
                     WHERE company='Persona' AND status IN ('new','filtered')""").rowcount
    c.commit()
    if n:
        done.append(f"{n} Persona (identity company) roles filtered")
    print("config updated:\n - " + "\n - ".join(done or ["nothing to add"]))


if __name__ == "__main__":
    main()
