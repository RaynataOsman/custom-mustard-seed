"""Tailor a COPY of the right master resume for one job.

Rules (from the Resume Tier Map):
  * never edit a master - masters/ is read only, output goes to Resume Copies
  * keywords and sentence construction only: no new employers, dates, numbers,
    tools or certifications. Every AI edit is checked against the master and
    thrown away if it introduces a tool/number the master doesn't contain.
  * plain ASCII, no invisible characters, no embedded fonts, clean metadata
"""
import copy, io, json, re, shutil, zipfile
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from util import MASTERS, OUT, ascii_clean, slug, load_config
import llm

W_T = qn("w:t")
FAMILY_FILE = {"dev": "Full-Stack Developer", "design": "UX-UI Figma Designer",
               "admin": "Administrative & Virtual Assistant"}


def master_path(family, tier):
    p = MASTERS / f"{family}_{tier}.docx"
    if not p.exists():
        cands = sorted(MASTERS.glob(f"{family}_*.docx"))
        if not cands:
            raise FileNotFoundError(f"no master for family {family} in {MASTERS}")
        p = cands[0]
    return p


def _texts(p):
    return [t for t in p._p.iter(W_T)]


def _set_par_text(p, new):
    ts = _texts(p)
    if not ts:
        return
    ts[0].text = new
    ts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    for t in ts[1:]:
        t.text = ""


def full_text(doc):
    return "\n".join("".join(t.text or "" for t in _texts(p)) for p in doc.paragraphs)


def structure(doc):
    """Find the editable parts: summary paragraph, experience bullets, skills paragraph(s)."""
    paras = doc.paragraphs
    items, in_exp, summary_done, skills = [], False, False, []
    for i, p in enumerate(paras):
        txt = "".join(t.text or "" for t in _texts(p)).strip()
        style = (p.style.name or "").lower()
        if not txt:
            continue
        if style.startswith("heading"):
            in_exp = True
            continue
        if i <= 1 or style in ("title", "subtitle"):
            continue
        if not in_exp and not summary_done and len(txt) > 120:
            items.append({"id": f"p{i}", "kind": "summary", "text": txt})
            summary_done = True
            continue
        if in_exp and re.match(r"^(tech stack|tools)\s*:", txt, re.I):
            continue
        if in_exp and ("\n" in txt or len(txt) > 600 or txt.count(",") > 12):
            skills.append(i)
            continue
        if in_exp and 25 < len(txt) < 400:
            items.append({"id": f"p{i}", "kind": "bullet", "text": txt})
    return items, skills


def vocab(family):
    """Lowercased skill vocabulary from every master of a family (used for scoring and guards)."""
    words = set()
    for f in MASTERS.glob(f"{family}_*.docx"):
        t = full_text(Document(f))
        for chunk in re.split(r"[,\n:()|/&]+", t):
            c = chunk.strip().lower()
            if 1 < len(c) < 40:
                words.add(c)
                for w in re.split(r"\s+", c):
                    if len(w) > 1:
                        words.add(w.strip("."))
    return words


_TECHISH = re.compile(r"\b([A-Z][a-zA-Z0-9]*[A-Z0-9][a-zA-Z0-9]*|[A-Z][a-z]+(?:\.js|JS)|[a-z]+\.js|"
                      r"[A-Z]{2,}[a-z]*|\d+(?:\.\d+)?%?)\b")


def guard(old, new, master_text, job_title=""):
    """Reject an edit that adds a tool/acronym/number the master doesn't have."""
    mt = master_text.lower()
    for m in _TECHISH.finditer(new):
        tok = m.group(1)
        if tok[0].isdigit():
            if tok not in old:
                return f"new number {tok}"
        elif tok.lower() not in mt:
            return f"new term {tok}"
    for tok in re.findall(r"\b[A-Z][a-z]+\b", new):
        # capitalised words mid-sentence that are proper nouns not in the master
        if tok.lower() not in mt and tok.lower() not in COMMON_CAPS and tok.lower() not in job_title.lower() and not re.search(
                r"(^|[.!?]\s+)" + tok + r"\b", new):
            return f"new name {tok}"
    if len(new) < 0.5 * len(old) or len(new) > 1.8 * len(old) + 40:
        return "length changed too much"
    return None


COMMON_CAPS = {"i", "a", "the", "remote", "south", "africa"}


def reorder_skills(doc, skill_pars, jd):
    """Move skills the posting mentions to the front of each comma list. Nothing added or removed."""
    jd_l = jd.lower()
    for i in skill_pars:
        for t in _texts(doc.paragraphs[i]):
            s = t.text or ""
            if s.count(",") < 2:
                continue
            trailing = s.endswith(",") or s.rstrip().endswith(",")
            parts = [x.strip() for x in s.split(",") if x.strip()]
            hit = [x for x in parts if re.search(r"(?<![a-z])" + re.escape(x.lower()) + r"(?![a-z])", jd_l)]
            rest = [x for x in parts if x not in hit]
            new = ", ".join(hit + rest) + ("," if trailing else "")
            if s.startswith(" "):
                new = " " + new
            t.text = new


def fix_header(doc, family, cfg):
    """Header line: show URLs as text (parsers read the label otherwise) and the right headline."""
    if len(doc.paragraphs) < 2:
        return
    hdr = doc.paragraphs[1]._p
    rels = doc.part.rels
    if cfg["resume"].get("plain_url_contacts", True):
        for h in hdr.iter(qn("w:hyperlink")):
            rid = h.get(qn("r:id"))
            if not rid or rid not in rels:
                continue
            target = rels[rid].target_ref
            label = re.sub(r"^mailto:", "", target)
            label = re.sub(r"^https?://(www\.)?", "", label).rstrip("/")
            ts = list(h.iter(W_T))
            if ts:
                ts[0].text = label
                for t in ts[1:]:
                    t.text = ""
    headline = cfg["families"][family].get("headline")
    if headline:
        for t in hdr.iter(W_T):
            if t.text and "Full-Stack Developer" in t.text and headline != "Full-Stack Developer":
                t.text = t.text.replace("Full-Stack Developer", headline)
                break


def sanitize_doc(doc, cfg):
    for p in doc.paragraphs:
        for t in _texts(p):
            if t.text:
                t.text = ascii_clean(t.text)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for t in _texts(p):
                        if t.text:
                            t.text = ascii_clean(t.text)
    cp = doc.core_properties
    cp.author = cfg["profile"]["name"]
    cp.last_modified_by = cfg["profile"]["name"]
    cp.comments = ""
    cp.keywords = ""
    cp.title = f'{cfg["profile"]["name"]} Resume'


def strip_fonts(path):
    """Drop the ~1.1 MB of embedded fonts (ATS parsers choke on heavy files)."""
    src = Path(path)
    buf = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename.startswith("word/fonts/"):
                continue
            data = zin.read(item.filename)
            if item.filename == "word/fontTable.xml":
                data = re.sub(rb"<w:embed(Regular|Bold|Italic|BoldItalic)\b[^>]*/>", b"", data)
            if item.filename == "word/_rels/fontTable.xml.rels":
                data = re.sub(rb"<Relationship [^>]*fonts/[^>]*/>", b"", data)
            zout.writestr(item, data)
    src.write_bytes(buf.getvalue())


SYSTEM = """You tailor a real person's resume to one job posting and write a short cover letter.
Hard rules:
- Only rephrase what the resume already says. Never add an employer, date, number, metric, tool,
  language, framework, certification or responsibility that is not already in the resume text.
- You may reuse words from the job posting only when the resume already supports that claim.
- Keep each edited paragraph about the same length. Keep past tense for past roles.
- Plain ASCII only. No em dashes, no fancy quotes, no emoji.
- Write like a busy professional, not a marketer: no "passionate", "leverage", "spearheaded",
  "results-driven", "dynamic", "synergy", "excited to", "thrilled", "I am writing to".
- Vary sentence openings. Do not start every bullet with the same verb.
Return JSON only."""


def _cover_example(cfg):
    """Your own past cover letter, used for structure and voice only (Settings > Cover letter example)."""
    p = Path(cfg.get("cover_letter", {}).get("example_file") or "masters/cover_letter_example.txt")
    if not p.is_absolute():
        p = MASTERS.parent / p
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _cover_rules(job, cfg):
    cl = cfg.get("cover_letter", {})
    return (f"{cl.get('words', '250-350')} words in 4-5 short paragraphs. Start with 'Dear {job['company']} team,'. "
            "Paragraph 1: name the role and say plainly why you fit it as a remote hire working from "
            f"{cfg['profile'].get('location', '')}. Paragraph 2: two concrete stories from resume_full_text that match "
            "the posting's main requirements - name the employer or client and what you actually did. Paragraph 3: how you "
            "work with distributed teams and which hours you overlap. Optional: one honest line about a gap if the posting "
            "asks for something the resume lacks. Close by inviting a conversation, then "
            f"'{cl.get('sign_off', 'Kind regards')},' and the name on its own line. Follow the STRUCTURE, TONE and SENTENCE "
            "STYLE of cover_letter_style_example when it is given, but NEVER copy a fact, number, employer, tool or "
            "years-of-experience figure from it - every fact must come from resume_full_text.")


_NUM_WORDS = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)"


def guard_cover(text, master_txt, job_text=""):
    """Drop cover-letter sentences that state a number (incl. 'eight years') the resume and posting don't contain."""
    src = (master_txt + " " + job_text).lower()
    kept, dropped = [], []
    for para in text.split("\n"):
        sents = re.split(r"(?<=[.!?])\s+", para)
        good = []
        for snt in sents:
            nums = re.findall(r"\b(\d[\d,.]*\+?%?|" + _NUM_WORDS + r")\s*(?=years?|yrs|clients|projects|%|percent|people|countries)",
                              snt, re.I) + re.findall(r"\b\d{2,}[\d,.]*%?", snt)
            bad = [n for n in nums if n.lower().strip("+%,.") not in src]
            (dropped if bad else good).append(snt)
        kept.append(" ".join(good))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip(), dropped


def _prompt(job, items, master_txt, family, tier, cfg, retry_note):
    lvl = {"J": "junior", "J-M": "junior-to-mid", "HM": "mid-level", "M-S": "mid-to-senior",
           "S": "senior"}.get(tier, "mid-level")
    p = cfg["profile"]
    return json.dumps({
        "task": ("Rewrite the summary to target this role at the " + lvl + " level, rewrite up to "
                 + str(cfg["resume"]["max_bullet_edits"]) +
                 " bullets so the strongest matches to the posting read first and use the posting's wording "
                 "where the resume supports it. Then write a cover letter (120-200 words, 3 short paragraphs, "
                 "no address block, sign off with the name), interview prep notes, and list posting "
                 "requirements the resume does NOT show."),
        "candidate": {"name": p["name"], "based_in": p["location"], "timezone": p["timezone"],
                      "work_setup": p["work_setup"]},
        "retry_instructions_from_candidate": retry_note or "",
        "job": {"title": job["title"], "company": job["company"], "location": job.get("location"),
                "description": (job.get("description") or "")[:7000]},
        "resume_full_text": master_txt[:9000],
        "editable_paragraphs": items,
        "return_format": {
            "edits": [{"id": "p<number from editable_paragraphs>", "text": "new paragraph text"}],
            "cover_letter": "string",
            "interview_prep": ["6-10 short bullets: what they will probe, which resume story answers it, "
                               "one question to ask them"],
            "gaps": ["requirements in the posting not evidenced in the resume"],
            "fit_line": "one sentence on why this is a fit"}
    })


def tailor(job, family, tier, retry_note=None, log=print):
    cfg = load_config()
    src = master_path(family, tier)
    doc = Document(src)
    master_txt = full_text(doc)
    items, skill_pars = structure(doc)
    result = {"edits_applied": [], "edits_rejected": [], "llm": None, "cover_letter": "", "interview_prep": [],
              "gaps": [], "fit_line": "", "master": src.name}

    try:
        from util import feature
        if not feature("ai_tailoring", cfg):
            raise llm.NoLLM("AI tailoring switched off in Settings > Features")
        data, who = llm.chat_json(SYSTEM, _prompt(job, items, master_txt, family, tier, cfg, retry_note),
                                  max_tokens=3500, log=log)
        result["llm"] = who
        by_id = {it["id"]: it for it in items}
        for e in (data.get("edits") or [])[: cfg["resume"]["max_bullet_edits"] + 1]:
            it = by_id.get(str(e.get("id")))
            new = ascii_clean((e.get("text") or "").strip())
            if not it or not new or new == it["text"]:
                continue
            why = guard(it["text"], new, master_txt, job.get("title", ""))
            if why:
                result["edits_rejected"].append({"id": it["id"], "why": why, "text": new})
                continue
            idx = int(it["id"][1:])
            _set_par_text(doc.paragraphs[idx], new)
            result["edits_applied"].append({"id": it["id"], "old": it["text"], "new": new})
        cover, dropped = guard_cover(ascii_clean(data.get("cover_letter") or ""), master_txt,
                                     job.get("description") or "")
        if dropped:
            log(f"  cover letter: removed {len(dropped)} sentence(s) with figures not on your resume")
            result["edits_rejected"] += [{"id": "cover", "why": "figure not on resume", "text": d} for d in dropped]
        result["cover_letter"] = cover if len(cover) > 300 else fallback_cover(job, cfg, master_txt)
        result["interview_prep"] = [ascii_clean(x) for x in (data.get("interview_prep") or [])]
        result["gaps"] = [ascii_clean(x) for x in (data.get("gaps") or [])]
        result["fit_line"] = ascii_clean(data.get("fit_line") or "")
    except llm.NoLLM as e:
        log(f"  no free AI available ({e}); using keyword-only tailoring")
        result["cover_letter"] = fallback_cover(job, cfg, master_txt)

    reorder_skills(doc, skill_pars, job.get("description") or "")
    fix_header(doc, family, cfg)
    sanitize_doc(doc, cfg)

    name = f'{cfg["profile"]["name"]} {FAMILY_FILE[family]} 2026 Resume_{slug(job["company"], 40)}_{slug(job["title"], 50)}'
    out_dir = Path(cfg["paths"]["resume_copies"])
    out_dir.mkdir(parents=True, exist_ok=True)
    docx_path = out_dir / f"{name}.docx"
    doc.save(docx_path)
    strip_fonts(docx_path)
    result["docx"] = str(docx_path)
    result["name"] = name
    # cover letter files
    if result["cover_letter"]:
        cl = out_dir / f'{cfg["profile"]["name"]} Cover Letter_{slug(job["company"], 40)}_{slug(job["title"], 50)}.txt'
        cl.write_text(result["cover_letter"], encoding="utf-8")
        result["cover_letter_path"] = str(cl)
    return result


def fallback_cover(job, cfg, master_txt=""):
    """Used only when no free AI answers. Built from your own resume summary, not a template."""
    p = cfg["profile"]
    summary = ""
    for para in master_txt.split("\n"):
        if len(para.strip()) > 160:
            summary = para.strip()
            break
    sign = cfg.get("cover_letter", {}).get("sign_off", "Kind regards")
    body = [f"Dear {job['company']} team,",
            f"I'd like to apply for the {job['title']} role. I work remotely from {p.get('location', '')} "
            f"({p.get('timezone', '')}), which overlaps fully with UK and European hours and covers the US East Coast afternoon."]
    if summary:
        body.append(summary)
    body += ["Every role I have held has been remote and client-facing, so I am used to turning a loose brief into "
             "something specific enough to build, and to flagging problems early rather than late.",
             "I would welcome a short call to talk through the role and what your team is working on.",
             f"{sign},\n{p['name']}"]
    return ascii_clean("\n\n".join(body))
