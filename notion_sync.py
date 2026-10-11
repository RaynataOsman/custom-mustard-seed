"""Write submitted applications (and their referral contacts) into Notion
"Application tracker 2.1" -> Applications database, and backfill referral
contacts for older rows whose Connections field is blank.

Needs NOTION_TOKEN in Settings, and the integration added to the Application
tracker 2.1 page (page ... menu > Connections > your integration)."""
import json, mimetypes, re
from pathlib import Path
from util import http, load_config, load_keys, ascii_clean

API = "https://api.notion.com/v1"
VER = "2022-06-28"


def _h(json_body=True):
    tok = load_keys().get("NOTION_TOKEN")
    if not tok:
        raise RuntimeError("NOTION_TOKEN not set (Settings tab)")
    h = {"Authorization": f"Bearer {tok}", "Notion-Version": VER}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _rt(text):
    text = ascii_clean(text or "")[:1990]
    return [{"type": "text", "text": {"content": text}}] if text else []


def _chunks(text, n=1900):
    text = ascii_clean(text or "")
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


def position_for(job, cfg):
    t = (job.get("title") or "").lower()
    for pat, opt in cfg["notion"]["title_position_overrides"]:
        if re.search(pat, t):
            return opt
    fam = cfg["notion"]["family_position"].get(job.get("family") or "dev", {})
    return fam.get(job.get("tier") or "HM") or next(iter(fam.values()), None)


def upload_file(path):
    """Notion file upload (small files, single part). Returns upload id or None."""
    p = Path(path)
    if not p.exists():
        return None
    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    r = http().post(f"{API}/file_uploads", headers=_h(), json={"filename": p.name, "content_type": ctype}, timeout=60)
    if r.status_code >= 300:
        return None
    up = r.json()
    with open(p, "rb") as f:
        r2 = http().post(f"{API}/file_uploads/{up['id']}/send", headers=_h(False),
                         files={"file": (p.name, f, ctype)}, timeout=120)
    return up["id"] if r2.status_code < 300 else None


def _connections_text(contacts):
    lines = [f'{c["name"]} - {c.get("headline") or c["kind"]} - {c["url"]}' for c in contacts]
    return "\n".join(lines)


def _blocks(job, contacts):
    b = []

    def h(t):
        b.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": _rt(t)}})

    def para(t):
        for c in _chunks(t):
            b.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rt(c)}})

    def bullet(t):
        b.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rt(t)}})

    h("The role")
    para(f'{job["title"]} at {job["company"]} - {job.get("location") or ""}'
         + (f' - {job["salary"]}' if job.get("salary") else ""))
    if job.get("url"):
        para(f'Posting: {job["url"]}')
    para(f'Resume used: {Path(job.get("resume_pdf") or job.get("resume_docx") or "").name}  '
         f'(tier {job.get("tier")}, fit score {int(job.get("score") or 0)})')
    if job.get("cover_letter"):
        h("Cover letter sent")
        para(job["cover_letter"])
    prep = json.loads(job["interview_prep"]) if job.get("interview_prep", "").startswith("[") else []
    if prep:
        h("How to walk into the interview")
        for x in prep:
            bullet(x)
    gaps = json.loads(job["gaps"]) if (job.get("gaps") or "").startswith("[") else []
    if gaps:
        h("Asked for but not on the resume (prep these)")
        for x in gaps:
            bullet(x)
    if contacts:
        add_contact_blocks(b, contacts)
    return b[:95]


def add_contact_blocks(b, contacts):
    b.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": _rt("Referral outreach (send from LinkedIn)")}})
    for c in contacts:
        b.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
            {"type": "text", "text": {"content": ascii_clean(f'{c["name"]} ({c["kind"].replace("_", " ")}) - ')}},
            {"type": "text", "text": {"content": "profile", "link": {"url": c["url"]}}},
            {"type": "text", "text": {"content": ascii_clean(f'\nNote: {c["note"]}\nAfter they accept: {c.get("followup") or ""}')[:1800]}}]}})
    return b


def push_application(job, contacts, log=print, stage="Applied", text_prefix=""):
    cfg = load_config()
    db_id = cfg["notion"]["database_id"]
    props = {
        "Company": {"title": _rt(job["company"])},
        "Job URL": {"url": job.get("url") or job.get("apply_url")},
        "Stage": {"status": {"name": stage}},
        "Apply date": {"date": {"start": (job.get("applied_at") or "")[:10] or None}},
        "Sourced": {"date": {"start": (job.get("found_at") or "")[:10] or None}},
        "Country": {"multi_select": [{"name": "Remote"}]},
        "Referral?": {"select": {"name": "No"}},
        "Text": {"rich_text": _rt(text_prefix + f'{job["title"]} | {job.get("board")} | {job.get("location") or ""}')},
        "Connections": {"rich_text": _rt(_connections_text(contacts))},
    }
    pos = position_for(job, cfg)
    if pos:
        props["Position"] = {"multi_select": [{"name": pos}]}
    for k in ("Apply date", "Sourced"):
        if not props[k]["date"]["start"]:
            props.pop(k)
    files = []
    for key, prop in (("resume_pdf", "Resume"), ("resume_docx", "Resume")):
        if job.get(key) and prop == "Resume" and not files:
            fid = upload_file(job[key])
            if fid:
                files.append({"type": "file_upload", "file_upload": {"id": fid}, "name": Path(job[key]).name[:95]})
    if files:
        props["Resume"] = {"files": files}
    body = {"parent": {"database_id": db_id}, "properties": props, "children": _blocks(job, contacts)}
    r = http().post(f"{API}/pages", headers=_h(), json=body, timeout=60)
    if r.status_code >= 300:
        # retry without the bits Notion is fussy about
        for k in ("Resume", "Position"):
            props.pop(k, None)
        r = http().post(f"{API}/pages", headers=_h(), json=body, timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"Notion: HTTP {r.status_code} {r.text[:300]}")
    pid = r.json()["id"]
    log(f"  Notion row created for {job['company']}")
    return pid


def update_stage(page_id, stage, applied_on=None):
    props = {"Stage": {"status": {"name": stage}}}
    if applied_on:
        props["Apply date"] = {"date": {"start": applied_on[:10]}}
    r = http().patch(f"{API}/pages/{page_id}", headers=_h(), json={"properties": props})
    return r.status_code < 300


def mark_connections_sent(page_id, text):
    http().patch(f"{API}/pages/{page_id}", headers=_h(), json={"properties": {"connections sent": {"rich_text": _rt(text)}}})


def rows_missing_connections():
    """Tracker rows in Applied / Followed up / Interview whose Connections is blank."""
    cfg = load_config()
    out, cursor = [], None
    flt = {"and": [
        {"property": "Connections", "rich_text": {"is_empty": True}},
        {"or": [{"property": "Stage", "status": {"equals": s}} for s in ("Applied", "Followed up", "Interview", "Waiting for a referral")]}]}
    while True:
        body = {"filter": flt, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = http().post(f"{API}/databases/{cfg['notion']['database_id']}/query", headers=_h(), json=body, timeout=60)
        r.raise_for_status()
        d = r.json()
        for pg in d["results"]:
            pr = pg["properties"]
            company = "".join(t["plain_text"] for t in pr["Company"]["title"])
            positions = [o["name"] for o in (pr.get("Position", {}).get("multi_select") or [])]
            text = "".join(t["plain_text"] for t in (pr.get("Text", {}).get("rich_text") or []))
            out.append({"page_id": pg["id"], "company": company, "position": (text.split("|")[0].strip() or
                                                                               (positions[0] if positions else "")),
                        "positions": positions, "url": pr.get("Job URL", {}).get("url")})
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]
    return out


def write_connections(page_id, contacts):
    r = http().patch(f"{API}/pages/{page_id}", headers=_h(), json={"properties": {
        "Connections": {"rich_text": _rt(_connections_text(contacts))}}})
    r.raise_for_status()
    blocks = add_contact_blocks([], contacts)
    http().patch(f"{API}/blocks/{page_id}/children", headers=_h(), json={"children": blocks})


def health():
    try:
        cfg = load_config()
        r = http().get(f"{API}/databases/{cfg['notion']['database_id']}", headers=_h(), timeout=20)
        if r.status_code == 200:
            return "ok"
        if r.status_code == 404:
            return "token works but the integration is not added to Application tracker 2.1 (page ... > Connections)"
        return f"HTTP {r.status_code}"
    except Exception as e:
        return str(e)
