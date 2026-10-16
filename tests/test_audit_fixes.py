"""Regression tests for the 16 Oct 2026 audit fixes. Offline: no network, no browser, no real DB."""
import os, sys, tempfile, threading, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import triage, llm, render, safeguards, pipeline, db

# 1. listing / alert headers are not jobs; real titles still pass
junk = ["Top Remote Account Executive (AE) Jobs", "Frontend jobs", "Your job alert for Software Engineer",
        "Software Engineer jobs in Asia", "30 Remote Javascript jobs", "Remote Customer Support Jobs",
        "Shopify Developer Jobs in Abu Dhabi", "New jobs in North America match your preferences"]
real = ["Senior Full Stack Developer", "Shopify Developer", "Customer Success Engineer", "Virtual Assistant (Remote)",
        "Jobs Coordinator", "Remote Frontend Engineer - React", "UX/UI Designer", "Account Manager, Client Services",
        "Executive Assistant to the CEO", "Job Board Developer (React)"]
assert all(triage.is_listing_title(t) for t in junk), [t for t in junk if not triage.is_listing_title(t)]
assert not any(triage.is_listing_title(t) for t in real), [t for t in real if triage.is_listing_title(t)]

# 2. broken model JSON is repaired; lists become dicts
assert llm._as_dict(llm.parse_json('```json\n{"a": 1, "b": [1,2,],}\n```')) == {"a": 1, "b": [1, 2]}
assert llm._as_dict(llm.parse_json('<think>x</think>{a: "x"}')) == {"a": "x"}
assert llm._as_dict(llm.parse_json('[{"x": 1}]')) == {"x": 1}
assert llm._as_dict(llm.parse_json('{"k": "v"\n "k2": "v2"}')) == {"k": "v", "k2": "v2"}

# 3. board health words
H = pipeline.board_health
assert H("render", None, 0, 0, 0, 0) == "broken: page empty"
assert H("render", None, 80, 0, 0, 0) == "broken: no job links"
assert H("render", None, 80, 12, 0, 0) == "quiet"
assert H("render", None, 80, 12, 5, 3) == "ok"
assert H("render", None, 40, 0, 0, 0, signin=True) == "needs sign-in"
assert H("render", "RuntimeError: blocked by bot protection (Cloudflare/Indeed check)", 0, 0, 0, 0) == "blocked"
assert H("email_alerts", "RuntimeError: Gmail not connected: add GMAIL_ADDRESS", None, None, 0, 0) == "needs sign-in"
assert H("himalayas", None, None, None, 0, 0) == "empty feed"
assert H("email_alerts", None, None, None, 0, 0) == "quiet"
assert H("render", None, 15, 1, 0, 0, signin_board=True) == "needs sign-in"
assert H("himalayas", None, None, None, 50, 0) == "quiet"

# 4. company when the page doesn't say; job-board hostnames are not employers
j = {"url": "https://wellfound.com/jobs/1-x", "title": "Full Stack Engineer at Fireflies.ai"}
assert render._company_guess(j, {}) == "Fireflies.ai" and j["title"] == "Full Stack Engineer"
assert render._company_guess({"url": "https://relocate.me/japan/tokyo/hennge/x-1", "title": "X"},
                             {"company_url_re": r"relocate\.me/[^/]+/[^/]+/([^/]+)/"}) == "Hennge"
hosts = safeguards.board_hosts()
assert safeguards.norm_company("www.jobbank.gc.ca") in hosts and safeguards.norm_company("Gong.io") not in hosts

# 5. autocommit DB: a second writer is never blocked by a long-running reader/writer session
tmp = tempfile.mkdtemp()
db.DB_PATH = os.path.join(tmp, "t.db")
a, b = db.conn(), db.conn()
a.execute("INSERT INTO events (ts, job_id, event, detail) VALUES ('t','j','e','d')")  # no commit call
b.execute("INSERT INTO events (ts, job_id, event, detail) VALUES ('t','j2','e','d')")  # must not wait/lock
assert b.execute("SELECT count(*) FROM events").fetchone()[0] == 2
assert "links" in [r[1] for r in a.execute("pragma table_info(board_runs)")]
print("audit fixes ok")
