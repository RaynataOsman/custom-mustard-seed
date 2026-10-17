"""Hand-edit feature: runs against one real Review role, then puts every file and field back exactly as it was."""
import json, shutil, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db, editor, app
from util import load_config

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print("PASS", name)
    else:
        FAIL += 1
        print("FAIL", name, extra)


c = db.conn()
jobs = db.rows(c, "SELECT * FROM jobs WHERE status='ready' AND resume_docx IS NOT NULL AND cover_letter IS NOT NULL "
                  "AND resume_pdf IS NOT NULL ORDER BY score DESC LIMIT 25")
job = None
for j in jobs:
    ed = json.loads(j.get("edits_log") or "{}")
    if ed.get("cover_letter_pdf") and Path(j["resume_docx"]).is_file() and Path(ed["cover_letter_pdf"]).is_file():
        job = j
        break
assert job, "no suitable ready role to test with"
jid = job["id"]
ed0 = json.loads(job["edits_log"])
files = [Path(job["resume_docx"]), Path(job["resume_pdf"])]
cl_pdf = Path(ed0["cover_letter_pdf"])
files += [cl_pdf, cl_pdf.with_suffix(".docx"), cl_pdf.with_suffix(".txt")]
snap = Path(tempfile.mkdtemp(prefix="edtest_"))
have = {}
for i, f in enumerate(files):
    if f.exists():
        shutil.copy2(f, snap / f"{i}_{f.name}")
        have[i] = f
fields = {k: job.get(k) for k in ("resume_docx", "resume_pdf", "cover_letter", "edits_log", "resume_edited_at", "cover_edited_at")}
print("testing on:", job["company"], "-", job["title"])

try:
    t = editor.get_texts(jid)
    check("get_texts returns resume + cover", t["ok"] and t["resume_text"] and t["cover_letter"] and t["editable"])
    lines = t["resume_text"].split("\n")

    r = editor.save(jid, "resume", t["resume_text"])
    check("unchanged resume saves nothing", r.get("ok") and r.get("unchanged"))

    r = editor.save(jid, "resume", "\n".join(lines[:-1]))
    check("wrong line count refused", not r["ok"] and "one line per paragraph" in r["error"].lower(), r)

    k = max(range(2, len(lines)), key=lambda i: len(lines[i]))
    bad = list(lines)
    bad[k] = lines[k] + " Led a 14 person Kubernetes migration at Acme Rocketry."
    r = editor.save(jid, "resume", "\n".join(bad))
    check("invented number/tool/employer blocked with warning", not r["ok"] and r.get("guard"), r)
    check("blocked save changed nothing", editor.get_texts(jid)["resume_text"] == t["resume_text"])

    good = list(lines)
    good[k] = lines[k].rstrip() + " Work was documented."
    mt = Path(job["resume_docx"]).stat().st_mtime
    r = editor.save(jid, "resume", "\n".join(good))
    check("benign resume edit saved", r.get("ok"), r)
    t2 = editor.get_texts(jid)
    check("docx now holds the edit", "Work was documented." in t2["resume_text"])
    check("resume flag set", bool(t2["resume_edited_at"]))
    pdfp = Path(db.rows(c, "SELECT resume_pdf FROM jobs WHERE id=?", (jid,))[0]["resume_pdf"] or "")
    check("resume pdf rebuilt", pdfp.is_file() and pdfp.stat().st_mtime > mt)

    ok_force = editor.save(jid, "resume", "\n".join(bad), force=True)
    check("force saves past the guard", ok_force.get("ok") and ok_force.get("forced"), ok_force)

    m = app.job_action(jid, {"action": "retry"})
    check("retry on an edited role warns first", m["ok"] is False and m.get("edited"), m)
    check("role still ready after warning", db.rows(c, "SELECT status FROM jobs WHERE id=?", (jid,))[0]["status"] == "ready")

    cov = t["cover_letter"]
    r = editor.save(jid, "cover", cov + "\n\nI have 15 years of experience and grew revenue 300%.")
    check("cover letter with invented figures blocked", not r["ok"] and r.get("guard"), r)
    newcov = cov.replace("Dear", "Dear", 1) + "\n\nHappy to share references on request."
    mt = cl_pdf.stat().st_mtime if cl_pdf.exists() else 0
    r = editor.save(jid, "cover", newcov)
    check("benign cover edit saved", r.get("ok"), r)
    row = db.rows(c, "SELECT * FROM jobs WHERE id=?", (jid,))[0]
    check("db cover text updated", "Happy to share references" in row["cover_letter"])
    txtp = cl_pdf.with_suffix(".txt")
    check(".txt rewritten", txtp.is_file() and "Happy to share references" in txtp.read_text(encoding="utf-8"))
    check(".docx rewritten", cl_pdf.with_suffix(".docx").is_file() and cl_pdf.with_suffix(".docx").stat().st_mtime > mt)
    check(".pdf rebuilt", cl_pdf.is_file() and cl_pdf.stat().st_mtime > mt)
    check("form filler path still points at the cover pdf", json.loads(row["edits_log"]).get("cover_letter_pdf") == str(cl_pdf))
    check("cover flag set", bool(row["cover_edited_at"]))

    master = Path(load_config()["paths"]["resume_copies"]).parent / "masters"
    check("copies are not the masters", "masters" not in str(Path(job["resume_docx"]).parent).lower())

    db.set_job(c, jid, status="submitted")
    c.commit()
    r = editor.save(jid, "cover", newcov + " x")
    check("submitted roles cannot be edited", not r["ok"], r)
finally:
    for i, f in have.items():
        shutil.copy2(snap / f"{i}_{f.name}", f)
    for f in files:
        if f not in have.values() and f.exists():
            f.unlink()
    c = db.conn()
    db.set_job(c, jid, status="ready", **fields)
    c.commit()
    shutil.rmtree(snap, ignore_errors=True)
    print("restored files and database fields")

print(f"\n{OK} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
