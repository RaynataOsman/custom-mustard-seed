"""Job Engine pipeline.  python pipeline.py <command>

  scan       read every enabled board, keep roles that match your families, score them
  prepare    tailor resume + cover letter + interview prep + referral contacts for the best new roles
  submit     apply to the roles you APPROVED in the dashboard (visible browser)
  backfill   find referral contacts for tracker rows whose Connections are blank
  referrals [n]  find referral contacts for roles in Review that have none (best scores first)
  tiers      fill the Notion "Tier used" column for rows already in the tracker
  sweep      apply the one-family-per-platform rule to roles already waiting in Review
  all        scan + expire + prepare + replies  (this is what the scheduled task runs; it never submits)
  expire     move roles older than search.max_age_days out of New / Review
  checklive  move roles whose posting was removed or closed out of New / Review  (checklive dry | checklive 500)
  replies    read employer replies in Gmail (read-only) -> Interview / Rejected / Offered in Notion
  board <name>   scan one board only (for testing)
"""
import json, sys, time, traceback, datetime, re
import db, triage, boards, tailor, referrals, safeguards, categories
from util import load_config, Log, job_key, get, strip_html, force_utf8_stdout, now_iso, OUT, feature

force_utf8_stdout()
log = Log("engine")


def _vocab_cache():
    return {fam: tailor.vocab(fam) for fam in load_config()["families"]}


def board_health(kind, err, links, hits, fetched, matched, signin=False, signin_board=False):
    """One word per board run, shown on the Boards tab:
    ok | quiet (worked, nothing for your resumes today) | needs sign-in | blocked | error |
    broken: page empty | broken: no job links (the site changed its layout - fix link_pattern) | empty feed"""
    if err:
        if re.search(r"bot protection|cloudflare|captcha|403|429", err, re.I):
            return "blocked"
        if re.search(r"sign.?in|login|not connected|password", err, re.I):
            return "needs sign-in"
        return "error"
    if (signin or (signin_board and (hits or 0) <= 2)) and not fetched:
        return "needs sign-in"
    if kind == "render":
        if not links:
            return "broken: page empty"
        if not hits:
            return "broken: no job links"
    elif not fetched:
        return "quiet" if kind == "email_alerts" else "empty feed"  # alerts: no NEW alert emails since last read
    return "ok" if matched else "quiet"


def pause_hours(runs, hours=24, hard=72):
    """Hours left to leave a board alone after the site blocked us (403 / human check): 24 h after one blocked run,
    72 h once the last three were all blocked. runs = this board's latest runs, newest first."""
    if not runs or not str(runs[0].get("health") or "").startswith("blocked"):
        return 0.0
    wait = hard if len(runs) >= 3 and all(str(r.get("health") or "").startswith("blocked") for r in runs[:3]) else hours
    try:
        t = datetime.datetime.fromisoformat(str(runs[0]["started"]))
    except Exception:
        return 0.0
    return max(0.0, wait - (datetime.datetime.now() - t).total_seconds() / 3600)


def scan(only=None):
    cfg = load_config()
    c = db.conn()
    total_new = 0
    t_ok = lambda t: triage.title_ok(t, cfg)
    if not only and not feature("scan_boards", cfg) and not feature("email_alerts", cfg):
        log("scanning is switched off in Settings > Features")
        return 0
    if any(b.get("track") == "relocation" and b.get("enabled", True) for b in cfg["boards"]):
        try:
            import sponsors
            sponsors.refresh(log)
        except Exception as e:
            log(f"UK sponsor register skipped: {e}")
    for b in cfg["boards"]:
        if only and only.lower() not in b["name"].lower():
            continue
        if not b.get("enabled", True) and not only:
            continue
        if not only and b["kind"] == "email_alerts" and not feature("email_alerts", cfg):
            continue
        if not only and b["kind"] != "email_alerts" and not feature("scan_boards", cfg):
            continue
        if b["kind"] == "render" and not only:
            left = pause_hours(db.rows(c, "SELECT health, started FROM board_runs WHERE board=? "
                                          "ORDER BY started DESC LIMIT 3", (b["name"],)))
            if left > 0:
                log(f"[{b['name']}] resting: the site blocked the last run (403 / human check). Next try in about "
                    f"{left:.0f} h. Run it by hand from Boards to try sooner.")
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
        matched = new = details = 0
        for j in raw:
            if not j.get("title") or not t_ok(j["title"]):
                continue
            matched += 1
            j["id"] = job_key(j.get("company"), j["title"])
            if b["kind"] == "linkedin" and not j.get("description") \
                    and not c.execute("SELECT 1 FROM jobs WHERE id=?", (j["id"],)).fetchone():
                # only new roles need the detail page (it used to be fetched for every match: ~18 min a scan)
                try:
                    boards.linkedin_detail(j)
                    details += 1
                    if details % 20 == 0:
                        log(f"  LinkedIn: read {details} new postings so far")
                    time.sleep(2)
                except Exception:
                    pass
            j.setdefault("board", b["name"])
            if db.upsert_job(c, j):
                new += 1
                _triage_one(c, j, b.get("track", "remote"), cfg)
        links = hits = None
        if b["kind"] == "render":
            import render
            links, hits = render.LAST.get("links"), render.LAST.get("hits")
        health = board_health(b["kind"], err, links, hits, len(raw), matched,
                              signin=b["kind"] == "render" and render.LAST.get("signin"),
                              signin_board=bool(b.get("signin_required")))
        c.execute("INSERT INTO board_runs (board, kind, started, seconds, ok, fetched, matched, new, error, links, hits, health) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (b["name"], b["kind"], now_iso(), round(time.time() - start, 1),
                                                0 if err else 1, len(raw), matched, new, err, links, hits, health))
        if health not in ("ok", "quiet"):
            log(f"  health: {health}")
        c.commit()
        total_new += new
        log(f"  fetched {len(raw)}, matched {matched}, new {new}" + (f"  !! {err}" if err else ""))
    try:
        import render
        render.shutdown()
    except Exception:
        pass
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
               employer_type=emp_type, employer_reason=emp_reason, tz_reason=tz_reason,
               category=categories.category_of(j["title"], j.get("description") or ""))


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
    track = next((b.get("track", "remote") for b in load_config()["boards"] if b["name"] == job.get("board")), "remote")
    return triage.geo(probe, track)


def _cover_files(res, job):
    """Cover letter as .docx + .pdf next to the resume, laid out like a letter (name, contact line, date, Re:)."""
    from docx import Document
    from docx.shared import Pt
    from pathlib import Path
    import pdf
    if not res.get("cover_letter"):
        return None
    cfg = load_config()
    pr = cfg["profile"]
    d = Document()
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(11)
    h = d.add_paragraph()
    r = h.add_run(pr["name"])
    r.bold, r.font.size = True, Pt(16)
    d.add_paragraph(" | ".join(x for x in (pr.get("email"), pr.get("phone"), pr.get("location"),
                                            pr.get("linkedin"), pr.get("portfolio")) if x))
    d.add_paragraph(datetime.date.today().strftime("%d %B %Y"))
    re_line = d.add_paragraph()
    re_line.add_run(f"Re: {job['title']} - {job['company']}").bold = True
    for para in res["cover_letter"].split("\n\n"):
        if para.strip():
            d.add_paragraph(para.strip())
    p = Path(res["cover_letter_path"]).with_suffix(".docx")
    d.core_properties.author = pr["name"]
    d.core_properties.comments = ""
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
    try:
        n, m = safeguards.sweep_all(c, log=log, cfg=cfg)
        if n:
            log(f"platform rule: {n} role(s) already in Review skipped (one family per platform)")
        if m:
            log(f"one application per company/recruiter: {m} weaker role(s) already in Review skipped")
    except Exception as e:
        log(f"platform sweep skipped: {e}")
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
            guard = safeguards.check(c, job, cfg)
            if guard and guard["level"] == "block":
                db.set_job(c, job["id"], status="skipped", status_note=guard["message"], lock_note=guard["message"])
                db.event(c, job["id"], "safeguard_skip", guard["message"])
                c.commit()
                log(f"  {job['company']}: skipped - {guard['message']}")
                continue
            if guard and guard["level"] == "wins":
                lose = guard.get("loser_note") or f"Platform rule: a stronger match at {job['company']} was chosen ({job['title']})"
                for lid in guard["losers"]:
                    db.set_job(c, lid, status="skipped", lock_note=lose, status_note=lose)
                    db.event(c, lid, "safeguard_skip", lose)
                log(f"  {job['company']}: {guard['message']}")
            db.set_job(c, job["id"], lock_note=safeguards.note_for(guard) if guard and guard["level"] != "wins" else None)
            log(f"  {job['company']} - {job['title']} [{job['family']} {job['tier']}]"
                + (f"  !! {guard['message']}" if guard and guard["level"] == "warn" else ""))
            res = tailor.tailor(job, job["family"], job["tier"], retry_note=job.get("retry_note"), log=log)
            pdf_path = pdf.to_pdf(res["docx"])
            cl_pdf = _cover_files(res, job)
            contacts = referrals.find(job["company"], job["title"], job["family"], log=log,
                                      exclude=contacted_elsewhere(c, job["id"])) \
                if feature("referrals", cfg) else []
            c.execute("DELETE FROM contacts WHERE job_id=? AND sent=0", (job["id"],))
            for p in contacts:
                c.execute("""INSERT OR IGNORE INTO contacts (job_id, company, name, headline, url, kind, rank, note,
                             followup, found_at, url_norm) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                          (job["id"], job["company"], p["name"], p["headline"], p["url"], p["kind"], p["rank"],
                           p["note"], p["followup"], now_iso(), safeguards.norm_profile_url(p["url"])))
            db.set_job(c, job["id"], status="ready", resume_docx=res["docx"], resume_pdf=pdf_path,
                       cover_letter=res["cover_letter"], interview_prep=json.dumps(res["interview_prep"]),
                       gaps=json.dumps(res["gaps"]), llm_used=res["llm"] or "none (keyword mode)",
                       edits_log=json.dumps({"applied": res["edits_applied"], "rejected": res["edits_rejected"],
                                             "fit": res["fit_line"], "master": res["master"],
                                             "cover_letter_pdf": cl_pdf}),
                       status_note=res["fit_line"] or None, retry_note=None,
                       resume_edited_at=None, cover_edited_at=None)
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


def contacted_elsewhere(c, job_id):
    """Profile URLs already lined up for a DIFFERENT role (sent or not) - they don't get a second note."""
    if not safeguards.settings().get("referral_dedup", True):
        return set()
    return {r["url_norm"] for r in db.rows(c, "SELECT DISTINCT url_norm FROM contacts WHERE job_id<>? AND url_norm IS NOT NULL",
                                           (job_id,))}


def notion_tiers():
    """Fill Notion's 'Tier used' column for applications already in the tracker."""
    import notion_sync
    c = db.conn()
    rows = db.rows(c, "SELECT * FROM jobs WHERE notion_page_id IS NOT NULL")
    n = 0
    for j in rows:
        try:
            if notion_sync.set_tier_used(j["notion_page_id"], j):
                n += 1
        except Exception as e:
            log(f"  {j['company']}: {e}")
    log(f"Tier used filled on {n} of {len(rows)} tracker row(s)")


def fix_links(quiet=False):
    """Re-check every saved apply link against its company + title. Links that belong to another job
    (taken from a 'similar jobs' box) are reset to the board page; submit then finds the real one."""
    import applylinks, urllib.parse
    c = db.conn()
    bad = 0
    for j in db.rows(c, "SELECT id, company, title, url, apply_url, status FROM jobs WHERE apply_url IS NOT NULL "
                        "AND apply_url <> url AND status IN ('new','ready','approved','retry','needs_you','preparing','failed')"):
        board_host = urllib.parse.urlparse(j["url"] or "").netloc
        if not applylinks.link_fits(j["apply_url"], j["company"], j["title"], board_host):
            db.set_job(c, j["id"], apply_url=j["url"])
            db.event(c, j["id"], "apply_link_reset", f"was {j['apply_url'][:200]} - belongs to another job")
            bad += 1
            if not quiet:
                log(f"  reset wrong apply link: {j['company']} - {j['title']} (was {j['apply_url'][:90]})")
    # platforms where you apply inside the site: label them so Review shows it before you approve
    for j in db.rows(c, "SELECT id FROM jobs WHERE (url LIKE '%wellfound.com%' OR apply_url LIKE '%wellfound.com%') "
                        "AND COALESCE(apply_route,'') = '' AND status IN ('new','ready','approved','retry')"):
        db.set_job(c, j["id"], apply_route="manual_platform")
    # links reset earlier that pass the current rules (e.g. employer name unknown but the link spells the title)
    back = 0
    for e in db.rows(c, "SELECT e.job_id, e.detail, j.company, j.title, j.url FROM events e JOIN jobs j ON j.id = e.job_id "
                        "WHERE e.event = 'apply_link_reset' AND j.apply_url = j.url"):
        old = re.sub(r"^was (\S+).*$", r"\1", e["detail"] or "")
        if old.startswith("http") and applylinks.link_fits(old, e["company"], e["title"], urllib.parse.urlparse(e["url"] or "").netloc):
            db.set_job(c, e["job_id"], apply_url=old)
            db.event(c, e["job_id"], "apply_link_restored", old[:200])
            back += 1
    c.commit()
    log(f"apply links checked: {bad} wrong link(s) reset, {back} restored")
    return bad


def submit_approved(auto=False):
    """auto=True on the scheduled runs: send every approved role, never wait for you - anything that
    hits a wall lands in Needs you with a 'Prep manual apply' note."""
    import submit, notion_sync
    if not feature("auto_fill"):
        log("auto-fill is switched off in Settings > Features - apply with the downloaded files, then press 'I submitted it'")
        return
    c = db.conn()
    jobs = db.rows(c, "SELECT * FROM jobs WHERE status='approved' ORDER BY score DESC")
    if not jobs:
        log("nothing approved to submit")
        return
    fix_links(quiet=True)
    jobs = db.rows(c, "SELECT * FROM jobs WHERE status='approved' ORDER BY score DESC")
    cfg = load_config()
    clear = []
    for j in jobs:
        guard = safeguards.check(c, j, cfg)
        if guard and guard["level"] == "block":
            # something else went to this company/platform after you approved - back to Review with the reason
            db.set_job(c, j["id"], status="ready", lock_note=guard["message"], status_note=guard["message"])
            db.event(c, j["id"], "safeguard_hold", guard["message"])
            log(f"  held back {j['company']} - {guard['message']}")
            continue
        try:
            j["cover_letter_pdf"] = json.loads(j.get("edits_log") or "{}").get("cover_letter_pdf")
        except Exception:
            pass
        db.set_job(c, j["id"], status="submitting", version_sent=safeguards.version_label(j["family"], j["tier"]))
        clear.append(j)
    c.commit()
    jobs = clear
    for job_id, status, note, route, qa in submit.run(jobs, log=log, auto=auto):
        fields = {"status": status, "status_note": note, "apply_route": route}
        if qa:
            fields["prep_answers"] = json.dumps(qa)
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
        try:
            notion_sync.set_tier_used(job["notion_page_id"], job)
        except Exception:
            pass
        return
    contacts = db.rows(c, "SELECT * FROM contacts WHERE job_id=? ORDER BY rank", (job_id,))
    try:
        pid = notion_sync.push_application(job, contacts, log=log)
        db.set_job(c, job_id, notion_page_id=pid)
        c.execute("UPDATE contacts SET notion_page_id=? WHERE job_id=?", (pid, job_id))
        c.commit()
    except Exception as e:
        log(f"  Notion write failed for {job['company']}: {e}")


def refer_ready(limit=None):
    """Referral contacts for roles already in Review that have none (e.g. prepared while SearXNG was off).
    Best scores first. Safe to stop and re-run: roles that got contacts, or were searched in the last
    7 days with no result, are skipped."""
    cfg = load_config()
    if not feature("referrals", cfg):
        log("Referrals are switched off in Settings > Features")
        return 0
    c = db.conn()
    rows = db.rows(c, """SELECT * FROM jobs j WHERE status='ready'
                         AND NOT EXISTS (SELECT 1 FROM contacts x WHERE x.job_id=j.id)
                         AND NOT EXISTS (SELECT 1 FROM events e WHERE e.job_id=j.id AND e.event='referrals_none'
                                         AND e.ts >= datetime('now','-7 day'))
                         ORDER BY score DESC, found_at DESC""" + (f" LIMIT {int(limit)}" if limit else ""))
    log(f"finding referral contacts for {len(rows)} role(s) in Review")
    done = people_total = 0
    try:
        for i, job in enumerate(rows, 1):
            try:
                people = referrals.find(job["company"], job["title"], job["family"], log=log,
                                        exclude=contacted_elsewhere(c, job["id"]))
            except Exception as e:
                log(f"  {job['company']}: referral search failed ({type(e).__name__}: {e})")
                continue
            if not people:
                db.event(c, job["id"], "referrals_none", "")
                continue
            for p in people:
                c.execute("""INSERT OR IGNORE INTO contacts (job_id, company, name, headline, url, kind, rank, note,
                             followup, found_at, url_norm) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                          (job["id"], job["company"], p["name"], p["headline"], p["url"], p["kind"], p["rank"],
                           p["note"], p["followup"], now_iso(), safeguards.norm_profile_url(p["url"])))
            done += 1
            people_total += len(people)
            if i % 10 == 0:
                log(f"  progress: {i}/{len(rows)} roles searched, {done} with contacts, {people_total} people")
    finally:
        try:
            referrals.close_browser()
        except Exception:
            pass
    log(f"referrals done: {done} of {len(rows)} roles now have contacts ({people_total} people)")
    return done


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
        people = referrals.find(r["company"], r["position"] or (r["positions"] or ["role"])[0], fam, log=log,
                                exclude=contacted_elsewhere(c, "notion:" + r["page_id"]))
        if not people:
            continue
        for p in people:
            c.execute("""INSERT OR IGNORE INTO contacts (job_id, notion_page_id, company, name, headline, url, kind,
                         rank, note, followup, found_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      ("notion:" + r["page_id"], r["page_id"], r["company"], p["name"], p["headline"], p["url"],
                       p["kind"], p["rank"], p["note"], p["followup"], now_iso()))
            c.execute("UPDATE contacts SET url_norm=? WHERE job_id=? AND url=?",
                      (safeguards.norm_profile_url(p["url"]), "notion:" + r["page_id"], p["url"]))
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
    elif cmd == "submit_auto":
        submit_approved(auto=True)
    elif cmd == "submit":
        submit_approved()
    elif cmd == "fixlinks":
        fix_links()
    elif cmd == "dryfill":
        import submit
        c = db.conn()
        jobs = db.rows(c, f"SELECT * FROM jobs WHERE id IN ({','.join('?' * len(sys.argv[2:]))})", sys.argv[2:])
        for jid, st, note, route, qa in submit.run(jobs, log=log, dry=True):
            log(f"DRY {jid}: {st} [{route}] - {note}")
            for q, a in (qa or [])[:12]:
                log(f"      Q: {q[:90]}\n      A: {a[:300]}")
    elif cmd == "discover":
        import ats_discover
        for n in (sys.argv[2:] or load_config().get("companies_to_watch", [])):
            ats_discover.resolve(n, log=log, force=True)
    elif cmd == "retriage":
        retriage()
    elif cmd == "categories":
        n = categories.backfill(db.conn(), only_missing=False)
        log(f"role categories re-sorted for {n} role(s)")
    elif cmd == "backfill":
        backfill()
    elif cmd == "referrals":
        refer_ready(int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None)
    elif cmd == "tiers":
        notion_tiers()
    elif cmd == "sweep":
        dry = len(sys.argv) > 2 and sys.argv[2] == "dry"  # "sweep dry" only counts, changes nothing
        p, n = safeguards.sweep_all(db.conn(), log=log, dry_run=dry)
        if dry:
            log(f"dry run: {n} weaker role(s) in Review would be skipped (best role per company / recruiter)")
        else:
            log(f"safeguards applied to roles already in Review: {p} skipped by the platform rule, "
                f"{n} by best-role-per-company / recruiter")
    elif cmd == "checklive":
        import liveness
        rest = sys.argv[2:]
        liveness.run(log, dry="dry" in rest, limit=next((int(a) for a in rest if a.isdigit()), None))
    elif cmd == "expire":
        import lifecycle
        lifecycle.expire_stale(log)
    elif cmd == "replies":
        import lifecycle
        lifecycle.watch_replies(log)
    elif cmd == "all":
        import lifecycle
        scan()
        lifecycle.expire_stale(log)
        try:
            import liveness
            liveness.run(log)  # before prepare: no AI time spent on roles that are already gone
        except Exception as e:
            log(f"removed-role check skipped: {type(e).__name__}: {e}")
        prepare()
        if load_config()["submit"].get("auto_submit"):
            try:
                submit_approved(auto=True)
            except Exception as e:
                log(f"auto-submit stopped: {type(e).__name__}: {e}")
        if feature("email_alerts", load_config()):
            try:
                lifecycle.watch_replies(log)
            except Exception as e:
                log(f"reply watch skipped: {type(e).__name__}: {e}")
        try:  # keep the phone site current even when the PC dashboard isn't open
            import cloud_sync
            cs = cloud_sync.settings()
            if cloud_sync.ready(cs):
                log(f"online dashboard: {cloud_sync.push(cs)} changed role(s) sent")
        except Exception as e:
            log(f"online dashboard update skipped: {type(e).__name__}: {e}")
    else:
        print(__doc__)
