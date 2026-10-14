"""UK register of licensed sponsors (workers) - every company allowed to sponsor a UK work visa.

The register is a daily CSV on gov.uk. We download it at most once a week into data/uk_sponsors.txt
(one normalised company name per line) and use it on the relocation track: a UK role at a company
on the register is marked "licensed UK visa sponsor", so it can sponsor you.
"""
import re, time
from util import DATA, get

PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
CACHE = DATA / "uk_sponsors.txt"
MAX_AGE = 7 * 86400
UK = re.compile(r"\b(united kingdom|uk|england|scotland|wales|northern ireland|london|manchester|birmingham|leeds|"
                r"glasgow|edinburgh|bristol|liverpool|cambridge|oxford|belfast|cardiff|reading|newcastle|sheffield|"
                r"nottingham|brighton|leicester)\b", re.I)
_NAMES = None


def refresh(log=print, force=False):
    if not force and CACHE.exists() and time.time() - CACHE.stat().st_mtime < MAX_AGE:
        return True
    from safeguards import norm_company
    try:
        html = get(PAGE, timeout=40).text
        m = re.search(r'https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv', html)
        if not m:
            log("  UK sponsor register: CSV link not found on gov.uk")
            return False
        import csv, io
        text = get(m.group(0), timeout=180).content.decode("utf-8-sig", errors="replace")
        names = set()
        for row in csv.reader(io.StringIO(text)):
            if row and row[0] and row[0] != "Organisation Name":
                n = norm_company(row[0])
                if n:
                    names.add(n)
        CACHE.write_text("\n".join(sorted(names)), encoding="utf-8")
        global _NAMES
        _NAMES = names
        log(f"  UK sponsor register: {len(names)} licensed sponsors saved")
        return True
    except Exception as e:
        log(f"  UK sponsor register: download failed ({e})")
        return False


def names():
    global _NAMES
    if _NAMES is None:
        try:
            _NAMES = set(CACHE.read_text(encoding="utf-8").split("\n"))
        except Exception:
            _NAMES = set()
    return _NAMES


def is_sponsor(company):
    """True / False, or None when the register isn't downloaded yet."""
    from safeguards import norm_company
    ns = names()
    if not ns:
        return None
    n = norm_company(company)
    if not n or len(n) < 3:
        return None
    return n in ns


def is_uk(job):
    return bool(UK.search(" ".join([job.get("location") or "", (job.get("description") or "")[:400]])))
