"""Job Engine pipeline.  python pipeline.py <command>

  scan       read every enabled board, keep roles that match your families, score them
  prepare    tailor resume + cover letter + interview prep + referral contacts for the best new roles
  submit     apply to the roles you APPROVED in the dashboard (visible browser)
  backfill   find referral contacts for tracker rows whose Connections are blank
  all        scan + prepare   (this is what the scheduled task runs; it never submits)
  board <name>   scan one board only (for testing)
"""
import json, sys, time, traceback, datetime, re
import db, triage, boards, tailor, referrals
from util import load_config, Log, job_key, get, strip_html, force_utf8_stdout, now_iso, OUT, feature

force_utf8_stdout()
log = Log("engine")


def _vocab_cache():
    return {fam: tailor.vocab(fam) for fam in load_config()["families"]}


def scan(only=None):
    cfg = load_config()
    c = db.conn()
    total_new = 0
    t_ok = lambda t: triage.title_ok(t, cfg)
    if not only and not feature("scan_boards", cfg) and not feature("email_alerts", cfg):
        log("scanning is switched off in Settings > Features")
        return 0
    for b in cfg["boards"]:
        if only and only.lower() not in b["name"].lower():
            continue
        if not b.get("enabled", True) and not only:
            continue
        if not only and b["kind"] == "email_alerts" and not feature("email_alerts", cfg):
            continue
        if not only and b["kind"] != "email_alerts" and not feature("scan_boards", cfg):
            continue
        start, err, raw = time.time(), None, []
        log(f"[{b['name']}] scanning ({b['kind']})")
        try:
            if b["kind"] == "render":
                import render
                known = {r["url"] for r in db.rows(c, "SELECT url FROM jobs WHERE board=?", (b["name"],))}
                raw = render.harvest(b, cfg, log, t_ok, known)
            else:
                raw = boards.ADAPTERS[b["kind"]](b, cfg, log)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            log(f"  ERROR {err}")
        matched = new = 0
        for j in raw:
            if not j.get("title") or not t_ok(j["title"]):
                continue
            matched += 1
            if b["kind"] == "linkedin" and not j.get("description"):
                try:
                    boards.linkedin_detail(j)
                    time.sleep(2)
                except Exception:
                    pass
            j["id"] = job_key(j.get("company"), j["title"])
            j.setdefault("board", b["name"])
            if db.upsert_job(c, j):
                new += 1
                _triage_one(c, j, b.get("track", "remote"), cfg)
        c.execute("INSERT INTO board_runs (board, kind, started, seconds, ok, fetched, matched, new, error) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (b["name"], b["kind"], now_iso(), round(time.time() - start, 1),
                                                0 if err else 1, len(raw), matched, new, err))
        c.commit()
        total_new += new
        log(f"  fetched {len(raw)}, matched {matched}, new {new}" + (f"  !! {err}" if err else ""))
    log(f"scan done: {total_new} new roles")
    return total_new


_VOCAB = None


def _triage_one(c, j, track, cfg):
    global _VOCAB
    if _VOCAB is None:
        _VOCAB = _vocab_cache()
    fam = triage.family_of(j["title"], cfg)
    tier, yrs = triage.tier_of(j["title"], j.get("description", ""), fam, cfg)
    ok, why = triage.geo(j, track)
    j["geo_ok"] = ok
    score, reasons = triage.fit_score(j, fam, _VOCAB[fam], track)
    ai_ban = 1 if triage.AI_BAN.search(j.get("description") or "") else 0
    status = "new"
    if ok == 0:
        status = "filtered"
    emp_type, emp_reason = triage.employer(j, cfg)
    if cfg["geo"].get("international_only", True) and track != "relocation" and emp_type in ("sa_local", "sa_aggregator"):
        status, why = "filtered", why + "; " + emp_reason
    tz_ok, tz_reason = triage.timezone_fit(j, cfg)
    if tz_ok is False:
        if cfg["geo"].get("strict_timezone", True):
            status, why = "filtered", why + "; time zone: " + tz_reason
        else:
            score = max(0, score - 15)
            reasons.append("time zone: " + tz_reason + " (-15)")
    if not triage.core_ok(j, fam, cfg):
        status, why = "filtered", why + "; core skills for this family not in the posting"
    try:
        age = (datetime.date.today() - datetime.date.fromisoformat((j.get("posted_at") or "")[:10])).days
        if age > cfg["search"]["max_age_days"]:
            status, why = "filtered", why + f"; too old ({age}d)"
    except Exception:
        pass
    db.set_job(c, j["id"], family=fam, tier=tier, geo_ok=ok, geo_reason=why, score=score,
               score_reasons="; ".join(reasons), ai_ban=ai_ban, status=status,
               employer_type=emp_type, employer_reason=emp_reason, tz_reason=tz_reason)


def retriage():
    """Re-apply the current rules to every role not yet prepared (after you change filters)."""
    cfg = load_config()
    c = db.conn()
    tracks = {b["name"]: b.get("track", "remote") for b in cfg["boards"]}
    n = 0
    for j in db.rows(c, "SELECT * FROM jobs WHERE status IN ('new','filtered')"):
        j["countries"] = None
        if not triage.title_ok(j["title"], cfg):
            db.set_job(c, j["id"], status="filtered", geo_reason="title no longer matches your families/filters")
            continue
        _triage_one(c, j, tracks.get(j["board"], "remote"), cfg)
        n += 1
    c.commit()
    log(f"re-triaged {n} roles")


def verify_geo(job):
    """For 'just says Remote' roles, read the employer's own page before spending effort."""
    url = job.get("apply_url") or job.get("url")
    try:
        r = get(url, timeout=25)
        text = strip_html(r.text)[:30000]
    except Exception:
        return None, "could not open apply page"
    probe = dict(job, description=text, location=job.get("location") or "", countries=None)
    return triage.geo(probe)


def _cover_files(res, job):
    """Cover letter as .docx + .pdf next to the resume (some forms want a file)."""
    from docx import Document
    from pathlib import Path
    import pdf
    if not res.get("cover_letter"):
        return None
    d = Document()
    for para in res["cover_letter"].split("\n"):
        d.add_paragraph(para)
    p = Path(res["cover_letter_path"]).with_suffix(".docx")
    d.core_properties.author = load_config()["profile"]["name"]
    d.save(p)
    return pdf.to_pdf(p)


def prepare(limit=None, ids=None):
    import pdf
    cfg = load_config()
    c = db.conn()
    limit = limit or cfg["schedule"]["prepare_max_per_run"]
    if ids:
        jobs = db.rows(c, f"SELECT * FROM jobs WHERE id IN ({','.join('?' * len(ids))})", ids)
    else:
        jobs = db.rows(c, """SELECT * FROM jobs WHERE status IN ('retry') OR (status='new' AND score>=?)
                             ORDER BY (status='retry') DESC, score DESC, found_at DESC LIMIT ?""",
                       (cfg["resume"]["min_score_to_prepare"], limit))
    log(f"preparing {len(jobs)} role(s)")
    for job in jobs:
        try:
            db.set_job(c, job["id"], status="preparing")
            c.commit()
            if job.get("geo_ok") is None and job.get("board") != "Manual":
                ok, why = verify_geo(job)
                if ok == 0:
                    db.set_job(c, job["id"], status="filtered", geo_ok=0, geo_reason="apply page: " + why)
                    c.commit()
                    log(f"  {job['company']}: filtered after checking apply page ({why})")
                    continue
                if ok == 1:
                    db.set_job(c, job["id"], geo_ok=1, geo_reason="apply page: " + why)
            log(f"  {job['company']} - {job['title']} [{job['family']} {job['tier']}]")
            res = tailor.tailor(job, job["family"], job["tier"], retry_note=job.get("retry_note"), log=log)
            pdf_path = pdf.to_pdf(res["docx"])
            cl_pdf = _cover_files(res, job)
            contacts = referrals.find(job["company"], job["title"], job["family"], log=log) \
                if feature("referrals", cfg) else []
            c.execute("DELETE FROM contacts WHERE job_id=? AND sent=0", (job["id"],))
            for p in contacts:
                c.execute("""INSERT OR IGNORE INTO contacts (job_id, company, name, headline, url, kind, rank, note,
                             followup, found_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                          (job["id"], job["company"], p["name"], p["headline"], p["url"], p["kind"], p["rank"],
                           p["note"], p["followup"], now_iso()))
            db.set_job(c, job["id"], status="ready", resume_docx=res["docx"], resume_pdf=pdf_path,
                       cover_letter=res["cover_letter"], interview_prep=json.dumps(res["interview_prep"]),
                       gaps=json.dumps(res["gaps"]), llm_used=res["llm"] or "none (keyword mode)",
                       edits_log=json.dumps({"applied": res["edits_applied"], "rejected": res["edits_rejected"],
                                             "fit": res["fit_line"], "master": res["master"],
                                             "cover_letter_pdf": cl_pdf}),
                       status_note=res["fit_line"] or None, retry_note=None)
            db.event(c, job["id"], "prepared", {"llm": res["llm"], "pdf": bool(pdf_path)})
            c.commit()
            if job.get("board") == "Manual" and feature("notion"):
                try:
                    import manual
                    manual.record_prepared(job["id"], log=log)
                except Exception as e:
                    log(f"  Notion write failed for {job['company']}: {e}")
        except Exception as e:
            log(f"  FAILED {job.get('company')}: {e}\n{traceback.format_exc()[-800:]}")
            db.set_job(c, job["id"], status="failed", status_note=str(e)[:300])
            c.commit()
    referrals.close_browser()


def submit_approved():
    import submit, notion_sync
    if not feature("auto_fill"):
        log("auto-fill is switched off in Settings > Features - apply with the downloaded files, then press 'I submitted it'")
        return
    c = db.conn()
    jobs = db.rows(c, "SELECT * FROM jobs WHERE status='approved' ORDER BY score DESC")
    if not jobs:
        log("nothing approved to submit")
        return
    for j in jobs:
        try:
            j["cover_letter_pdf"] = json.loads(j.get("edits_log") or "{}").get("cover_letter_pdf")
        except Exception:
            pass
        db.set_job(c, j["id"], status="submitting")
    c.commit()
    for job_id, status, note in submit.run(jobs, log=log):
        fields = {"status": status, "status_note": note}
        if status == "submitted":
            fields["applied_at"] = now_iso()
        db.set_job(c, job_id, **fields)
        db.event(c, job_id, status, note)
        c.commit()
        if status == "submitted":
            record_in_notion(job_id)


def record_in_notion(job_id):
    import notion_sync
    if not feature("notion"):
        return
    c = db.conn()
    job = db.rows(c, "SELECT * FROM jobs WHERE id=?", (job_id,))[0]
    if job.get("notion_page_id"):
        notion_sync.update_stage(job["notion_page_id"], "Applied", applied_on=job.get("applied_at") or now_iso())
        return
    contacts = db.rows(c, "SELECT * FROM contacts WHERE job_id=? ORDER BY rank", (job_id,))
    try:
        pid = notion_sync.push_application(job, contacts, log=log)
        db.set_job(c, job_id, notion_page_id=pid)
        c.execute("UPDATE contacts SET notion_page_id=? WHERE job_id=?", (pid, job_id))
        c.commit()
    except Exception as e:
        log(f"  Notion write failed for {job['company']}: {e}")


def backfill():
    import notion_sync
    cfg = load_config()
    if not (feature("notion", cfg) and feature("referrals", cfg)):
        log("backfill needs both Notion and Referrals switched on")
        return
    rows = notion_sync.rows_missing_connections()
    log(f"{len(rows)} tracker row(s) with blank Connections")
    c = db.conn()
    for r in rows:
        fam = triage.family_of(r["position"] or " ".join(r["positions"]), cfg) or "dev"
        people = referrals.find(r["company"], r["position"] or (r["positions"] or ["role"])[0], fam, log=log)
        if not people:
            continue
        for p in people:
            c.execute("""INSERT OR IGNORE INTO contacts (job_id, notion_page_id, company, name, headline, url, kind,
                         rank, note, followup, found_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      ("notion:" + r["page_id"], r["page_id"], r["company"], p["name"], p["headline"], p["url"],
                       p["kind"], p["rank"], p["note"], p["followup"], now_iso()))
        c.commit()
        try:
            notion_sync.write_connections(r["page_id"], people)
        except Exception as e:
            log(f"  Notion update failed for {r['company']}: {e}")
        time.sleep(2)
    referrals.close_browser()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    log(f"=== {cmd} ===")
    if cmd == "scan":
        scan()
    elif cmd == "board":
        scan(only=" ".join(sys.argv[2:]))
    elif cmd == "prepare":
        prepare(ids=sys.argv[2:] or None)
    elif cmd == "submit":
        submit_approved()
    elif cmd == "dryfill":
        import submit
        c = db.conn()
        jobs = db.rows(c, f"SELECT * FROM jobs WHERE id IN ({','.join('?' * len(sys.argv[2:]))})", sys.argv[2:])
        for jid, st, note in submit.run(jobs, log=log, dry=True):
            log(f"DRY {jid}: {st} - {note}")
    elif cmd == "discover":
        import ats_discover
        for n in (sys.argv[2:] or load_config().get("companies_to_watch", [])):
            ats_discover.resolve(n, log=log, force=True)
    elif cmd == "retriage":
        retriage()
    elif cmd == "backfill":
        backfill()
    elif cmd == "all":
        scan()
        prepare()
    else:
        print(__doc__)
