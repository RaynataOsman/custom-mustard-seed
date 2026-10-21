"""Draft answers for application questions the answer bank can't fill (you chose: send as drafted).

Truth rules: answers come only from your resume, profile and standing answers (Settings > Standing answers).
Free-text answers go through tailor.guard_cover, which drops any sentence stating a figure, tool or name
the resume doesn't have. Questions that can't be answered truthfully stay for you (Needs you).
"""
import json, re
import llm
from util import ascii_clean

STANDING = [  # key, label in Settings, question pattern, default
    ("messenger", "Preferred messenger", r"preferred (messenger|chat|messaging)|which messenger|messenger\b(?!.*(id|handle|user))", "WhatsApp"),
    ("messenger_id", "Messenger ID / handle", r"(messenger|telegram|whatsapp|skype|signal)\s*(id|handle|username|number)|id for the (selected )?messenger|your (telegram|skype) ", ""),
    ("id_number", "ID / passport number (only if a form asks)", r"\b(id|identity|identification) (number|no\.?)\b|national id|passport (number|no)", ""),
    ("start_date", "Earliest start date", r"start date|when (can|could) you start|earliest (start|date)|available to start|availability to start", "Immediately"),
    ("startup_experience", "Worked in a startup?", r"start-?up", "Yes"),
    ("agency_experience", "Worked in/with an agency?", r"\bagency\b", ""),
    ("english", "English level", r"english|language proficiency|working language", "Fluent (full professional)"),
    ("relocate", "Willing to relocate?", r"relocat", "No - I work remotely from Cape Town"),
    ("hours", "Hours available per week", r"how many hours|hours (per|a) week|weekly (hours|availability)|full[- ]time or part[- ]time", "20-40 hours per week"),
    ("timezone_overlap", "Can you work US Eastern / UK hours?", r"(comfortable|able|willing).{0,40}(est|et|eastern|uk|gmt|pst|hours|time ?zone|overlap)", "Yes"),
    ("equipment", "Own laptop + reliable internet?", r"(laptop|computer|internet|backup power|load ?shedding|equipment)", "Yes"),
    ("eeo", "Gender / race / disability questions", r"gender|\brace\b|ethnic|veteran|disabilit|pronoun|sexual orientation", "Prefer not to say|Decline to self-identify|I don't wish to answer"),
    ("referral", "Were you referred?", r"referred|referral|who told you", "No"),
    ("salary_currency", "Salary currency", r"currency", "USD"),
    ("voice_sample", "Voice recording link (e.g. Vocaroo / Google Drive)", r"voice (audio )?(sample|recording)|audio (sample|recording)|vocaroo", ""),
    ("video_sample", "Video introduction link (Loom / YouTube / Drive)", r"video (recording|sample|introduction|intro)|loom", ""),
    ("computer_specs", "Computer specs (CPU / RAM)", r"\bram\b|processor|cpu|computer spec|pc spec|laptop spec", ""),
    ("internet_speed", "Internet speed (e.g. 50 Mbps fibre)", r"internet speed|mbps|bandwidth|speed ?test", ""),
]


def standing(cfg):
    have = (cfg.get("submit", {}) or {}).get("standing", {}) or {}
    return {k: (have.get(k) if have.get(k) not in (None,) else d) for k, _, _, d in STANDING}


def bank(cfg):
    """Standing answers as answer-bank rows (pattern, answer) - checked before the AI."""
    s = standing(cfg)
    return [(pat, s[k]) for k, _, pat, _ in STANDING if s.get(k)]


COLLECT_JS = """() => {
  const out = []; let n = 0; const run = 'f' + (Date.now() % 1000000) + '_';
  const lab = el => {
    let t = '';
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) t = l.innerText; }
    if (!t) { const l = el.closest('label'); if (l) t = l.innerText; }
    if (!t && el.getAttribute('aria-labelledby')) { const l = document.getElementById(el.getAttribute('aria-labelledby').split(' ')[0]); if (l) t = l.innerText; }
    if (!t) { const fs = el.closest('fieldset'); const lg = fs && fs.querySelector('legend'); if (lg) t = lg.innerText; }
    if (!t) { let p = el.parentElement; for (let i = 0; i < 5 && p && !t; i++, p = p.parentElement) { const l = p.querySelector('label,legend,.label,[class*=question],[class*=label]'); if (l && !l.contains(el)) t = l.innerText; } }
    t = (t || '').replace(/[*]+/g, ' ').replace(/\\s+/g, ' ').trim();
    if (t.replace(/[^a-z0-9]/gi, '').length < 4) {
      let p = el.parentElement;
      for (let i = 0; i < 8 && p; i++, p = p.parentElement) {
        const own = (p.innerText || '').replace(/[*]+/g, ' ').replace(/\\s+/g, ' ').trim();
        if (own.replace(/[^a-z0-9]/gi, '').length >= 8 && own.length < 600) { t = own; break; }
      }
    }
    return (t || el.placeholder || el.name || '').trim().slice(0, 300);
  };
  const req = el => !!(el.required || el.getAttribute('aria-required') === 'true' || /\\*\\s*$/.test(lab(el)));
  for (const el of document.querySelectorAll('textarea, input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=button]):not([type=password]), select')) {
    if (el.offsetParent === null) continue;
    const v = el.tagName === 'SELECT' ? el.value : (el.value || '').trim();
    if (v) continue;
    const k = run + (n++); el.setAttribute('data-ms-key', k);
    const opts = el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()).filter(t => t && !/^(select|choose|please|--)/i.test(t)).slice(0, 40) : [];
    out.push({key: k, kind: el.tagName === 'SELECT' ? 'select' : (el.tagName === 'TEXTAREA' ? 'textarea' : 'text'), label: lab(el), options: opts, required: req(el)});
  }
  const groups = {};
  for (const r of document.querySelectorAll('input[type=radio], input[type=checkbox]')) {
    if (r.offsetParent === null && !(r.labels && r.labels[0] && r.labels[0].offsetParent)) continue;
    const name = r.name || r.id; if (!name) continue;
    const g = groups[name] = groups[name] || {name, kind: r.type, opts: [], checked: false, el: r};
    const t = (r.labels && r.labels[0] ? r.labels[0].innerText : (r.parentElement.innerText || r.value)).trim().slice(0, 120);
    g.opts.push(t); if (r.checked) g.checked = true;
  }
  for (const g of Object.values(groups)) {
    if (g.checked) continue;
    if (g.kind === 'checkbox' && g.opts.length === 1 && /privacy|terms|consent|agree|policy|gdpr/i.test(g.opts[0])) continue;
    let q = ''; const fs = g.el.closest('fieldset'); const lg = fs && fs.querySelector('legend'); if (lg) q = lg.innerText;
    q = (q || '').replace(/[*]+/g, ' ').replace(/\\s+/g, ' ').trim();
    if (q.replace(/[^a-z0-9]/gi, '').length < 4) { q = ''; let p = g.el.parentElement; for (let i = 0; i < 9 && p; i++, p = p.parentElement) {
        const lines = (p.innerText || '').split('\\n').map(x => x.replace(/[*]+/g, ' ').trim()).filter(x => x.replace(/[^a-z0-9]/gi, '').length >= 4 && !g.opts.includes(x) && !/^(yes|no)$/i.test(x));
        if (lines.length) { q = lines[0]; break; } } }
    const k = run + (n++);
    document.querySelectorAll('input[name="' + CSS.escape(g.name) + '"]').forEach(x => x.setAttribute('data-ms-key', k));
    out.push({key: k, kind: g.kind === 'radio' ? 'radio' : 'checkboxes', label: (q || g.name).slice(0, 300), options: g.opts.slice(0, 30), required: g.kind === 'radio'});
  }
  return out; }"""

SYSTEM = """You fill in job application questions for one real person, Raynata Osman, from her resume, profile and standing answers.
Rules:
- Truth only. Never invent employers, numbers, tools, certifications, degrees, dates or experience that the resume does not state.
- For select / radio fields, answer with EXACTLY one of the given options (copy its text). For checkboxes, answer with a list of option texts.
- Yes/No questions: answer Yes only when the resume or standing answers support it; otherwise No (or SKIP if unclear).
- Free-text answers: 1-4 plain sentences, first person, specific to this job, using only resume facts. No em dashes, no hype words
  (passionate, leverage, spearheaded, results-driven, synergy, thrilled).
- Personal data you are not given (ID numbers, references, URLs you don't have) -> "SKIP".
- Salary/rate questions: use the rate given in the profile.
- Location / "where will you work from": Cape Town, South Africa (remote).
- Never copy the question's own hints or instructions into the answer ("if not, leave blank" etc.). If the honest answer is
  "no" or "not applicable", say that; if you do not know, answer SKIP.
- Never answer Yes to a confirmation, declaration or eligibility statement unless the resume or standing answers clearly support it.
Return JSON: {"answers": {"<key>": "<answer or SKIP>" | ["option", ...]}}"""


def draft(fields, job, cfg, resume_text, rate):
    prof = {k: cfg["profile"].get(k) for k in ("name", "email", "phone", "location", "country", "timezone", "linkedin",
                                                "portfolio", "work_setup", "notice")}
    user = json.dumps({"job": {"title": job.get("title"), "company": job.get("company"),
                               "description": (job.get("description") or "")[:3500]},
                       "profile": prof, "rate": rate, "standing_answers": standing(cfg),
                       "years_experience_for_this_kind_of_role": (cfg.get("submit", {}).get("years_by_family") or {}).get(job.get("family") or ""),
                       "resume": resume_text[:7000],
                       "fields": [{k: f[k] for k in ("key", "kind", "label", "options", "required")} for f in fields]})
    data, who = llm.chat_json(SYSTEM, user, max_tokens=2500, temperature=0.2)
    return (data.get("answers") or {}), who


def _pick(options, ans):
    a = (ans or "").strip().lower()
    for o in options:
        if o.strip().lower() == a:
            return o
    for o in options:
        if a and (o.strip().lower().startswith(a) or a.startswith(o.strip().lower()[:12])):
            return o
    return None


def answer_form(page, job, cfg, resume_text, rate, log, only_required=False):
    """Fill what's still empty. Returns (filled_labels, left_labels); the Q&A written goes to job['_qa']."""
    import tailor
    try:
        fields = page.evaluate(COLLECT_JS)
    except Exception as e:
        log(f"    could not read the questions: {e}")
        return [], []
    fields = [f for f in fields if f["label"] and (f["required"] or f["kind"] in ("textarea", "radio", "select"))]
    unreadable = [f for f in fields if len(re.sub(r"[^a-z0-9]", "", f["label"].lower())) < 6]
    for f in unreadable:
        if f["required"]:
            job.setdefault("_qa", []).append([f["label"][:200] or "(question text not readable)", "(you need to answer this one)"])
    fields = [f for f in fields if f not in unreadable]
    pre_left = [(f["label"] or "unreadable question")[:80] for f in unreadable if f["required"]]
    if only_required:
        fields = [f for f in fields if f["required"]]
    if not fields:
        return [], pre_left
    try:
        answers, who = draft(fields, job, cfg, resume_text, rate)
    except Exception as e:
        log(f"    AI answers unavailable ({type(e).__name__}) - leaving these for you")
        return [], [f["label"][:80] for f in fields if f["required"]]
    filled, left = [], list(pre_left)

    def _sel(f):
        """Selector for this field; React forms re-render and drop our marker, so re-find it by its question."""
        sel = f'[data-ms-key="{f["key"]}"]'
        if page.query_selector(sel):
            return sel
        try:
            for g in page.evaluate(COLLECT_JS):
                if g["label"] == f["label"] and g["kind"] == f["kind"]:
                    return f'[data-ms-key="{g["key"]}"]'
        except Exception:
            pass
        return sel

    for f in fields:
        a = answers.get(f["key"])
        sel = _sel(f)
        try:
            if a in (None, "", "SKIP") or a == ["SKIP"]:
                if f["required"]:
                    left.append(f["label"][:80])
                    job.setdefault("_qa", []).append([f["label"][:200], "(you need to answer this one)"])
                continue
            if f["kind"] in ("text", "textarea"):
                text = ascii_clean(a if isinstance(a, str) else ", ".join(a))
                if f["kind"] == "textarea" or len(text) > 60:
                    text, dropped = tailor.guard_cover(text, resume_text, job.get("description") or "")
                    if not text.strip():
                        if f["required"]:
                            left.append(f["label"][:80])
                        continue
                el0 = page.query_selector(sel)
                if el0 is None:
                    raise RuntimeError("field disappeared from the form")
                if (el0.get_attribute("type") or "").lower() == "number":
                    m = re.search(r"\d[\d,. ]*", text)
                    text = re.sub(r"[^\d.]", "", m.group(0)) if m else ""
                    if not text:
                        if f["required"]:
                            left.append(f["label"][:80])
                        continue
                el0.fill(text, timeout=8000)
                job.setdefault("_qa", []).append([f["label"][:200], text])
            elif f["kind"] == "select":
                o = _pick(f["options"], a if isinstance(a, str) else a[0])
                if not o:
                    if f["required"]:
                        left.append(f["label"][:80])
                    continue
                page.select_option(sel, label=o)
                job.setdefault("_qa", []).append([f["label"][:200], o])
            elif f["kind"] in ("radio", "checkboxes"):
                wanted = a if isinstance(a, list) else [a]
                done = False
                for el in page.query_selector_all(sel):
                    t = el.evaluate("e => (e.labels && e.labels[0] ? e.labels[0].innerText : (e.parentElement.innerText || e.value)).trim()")
                    if any(_pick([t], w) for w in wanted):
                        try:
                            el.check(timeout=2000)
                        except Exception:
                            el.evaluate("e => (e.labels && e.labels[0] ? e.labels[0] : e).click()")
                        done = True
                        if f["kind"] == "radio":
                            break
                if not done:
                    if f["required"]:
                        left.append(f["label"][:80])
                    continue
                job.setdefault("_qa", []).append([f["label"][:200], ", ".join(wanted)])
            filled.append(f["label"][:40])
        except Exception as e:
            errs = job.setdefault("_qa_errors", [])
            if len(errs) < 3:
                errs.append(f"{f['kind']} '{f['label'][:40]}': {type(e).__name__}: {str(e)[:160]}")
                log(f"    could not write an answer - {errs[-1]}")
            if f["required"]:
                left.append(f["label"][:80])
    if not answers:
        log("    the AI returned no answers for this form")
    log(f"    AI answered {len(filled)} question(s) ({who}); {len(left)} left for you")
    return filled, left
