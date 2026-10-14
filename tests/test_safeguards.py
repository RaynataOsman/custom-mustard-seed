"""Company lock, platform rule, version labels and referral dedup. Runs on a throwaway database."""
import datetime, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import db, safeguards as sg

db.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "t.db"
c = db.conn()
CFG = {"safeguards": {"company_mode": "warn", "lookback_days": 90}}
today = datetime.date.today().isoformat()


def add(jid, company, family, tier, status, score=60, applied=None):
    db.upsert_job(c, {"id": jid, "title": f"{family} {tier} role {jid}", "company": company})
    db.set_job(c, jid, family=family, tier=tier, status=status, score=score, applied_at=applied)
    c.commit()
    return db.rows(c, "SELECT * FROM jobs WHERE id=?", (jid,))[0]


# names
assert sg.norm_company("Pavago, LLC") == sg.norm_company("pavago.com") == sg.norm_company("Pavago (Remote)") == "pavago"
assert sg.norm_company("The Acme Group Ltd") == "acme"
assert sg.version_label("dev", "HM") == "HM_ Dev" and sg.version_label("admin", "J") == "J_ Admin"
assert sg.norm_profile_url("https://za.linkedin.com/in/jane-doe-123?trk=x") == sg.norm_profile_url("https://www.linkedin.com/in/jane-doe-123/")
assert sg.is_platform({"company": "Pavago"}, sg.settings(CFG))
assert not sg.is_platform({"company": "Magic Leap"}, sg.settings(CFG))

# 1. company lock: different version at the same company -> warning in Review
add("a1", "Acme Inc", "dev", "HM", "submitted", applied=today)
j = add("a2", "ACME", "admin", "J", "new")
r = sg.check(c, j, CFG)
assert r["level"] == "warn" and "HM_ Dev" in r["message"] and "Already applied" in r["message"], r
r = sg.check(c, j, {"safeguards": {"company_mode": "skip"}})
assert r["level"] == "block", r
# same version again -> just a note
j = add("a3", "Acme", "dev", "HM", "new")
assert sg.check(c, j, CFG)["level"] == "info"
# outside the 90-day window -> clear
c.execute("UPDATE jobs SET applied_at='2020-01-01', updated_at='2020-01-01', found_at='2020-01-01' WHERE id='a1'"); c.commit()
assert sg.check(c, add("a4", "Acme", "admin", "J-M", "new"), CFG) is None

# 2. platform rule: family already SENT to the platform -> block other families
add("p1", "Pavago", "admin", "J", "submitted", score=55, applied=today)
r = sg.check(c, add("p2", "Pavago LLC", "dev", "S", "new", score=90), CFG)
assert r["level"] == "block" and r["rule"] == "platform", r
# same family, other tier -> company warning, not a platform block
r = sg.check(c, add("p3", "Pavago", "admin", "HM", "new"), CFG)
assert r["level"] == "warn", r
# nothing sent yet: the strongest match wins, weaker roles are the losers
add("h1", "Huzzle", "admin", "J", "ready", score=50)
r = sg.check(c, add("h2", "Huzzle", "dev", "HM", "new", score=80), CFG)
assert r["level"] == "wins" and r["losers"] == ["h1"], r
r = sg.check(c, add("h3", "Huzzle", "design", "ONE", "new", score=40), CFG)
assert r["level"] == "block" and "stronger" in r["message"], r

# 4. referral dedup data: url_norm is filled on old rows
c.execute("INSERT INTO contacts (job_id, company, name, url, kind, rank) VALUES ('a1','Acme','Jane','https://www.linkedin.com/in/jane/','recruiter',1)")
c.commit()
c2 = db.conn()
assert db.rows(c2, "SELECT url_norm FROM contacts")[0]["url_norm"] == "li:jane"
print("safeguards ok")

# sweep: roles prepared before the rule existed
add("s1", "Pearl Talent", "admin", "J", "ready", score=70)
add("s2", "Pearl Talent", "admin", "HM", "ready", score=50)
add("s3", "Pearl Talent", "dev", "S", "ready", score=60)
assert sg.sweep(c, log=lambda *a: None, cfg=CFG) >= 1
st = {r["id"]: r["status"] for r in db.rows(c, "SELECT id, status FROM jobs WHERE id IN ('s1','s2','s3')")}
assert st == {"s1": "ready", "s2": "ready", "s3": "skipped"}, st
print("sweep ok")
