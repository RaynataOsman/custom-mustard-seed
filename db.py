"""SQLite store for jobs, contacts and per-board health."""
import json, sqlite3
from util import DATA, now_iso

DB_PATH = DATA / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,              -- hash of company+title
  source TEXT, board TEXT,
  url TEXT, apply_url TEXT,
  title TEXT, company TEXT,
  location TEXT, geo_ok INTEGER, geo_reason TEXT,
  salary TEXT, employment_type TEXT,
  description TEXT,
  posted_at TEXT, found_at TEXT, updated_at TEXT,
  family TEXT, tier TEXT, score REAL, score_reasons TEXT,
  ai_ban INTEGER DEFAULT 0,
  status TEXT DEFAULT 'new',        -- new|filtered|preparing|ready|approved|retry|submitting|submitted|needs_you|skipped|failed|expired
  status_note TEXT,
  retry_note TEXT,
  resume_docx TEXT, resume_pdf TEXT, cover_letter TEXT, interview_prep TEXT,
  gaps TEXT, edits_log TEXT, llm_used TEXT,
  notion_page_id TEXT,
  applied_at TEXT,
  employer_type TEXT, employer_reason TEXT, tz_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS sync_state (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT, notion_page_id TEXT,
  company TEXT, name TEXT, headline TEXT, url TEXT,
  kind TEXT,                         -- recruiter|hiring_manager|team|email
  rank INTEGER, note TEXT, followup TEXT,
  sent INTEGER DEFAULT 0, sent_at TEXT,
  found_at TEXT,
  UNIQUE(job_id, url)
);
CREATE TABLE IF NOT EXISTS board_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  board TEXT, kind TEXT, started TEXT, seconds REAL,
  ok INTEGER, fetched INTEGER, matched INTEGER, new INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, job_id TEXT, event TEXT, detail TEXT
);
"""


_SCHEMA_DONE = set()  # DB paths already migrated in this process


def conn():
    """Autocommit connection (each statement commits at once) so no caller can hold the write lock
    across slow network work - a long LinkedIn board used to lock out cloud sync for 15+ minutes."""
    c = sqlite3.connect(DB_PATH, timeout=60, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=60000")
    if str(DB_PATH) in _SCHEMA_DONE:
        _backfill_norms(c)  # cheap: two indexed-null checks, writes only when something is missing
        return c
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    for col in ("employer_type", "employer_reason", "tz_reason", "company_norm", "lock_note", "version_sent", "contact_keys"):
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass  # already there
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN allow_override INTEGER DEFAULT 0")  # "Allow anyway" pressed by the owner
    except sqlite3.OperationalError:
        pass
    for col, typ in (("links", "INTEGER"), ("hits", "INTEGER"), ("health", "TEXT")):
        try:
            c.execute(f"ALTER TABLE board_runs ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("ALTER TABLE contacts ADD COLUMN url_norm TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute("CREATE INDEX IF NOT EXISTS ix_jobs_company_norm ON jobs(company_norm)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_contacts_url_norm ON contacts(url_norm)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_board_runs_board ON board_runs(board, id)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_jobs_ck_null ON jobs(status) WHERE contact_keys IS NULL")
    _backfill_norms(c)
    _SCHEMA_DONE.add(str(DB_PATH))
    return c


def _backfill_norms(c):
    """Fill company_norm / url_norm for rows written before these columns existed (runs once, then no-ops)."""
    from safeguards import norm_company, norm_profile_url
    jobs = c.execute("SELECT id, company FROM jobs WHERE company_norm IS NULL").fetchall()
    if jobs:
        c.executemany("UPDATE jobs SET company_norm=? WHERE id=?", [(norm_company(r["company"]), r["id"]) for r in jobs])
    people = c.execute("SELECT id, url FROM contacts WHERE url_norm IS NULL").fetchall()
    if people:
        c.executemany("UPDATE contacts SET url_norm=? WHERE id=?", [(norm_profile_url(r["url"]), r["id"]) for r in people])
    keyrows = c.execute("SELECT id, apply_url, url, description FROM jobs WHERE contact_keys IS NULL "
                        "AND status NOT IN ('filtered','expired','failed')").fetchall()
    if keyrows:  # recruiter keys (emails / hiring account / LinkedIn) used by the recruiter safeguard
        from safeguards import contact_keys
        c.executemany("UPDATE jobs SET contact_keys=? WHERE id=?",
                      [(contact_keys(r["apply_url"], r["url"], r["description"]), r["id"]) for r in keyrows])
    if jobs or people or keyrows:
        c.commit()


def upsert_job(c, j):
    """Insert a newly found job. Returns True if it was new."""
    row = c.execute("SELECT id, status FROM jobs WHERE id=?", (j["id"],)).fetchone()
    if row:
        # keep a better (longer) description / apply url if we found one now
        c.execute("""UPDATE jobs SET description=CASE WHEN length(coalesce(?,''))>length(coalesce(description,''))
                     THEN ? ELSE description END,
                     contact_keys=CASE WHEN length(coalesce(?,''))>length(coalesce(description,'')) THEN NULL ELSE contact_keys END,
                     apply_url=coalesce(apply_url, ?), company=coalesce(nullif(company,''), ?),
                     updated_at=? WHERE id=?""",
                  (j.get("description"), j.get("description"), j.get("description"), j.get("apply_url"), j.get("company"), now_iso(), j["id"]))
        if j.get("company"):
            from safeguards import norm_company
            c.execute("UPDATE jobs SET company_norm=? WHERE id=? AND coalesce(company_norm,'')=''",
                      (norm_company(j["company"]), j["id"]))
        return False
    from safeguards import norm_company
    j["company_norm"] = norm_company(j.get("company"))
    cols = ["id", "source", "board", "url", "apply_url", "title", "company", "location", "salary",
            "employment_type", "description", "posted_at", "company_norm"]
    vals = [j.get(k) for k in cols]
    c.execute(f"INSERT INTO jobs ({','.join(cols)}, found_at, updated_at, status) VALUES "
              f"({','.join('?' * len(cols))}, ?, ?, 'new')", vals + [now_iso(), now_iso()])
    return True


def set_job(c, job_id, **fields):
    if not fields:
        return
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k}=?" for k in fields)
    c.execute(f"UPDATE jobs SET {sets} WHERE id=?", list(fields.values()) + [job_id])


def event(c, job_id, ev, detail=""):
    c.execute("INSERT INTO events (ts, job_id, event, detail) VALUES (?,?,?,?)",
              (now_iso(), job_id, ev, detail if isinstance(detail, str) else json.dumps(detail)))


def rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args).fetchall()]
