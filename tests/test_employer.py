import os, sys, tempfile, sqlite3, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import triage, db, util

CFG = {"geo": {}, "companies_to_watch": ["GitLab", "Zapier"], "boards": [{"name": "SA Board", "local": True}]}
E = lambda **k: triage.employer(k, CFG)
T = lambda d: triage.timezone_fit({"description": d}, CFG)

assert E(company="Acme (Pty) Ltd", description="Remote. R30 000 CTC")[0] == "sa_local"
r = E(location="Johannesburg, Gauteng, South Africa", description="Remote role for a US SaaS company, pay USD 2,000/month")
assert r[0] != "sa_local", r
assert E(company="Cherry Assistant", description="R12 000 per month")[0] == "sa_aggregator"
assert E(company="Cherry Assistant", description="paid in USD")[0] not in ("sa_aggregator", "sa_local")
assert E(company="Deel", description="anything")[0] == "overseas_platform"
assert E(location="Anywhere in the World (HQ: United States)", description="fully remote")[0] == "overseas_direct"
assert E(location="South Africa", description="Remote, async team")[0] in ("unknown", "overseas_direct")
assert E(company="BrandCo", description="We build brands for clients")[0] != "sa_local"
assert "rand" not in E(company="BrandCo", description="We build brands for clients")[1]
ok, why = T("Must work PST business hours"); assert ok is False and "Pacific" in why, why
assert T("4 hours overlap with EST required")[0] is True
assert T("Work during UK hours")[0] is True
assert T("We are a friendly remote team")[0] is None
assert triage.sa_local({"company": "Acme (Pty) Ltd", "description": "R30 000 CTC"}) is True

# old-schema DB upgrade
tmp = pathlib.Path(tempfile.mkdtemp()) / "old.db"
o = sqlite3.connect(tmp)
o.executescript(db.SCHEMA.replace(",\n  employer_type TEXT, employer_reason TEXT, tz_reason TEXT", ""))
o.execute("INSERT INTO jobs (id,title) VALUES ('1','x')"); o.commit(); o.close()
assert "employer_type" not in {r[1] for r in sqlite3.connect(tmp).execute('PRAGMA table_info(jobs)')}
db.DB_PATH = tmp
c = db.conn()
cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
assert {"employer_type", "employer_reason", "tz_reason"} <= cols, cols
db.set_job(c, "1", employer_type="unknown", tz_reason="x")
c.close(); db.conn().close()  # second open is idempotent
print("all tests passed")
