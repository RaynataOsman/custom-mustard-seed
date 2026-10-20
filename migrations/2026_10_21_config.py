"""21 Oct 2026 config update: more boards. Safe to run more than once: it only adds what is missing.
Backs up config.json to data/config_backup_<time>.json first.

Already scraped, so NOT added again: Remotive, We Work Remotely, Arbeitnow, Relocate.me, Wellfound,
Bayt, GulfTalent.

Added (Europe / Ireland / Canada / Asia, all on the relocation track because the roles are on-site in
that country; roles that don't mention sponsorship land in 'check' instead of being thrown away):
EU-Startups jobs, Berlin Startup Jobs, GermanTechJobs, SwissDevJobs, DevITJobs (NL), Techleap,
IrishJobs, Jobs Ireland, Communitech Work In Tech, Tech West Canada, Tech in Asia, NodeFlair, Habr Career.
Added but switched off: WORK180 (job pages need an account; platform is aimed at women, so only turn it on
if it applies to you).
Not added: siliconroundabout.tech - it is a deep-tech community/VC site with no job listings.

Patterns marked "unverified" could not be test-read from the build machine. Run one scan and check the
'N matching links' line in the log for that board; if it says 0, tune link_pattern in Boards.
Usage:  python migrations/2026_10_21_config.py            (config.json)
        python migrations/2026_10_21_config.py --example  (config.example.json, for fresh installs)
"""
import json, sys, time, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

NEW_BOARDS = [
    {"name": "EU-Startups jobs", "kind": "render", "enabled": True, "track": "relocation",
     "url": "https://www.eu-startups.com/startup-jobs/",
     "link_pattern": r"eu-startups\.com/job/[a-z0-9-]+/?$", "max_details": 12},
    {"name": "Berlin Startup Jobs", "kind": "render", "enabled": True, "track": "relocation",
     "urls": ["https://berlinstartupjobs.com/engineering/", "https://berlinstartupjobs.com/"],
     "link_pattern": r"berlinstartupjobs\.com/(?!page/)[a-z-]+/(?!page/)[a-z0-9-]{12,}/?$", "max_details": 12},
    {"name": "GermanTechJobs", "kind": "render", "enabled": True, "track": "relocation",
     "url": "https://germantechjobs.de/",
     "link_pattern": r"germantechjobs\.de/jobs/[^/?]+", "url_strip": r"\?utm_.*$", "max_details": 12},
    {"name": "SwissDevJobs", "kind": "render", "enabled": True, "track": "relocation",
     "url": "https://swissdevjobs.ch/jobs",
     "link_pattern": r"swissdevjobs\.ch/jobs/[A-Za-z0-9][^/?]+", "max_details": 12},
    {"name": "DevITJobs (Netherlands)", "kind": "render", "enabled": True, "track": "relocation",
     "url": "https://devitjobs.nl/", "max_details": 12,
     "note": "unverified link pattern - uses the default job-link match"},
    {"name": "Techleap jobs (Netherlands)", "kind": "render", "enabled": True, "track": "relocation",
     "url": "https://jobs.techleap.nl/?lang=en#vacancies", "link_pattern": r"jobs\.techleap\.nl/companies/[^/]+/jobs/\d+",
     "max_details": 12, "note": "unverified link pattern (Getro-style board)"},
    {"name": "IrishJobs.ie", "kind": "render", "enabled": True, "track": "relocation", "q_slug": True,
     "url": "https://www.irishjobs.ie/jobs/{q}", "link_pattern": r"irishjobs\.ie/job/[^?]+", "max_details": 12,
     "note": "unverified link pattern"},
    {"name": "Jobs Ireland (gov)", "kind": "render", "enabled": True, "track": "relocation",
     "url": "https://jobsireland.ie/en-US/browse-jobs", "link_pattern": r"jobsireland\.ie/en-US/job-Details/\d+",
     "max_details": 12, "note": "unverified link pattern; public vacancies are mostly non-tech"},
    {"name": "Communitech Work In Tech (Canada)", "kind": "render", "enabled": True, "track": "relocation",
     "url": "https://www1.communitech.ca/jobs", "link_pattern": r"communitech\.ca/companies/[^/]+/jobs/\d+",
     "max_details": 12, "note": "unverified link pattern (Getro-style board)"},
    {"name": "Tech West Canada", "kind": "render", "enabled": True, "track": "relocation",
     "url": "https://techwestcanada.ca/", "max_details": 12,
     "note": "unverified - site could not be read by the build machine; check the scan log"},
    {"name": "Tech in Asia Jobs", "kind": "render", "enabled": True, "track": "relocation",
     "url": "https://www.techinasia.com/jobs", "link_pattern": r"techinasia\.com/jobs/[0-9a-f-]{20,}",
     "max_details": 12, "note": "unverified link pattern - site blocked the build machine"},
    {"name": "NodeFlair (Singapore)", "kind": "render", "enabled": True, "track": "relocation",
     "url": "https://nodeflair.com/jobs?countries%5B%5D=Singapore", "link_pattern": r"nodeflair\.com/jobs/\d+",
     "max_details": 12, "note": "unverified job-link pattern"},
    {"name": "Habr Career", "kind": "render", "enabled": True, "track": "relocation",
     "urls": ["https://career.habr.com/vacancies?remote=true&type=all",
              "https://career.habr.com/vacancies?remote=true&type=all&page=2"],
     "link_pattern": r"career\.habr\.com/vacancies/\d+$", "max_details": 12,
     "note": "mostly Russian-language postings"},
    {"name": "WORK180", "kind": "render", "enabled": False,
     "why_off": "Job pages sit behind per-employer pages and an account; the platform is aimed at women - turn on only if it applies to you",
     "url": "https://work180.com/search", "max_details": 10},
]


def add_boards(cfg):
    done = []
    names = {b["name"].lower() for b in cfg["boards"]}
    urls = {b["url"].rstrip("/").lower() for b in cfg["boards"] if b.get("url")}
    idx = next((i for i, b in enumerate(cfg["boards"]) if b.get("kind") == "email_alerts"), len(cfg["boards"]))
    for b in NEW_BOARDS:
        if b["name"].lower() in names or (b.get("url") and b["url"].rstrip("/").lower() in urls):
            continue
        cfg["boards"].insert(idx, b)
        idx += 1
        done.append(f"board {b['name']}")
    return done


def main():
    example = "--example" in sys.argv
    path = ROOT / ("config.example.json" if example else "config.json")
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    if not example:
        DATA.mkdir(exist_ok=True)
        shutil.copy(path, DATA / f"config_backup_{time.strftime('%Y%m%d_%H%M')}.json")
    done = add_boards(cfg)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"{path.name} updated:\n - " + "\n - ".join(done or ["nothing to add"]))


if __name__ == "__main__":
    main()
