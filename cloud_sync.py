"""Keeps the online dashboard (Vercel) in step with this PC.

How it works
- Supabase (free) sits in the middle. This PC pushes a copy of the roles you care about (Review,
  Needs you, Applied, referral notes, board status, runs) and their resume / cover letter PDFs.
- The online dashboard never talks to your PC directly. When you press Approve (or Run, or
  "I sent it") online, it drops a command in Supabase; this PC picks it up within ~15 seconds,
  runs it exactly as if you had pressed the button here, and pushes the result back.
- So the online dashboard works whenever this dashboard (start.bat) is running.

Settings
- config.json "cloud": {"enabled": true, "supabase_url": ..., "anon_key": ..., "web_url": ...}
- keys.env: CLOUD_TOKEN (shared secret - the Supabase functions refuse anything without it)
            CLOUD_PASSWORD (the password you type on the online dashboard; change it in Settings > Keys)

Nothing here needs Claude credits. Supabase and Vercel free tiers cover it.
"""
import base64, datetime, hashlib, json, os, socket, threading, time, traceback
from pathlib import Path
import db
from util import load_config, load_keys, http, now_iso, LOGS

STATUS = {"state": "off", "last_push": None, "last_error": None, "pushed": 0, "commands": 0, "started": None}
_STOP = threading.Event()
_KICK = threading.Event()
ACTIVE = ("ready", "approved", "retry", "preparing", "submitting", "needs_you", "failed")
RUN_JOBS = {"scan", "prepare", "submit", "all", "backfill", "tiers", "retriage", "sweep", "referrals", "expire", "replies",
            "board"}
MAX_FILE_BYTES = 900_000
PRELOAD_READY = 20


def settings():
    cfg = load_config()
    c = cfg.get("cloud") or {}
    k = load_keys()
    return {"enabled": bool(c.get("enabled")), "url": (c.get("supabase_url") or "").rstrip("/"),
            "anon": c.get("anon_key") or "", "web_url": c.get("web_url") or "",
            "token": k.get("CLOUD_TOKEN") or "", "password": k.get("CLOUD_PASSWORD") or "",
            "found_limit": int(c.get("found_limit", 150))}


def ready(s=None):
    s = s or settings()
    return s["enabled"] and s["url"] and s["anon"] and s["token"]


def rpc(s, name, **args):
    r = http().post(f"{s['url']}/rest/v1/rpc/{name}", timeout=60,
                    headers={"apikey": s["anon"], "Authorization": f"Bearer {s['anon']}",
                             "Content-Type": "application/json"},
                    json={"p_token": s["token"], **args})
    if r.status_code >= 300:
        raise RuntimeError(f"{name}: HTTP {r.status_code} {r.text[:200]}")
    return r.json() if r.text else None


# ------------------------------------------------------------------ local state
def _sget(c, k, default=None):
    row = c.execute("SELECT v FROM sync_state WHERE k=?", (k,)).fetchone()
    try:
        return json.loads(row["v"]) if row else default
    except Exception:
        return default


def _sset(c, k, v):
    c.execute("INSERT INTO sync_state (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))
    c.commit()


# ------------------------------------------------------------------ what gets pushed
def _rows_to_sync(c, s):
    rows = db.rows(c, f"""SELECT * FROM jobs WHERE status IN ({','.join('?' * len(ACTIVE))})
                          OR (status='submitted' AND coalesce(applied_at, updated_at) >= date('now','-90 day'))
                          OR (status='skipped' AND (updated_at >= date('now','-7 day') OR lock_note IS NOT NULL))""", ACTIVE)
    rows += db.rows(c, """SELECT * FROM jobs WHERE status='new' AND coalesce(geo_ok,1)<>0
                          ORDER BY score DESC, found_at DESC LIMIT ?""", (s["found_limit"],))
    return rows


def _salary(v):
    """'USD 100.0-None MONTH' -> 'USD 100 MONTH'."""
    if not v:
        return v
    import re
    v = re.sub(r"(\d)\.0\b", r"\1", str(v))
    v = re.sub(r"-\s*None|None\s*-", "", v)
    return re.sub(r"\s+", " ", v).strip() or None


def _payload(c, j):
    import safeguards
    ed = {}
    try:
        ed = json.loads(j.get("edits_log") or "{}")
    except Exception:
        pass
    full = j["status"] in ("ready", "approved", "needs_you", "retry", "submitted")
    contacts = db.rows(c, "SELECT id, name, headline, url, kind, rank, note, followup, sent, sent_at FROM contacts "
                          "WHERE job_id=? ORDER BY rank", (j["id"],))
    lock = safeguards.lock_for(c, j)

    def js(v):
        try:
            return json.loads(v) if v else None
        except Exception:
            return None
    return {
        "id": j["id"], "status": j["status"], "status_note": j.get("status_note"), "title": j["title"],
        "company": j.get("company"), "location": j.get("location"), "board": j.get("board"), "url": j.get("url"),
        "apply_url": j.get("apply_url"), "score": j.get("score") or 0, "score_reasons": (j.get("score_reasons") or "")[:600],
        "family": j.get("family"), "tier": j.get("tier"),
        "version": j.get("version_sent") or safeguards.version_label(j.get("family"), j.get("tier")),
        "geo_ok": j.get("geo_ok"), "geo_reason": (j.get("geo_reason") or "")[:300], "employer_type": j.get("employer_type"),
        "salary": _salary(j.get("salary")), "employment_type": j.get("employment_type"), "posted_at": j.get("posted_at"),
        "found_at": j.get("found_at"), "applied_at": j.get("applied_at"), "ai_ban": j.get("ai_ban"),
        "reply_kind": j.get("reply_kind"), "reply_at": j.get("reply_at"), "followup_at": j.get("followup_at"),
        "in_notion": bool(j.get("notion_page_id")), "lock": lock, "is_platform": safeguards.is_platform(j),
        "cover_letter": j.get("cover_letter") if full else None,
        "edited": bool(j.get("resume_edited_at") or j.get("cover_edited_at")),
        "interview_prep": js(j.get("interview_prep")) if full else None,
        "gaps": js(j.get("gaps")) if full else None,
        "fit_line": ed.get("fit"), "edits": len(ed.get("applied") or []), "llm_used": j.get("llm_used"),
        "description": (j.get("description") or "")[: 4000 if full else 700],
        "contacts": contacts,
        "files": {k: Path(p).name for k, p in (("resume", j.get("resume_pdf")), ("cover", ed.get("cover_letter_pdf"))) if p},
    }


def _files_for(j):
    ed = {}
    try:
        ed = json.loads(j.get("edits_log") or "{}")
    except Exception:
        pass
    return [(k, p) for k, p in (("resume", j.get("resume_pdf")), ("cover", ed.get("cover_letter_pdf"))) if p]


def push(s, force=False):
    c = db.conn()
    rows = _rows_to_sync(c, s)
    seen = {}
    for j in rows:
        seen[j["id"]] = j
    hashes = {} if force else _sget(c, "cloud_hashes", {})
    changed, new_hashes = [], {}
    for jid, j in seen.items():
        p = _payload(c, j)
        h = hashlib.sha1(json.dumps(p, sort_keys=True, default=str).encode()).hexdigest()
        new_hashes[jid] = h
        if hashes.get(jid) != h:
            changed.append(p)
    for i in range(0, len(changed), 40):
        rpc(s, "ms_push_jobs", p_rows=changed[i:i + 40])
    if force or set(hashes) != set(new_hashes):
        rpc(s, "ms_prune_jobs", p_keep=list(new_hashes))
    _sset(c, "cloud_hashes", new_hashes)

    # PDFs: uploaded ahead of time only for the roles you're most likely to open (the free database is
    # small and shared); any other PDF is fetched from this PC the moment you open it online.
    ready_top = sorted((j for j in seen.values() if j["status"] == "ready"), key=lambda j: -(j.get("score") or 0))
    want = {j["id"] for j in seen.values() if j["status"] in ("approved", "needs_you")}
    want |= {j["id"] for j in ready_top[:PRELOAD_READY]}
    sent = {k: v for k, v in (_sget(c, "cloud_files", {}) or {}).items() if isinstance(v, dict)} if not force else {}
    for jid in want:
        for kind, _ in _files_for(seen[jid]):
            upload_file(s, seen[jid], kind, sent)
    keep = {k: v for k, v in sent.items()
            if k.split("|")[0] in want or (time.time() - v.get("at", 0) < 72 * 3600 and k.split("|")[0] in seen)}
    if force or set(keep) != set(sent):
        rpc(s, "ms_keep_files", p_keys=list(keep))
    _sset(c, "cloud_files", keep)
    STATUS["pushed"] += len(changed)
    return len(changed)


def upload_file(s, job, kind, sent=None):
    """Send one PDF (resume / cover) for a role. Returns True if it is online now."""
    path = dict(_files_for(job)).get(kind)
    p = Path(path) if path else None
    if not p or not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
        return False
    key, sig = f"{job['id']}|{kind}", f"{p}|{int(p.stat().st_mtime)}"
    if sent is not None and (sent.get(key) or {}).get("sig") == sig:
        return True
    rpc(s, "ms_put_file", p_job_id=job["id"], p_kind=kind, p_name=p.name,
        p_b64=base64.b64encode(p.read_bytes()).decode())
    if sent is not None:
        sent[key] = {"sig": sig, "at": time.time()}
    return True


def push_state(s):
    import app
    ov = app.overview()
    boards = [{"board": b.get("board"), "ok": b.get("ok"), "fetched": b.get("fetched"), "new": b.get("new"),
               "error": (b.get("error") or "")[:200], "started": b.get("started"), "never_run": b.get("never_run"),
               "health": b.get("health"), "links": b.get("links"), "hits": b.get("hits")}
              for b in ov["boards"]]
    runs = app.runs_snapshot()[:8]
    for r in runs[:2]:
        try:
            with open(r["log"], encoding="utf-8", errors="replace") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 6000))
                r["tail"] = f.read()
        except Exception:
            r["tail"] = ""
        r.pop("log", None)
    for r in runs[2:]:
        r.pop("log", None)
    rpc(s, "ms_set_state", p_k="overview", p_v={"applied_week": ov["applied_week"], "contacts_pending": ov["contacts_pending"],
                                                   "counts_local": ov["counts"], "boards": boards})
    rpc(s, "ms_set_state", p_k="runs", p_v=runs)
    rpc(s, "ms_set_state", p_k="heartbeat", p_v={"at": now_iso(), "pc": socket.gethostname(),
                                                    "web_url": s["web_url"], "status": STATUS["state"]})


def _password(s):
    c = db.conn()
    h = hashlib.sha256((s["password"] or "").encode()).hexdigest()
    if s["password"] and _sget(c, "cloud_pw") != h:
        rpc(s, "ms_set_password", p_password=s["password"])
        _sset(c, "cloud_pw", h)


def run_command(cmd):
    import app
    kind, p = cmd["kind"], cmd.get("payload") or {}
    if kind == "job_action" and p.get("action") == "resume_text":
        import editor
        t = editor.get_texts(str(p.get("id")))
        return {"ok": True, "text": t.get("resume_text") or ""}
    if kind == "job_action" and p.get("action") == "edit_text":
        import editor
        return editor.save(str(p.get("id")), p.get("what"), p.get("text") or "", bool(p.get("force")))
    if kind == "job_action":
        return app.job_action(str(p.get("id")), {"action": p.get("action"), "note": p.get("note"),
                                                  "override": bool(p.get("override")),
                                                  "discard": bool(p.get("discard"))})
    if kind == "resume_text":
        import editor
        t = editor.get_texts(str(p.get("id")))
        return {"ok": True, "text": t.get("resume_text") or ""}
    if kind == "edit_text":
        import editor
        return editor.save(str(p.get("id")), p.get("what"), p.get("text") or "", bool(p.get("force")))
    if kind == "contact_sent":
        return app.contact_sent(int(p.get("id")))
    if kind == "followed_up":
        import lifecycle
        lifecycle.mark_followed_up(str(p.get("id")))
        return {"ok": True}
    if kind == "approve_all":
        return app.approve_all({"min_score": p.get("min_score", 60)})
    if kind == "file":
        s = settings()
        c = db.conn()
        rows = db.rows(c, "SELECT * FROM jobs WHERE id=?", (str(p.get("id")),))
        if not rows:
            return {"ok": False, "error": "role not found on the PC"}
        sent = {k: v for k, v in (_sget(c, "cloud_files", {}) or {}).items() if isinstance(v, dict)}
        ok = upload_file(s, rows[0], p.get("kind"), sent)
        _sset(c, "cloud_files", sent)
        return {"ok": ok} if ok else {"ok": False, "error": "that PDF is not on the PC (prepare the role again?)"}
    if kind == "run":
        job = p.get("job")
        if job not in RUN_JOBS:
            return {"ok": False, "error": "that run is not allowed from the online dashboard"}
        arg = p.get("arg")
        if job == "board":
            import util
            if arg not in {b["name"] for b in util.load_config()["boards"]}:
                return {"ok": False, "error": "unknown board"}
        elif arg is not None and not str(arg).replace("_", "").isalnum():
            return {"ok": False, "error": "bad argument"}
        return app.start_run(job, arg)
    return {"ok": False, "error": "unknown command"}


def pull(s):
    cmds = rpc(s, "ms_take_commands") or []
    for cmd in cmds:
        try:
            res = run_command(cmd)
        except Exception as e:
            res = {"ok": False, "error": str(e)[:300]}
        rpc(s, "ms_finish_command", p_id=cmd["id"], p_result=json.loads(json.dumps(res, default=str)))
        STATUS["commands"] += 1
    return len(cmds)


def refresh_job(job_id):
    """After a hand edit: push that role and its fresh PDFs now (not on the next 60 s sweep)."""
    s = settings()
    if not ready(s):
        return
    c = db.conn()
    rows = db.rows(c, "SELECT * FROM jobs WHERE id=?", (job_id,))
    if not rows:
        return
    rpc(s, "ms_push_jobs", p_rows=[_payload(c, rows[0])])
    for kind, _ in _files_for(rows[0]):
        try:
            upload_file(s, rows[0], kind, None)
        except Exception:
            pass
    kick()


def kick():
    """Push soon (called after local actions so the online copy catches up quickly)."""
    _KICK.set()


def loop():
    STATUS.update(state="starting", started=now_iso())
    last_push = last_state = 0
    while not _STOP.is_set():
        s = settings()
        if not ready(s):
            STATUS["state"] = "off" if not s["enabled"] else "missing settings (CLOUD_TOKEN / Supabase URL)"
            _KICK.wait(30)
            _KICK.clear()
            continue
        try:
            if STATUS["state"] != "on":
                _password(s)
            n = pull(s)
            now = time.time()
            if n or _KICK.is_set() or now - last_push > 60:
                _KICK.clear()
                push(s, force=(last_push == 0))
                last_push = time.time()
            if n or now - last_state > 45:
                push_state(s)
                last_state = time.time()
            STATUS.update(state="on", last_push=now_iso(), last_error=None)
        except Exception as e:
            STATUS.update(state="error", last_error=f"{type(e).__name__}: {str(e)[:300]}")
            try:
                with open(LOGS / "cloud_sync.log", "a", encoding="utf-8") as f:
                    f.write(f"[{now_iso()}] {traceback.format_exc()[-1500:]}\n")
            except Exception:
                pass
            _STOP.wait(60)
        _KICK.wait(15)


def start():
    t = threading.Thread(target=loop, name="cloud-sync", daemon=True)
    t.start()
    return t


def status():
    s = settings()
    return dict(STATUS, enabled=s["enabled"], web_url=s["web_url"], has_token=bool(s["token"]),
                has_password=bool(s["password"]), supabase=bool(s["url"]))


if __name__ == "__main__":
    s = settings()
    if not ready(s):
        print("cloud sync is not set up:", status())
    else:
        _password(s)
        print("pushed", push(s, force=True), "changed roles")
        push_state(s)
        print("commands run:", pull(s))
