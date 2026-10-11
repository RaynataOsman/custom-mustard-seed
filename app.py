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
KEY_NAMES = ["GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY", "NOTION_TOKEN", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"]


def start_run(job, arg=None):
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
    try:
        r = get(cfg["referrals"]["searxng_url"].rstrip("/") + "/search", params={"q": "test", "format": "json"}, timeout=6)
        v["searxng"] = r.status_code == 200
    except Exception:
        v["searxng"] = False
    v["notion"] = notion_sync.health() if keys.get("NOTION_TOKEN") else "no token"
    try:
        r = get("http://127.0.0.1:11434/api/tags", timeout=3)
        v["ollama"] = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        v["ollama"] = None
    v["masters"] = sorted(p.name for p in (ROOT / "masters").glob("*.docx"))
    v["resume_copies"] = cfg["paths"]["resume_copies"]
    _health_cache.update(t=time.time(), v=v)
    return v


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


def list_jobs(q):
    c = db.conn()
    status = q.get("status", ["ready"])[0]
    text = q.get("q", [""])[0].strip()
    where, args = [], []
    if status != "all":
        where.append("status IN (" + ",".join("?" * len(status.split(","))) + ")")
        args += status.split(",")
    board = q.get("board", [""])[0]
    if board:
        where.append("board=?")
        args.append(board)
    if text:
        where.append("(title LIKE ? OR company LIKE ?)")
        args += [f"%{text}%"] * 2
    sql = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY score DESC, found_at DESC LIMIT 300"
    jobs = db.rows(c, sql, args)
    ids = [j["id"] for j in jobs]
    contacts = {}
    if ids:
        for ct in db.rows(c, f"SELECT * FROM contacts WHERE job_id IN ({','.join('?' * len(ids))}) ORDER BY rank", ids):
            contacts.setdefault(ct["job_id"], []).append(ct)
    for j in jobs:
        j["contacts"] = contacts.get(j["id"], [])
        j["description"] = (j.get("description") or "")[:6000]
        for k in ("interview_prep", "gaps", "edits_log"):
            try:
                j[k] = json.loads(j[k]) if j.get(k) else None
            except Exception:
                pass
    return jobs


def job_action(job_id, body):
    c = db.conn()
    a = body.get("action")
    note = (body.get("note") or "").strip()
    job = db.rows(c, "SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job:
        return {"ok": False, "error": "not found"}
    if a == "approve":
        db.set_job(c, job_id, status="approved")
    elif a == "retry":
        db.set_job(c, job_id, status="retry", retry_note=note or None)
    elif a == "skip":
        db.set_job(c, job_id, status="skipped", status_note=note or None)
    elif a == "reopen":
        db.set_job(c, job_id, status="new")
    elif a == "done":  # finished by hand in the browser
        db.set_job(c, job_id, status="submitted", applied_at=now_iso(), status_note="finished by you")
        c.commit()
        threading.Thread(target=lambda: subprocess.run([sys.executable, "-c",
                         f"import pipeline; pipeline.record_in_notion({json.dumps(job_id)})"], cwd=ROOT), daemon=True).start()
    else:
        return {"ok": False, "error": "unknown action"}
    db.event(c, job_id, a, note)
    c.commit()
    return {"ok": True}


def approve_all(body):
    c = db.conn()
    ms = float(body.get("min_score", 60))
    n = c.execute("UPDATE jobs SET status='approved' WHERE status='ready' AND ai_ban=0 AND geo_ok=1 AND score>=?",
                  (ms,)).rowcount
    c.commit()
    return {"ok": True, "approved": n}


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
            if u.path == "/api/overview":
                return self._send(200, overview())
            if u.path == "/api/health":
                return self._send(200, health(force="force" in q))
            if u.path == "/api/llm":
                import llm
                return self._send(200, llm.health())
            if u.path == "/api/jobs":
                return self._send(200, list_jobs(q))
            if u.path == "/api/contacts":
                return self._send(200, all_contacts())
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
                if not any(str(p).startswith(str(r)) for r in ALLOWED_FILE_ROOTS()) or not p.exists():
                    return self._send(404, {"error": "not found"})
                return self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            if u.path == "/open-folder":
                p = Path(q.get("path", [""])[0])
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
                return self._send(200, job_action(m.group(1), b))
            m = re.match(r"/api/contact/(\d+)/sent", u.path)
            if m:
                return self._send(200, contact_sent(int(m.group(1))))
            if u.path == "/api/manual/analyse":
                import manual
                return self._send(200, manual.analyse(b))
            if u.path == "/api/manual/prepare":
                return self._send(200, manual_prepare(b))
            if u.path == "/api/features":
                return self._send(200, features_set(b))
            if u.path == "/api/family/add":
                return self._send(200, add_family(b))
            if u.path == "/api/profile":
                return self._send(200, profile_set(b))
            if u.path == "/api/family/remove":
                return self._send(200, remove_family(b))
            if u.path == "/api/master/upload":
                return self._send(200, upload_master(b))
            if u.path == "/api/approve_all":
                return self._send(200, approve_all(b))
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
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(400, {"ok": False, "error": str(e)})


def main():
    port = PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    db.conn()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://localhost:{port}"
    print(f"Job Engine dashboard: {url}  (close this window to stop it)", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
