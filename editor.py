"""Hand-edit a role's tailored resume or cover letter (dashboard Edit button, PC and phone).

Rules
  * only the tailored COPY in Resume Copies is ever written - never a master
  * the truth guard that checks AI edits checks yours too: a new number, tool or name that is not on
    your master resume (or, for the cover letter, a figure the resume/posting lacks) is reported back and the
    save waits for "Save anyway" (force=True)
  * a save rewrites every file the form filler uses: resume .docx + .pdf, cover letter .txt + .docx + .pdf,
    and the database text. Your edit is kept until you press Retry (which warns you first).
"""
import json, os
from pathlib import Path
from docx import Document
import db, tailor
from util import MASTERS, ascii_clean, load_config, now_iso

EDITABLE = ("ready", "approved", "needs_you")
MAX_CHARS = 20000


def _job(c, job_id):
    rows = db.rows(c, "SELECT * FROM jobs WHERE id=?", (job_id,))
    if not rows:
        raise ValueError("role not found")
    return rows[0]


def _ed(j):
    try:
        return json.loads(j.get("edits_log") or "{}")
    except Exception:
        return {}


def _copies_dir(cfg):
    return Path(cfg["paths"]["resume_copies"]).resolve()


def _safe_copy(path, cfg):
    """The file must sit inside Resume Copies (so a master can never be written)."""
    p = Path(path).resolve()
    if _copies_dir(cfg) not in p.parents:
        raise ValueError("that file is not a tailored copy - refusing to edit it")
    try:
        if MASTERS.resolve() in p.parents:
            raise ValueError("masters are never edited")
    except OSError:
        pass
    return p


def resume_paragraphs(docx_path):
    """(paragraph index, text) for every non-empty paragraph, in order."""
    doc = Document(docx_path)
    out = []
    for i, p in enumerate(doc.paragraphs):
        t = "".join(x.text or "" for x in tailor._texts(p))
        if not t.strip():
            continue
        if _special(p):
            continue  # line breaks / tabs / links / pictures: rewriting the text would break the layout
        out.append((i, t.strip()))
    return out


def _special(p):
    from docx.oxml.ns import qn
    return any(True for tag in ("w:br", "w:tab", "w:hyperlink", "w:drawing", "w:pict", "w:fldChar")
               for _ in p._p.iter(qn(tag)))


def resume_text(docx_path):
    try:
        return "\n".join(t for _, t in resume_paragraphs(docx_path))
    except Exception:
        return None


def cover_text_path(j, cfg=None):
    cfg = cfg or load_config()
    ed = _ed(j)
    pdf = ed.get("cover_letter_pdf")
    if pdf:
        return Path(pdf).with_suffix(".txt")
    from util import slug
    name = f'{cfg["profile"]["name"]} Cover Letter_{slug(j["company"], 40)}_{slug(j["title"], 50)}.txt'
    return Path(cfg["paths"]["resume_copies"]) / name


def get_texts(job_id):
    c = db.conn()
    j = _job(c, job_id)
    cfg = load_config()
    rt = None
    if j.get("resume_docx") and Path(j["resume_docx"]).is_file():
        rt = resume_text(j["resume_docx"])
    return {"ok": True, "id": job_id, "status": j["status"], "editable": j["status"] in EDITABLE,
            "resume_text": rt, "cover_letter": j.get("cover_letter") or "",
            "resume_edited_at": j.get("resume_edited_at"), "cover_edited_at": j.get("cover_edited_at")}


def _master_text(j):
    ed = _ed(j)
    name = ed.get("master")
    p = MASTERS / name if name else None
    if not p or not p.is_file():
        p = tailor.master_path(j.get("family") or "dev", j.get("tier") or "HM")
    return tailor.full_text(Document(p))


def check_resume(j, old_lines, new_lines, master_txt):
    warns = []
    for (o, n) in zip(old_lines, new_lines):
        if o == n or not n:
            continue
        why = tailor.guard(o, n, master_txt, j.get("title", ""))
        if why and why != "length changed too much":
            warns.append({"why": why, "text": n[:160]})
    return warns


def save_resume(job_id, text, force=False):
    c = db.conn()
    j = _job(c, job_id)
    if j["status"] not in EDITABLE:
        return {"ok": False, "error": f"This role is {j['status']}; edit it from Review before it is sent."}
    cfg = load_config()
    if not j.get("resume_docx") or not Path(j["resume_docx"]).is_file():
        return {"ok": False, "error": "this role has no resume copy yet (prepare it first)"}
    path = _safe_copy(j["resume_docx"], cfg)
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_CHARS:
        return {"ok": False, "error": "that is too long for a resume"}
    paras = resume_paragraphs(path)
    new_lines = [ascii_clean(x).strip() for x in text.split("\n")]
    while new_lines and not new_lines[-1] and len(new_lines) > len(paras):
        new_lines.pop()
    if len(new_lines) != len(paras):
        return {"ok": False, "error": f"Keep one line per paragraph: found {len(new_lines)} lines, expected {len(paras)}. "
                                      "To remove a bullet, clear its text but leave the line there."}
    old_lines = [t for _, t in paras]
    if new_lines == old_lines:
        return {"ok": True, "unchanged": True}
    warns = check_resume(j, old_lines, new_lines, _master_text(j))
    if warns and not force:
        return {"ok": False, "guard": warns,
                "error": "The truth guard found things that are not on your master resume: "
                         + "; ".join(f"{w['why']} in \"{w['text'][:60]}\"" for w in warns[:4])}
    doc = Document(path)
    for (idx, old), new in zip(paras, new_lines):
        if new != old:
            tailor._set_par_text(doc.paragraphs[idx], new)
    tailor.sanitize_doc(doc, cfg)
    doc.save(path)
    tailor.strip_fonts(path)
    import pdf
    pdf_path = None
    old_pdf = Path(path).with_suffix(".pdf")
    try:
        if old_pdf.exists():
            old_pdf.unlink()
    except OSError:
        pass
    pdf_path = pdf.to_pdf(path)
    db.set_job(c, job_id, resume_docx=str(path), resume_pdf=pdf_path, resume_edited_at=now_iso())
    db.event(c, job_id, "edited_resume", {"lines": sum(1 for a, b in zip(old_lines, new_lines) if a != b),
                                          "forced": bool(warns)})
    c.commit()
    out = {"ok": True, "pdf": bool(pdf_path), "forced": bool(warns)}
    if not pdf_path:
        out["note"] = "Saved the .docx, but the PDF could not be rebuilt (install LibreOffice or Word). The form filler will upload the .docx."
    return out


def save_cover(job_id, text, force=False):
    c = db.conn()
    j = _job(c, job_id)
    if j["status"] not in EDITABLE:
        return {"ok": False, "error": f"This role is {j['status']}; edit it from Review before it is sent."}
    cfg = load_config()
    text = ascii_clean((text or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    if len(text) < 80:
        return {"ok": False, "error": "that cover letter is too short to send"}
    if len(text) > MAX_CHARS:
        return {"ok": False, "error": "that is too long for a cover letter"}
    master = _master_text(j)
    _, dropped = tailor.guard_cover(text, master, j.get("description") or "")
    if dropped and not force:
        return {"ok": False, "guard": [{"why": "figure not on resume", "text": d[:160]} for d in dropped],
                "error": "These sentences state a figure that is not on your resume or in the posting: "
                         + " | ".join(d[:80] for d in dropped[:3])}
    txt = cover_text_path(j, cfg)
    txt.parent.mkdir(parents=True, exist_ok=True)
    _safe_copy(txt, cfg)
    txt.write_text(text, encoding="utf-8")
    import pipeline
    old_pdf = txt.with_suffix(".pdf")
    try:
        if old_pdf.exists():
            old_pdf.unlink()
    except OSError:
        pass
    cl_pdf = pipeline._cover_files({"cover_letter": text, "cover_letter_path": str(txt)}, j)
    ed = _ed(j)
    ed["cover_letter_pdf"] = cl_pdf or str(old_pdf)
    if not cl_pdf:
        ed.pop("cover_letter_pdf", None)
    db.set_job(c, job_id, cover_letter=text, edits_log=json.dumps(ed), cover_edited_at=now_iso())
    db.event(c, job_id, "edited_cover", {"forced": bool(dropped)})
    c.commit()
    out = {"ok": True, "pdf": bool(cl_pdf), "forced": bool(dropped)}
    if not cl_pdf:
        out["note"] = "Saved the text and .docx; the PDF could not be rebuilt."
    return out


def save(job_id, what, text, force=False):
    try:
        if what == "resume":
            r = save_resume(job_id, text, force)
        elif what == "cover":
            r = save_cover(job_id, text, force)
        else:
            return {"ok": False, "error": "unknown part"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    if r.get("ok") and not r.get("unchanged"):
        try:
            import cloud_sync
            cloud_sync.refresh_job(job_id)
        except Exception:
            pass
    return r
