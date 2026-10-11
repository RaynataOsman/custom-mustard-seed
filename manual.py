"""Manual jobs: a role you found yourself (LinkedIn post, WhatsApp group, a board we can't read,
an email from a recruiter). You paste the brief - or the link - and the engine:

  1. weighs it against EVERY resume family/tier you have and picks the best one (you can override),
  2. checks employer type (overseas vs SA agency), time zone and red flags,
  3. asks the free AI for an honest odds verdict,
  4. on "Prepare" runs the normal pipeline (tailored resume + cover letter + interview prep +
     referral contacts) and puts a row in Notion as "Waiting for a referral" so it is tracked
     even before you apply,
  5. when you press "I submitted it" the same Notion row moves to Applied with today's date.

Nothing is submitted for you here - you apply yourself with the downloaded files.
"""
import json, re
import db, triage, tailor
from util import load_config, job_key, get, strip_html, now_iso, ascii_clean

BOARD = "Manual"


def _fetch(url):
    try:
        r = get(url, timeout=25)
        if r.status_code >= 400:
            return "", f"could not open the link (HTTP {r.status_code}) - paste the text instead"
        html = r.text
        # JSON-LD JobPosting is the cleanest source when the page has it
        for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
            try:
                d = json.loads(m.group(1).strip())
            except Exception:
                continue
            for it in (d if isinstance(d, list) else d.get("@graph", [d])):
                if isinstance(it, dict) and it.get("@type") == "JobPosting":
                    org = it.get("hiringOrganization") or {}
                    return json.dumps({"title": it.get("title"), "company": org.get("name") if isinstance(org, dict) else "",
                                       "description": strip_html(it.get("description") or "")}), "ok"
        text = strip_html(html)
        if re.search(r"just a moment|verify you are human|enable javascript", text[:2000], re.I) or len(text) < 400:
            return "", "the site blocked the read or needs a sign-in - paste the job text instead"
        return text[:30000], "ok"
    except Exception as e:
        return "", f"could not open the link ({type(e).__name__}) - paste the text instead"


def _guess(text):
    """Best-effort title / company from pasted text when the boxes are left blank."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = company = ""
    for l in lines[:15]:
        if not title and 3 < len(l) < 90 and triage.family_of(l, load_config()):
            title = l
        m = re.search(r"\b(?:at|@|company:)\s+([A-Z][\w&.\- ]{1,40})", l)
        if not company and m:
            company = m.group(1).strip(" .-")
    return title or (lines[0][:90] if lines else ""), company


ODDS_SYS = ("You are a blunt recruiter. Judge a candidate's real chances for one job. Use ONLY the resume and job text. "
            "Return JSON: {\"odds\": \"high|medium|low\", \"match_pct\": 0-100, \"why\": [max 4 short reasons], "
            "\"red_flags\": [max 4: e.g. needs local entity, US-only, unpaid trial, crypto/MLM, pay via agency, "
            "night shift, asks for payment], \"must_mention\": [max 4 things the cover letter must cover]}. "
            "Plain ASCII, no marketing words.")


def analyse(body):
    cfg = load_config()
    url = (body.get("url") or "").strip()
    text = (body.get("text") or "").strip()
    title = (body.get("title") or "").strip()
    company = (body.get("company") or "").strip()
    note = ""
    if url and len(text) < 200:
        got, note = _fetch(url)
        if got.startswith("{"):
            d = json.loads(got)
            title, company, text = title or d["title"] or "", company or d["company"] or "", d["description"]
        elif got:
            text = got
    if len(text) < 80:
        return {"ok": False, "error": note or "Paste the job description (at least a few lines) or a working link."}
    if not title or not company:
        gt, gc = _guess(text)
        title, company = title or gt, company or gc or "Unknown company"

    job = {"title": ascii_clean(title)[:150], "company": ascii_clean(company)[:120], "url": url or None,
           "apply_url": url or None, "location": (body.get("location") or "").strip(), "description": text,
           "salary": (body.get("salary") or "").strip() or None, "board": BOARD, "source": "manual",
           "posted_at": now_iso()[:10]}
    job["id"] = job_key(job["company"], job["title"])

    # score against every family/tier, not just the one the title points at
    options = []
    for fam in cfg["families"]:
        tier, yrs = triage.tier_of(job["title"], text, fam, cfg)
        try:
            tailor.master_path(fam, tier)
        except FileNotFoundError:
            continue  # no resume uploaded for this family yet
        s, reasons = triage.fit_score(dict(job, geo_ok=1), fam, tailor.vocab(fam))
        options.append({"family": fam, "tier": tier, "score": s, "reasons": reasons, "years_asked": yrs})
    options.sort(key=lambda o: -o["score"])
    pick = dict(options[0]) if options else {"family": "dev", "tier": "HM", "score": 0, "reasons": []}
    if body.get("family") in cfg["families"]:
        pick["family"] = body["family"]
        pick["tier"] = body.get("tier") or triage.tier_of(job["title"], text, pick["family"], cfg)[0]
        pick.update(next((o for o in options if o["family"] == pick["family"]), {}), family=pick["family"],
                    tier=pick["tier"])

    geo_ok, geo_why = triage.geo(job)
    emp_type, emp_why = triage.employer(job, cfg)
    tz_ok, tz_why = triage.timezone_fit(job, cfg)
    ai_ban = bool(triage.AI_BAN.search(text))
    warnings = []
    if not triage.family_of(job["title"], cfg) and not body.get("family"):
        warnings.append(f"This title doesn't match any of your resume families - closest resume is "
                        f"{pick['family']} {pick['tier']}. Add a family in Settings if you want to go after this kind of role.")
    if geo_ok == 0:
        warnings.append("Location: " + geo_why)
    if emp_type in ("sa_local", "sa_aggregator"):
        warnings.append("Employer: " + emp_why + " (you said you only want overseas employers who pay you directly)")
    if tz_ok is False:
        warnings.append("Hours: " + tz_why)
    if ai_ban:
        warnings.append("This posting bans AI-written applications - rewrite the cover letter in your own words.")
    if re.search(r"\b(pay (a|the) fee|training fee|starter kit|deposit|telegram|whatsapp only|crypto|forex|commission[- ]only)\b",
                 text, re.I):
        warnings.append("Scam signals: asks for money, Telegram/WhatsApp-only contact, or commission-only.")

    odds = None
    try:
        import llm
        if llm.available():
            master = tailor.full_text(__import__("docx").Document(tailor.master_path(pick["family"], pick["tier"])))
            odds, who = llm.chat_json(ODDS_SYS, f"RESUME:\n{master[:7000]}\n\nJOB: {job['title']} at {job['company']}\n{text[:9000]}",
                                      max_tokens=700, temperature=0.2)
            if isinstance(odds, dict):
                odds["model"] = who
    except Exception as e:
        odds = {"error": f"AI odds unavailable ({e})"}

    c = db.conn()
    is_new = db.upsert_job(c, job)
    db.set_job(c, job["id"], board=BOARD, family=pick["family"], tier=pick["tier"], geo_ok=geo_ok,
               geo_reason=geo_why, score=pick["score"], score_reasons="; ".join(pick.get("reasons", [])),
               ai_ban=1 if ai_ban else 0, employer_type=emp_type, employer_reason=emp_why, tz_reason=tz_why,
               status_note=("Manual: " + "; ".join(warnings))[:500] if warnings else "Manual entry",
               **({"status": "new"} if is_new else {}))
    db.event(c, job["id"], "manual_added", {"odds": odds, "warnings": warnings})
    c.commit()
    return {"ok": True, "id": job["id"], "new": is_new, "title": job["title"], "company": job["company"],
            "pick": pick, "options": options[:6], "warnings": warnings, "odds": odds,
            "employer": emp_type, "timezone": tz_why, "fetch_note": note,
            "families": {f: v["tiers"] for f, v in cfg["families"].items()}}


def record_prepared(job_id, log=print):
    """After a manual job is prepared: Notion row as 'Waiting for a referral' so it is tracked before you apply."""
    import notion_sync
    c = db.conn()
    job = db.rows(c, "SELECT * FROM jobs WHERE id=?", (job_id,))[0]
    if job.get("notion_page_id"):
        return job["notion_page_id"]
    contacts = db.rows(c, "SELECT * FROM contacts WHERE job_id=? ORDER BY rank", (job_id,))
    pid = notion_sync.push_application(job, contacts, log=log, stage="Waiting for a referral",
                                       text_prefix="PREPARED - submit manually | ")
    db.set_job(c, job_id, notion_page_id=pid)
    c.execute("UPDATE contacts SET notion_page_id=? WHERE job_id=?", (pid, job_id))
    c.commit()
    return pid
