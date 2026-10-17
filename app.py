#!/usr/bin/env python3
"""Job Engine dashboard. Python standard library only.  python app.py [--port 8766] [--no-browser]
Binds to 127.0.0.1 (this PC only)."""
import json, os, re, subprocess, sys, threading, time, urllib.parse, webbrowser, mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import db
from util import ROOT, LOGS, OUT, load_config, save_config_text, load_keys, save_keys, now_iso, force_utf8_stdout, get

force_utf8_stdout()
PORT = 8766
RUNS = {}  # id -> {proc, log, label, started, status}
_lock = threading.Lock()
KEY_NAMES = ["GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY", "NOTION_TOKEN", "GMAIL_ADDRESS",
             "GMAIL_APP_PASSWORD", "CLOUD_TOKEN", "CLOUD_PASSWORD"]


RUN_JOBS = {"scan", "board", "prepare", "submit", "backfill", "retriage", "sweep", "tiers", "expire", "replies", "referrals",
            "all", "discover", "dryfill", "login"}


def start_run(job, arg=None):
    if job not in RUN_JOBS:
        return {"ok": False, "error": f"unknown run '{job}'"}
    with _lock:
        if any(r["status"] == "running" and r["job"] not in ("login",) for r in RUNS.values()) and job != "login":
            return {"ok": False, "error": "another run is in progress - wait for it to finish"}
        rid = str(int(time.time() * 1000))
        logp = LOGS / f"run_{rid}.log"
        if job == "login":
            cmd = [sys.executable, "-c", f"import render; render.open_login_browser({json.dumps(arg or 'https://www.linkedin.com/login')})"]
        else:
            cmd = [sys.executable, "pipeline.py", job] + ([arg] if arg else [])
        f = open(logp, "w", encoding="utf-8")
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        RUNS[rid] = {"id": rid, "job": job, "arg": arg, "proc": proc, "log": str(logp), "started": now_iso(),
                     "status": "running"}
        return {"ok": True, "id": rid}


def runs_snapshot():
    out = []
    for r in sorted(RUNS.values(), key=lambda x: x["id"], reverse=True)[:20]:
        if r["status"] == "running" and r["proc"].poll() is not None:
            r["status"] = "done" if r["proc"].returncode == 0 else f"failed ({r['proc'].returncode})"
        out.append({k: v for k, v in r.items() if k != "proc"})
    return out


_health_cache = {"t": 0, "v": {}}


def health(force=False):
    if not force and time.time() - _health_cache["t"] < 120:
        return _health_cache["v"]
    import pdf, notion_sync
    cfg = load_config()
    keys = load_keys()
    v = {"keys": {k: bool(keys.get(k)) for k in KEY_NAMES}, "pdf": pdf.available() or "none - install LibreOffice"}
    from concurrent.futures import ThreadPoolExecutor

    def searx():
        # 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and a closed port costs ~20 s
        try:
            u = cfg["referrals"]["searxng_url"].rstrip("/").replace("//localhost", "//127.0.0.1")
            return get(u + "/search", params={"q": "test", "format": "json"}, timeout=3).status_code == 200
        except Exception:
            return False

    def ollama():
        if not any(p.get("name") == "ollama" and p.get("enabled", True) for p in cfg.get("llm", {}).get("providers", [])):
            return "off"
        try:
            return [m["name"] for m in get("http://127.0.0.1:11434/api/tags", timeout=2).json().get("models", [])]
        except Exception:
            return None

    def notion():
        return notion_sync.health() if keys.get("NOTION_TOKEN") else "no token"
    with ThreadPoolExecutor(3) as ex:
        fs, fo, fn = ex.submit(searx), ex.submit(ollama), ex.submit(notion)
        v["searxng"] = fs.result()
        v["ollama"] = fo.result()
        v["notion"] = fn.result()
    if not v["searxng"]:
        v["searxng_note"] = "SearXNG is not running (start Docker Desktop). Referral search falls back to Chrome."
    v["masters"] = sorted(p.name for p in (ROOT / "masters").glob("*.docx"))
    v["resume_copies"] = cfg["paths"]["resume_copies"]
    _health_cache.update(t=time.time(), v=v)
    return v


def board_health_summary():
    """Latest health word per enabled board + how many of its last 5 runs were bad."""
    c = db.conn()
    cfg = load_config()
    out = []
    for b in cfg["boards"]:
        if not b.get("enabled", True):
            continue
        runs = db.rows(c, "SELECT started, health, fetched, matched, new, links, hits, error FROM board_runs "
                          "WHERE board=? ORDER BY id DESC LIMIT 5", (b["name"],))
        bad = sum(1 for r in runs if (r.get("health") or "").startswith(("broken", "blocked", "error", "needs", "empty")))
        out.append({"board": b["name"], "kind": b["kind"], "last": runs[0] if runs else None, "bad_of_last5": bad,
                    "note": b.get("note", "")})
    return out


def overview():
    c = db.conn()
    counts = {r["status"]: r["n"] for r in db.rows(c, "SELECT status, count(*) n FROM jobs GROUP BY status")}
    boards = db.rows(c, """SELECT b.* FROM board_runs b JOIN (SELECT board, max(id) mid FROM board_runs GROUP BY board) m
                           ON b.id=m.mid ORDER BY b.board""")
    totals = {r["board"]: r for r in db.rows(c, """SELECT board, count(*) runs, sum(fetched) fetched, sum(new) new,
                           sum(1-ok) errors FROM board_runs GROUP BY board""")}
    cfg = load_config()
    names = [b["name"] for b in cfg["boards"] if b.get("enabled", True)]
    seen = {b["board"] for b in boards}
    for n in names:
        if n not in seen:
            boards.append({"board": n, "never_run": True})
    for b in boards:
        b["totals"] = totals.get(b["board"])
    applied_week = db.rows(c, "SELECT count(*) n FROM jobs WHERE status='submitted' AND applied_at >= date('now','-7 day')")[0]["n"]
    contacts_pending = db.rows(c, "SELECT count(*) n FROM contacts WHERE sent=0")[0]["n"]
    return {"counts": counts, "boards": boards, "applied_week": applied_week, "contacts_pending": contacts_pending,
            "runs": runs_snapshot(), "not_scraped": cfg.get("not_scraped", {}).get("list", [])}


LENSES = {
    # quick categories on Review / All found. Each is a SQL condition on the jobs table.
    "best": "score >= 70 AND geo_ok = 1",
    "open_sa": "geo_ok = 1",
    "fresh": "date(coalesce(nullif(posted_at,''), found_at)) >= date('now','-3 day')",
    "contract": "(lower(coalesce(employment_type,'')) GLOB '*contract*' OR lower(coalesce(employment_type,'')) GLOB '*part*' "
                "OR lower(coalesce(employment_type,'')) GLOB '*freelance*' OR score_reasons LIKE '%stackable%')",
    "overseas": "employer_type IN ('overseas_direct','overseas_platform')",
    "long_shot": "(score < 50 OR geo_ok IS NULL)",
    "ai_ban": "ai_ban = 1",
}


def _job_filters(q):
    where, args = [], []
    status = q.get("status", ["ready"])[0]
    if status != "all":
        where.append("status IN (" + ",".join("?" * len(status.split(","))) + ")")
        args += status.split(",")
    for key, col in (("board", "board"), ("family", "family"), ("tier", "tier"), ("employer", "employer_type")):
        val = q.get(key, [""])[0]
        if val:
            where.append(f"{col}=?")
            args.append(val)
    text = q.get("q", [""])[0].strip()
    if text:
        where.append("(title LIKE ? OR company LIKE ? OR description LIKE ?)")
        args += [f"%{text}%"] * 3
    if q.get("min_score", [""])[0]:
        where.append("score >= ?")
        args.append(float(q["min_score"][0]))
    return where, args


def list_jobs(q):
    c = db.conn()
    where, args = _job_filters(q)
    lens = q.get("lens", [""])[0]
    if lens in LENSES:
        where.append("(" + LENSES[lens] + ")")
    order = {"newest": "coalesce(nullif(posted_at,''), found_at) DESC", "company": "company COLLATE NOCASE",
             "fit": "score DESC, found_at DESC"}.get(q.get("sort", ["fit"])[0], "score DESC, found_at DESC")
    limit = min(int(q.get("limit", ["300"])[0] or 300), 1000)
    sql = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order} LIMIT {limit}"
    jobs = db.rows(c, sql, args)
    ids = [j["id"] for j in jobs]
    contacts = {}
    if ids:
        for ct in db.rows(c, f"SELECT * FROM contacts WHERE job_id IN ({','.join('?' * len(ids))}) ORDER BY rank", ids):
            contacts.setdefault(ct["job_id"], []).append(ct)
    import safeguards
    sg = safeguards.settings()
    for j in jobs:
        lk = safeguards.lock_for(c, j)
        if lk:
            j["lock"] = lk
        j["version"] = j.get("version_sent") or safeguards.version_label(j.get("family"), j.get("tier"))
        j["is_platform"] = safeguards.is_platform(j, sg)
        j["contacts"] = contacts.get(j["id"], [])
        j["description"] = (j.get("description") or "")[:6000]
        for k in ("interview_prep", "gaps", "edits_log"):
            try:
                j[k] = json.loads(j[k]) if j.get(k) else None
            except Exception:
                pass
    return jobs


def job_facets(q):
    """Counts for each quick category and the dropdowns, for the current status + dropdown filters."""
    c = db.conn()
    where, args = _job_filters(q)
    base = " AND ".join(where) or "1=1"
    out = {"total": db.rows(c, f"SELECT count(*) n FROM jobs WHERE {base}", args)[0]["n"], "lenses": {}}
    for k, cond in LENSES.items():
        out["lenses"][k] = db.rows(c, f"SELECT count(*) n FROM jobs WHERE {base} AND ({cond})", args)[0]["n"]
    sw, sa = _job_filters({"status": q.get("status", ["ready"])})
    sb = " AND ".join(sw) or "1=1"
    for col in ("family", "tier", "board", "employer_type"):
        out[col] = [[r["v"], r["n"]] for r in db.rows(
            c, f"SELECT {col} v, count(*) n FROM jobs WHERE {sb} AND {col} IS NOT NULL GROUP BY {col} ORDER BY n DESC", sa)]
    return out


def _cover_example_path():
    cfg = load_config()
    p = Path(cfg.get("cover_letter", {}).get("example_file") or "masters/cover_letter_example.txt")
    return p if p.is_absolute() else ROOT / p


def cover_example_get():
    p = _cover_example_path()
    return {"text": p.read_text(encoding="utf-8") if p.exists() else "", "path": str(p)}


def cover_example_set(b):
    from util import ascii_clean
    p = _cover_example_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(ascii_clean(b.get("text", "")).strip() + "\n", encoding="utf-8")
    return {"ok": True}


def signins():
    cfg = load_config()
    try:
        seen = json.loads((ROOT / "data" / "signins.json").read_text())
    except Exception:
        seen = {}
    out = []
    for s in cfg.get("signins", []):
        host = urllib.parse.urlparse(s["url"]).netloc
        out.append(dict(s, last_scan=seen.get(f"real-chrome|{host}"), last_apply=seen.get(f"apply-profile|{host}")))
    import render
    return {"sites": out, "window_open": render.login_window_open()}


def job_action(job_id, body):
    c = db.conn()
    a = body.get("action")
    note = (body.get("note") or "").strip()
    job = db.rows(c, "SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job:
        return {"ok": False, "error": "not found"}
    if a == "approve":
        import safeguards
        guard = safeguards.check(c, job[0])
        if guard and guard["level"] == "block" and not body.get("override"):
            return {"ok": False, "error": guard["message"], "lock": guard}
        if guard and guard["level"] == "wins":
            lose = guard.get("loser_note") or f"Platform rule: you approved {job[0]['title']} at {job[0]['company']} instead"
            for lid in guard["losers"]:
                db.set_job(c, lid, status="skipped", lock_note=lose, status_note=lose)
        db.set_job(c, job_id, status="approved", lock_note=safeguards.note_for(guard))
    elif a == "allow":  # "Allow anyway": the safeguards never hold or skip this role again
        keep = job[0]["status"]
        if keep == "skipped":
            keep = "ready" if job[0].get("resume_docx") else "new"
        db.set_job(c, job_id, allow_override=1, status=keep, lock_note=None, status_note=None)
    elif a == "retry":
        db.set_job(c, job_id, status="retry", retry_note=note or None)
    elif a == "skip":
        db.set_job(c, job_id, status="skipped", status_note=note or None)
    elif a == "reopen":
        db.set_job(c, job_id, status="ready")
    elif a == "done":  # finished by hand in the browser
        import safeguards
        db.set_job(c, job_id, status="submitted", applied_at=now_iso(), status_note="finished by you",
                   version_sent=safeguards.version_label(job[0].get("family"), job[0].get("tier")))
        c.commit()
        threading.Thread(target=lambda: subprocess.run([sys.executable, "-c",
                         f"import pipeline; pipeline.record_in_notion({json.dumps(job_id)})"], cwd=ROOT), daemon=True).start()
    else:
        return {"ok": False, "error": "unknown action"}
    db.event(c, job_id, a, note)
    c.commit()
    return {"ok": True}


def approve_all(body):
    """Bulk approve - but never a role with a safeguard warning (those need your eyes)."""
    import safeguards
    c = db.conn()
    ms = float(body.get("min_score", 60))
    n = held = 0
    for j in db.rows(c, "SELECT * FROM jobs WHERE status='ready' AND ai_ban=0 AND geo_ok=1 AND score>=? "
                        "ORDER BY score DESC", (ms,)):
        cur = db.rows(c, "SELECT status FROM jobs WHERE id=?", (j["id"],))
        if not cur or cur[0]["status"] != "ready":
            continue  # skipped earlier in this loop by the platform rule
        guard = safeguards.check(c, j)
        if guard and guard["level"] in ("warn", "block"):
            held += 1
            continue
        if guard and guard["level"] == "wins":
            lose = guard.get("loser_note") or f"Platform rule: {j['title']} at {j['company']} was approved instead"
            for lid in guard["losers"]:
                db.set_job(c, lid, status="skipped", lock_note=lose, status_note=lose)
        db.set_job(c, j["id"], status="approved", lock_note=safeguards.note_for(guard))
        c.commit()  # later roles in this loop must see this one as approved
        n += 1
    return {"ok": True, "approved": n, "held": held}


def cloud_get():
    import cloud_sync
    return cloud_sync.status()


def cloud_set(b):
    import cloud_sync
    cfg = load_config()
    cl = cfg.setdefault("cloud", {})
    if "enabled" in b:
        cl["enabled"] = bool(b["enabled"])
    for k in ("web_url", "supabase_url", "anon_key"):
        if isinstance(b.get(k), str) and b[k].strip():
            cl[k] = b[k].strip()
    save_config_text(json.dumps(cfg, indent=2))
    cloud_sync.STATUS["state"] = "refresh"
    cloud_sync.kick()
    return {"ok": True}


def safeguards_get():
    import safeguards
    s = safeguards.settings()
    return {k: s[k] for k in ("enabled", "lookback_days", "company_mode", "platform_rule", "referral_dedup",
                              "recruiter_check", "platforms")}


def safeguards_set(b):
    import safeguards
    cfg = load_config()
    sg = cfg.setdefault("safeguards", {})
    for k in ("enabled", "platform_rule", "referral_dedup", "recruiter_check"):
        if k in b:
            sg[k] = bool(b[k])
    if b.get("company_mode") in ("warn", "skip"):
        sg["company_mode"] = b["company_mode"]
    if str(b.get("lookback_days", "")).isdigit():
        sg["lookback_days"] = max(7, min(365, int(b["lookback_days"])))
    if isinstance(b.get("platforms"), list):
        sg["platforms"] = sorted({str(p).strip().lower() for p in b["platforms"] if str(p).strip()})
    save_config_text(json.dumps(cfg, indent=2))
    return {"ok": True}


def contact_sent(cid):
    c = db.conn()
    c.execute("UPDATE contacts SET sent=1, sent_at=? WHERE id=?", (now_iso(), cid))
    c.commit()
    ct = db.rows(c, "SELECT * FROM contacts WHERE id=?", (cid,))[0]
    pid = ct.get("notion_page_id")
    if not pid and not str(ct["job_id"]).startswith("notion:"):
        j = db.rows(c, "SELECT notion_page_id FROM jobs WHERE id=?", (ct["job_id"],))
        pid = j[0]["notion_page_id"] if j else None
    if pid:
        sent = db.rows(c, "SELECT name, sent_at FROM contacts WHERE (notion_page_id=? OR job_id IN "
                          "(SELECT id FROM jobs WHERE notion_page_id=?)) AND sent=1", (pid, pid))
        try:
            import notion_sync
            notion_sync.mark_connections_sent(pid, "; ".join(f'{s["name"]} ({s["sent_at"][:10]})' for s in sent))
        except Exception:
            pass
    return {"ok": True}


def all_contacts():
    c = db.conn()
    return db.rows(c, """SELECT ct.*, j.title, j.status job_status FROM contacts ct LEFT JOIN jobs j ON j.id=ct.job_id
                         ORDER BY ct.sent, ct.found_at DESC LIMIT 400""")


def manual_prepare(b):
    c = db.conn()
    jid = b.get("id")
    if not db.rows(c, "SELECT id FROM jobs WHERE id=?", (jid,)):
        return {"ok": False, "error": "analyse the job first"}
    cfg = load_config()
    fields = {"status": "new"}
    if b.get("family") in cfg["families"]:
        fields["family"] = b["family"]
    if b.get("tier") in cfg["families"].get(b.get("family"), {}).get("tiers", []):
        fields["tier"] = b["tier"]
    if b.get("note"):
        fields["retry_note"] = b["note"][:500]
    db.set_job(c, jid, **fields)
    c.commit()
    return start_run("prepare", jid)


def features_get():
    from util import FEATURE_DEFAULTS
    cfg = load_config()
    f = cfg.get("features", {})
    return {k: bool(f.get(k, v)) for k, v in FEATURE_DEFAULTS.items()}


def features_set(b):
    from util import FEATURE_DEFAULTS
    cfg = load_config()
    cfg.setdefault("features", {}).update({k: bool(v) for k, v in b.items() if k in FEATURE_DEFAULTS})
    save_config_text(json.dumps(cfg, indent=2))
    return {"ok": True}


def presets():
    p = ROOT / "presets" / "families.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def add_family(b):
    name = b.get("preset")
    pr = presets().get(name)
    if not pr:
        return {"ok": False, "error": "unknown preset"}
    cfg = load_config()
    if name in cfg["families"]:
        return {"ok": False, "error": "already added"}
    cfg["families"][name] = {k: v for k, v in pr.items() if k in ("title_patterns", "tiers", "headline", "core")}
    qs = cfg["search"].setdefault("queries", [])
    qs += [q for q in pr.get("queries", []) if q not in qs]
    save_config_text(json.dumps(cfg, indent=2))
    return {"ok": True, "masters_needed": [f"{name}_{t}.docx" for t in pr["tiers"]]}


PROFILE_FIELDS = ["first_name", "last_name", "email", "phone", "location", "linkedin", "portfolio", "github", "notice"]


def profile_get():
    cfg = load_config()
    pr = cfg["profile"]
    return {"fields": {k: pr.get(k, "") for k in PROFILE_FIELDS}, "rates": pr.get("rate_by_tier", {}),
            "international_only": bool(cfg["geo"].get("international_only")), "work_window": cfg["geo"].get("work_window_sast", "07:00-23:00"),
            "notion_database": cfg["notion"].get("database_id", ""), "resume_copies": cfg["paths"]["resume_copies"]}


def profile_set(b):
    cfg = load_config()
    pr = cfg["profile"]
    for k, v in (b.get("fields") or {}).items():
        if k in PROFILE_FIELDS:
            pr[k] = str(v).strip()
    pr["name"] = (pr.get("first_name", "") + " " + pr.get("last_name", "")).strip()
    if isinstance(b.get("rates"), dict):
        pr["rate_by_tier"] = {k: str(v).strip() for k, v in b["rates"].items() if k in ("J", "J-M", "HM", "M-S", "S", "ONE")}
    if "international_only" in b:
        cfg["geo"]["international_only"] = bool(b["international_only"])
    if re.fullmatch(r"\d{2}:\d{2}-\d{2}:\d{2}", b.get("work_window", "")):
        cfg["geo"]["work_window_sast"] = b["work_window"]
    m = re.search(r"([0-9a-f]{32})", (b.get("notion_database") or "").replace("-", ""))
    if m:
        cfg["notion"]["database_id"] = m.group(1)
    if b.get("resume_copies"):
        cfg["paths"]["resume_copies"] = b["resume_copies"].strip()
    save_config_text(json.dumps(cfg, indent=2))
    return {"ok": True}


def remove_family(b):
    cfg = load_config()
    name = b.get("family")
    if name not in cfg["families"] or len(cfg["families"]) == 1:
        return {"ok": False, "error": "keep at least one family"}
    cfg["families"].pop(name)
    pr = presets().get(name, {})
    cfg["search"]["queries"] = [q for q in cfg["search"].get("queries", []) if q not in pr.get("queries", [])]
    save_config_text(json.dumps(cfg, indent=2))
    return {"ok": True}


def upload_master(b):
    import base64
    cfg = load_config()
    fam, tier = b.get("family"), b.get("tier")
    if fam not in cfg["families"] or tier not in cfg["families"][fam]["tiers"]:
        return {"ok": False, "error": "pick a family and level that exist"}
    data = base64.b64decode(b.get("data_b64", ""))
    if not data.startswith(b"PK"):
        return {"ok": False, "error": "that is not a .docx file (save it from Word / Google Docs as .docx)"}
    dest = ROOT / "masters" / f"{fam}_{tier}.docx"
    dest.parent.mkdir(exist_ok=True)
    if dest.exists():
        dest.replace(dest.with_suffix(".docx.bak"))
    dest.write_bytes(data)
    try:
        import tailor
        tailor.strip_fonts(dest)
    except Exception:
        pass
    _health_cache["t"] = 0
    return {"ok": True, "saved": dest.name}


ALLOWED_FILE_ROOTS = lambda: [Path(load_config()["paths"]["resume_copies"]).resolve(), OUT.resolve()]


def allowed_file(path):
    """Compare path components, not prefixes (out-private is not inside out)."""
    return any(path.is_relative_to(root) for root in ALLOWED_FILE_ROOTS())


def _kicked(res):
    try:
        import cloud_sync
        cloud_sync.kick()
    except Exception:
        pass
    return res


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body, default=str) if ctype == "application/json"
                                                       else body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json")) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if (self.headers.get("Host") or "").split(":")[0] not in ("localhost", "127.0.0.1"):
            return self._send(403, {"error": "forbidden"})  # DNS-rebinding guard
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (ROOT / "ui" / "index.html").read_bytes(), "text/html")
            if u.path == "/seed.svg":
                p = ROOT / "ui" / u.path.lstrip("/")
                return self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0])
            if u.path == "/api/overview":
                return self._send(200, overview())
            if u.path == "/api/health":
                return self._send(200, health(force="force" in q))
            if u.path == "/api/llm":
                import llm
                return self._send(200, llm.health())
            if u.path == "/api/jobs/facets":
                return self._send(200, job_facets(q))
            if u.path == "/api/cover_example":
                return self._send(200, cover_example_get())
            if u.path == "/api/signins":
                return self._send(200, signins())
            if u.path == "/api/jobs":
                return self._send(200, list_jobs(q))
            if u.path == "/api/contacts":
                return self._send(200, all_contacts())
            if u.path == "/api/followups":
                import lifecycle
                return self._send(200, lifecycle.followups())
            if u.path == "/api/board_health":
                return self._send(200, board_health_summary())
            if u.path == "/api/runs":
                return self._send(200, runs_snapshot())
            m = re.match(r"/api/run/(\d+)/log", u.path)
            if m and m.group(1) in RUNS:
                off = int(q.get("offset", ["0"])[0])
                with open(RUNS[m.group(1)]["log"], encoding="utf-8", errors="replace") as f:
                    f.seek(off)
                    t = f.read()
                    return self._send(200, {"text": t, "offset": f.tell(), "status": runs_snapshot() and RUNS[m.group(1)]["status"]})
            if u.path == "/api/config":
                return self._send(200, {"text": (ROOT / "config.json").read_text(encoding="utf-8-sig")})
            if u.path == "/api/features":
                return self._send(200, features_get())
            if u.path == "/api/safeguards":
                return self._send(200, safeguards_get())
            if u.path == "/api/cloud":
                return self._send(200, cloud_get())
            if u.path == "/api/profile":
                return self._send(200, profile_get())
            if u.path == "/api/presets":
                cfg = load_config()
                return self._send(200, {"presets": {k: v.get("label", k) for k, v in presets().items()},
                                        "families": {f: v["tiers"] for f, v in cfg["families"].items()}})
            if u.path == "/api/keys":
                k = load_keys()
                return self._send(200, {n: {"set": bool(k.get(n)), "hint": ("..." + k[n][-4:]) if k.get(n) else ""}
                                        for n in KEY_NAMES})
            if u.path == "/file":
                p = Path(q.get("path", [""])[0]).resolve()
                if not allowed_file(p) or not p.is_file():
                    return self._send(404, {"error": "not found"})
                return self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            if u.path == "/open-folder":
                p = Path(q.get("path", [""])[0]).resolve()
                if not allowed_file(p):
                    return self._send(403, {"error": "folder is outside the output folders"})
                if p.exists() and sys.platform == "win32":
                    subprocess.Popen(["explorer", "/select,", str(p)] if p.is_file() else ["explorer", str(p)])
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": str(e)})

    def _same_origin(self):
        """Block other websites from poking this dashboard: POSTs must be JSON (forces a CORS preflight,
        which we never answer) and come from this page itself."""
        host_ok = (self.headers.get("Host") or "").split(":")[0] in ("localhost", "127.0.0.1")
        origin = self.headers.get("Origin")
        origin_ok = origin is None or urllib.parse.urlparse(origin).hostname in ("localhost", "127.0.0.1")
        json_ok = (self.headers.get("Content-Type") or "").startswith("application/json")
        return host_ok and origin_ok and json_ok

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not self._same_origin():
            return self._send(403, {"ok": False, "error": "requests from other sites are refused"})
        b = self._body()
        try:
            m = re.match(r"/api/job/([^/]+)/action", u.path)
            if m:
                return self._send(200, _kicked(job_action(m.group(1), b)))
            m = re.match(r"/api/job/([0-9a-f]{8,40})/followed_up", u.path)
            if m:
                import lifecycle
                lifecycle.mark_followed_up(m.group(1))
                return self._send(200, _kicked({"ok": True}))
            m = re.match(r"/api/contact/(\d+)/sent", u.path)
            if m:
                return self._send(200, _kicked(contact_sent(int(m.group(1)))))
            if u.path == "/api/manual/analyse":
                import manual
                return self._send(200, manual.analyse(b))
            if u.path == "/api/manual/prepare":
                return self._send(200, manual_prepare(b))
            if u.path == "/api/features":
                return self._send(200, features_set(b))
            if u.path == "/api/safeguards":
                return self._send(200, safeguards_set(b))
            if u.path == "/api/cloud":
                return self._send(200, cloud_set(b))
            if u.path == "/api/cover_example":
                return self._send(200, cover_example_set(b))
            if u.path == "/api/family/add":
                return self._send(200, add_family(b))
            if u.path == "/api/profile":
                return self._send(200, profile_set(b))
            if u.path == "/api/family/remove":
                return self._send(200, remove_family(b))
            if u.path == "/api/master/upload":
                return self._send(200, upload_master(b))
            if u.path == "/api/approve_all":
                return self._send(200, _kicked(approve_all(b)))
            if u.path == "/api/run":
                return self._send(200, start_run(b.get("job"), b.get("arg")))
            m = re.match(r"/api/run/(\d+)/stop", u.path)
            if m and m.group(1) in RUNS:
                RUNS[m.group(1)]["proc"].terminate()
                return self._send(200, {"ok": True})
            if u.path == "/api/config":
                save_config_text(b.get("text", ""))
                return self._send(200, {"ok": True})
            if u.path == "/api/keys":
                save_keys({k: v for k, v in b.items() if k in KEY_NAMES})
                _health_cache["t"] = 0
                if any(k.startswith("CLOUD_") for k in b):
                    import cloud_sync
                    cloud_sync.STATUS["state"] = "refresh"
                    cloud_sync.kick()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(400, {"ok": False, "error": str(e)})


def main():
    port = PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    db.conn()
    sys.modules.setdefault("app", sys.modules[__name__])  # cloud sync shares this process's RUNS list
    try:
        import cloud_sync
        cloud_sync.start()  # online dashboard sync; idles until switched on in Settings
    except Exception as e:
        print(f"cloud sync not started: {e}", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://localhost:{port}"
    print(f"Job Engine dashboard: {url}  (close this window to stop it)", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
