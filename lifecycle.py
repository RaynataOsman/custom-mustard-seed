"""What happens to a role after it is found: it goes stale, it needs a follow-up, or the employer replies.

  expire_stale()   roles waiting in New / Review longer than search.max_age_days -> 'expired'
                   (sweeps decay in about a week; a 3-week-old Review queue is mostly dead links)
  followups()      roles applied to 7+ days ago with no reply -> listed on the Applied tab with a draft note
  watch_replies()  reads the Gmail inbox (read-only, never marks anything read) for replies from employers
                   you applied to, classifies them interview / rejection / received / offer, records it on the
                   role and moves the Notion Stage (Interview, Rejected, Offered) with the Response date.

All three are rules only - no AI, no Claude, no messages sent.
"""
import datetime, email, email.utils, imaplib, json, re
import db
from util import load_config, now_iso, today

REPLY_RULES = [  # first match wins; checked against subject + first 3000 chars of the body
    ("offer", re.compile(r"\b(offer letter|pleased to offer|job offer|offer of employment|contract (attached|for you))\b", re.I)),
    ("interview", re.compile(r"\b(interview|schedule (a|an|some) (call|time|chat)|book a (time|slot)|calendly\.com|"
                             r"next (step|stage|round)|availability (for|to)|meet the team|assessment|take-home|"
                             r"technical (test|task|challenge)|screening call)\b", re.I)),
    ("rejection", re.compile(r"\b(unfortunately|not (be )?moving forward|decided to (move|proceed) with other|"
                             r"other candidates|not been successful|regret to inform|will not be progressing|"
                             r"position has been filled|no longer (being )?considered|not selected)\b", re.I)),
    ("received", re.compile(r"\b(received your application|thank(s| you) for (applying|your application|your interest)|"
                            r"application (has been )?(received|submitted))\b", re.I)),
]
NOTION_STAGE = {"interview": "Interview", "rejection": "Rejected", "offer": "Offered"}


def _cfg():
    cfg = load_config()
    lc = cfg.get("lifecycle", {})
    return cfg, {"followup_days": int(lc.get("followup_days", 7)), "reply_days": int(lc.get("reply_days", 45)),
                 "expire_days": int(lc.get("expire_days", cfg["search"].get("max_age_days", 21)))}


def _ensure_cols(c):
    for col in ("reply_kind", "reply_at", "reply_from", "reply_subject", "followup_at"):
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
        except Exception:
            pass


# ------------------------------------------------------------------ stale roles
def expire_stale(log=print):
    cfg, s = _cfg()
    c = db.conn()
    cut = (datetime.date.today() - datetime.timedelta(days=s["expire_days"])).isoformat()
    rows = db.rows(c, """SELECT id, found_at, posted_at FROM jobs WHERE status IN ('new','ready','retry')
                         AND coalesce(nullif(substr(posted_at,1,10),''), substr(found_at,1,10)) < ?""", (cut,))
    for r in rows:
        db.set_job(c, r["id"], status="expired",
                   status_note=f"Posted or found more than {s['expire_days']} days ago - most roles this old are closed")
    if rows:
        log(f"expired {len(rows)} roles older than {s['expire_days']} days")
    return len(rows)


# ------------------------------------------------------------------ follow-ups
def followups(c=None):
    """Roles applied to followup_days+ ago with no reply and no follow-up recorded yet."""
    cfg, s = _cfg()
    c = c or db.conn()
    _ensure_cols(c)
    cut = (datetime.date.today() - datetime.timedelta(days=s["followup_days"])).isoformat()
    rows = db.rows(c, """SELECT id, title, company, applied_at, url, apply_url, notion_page_id FROM jobs
                         WHERE status='submitted' AND coalesce(reply_kind,'') IN ('','received')
                         AND followup_at IS NULL AND substr(applied_at,1,10) <= ? ORDER BY applied_at""", (cut,))
    name = (cfg.get("profile", {}).get("name") or "").split(" ")[0] or "there"
    for r in rows:
        days = (datetime.date.today() - datetime.date.fromisoformat(r["applied_at"][:10])).days
        r["days"] = days
        r["draft"] = (f"Hi {r['company']} team, I applied for the {r['title']} role on "
                      f"{datetime.date.fromisoformat(r['applied_at'][:10]):%d %b} and wanted to check in. I'm still very "
                      f"interested and happy to share more work or jump on a short call. Kind regards, "
                      f"{cfg.get('profile', {}).get('name', '')}").strip()
    return rows


def mark_followed_up(job_id):
    c = db.conn()
    _ensure_cols(c)
    db.set_job(c, job_id, followup_at=now_iso())
    db.event(c, job_id, "followed_up", "")
    row = db.rows(c, "SELECT notion_page_id FROM jobs WHERE id=?", (job_id,))
    if row and row[0]["notion_page_id"]:
        try:
            import notion_sync
            notion_sync.update_stage(row[0]["notion_page_id"], "Followed up")
        except Exception:
            pass


# ------------------------------------------------------------------ employer replies
def classify(subject, body):
    text = f"{subject}\n{(body or '')[:3000]}"
    for kind, rx in REPLY_RULES:
        if rx.search(text):
            return kind
    return None


def _match(job_norms, sender, subject, body):
    """Which applied role does this email belong to? Company name in the sender, its domain or the subject."""
    from safeguards import norm_company
    name, addr = email.utils.parseaddr(sender)
    dom = addr.split("@")[-1].lower() if "@" in addr else ""
    dom_core = norm_company(dom.split(".")[-2] if dom.count(".") >= 1 else dom)
    hay = norm_company(f"{name} {subject}") + " " + norm_company((body or "")[:1500])
    best = None
    for jid, n in job_norms:
        if len(n) < 3:
            continue
        if n == dom_core or (len(n) >= 5 and n in hay):
            best = jid
            break
    return best


def watch_replies(log=print, dry=False):
    import email_alerts
    cfg, s = _cfg()
    c = db.conn()
    _ensure_cols(c)
    since_d = (datetime.date.today() - datetime.timedelta(days=s["reply_days"])).isoformat()
    jobs = db.rows(c, """SELECT id, company, company_norm, notion_page_id, reply_kind FROM jobs
                         WHERE status IN ('submitted','needs_you') AND substr(coalesce(applied_at, updated_at),1,10) >= ?""",
                   (since_d,))
    if not jobs:
        log("reply watch: no applications in the look-back window yet")
        return []
    norms = [(j["id"], j["company_norm"] or "") for j in jobs]
    by_id = {j["id"]: j for j in jobs}
    seen_ids = {r["detail"] for r in db.rows(c, "SELECT detail FROM events WHERE event='reply_msg'")}
    M = email_alerts._connect()
    found = []
    try:
        M.select("INBOX", readonly=True)
        since = datetime.date.today() - datetime.timedelta(days=s["reply_days"])
        typ, data = M.search(None, f'(SINCE {since:%d-%b-%Y})')
        ids = (data[0] or b"").split()[-800:]
        for mid in reversed(ids):
            typ, msg_data = M.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            hdr = email.message_from_bytes(msg_data[0][1])
            msgid = (hdr.get("Message-ID") or mid.decode()).strip()
            if msgid in seen_ids:
                continue
            sender, subject = email_alerts._decode(hdr.get("From", "")), email_alerts._decode(hdr.get("Subject", ""))
            if re.search(r"noreply@(linkedin|indeed|glassdoor)|jobalerts|job alert|newsletter", sender + subject, re.I):
                continue  # alert emails, not replies
            jid = _match(norms, sender, subject, "")
            if not jid:
                continue
            typ, full = M.fetch(mid, "(BODY.PEEK[])")
            msg = email.message_from_bytes(full[0][1])
            body = email_alerts.strip_html(email_alerts._body(msg)) if hasattr(email_alerts, "strip_html") else ""
            kind = classify(subject, body)
            if not kind:
                continue
            try:
                when = email.utils.parsedate_to_datetime(hdr.get("Date")).date().isoformat()
            except Exception:
                when = today()
            found.append({"job_id": jid, "kind": kind, "from": sender, "subject": subject, "date": when})
            if dry:
                continue
            rank = ["received", "rejection", "interview", "offer"]
            cur = by_id[jid].get("reply_kind") or ""
            if not cur or rank.index(kind) >= rank.index(cur if cur in rank else "received"):
                db.set_job(c, jid, reply_kind=kind, reply_at=when, reply_from=sender[:200], reply_subject=subject[:200])
                by_id[jid]["reply_kind"] = kind
                page = by_id[jid].get("notion_page_id")
                if page and kind in NOTION_STAGE:
                    try:
                        import notion_sync
                        from util import http
                        notion_sync.update_stage(page, NOTION_STAGE[kind])
                        http().patch(f"{notion_sync.API}/pages/{page}", headers=notion_sync._h(),
                                     json={"properties": {"Response date": {"date": {"start": when}}}})
                    except Exception as e:
                        log(f"  Notion stage update failed for {jid}: {e}")
            db.event(c, jid, "reply_msg", msgid)
            log(f"  reply: {kind} - {by_id[jid]['company']} - {subject[:70]}")
    finally:
        try:
            M.logout()
        except Exception:
            pass
    log(f"reply watch: {len(found)} employer replies matched")
    return found
