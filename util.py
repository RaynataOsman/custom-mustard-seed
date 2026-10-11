"""Shared helpers: paths, config, keys, HTTP session, text cleanup, logging."""
import json, os, re, sys, time, hashlib, datetime, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LOGS = ROOT / "logs"
OUT = ROOT / "out"
MASTERS = ROOT / "masters"
for _d in (DATA, LOGS, OUT):
    _d.mkdir(exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")


def load_config():
    with open(ROOT / "config.json", encoding="utf-8-sig") as f:
        return json.load(f)


FEATURE_DEFAULTS = {
    "scan_boards": True,      # read the job boards on a schedule
    "email_alerts": True,     # read job-alert emails from Gmail
    "ai_tailoring": True,     # use the free AI to rewrite bullets + write cover letters (off = keyword mode)
    "referrals": True,        # look up recruiters / hiring managers and draft LinkedIn notes
    "notion": True,           # write rows to the Notion tracker
    "auto_fill": True,        # open application forms and fill them after you approve
}


def feature(name, cfg=None):
    """On/off switches from config.json -> features (Settings > Features in the dashboard)."""
    cfg = cfg or load_config()
    return bool(cfg.get("features", {}).get(name, FEATURE_DEFAULTS.get(name, True)))


def save_config_text(text):
    json.loads(text)  # validate first
    (ROOT / "config.json").write_text(text, encoding="utf-8")


def load_keys():
    """keys.env holds NAME=value lines. Environment variables override."""
    keys = {}
    p = ROOT / "keys.env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    for k in list(keys) + ["GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
                           "NOTION_TOKEN", "CEREBRAS_API_KEY", "MISTRAL_API_KEY"]:
        if os.environ.get(k):
            keys[k] = os.environ[k]
    return keys


def save_keys(updates):
    keys = load_keys()
    for k, v in updates.items():
        if v is None or v == "":
            continue
        keys[k] = v.strip()
    lines = [f"{k}={v}" for k, v in keys.items()]
    (ROOT / "keys.env").write_text("\n".join(lines) + "\n", encoding="utf-8")


_session = None


def http():
    global _session
    if _session is None:
        import requests
        _session = requests.Session()
        _session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    return _session


def get(url, **kw):
    kw.setdefault("timeout", 30)
    last = None
    for attempt in range(3):
        try:
            r = http().get(url, **kw)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                last = r
                continue
            return r
        except Exception as e:  # network blips
            last = e
            time.sleep(2 * (attempt + 1))
    if isinstance(last, Exception):
        raise last
    return last


# ---------- text cleanup (ATS-safe plain ASCII) ----------
_REPL = {
    "—": "-", "–": "-", "‒": "-", "‐": "-", "‑": "-",
    "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"',
    "•": "-", "·": "-", "…": "...", " ": " ", " ": " ", " ": " ",
    "®": "", "™": "", "→": "->",
}
_INVISIBLE = re.compile("[​-‏ -‮⁠-⁤﻿­]")


def ascii_clean(s):
    if not s:
        return s
    s = _INVISIBLE.sub("", s)
    for a, b in _REPL.items():
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    return s


def strip_html(html):
    if not html:
        return ""
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    import html as _h
    t = _h.unescape(html)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def slug(s, n=60):
    s = ascii_clean(s or "")
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:n] or "x"


def job_key(company, title):
    norm = lambda x: re.sub(r"[^a-z0-9]", "", (x or "").lower())
    return hashlib.sha1(f"{norm(company)}|{norm(title)}".encode()).hexdigest()[:16]


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def today():
    return datetime.date.today().isoformat()


class Log:
    """Prints and appends to logs/<name>_<date>.log so the UI can show it."""

    def __init__(self, name):
        self.path = LOGS / f"{name}_{today()}.log"

    def __call__(self, *parts):
        line = f"[{datetime.datetime.now():%H:%M:%S}] " + " ".join(str(p) for p in parts)
        print(line, flush=True)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def force_utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
