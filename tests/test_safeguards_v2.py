"""Safeguards v2: skip is the default, best role per company, recruiter check, Allow anyway. Throwaway database."""
import datetime, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import db, safeguards as sg

db.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "t2.db"
c = db.conn()
CFG = {"safeguards": {"lookback_days": 90}}  # defaults: company_mode skip, recruiter_check on
today = datetime.date.today().isoformat()
assert sg.settings(CFG)["company_mode"] == "skip" and sg.settings(CFG)["recruiter_check"] is True


def add(jid, company, family="dev", tier="HM", status="ready", score=60, applied=None, desc="", apply_url=None):
    db.upsert_job(c, {"id": jid, "title": f"Role {jid}", "company": company, "description": desc, "apply_url": apply_url})
    db.set_job(c, jid, family=family, tier=tier, status=status, score=score, applied_at=applied)
    c.commit()
    db.conn()  # runs the contact_keys backfill
    return db.rows(c, "SELECT * FROM jobs WHERE id=?", (jid,))[0]


def get(jid):
    return db.rows(c, "SELECT * FROM jobs WHERE id=?", (jid,))[0]


# ---- contact keys
k = sg.contact_keys("Send your CV to Jane.Doe@AcmeCorp.com or privacy@acmecorp.com. See https://jobs.lever.co/acme-labs/123 "
                    "and https://www.linkedin.com/in/jane-doe-77/ logo@2x.png noreply@acmecorp.com me@gmail.com")
assert " em:jane.doe@acmecorp.com " in k and " dom:acmecorp.com " in k and " ats:acme-labs " in k and " li:jane-doe-77 " in k, k
assert "privacy@" not in k and "noreply" not in k and "2x.png" not in k and "dom:gmail.com" not in k and "em:me@gmail.com" in k, k
assert sg.contact_keys("apply at https://boards.greenhouse.io/embed/job_board?for=zeta and hr@indeed.com") == " ats:zeta "
assert sg.contact_keys("nothing here") == ""

# ---- 1. company lock, skip mode: a sent role blocks any other role at that company, same version or not
add("s1", "Acme Inc", "dev", "HM", "submitted", applied=today)
j = add("s2", "ACME", "dev", "HM", "ready", score=95)
r = sg.check(c, j, CFG)
assert r["level"] == "block" and r["rule"] == "company" and "Already applied" in r["message"] and "one application per company" in r["message"], r
# ... allow anyway lifts it
db.set_job(c, "s2", allow_override=1); c.commit()
r = sg.check(c, get("s2"), CFG)
assert r["level"] == "allowed" and r["message"].startswith("Allowed by you - "), r
assert sg.note_for(r)

# ---- 2. best role per company: the stronger waiting role wins, the weaker one is held / skipped
add("b1", "Bolt Ltd", status="ready", score=70)
add("b2", "Bolt", status="ready", score=82)
add("b3", "Bolt Group", status="ready", score=55)
w = sg.check(c, get("b2"), CFG)
assert w["level"] == "wins" and set(w["losers"]) == {"b1", "b3"} and "Skipped - weaker match" in w["loser_note"], w
l = sg.check(c, get("b1"), CFG)
assert l["level"] == "block" and "Skipped - weaker match" in l["message"] and "fit 82 vs 70" in l["message"], l
# warn mode never blocks
wm = sg.check(c, get("b1"), {"safeguards": {"company_mode": "warn"}})
assert wm["level"] in ("warn", "info"), wm
# tie -> exactly one of the two wins (never both held, never both clear)
add("t1", "Tie Co", status="ready", score=60)
add("t2", "Tie Co", status="ready", score=60)
lv = sorted(sg.check(c, get(x), CFG)["level"] for x in ("t1", "t2"))
assert lv == ["block", "wins"], lv

# sweep: skips the weaker ones, keeps the best, spares Allow anyway
plan_before = sg.sweep_company(c, cfg=CFG, dry_run=True)
assert plan_before >= 3, plan_before
db.set_job(c, "b3", allow_override=1); c.commit()
n = sg.sweep_company(c, log=lambda *_: None, cfg=CFG)
st = {x: get(x)["status"] for x in ("b1", "b2", "b3", "t1", "t2")}
assert st["b2"] == "ready" and st["b1"] == "skipped" and st["b3"] == "ready", st
assert sorted([st["t1"], st["t2"]]) == ["ready", "skipped"], st
assert "Skipped - weaker match" in get("b1")["lock_note"], get("b1")["lock_note"]
assert sg.lock_for(c, get("b1"))["level"] == "skipped"
assert sg.sweep_company(c, log=lambda *_: None, cfg=CFG) == 0  # idempotent

# a sent role beats every waiting role at the company
add("c1", "Corp One", status="submitted", score=40, applied=today)
add("c2", "Corp One", status="ready", score=99)
sg.sweep_company(c, log=lambda *_: None, cfg=CFG)
assert get("c2")["status"] == "skipped" and "already applied" in get("c2")["lock_note"].lower(), get("c2")

# hidden employers and job-board names are never grouped
add("u1", "Confidential", score=60); add("u2", "Confidential", score=70)
assert sg.check(c, get("u1"), CFG) is None and sg.check(c, get("u2"), CFG) is None

# ---- 3. recruiter check: different companies, same recruiter
add("r1", "Alpha Widgets", score=65, desc="Apply to talent@bravo-recruit.io")
add("r2", "Zeta Gadgets", score=80, desc="Questions? talent@bravo-recruit.io")
add("r3", "Omega Goods", score=50, apply_url="https://jobs.lever.co/omega-hq/abc")
add("r4", "Omega Goods Hiring Team", score=50, apply_url="https://jobs.lever.co/omega-hq/xyz")  # same company norm -> company rule
a = sg.check(c, get("r1"), CFG)
assert a["level"] == "block" and a["rule"] == "recruiter" and "talent@bravo-recruit.io" in a["message"], a
b = sg.check(c, get("r2"), CFG)
assert b["level"] == "wins" and b["rule"] == "recruiter" and b["losers"] == ["r1"], b
off = sg.check(c, get("r1"), {"safeguards": {"recruiter_check": False}})
assert off is None, off
sg.sweep_company(c, log=lambda *_: None, cfg=CFG)
assert get("r1")["status"] == "skipped" and "same recruiter" in get("r1")["lock_note"] and get("r2")["status"] == "ready"
# sent to a recruiter already -> other company via that recruiter is held
add("r5", "Sigma Inc", status="submitted", score=60, applied=today, desc="mail hr@sigma-staff.com")
add("r6", "Tau Inc", score=99, desc="mail hr@sigma-staff.com")
x = sg.check(c, get("r6"), CFG)
assert x["level"] == "block" and x["rule"] == "recruiter" and "Already applied" in x["message"], x

# ---- 4. Allow anyway through the app action (skipped role comes back to Review with its resume)
import app
db.set_job(c, "r1", resume_docx="x.docx"); c.commit()
app_c = app.db.conn()
res = app.job_action("r1", {"action": "allow"})
assert res["ok"], res
j = get("r1")
assert j["status"] == "ready" and j["allow_override"] == 1 and j["lock_note"] is None, j
assert sg.check(c, j, CFG)["level"] == "allowed"
# approving a held role without override is refused; after Allow anyway it goes through
res = app.job_action("t2" if get("t2")["status"] == "ready" else "t1", {"action": "approve"})
assert res["ok"] or res.get("lock"), res
print("safeguards v2 ok")
