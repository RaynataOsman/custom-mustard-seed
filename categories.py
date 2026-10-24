"""Role categories: a display/filter label for each job, worked out from the title (and, for dev
roles, the posting text). It never changes family, tier, status or score."""
import re

# (key, label, title regex) - evaluated against title.lower(); first match wins.
_RAW = [
    ("ai_ml", "AI / ML",
     r"\b(ml|mlops|llm|llms|genai|nlp|rlhf)\b|machine learning|generative ai|\bai\s*/\s*ml\b|"
     r"\bai (engineer|researcher|research|scientist|trainer|tutor|specialist|expert|data|content|model|evaluat)|"
     r"\ba\.i\. (engineer|researcher|trainer)|prompt engineer|data annotat|computer vision|model evaluat|"
     r"\bllm(?! application)|deep learning|artificial intelligence|\bai\b.*\b(trainer|tutor|annotat|rater|evaluat)"),
    ("ai_forward", "AI-forward dev",
     r"\bai[- ]full[- ]?stack|ai[- ]first|\bai product engineer|\bai (application|app) (developer|engineer)|"
     r"\bai[- ]?(powered )?(web )?(developer|software engineer)|\bai automation|\bagentic\b|"
     r"\bagents? (engineer|developer)|automation engineer|forward[- ]deploy(ed|ment)|llm application|\bmcp\b|"
     r"\bai (full|stack|builder|solutions)|\bai[- ]native|\bai\b.*\bautomations?\b|\bai (tooling|tools?) engineer|automations? engineer|engineer\W+automations?|"
     r"d.velop+e(ur|use).*\bia\b"),
    ("solutions", "Customer Success / Solutions",
     r"solutions? (engineer|architect|consultant)|(customer|client) success|"
     r"implementation (engineer|specialist|consultant|manager)|integrations? engineer|technical account manager|"
     r"sales engineer|pre-?sales|customer engineer|onboarding specialist|(customer )?support engineer|technical consultant"),
    ("uxui", "UX/UI Design",
     r"\bux\b|user experience (engineer|designer|researcher)|\bui\s*/?\s*ux|\bui (designer|design)|product designer|visual designer|web designer|interaction designer|"
     r"figma|graphic designer|design lead|ux researcher|\bdesigner\b|\bcreative director"),
    ("ecommerce", "Shopify / E-commerce",
     r"shopify|e-?commerce|\becom\b|woocommerce|magento|bigcommerce|amazon (seller|marketplace|account|ppc|listing)|"
     r"marketplace (manager|specialist|coordinator)|klaviyo|\bdtc\b|conversion rate|\bcro\b"),
    ("mobile", "Mobile",
     r"^(?!.*back[- ]?end).*(\bios\b|android|react native|flutter|mobile (app )?(developer|engineer)|\bswift\b|kotlin)"),
    ("cloud", "Cloud / DevOps",
     r"devops|\bsre\b|site reliability|cloud (engineer|architect|developer|ops|infrastructure)|platform engineer|"
     r"infrastructure engineer|(aws|azure|gcp) (\w+ )?(engineer|architect)|devsecops|kubernetes|\bsysops\b"),
    ("data", "Data / Analytics",
     r"data (engineer|analyst|scientist|architect|analytics|quality|steward)|analytics|\bbi (developer|analyst)|"
     r"business intelligence|power ?bi|tableau|\betl\b"),
    ("qa", "QA / Testing",
     r"\bqa\b|quality assurance|test (engineer|automation|analyst|lead)|\bsdet\b|\btesters?\b"),
    ("it_systems", "IT / Systems / Security",
     r"it support|help ?desk|service desk|systems? administrator|sysadmin|network (engineer|administrator)|"
     r"security (engineer|analyst|architect)|cyber|active directory|\bentra\b|(m365|office 365|microsoft 365) (admin|engineer)|"
     r"\bit (technician|specialist|manager|operations|administrator|engineer|analyst)|desktop support|infosec|\bsoc\b"),
    ("fullstack", "Full-Stack", r"full[- ]?stack"),
    ("frontend", "Frontend",
     r"front[- ]?end|react (developer|engineer)|\breact\b|\bvue\b|angular|javascript developer|wordpress|webflow|"
     r"web developer(?!.*back[- ]?end)|\bweb dev(elopment)?\b|design engineer|ui (engineer|developer)|next\.?js|typescript developer|html"),
    ("backend", "Backend",
     r"back[- ]?end|api (developer|engineer)|node(\.?js)? (developer|engineer)|python (developer|engineer)|"
     r"java (developer|engineer)|(golang|go) (developer|engineer)|\bphp\b|\bruby\b|\brails\b|\.net|\bc#|django|"
     r"rust (developer|engineer)|scala (developer|engineer)|web developer"),
    ("dev_general", "Software (general)",
     r"software|\bdeveloper\b|programmer|(web|application|applications|systems|platform) engineer|\bengineer(ing)? lead\b|"
     r"\bsde\b|d.velop+e(ur|use)|product engineer(ing)?|performance engineer|\bcoder\b|technical lead|tech lead|\bcto\b"),
    ("va", "Virtual Assistant",
     r"virtual assistant|\bva\b|executive assistant|personal assistant|remote assistant|\bassistant to\b|"
     r"\bpa to\b|office assistant"),
    ("support", "Customer Service / Support",
     r"customer (service|support|care|experience|happiness|champion)(?! engineer)|"
     r"support (specialist|agent|representative|rep|associate|advocate)|call cent|contact cent|"
     r"technical support(?! engineer)|chat (agent|support)|helpline|client (service|support)|\bcsr\b|"
     r"service (agent|representative)"),
    ("admin", "Admin / Operations",
     r"\badmin|administrat|office manager|operations (assistant|coordinator|specialist|associate|manager|analyst)|"
     r"data entry|(?<!marketing )(?<!project )(?<!program )(?<!media )(?<!content )(?<!seo )(?<!event )coordinator|"
     r"bookkeep|accounts? (payable|receivable|assistant|clerk)|payroll|back office|clerk|logistics|freight|"
     r"dispatcher|receptionist|secretary|supply chain|procurement|warehouse|\bhr (manager|assistant|administrator|coordinator|officer|generalist)|human resources|recruit|"
     r"accountant|finance (assistant|officer)|operations"),
    ("sales", "Sales / Account Mgmt",
     r"account (executive|manager|director)|\bsales|business development|\bbdr\b|\bsdr\b|partnerships?|\bcloser\b|"
     r"appointment setter|lead generation|\bbdm\b|revenue"),
    ("marketing", "Marketing / Content / SEO",
     r"marketing|\bseo\b|content|copywrit|social media|growth|\bbrand|community manager|email marketing|"
     r"ppc|paid media|\bpr\b|public relations|video editor|\bwriter\b|editor"),
    ("product", "Product / Project",
     r"product (manager|owner|lead)|project (manager|coordinator|lead)|program(me)? manager|scrum master|"
     r"delivery manager|\bpmo\b|product operations"),
    ("other", "Other", None),
]

CATEGORIES = [(k, lab, rx) for k, lab, rx in _RAW]
LABELS = {k: lab for k, lab, _ in CATEGORIES}
_COMPILED = [(k, re.compile(rx)) for k, _, rx in CATEGORIES if rx]

AI_SIGNAL = re.compile(
    r"\b(llms?|large language|openai|anthropic|claude|gpt|chatgpt|cursor|copilot|langchain|llamaindex|rag|"
    r"retrieval[- ]augmented|agentic|ai agents?|generative ai|genai|prompt engineering|"
    r"vector (db|database|store)|embeddings|mcp)\b", re.I)

_DEV = {"fullstack", "frontend", "backend", "dev_general", "mobile"}


def _title_match(title):
    t = (title or "").lower()
    for k, rx in _COMPILED:
        if rx.search(t):
            return k
    return "other"


def category_of(title, description=""):
    k = _title_match(title)
    if k in _DEV and description:
        found = {m.group(1).lower() for m in AI_SIGNAL.finditer(description[:8000])}
        if len(found) >= 2:
            return "ai_forward"
    return k


def label(key):
    return LABELS.get(key, LABELS["other"])


def backfill(c, only_missing=True, batch=500):
    """Set jobs.category for existing rows. Returns the number of rows updated."""
    where = " WHERE category IS NULL" if only_missing else ""
    rows = c.execute("SELECT id, title, substr(description,1,8000) d FROM jobs" + where).fetchall()
    n = 0
    for i in range(0, len(rows), batch):
        chunk = [(category_of(r[1], r[2] or ""), r[0]) for r in rows[i:i + batch]]
        c.executemany("UPDATE jobs SET category=? WHERE id=?", chunk)
        if c.in_transaction:
            c.commit()
        n += len(chunk)
    return n
