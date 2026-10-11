"""Decide, for each found job: can a Cape Town contractor take it (geo),
which resume family + tier fits, does it ban AI-assisted applications,
and how good a fit it is (0-100). Pure rules - no AI, no cost."""
import datetime, re
from util import load_config

# ---------------------------------------------------------------- geo
YES = re.compile(r"\b(worldwide|anywhere|global(ly)?|south africa|cape town|johannesburg|durban|"
                 r"africa|emea|sast|utc ?\+ ?2|gmt ?\+ ?2|cet|eet|work from anywhere|remote[- ]first, any)\b", re.I)
YES_DESC = re.compile(r"\b(worldwide|anywhere in the world|work from anywhere|from anywhere|south africa|africa|emea|"
                      r"utc ?\+ ?2|gmt ?\+ ?2|sast)\b", re.I)
NO_LOC = re.compile(r"\b(us|usa|u\.s\.|united states|canada|uk only|united kingdom only|latam|latin america|"
                    r"philippines|india|pakistan|brazil|mexico|colombia|argentina)\s*(only|based|residents?)?\b", re.I)
NO_DESC = re.compile(
    r"(must (be|reside|live)( located| based)? (in|within) (the )?(us|u\.s\.|usa|united states|canada|uk|"
    r"united kingdom|eu|european union|europe|latam|philippines|india)\b"
    r"|(us|u\.s\.|usa|united states|canada|uk|eu)[- ](only|based (candidates|applicants) only|residents only)"
    r"|authori[sz]ed to work in (the )?(us|u\.s\.|usa|united states|uk|canada|eu)"
    r"|only (accepting|considering) (applicants|candidates) (from|in|based in) (the )?(us|usa|united states|canada|uk|eu|latam|europe)"
    r"|this (position|role) is (only )?open to (residents|candidates) (of|in) (the )?(us|usa|united states|canada|uk)"
    r"|w-?2 (employee|only)|eligible to work in the (us|united states)"
    r"|security clearance|us citizenship)", re.I)
REMOTE_ONLY = re.compile(r"^\s*(remote|fully remote|100% remote)\s*$", re.I)

AI_BAN = re.compile(
    r"(ai[- ]generated (applications?|resumes?|cvs?|cover letters?|materials?|answers?)"
    r"|(do not|don't|please don't|refrain from) us(e|ing) (ai|chatgpt|gpt|llms?)"
    r"|(written|generated) (by|with|using) (ai|chatgpt|an llm)[^.]{0,80}(disqualif|reject|not be considered)"
    r"|without (the )?(use of|help of) (ai|chatgpt))", re.I)


SA_CITIES = (r"johannesburg|joburg|sandton|cape town|durban|pretoria|centurion|midrand|stellenbosch|gqeberha|"
             r"port elizabeth|bloemfontein|randburg|rosebank|umhlanga|century city|bellville|paarl|east london")
SA_CITY_LOC = re.compile(r"(" + SA_CITIES + r"|gauteng|western cape|kwazulu|free state|eastern cape|kempton|mangaung|"
                         r"limpopo|mpumalanga|north west province|northern cape)", re.I)
SA_ANY = re.compile(r"(south africa|" + SA_CITIES + r"|gauteng|western cape|kwazulu)", re.I)

DEFAULT_PLATFORMS = ["deel", "remote.com", "oyster", "toptal", "lemon.io", "turing", "andela", "proxify",
                     "hire overseas", "pavago", "huzzle", "pearl talent", "multiplier", "omnipresent",
                     "arc.dev", "x-team", "bairesdev"]
DEFAULT_AGGREGATORS = ["cherry assistant", "recruitmymom", "workforce staffing", "adcorp", "kelly",
                       "network recruitment", "e-merge", "jobvine"]

# strong SA-local signals
S_PTY = re.compile(r"\(pty\)|\bpty\.? ?ltd", re.I)
S_EE = re.compile(r"\bb-?bbee\b|employment equity|\bEE (position|candidates?|appointment)\b", re.I)
S_RAND = re.compile(r"(?<![A-Za-z$])R ?\d{1,3}(?:[ ,]\d{3})+\b|(?<![A-Za-z$])R ?\d{4,6}\b|(?<![A-Za-z$])R ?\d{2,3} ?k\b"
                    r"|\bZAR\b|\bCTC\b|cost[- ]to[- ]company|\d ?rand\b")
S_ONSITE = re.compile(r"\b(hybrid|on-?site|in-?office|office[- ]based|(?:" + SA_CITIES + r") (?:office|based|head office|hq))\b", re.I)
# weak SA signals
W_COZA = re.compile(r"\.co\.za\b", re.I)
W_PHONE = re.compile(r"(?<!\d)\+27[ \d()-]{8,}")
W_SACO = re.compile(r"south african (company|based|business|owned)", re.I)
W_UIF = re.compile(r"\b(UIF|PAYE)\b")
# overseas signals
O_PAY = re.compile(r"\$ ?\d|US\$|\b(USD|EUR|GBP|AED)\b|[\u20ac\u00a3]")
O_CLIENT = re.compile(r"\b(US|UK|EU|Australian|American|European|British|Canadian|U\.S\.)[- ](?:based )?(?:clients?|customers?|company|companies|startups?|agenc(?:y|ies)|teams?)\b")
O_CLIENT2 = re.compile(r"\b(?:US|UK|EU|Australian|American|European|British|Canadian)[ /,]+(?:and )?(?:(?:US|UK|EU|Australian)[ /,]+)*clients?\b", re.I)
O_HQ = re.compile(r"headquartered in ([A-Z][\w., ]{2,40})")
O_HQ_LOC = re.compile(r"HQ:\s*([^)]+)", re.I)
TZ_ZONES = {}  # filled below


def _cfg_geo(cfg):
    cfg = cfg if cfg is not None else load_config()
    return cfg, (cfg.get("geo") or {})


def _name_hit(company, names):
    c = (company or "").lower().strip()
    for n in names:
        n = n.lower()
        if c == n or re.search(r"(?<![\w])" + re.escape(n) + r"(?![\w])", c):
            return n
    return None


def _is_local_board(job, cfg):
    for b in cfg.get("boards", []) or []:
        if b.get("name") == job.get("board"):
            return bool(b.get("local"))
    return False


def employer(job, cfg=None):
    """Classify the employer. Returns (type, reason); type is one of overseas_direct, overseas_platform,
    sa_aggregator, sa_local, unknown."""
    cfg, g = _cfg_geo(cfg)
    company = job.get("company") or ""
    loc = job.get("location") or ""
    desc = (job.get("description") or "")[:8000]
    text = " ".join([company, loc, job.get("salary") or "", desc])
    url = (job.get("apply_url") or "") + " " + (job.get("url") or "")

    # --- overseas evidence
    over, over_pay = [], False
    m = O_PAY.search(text)
    if m:
        over_pay = True
        over.append(f"pay in {m.group(0).strip()[:12]}")
    m = O_CLIENT.search(text) or O_CLIENT2.search(text)
    if m:
        over.append(f'"{m.group(0)[:30]}"')
    m = O_HQ.search(desc)
    if m and not SA_ANY.search(m.group(1)):
        over.append(f"HQ {m.group(1).strip()[:25]}")
    m = O_HQ_LOC.search(loc)
    if m and not SA_ANY.search(m.group(1)):
        over.append(f"HQ {m.group(1).strip()[:25]}")
    watch = _name_hit(company, g.get("watch_override") or cfg.get("companies_to_watch") or [])
    if watch:
        over.append(f"watch-list company {watch}")
    strong_over = len(over)
    board_over = not _is_local_board(job, cfg)
    n_over = strong_over + (1 if board_over else 0)

    # --- international platforms
    plats = g.get("international_platforms") or DEFAULT_PLATFORMS
    p = _name_hit(company, plats)
    if not p:
        for n in plats:
            if re.search(r"\b(?:via|through|on|with|by|using|powered by)\s+(?:the\s+)?" + re.escape(n) + r"(?![\w])", desc, re.I):
                p = n
                break
    if p:
        return "overseas_platform", f"international platform: {p}"

    # --- SA aggregators
    ag = _name_hit(company, g.get("sa_aggregators") or DEFAULT_AGGREGATORS)
    if ag:
        if over_pay:
            return "unknown", f"SA staffing name ({ag}) but posting states foreign-currency pay - check where the employer is based"
        return "sa_aggregator", f"sa_aggregator: {ag}, no USD/EUR/GBP/AED pay stated"

    # --- strong SA signals
    strong = []
    if S_PTY.search(company + " " + desc):
        strong.append("Pty Ltd")
    if S_EE.search(desc):
        strong.append("B-BBEE/employment equity")
    mr = S_RAND.search(text)
    if mr and not over_pay:
        strong.append(f"salary in rand ({mr.group(0).strip()[:14]})")
    mo = S_ONSITE.search(desc)
    if mo and (SA_CITY_LOC.search(loc) or SA_CITY_LOC.search(desc)):
        strong.append(f"{mo.group(0).strip()[:20]} in SA")
    if strong and not over_pay:
        return "sa_local", "sa_local: " + " + ".join(strong)
    if strong and over_pay and not (len(strong) == 1 and strong[0] == "Pty Ltd" and False):
        pass  # foreign pay stated: strong signals alone are not enough, fall through to weak count

    # --- weak SA signals
    weak = []
    loc_city = bool(SA_CITY_LOC.search(loc))
    if loc_city:
        weak.append(f"location {loc[:30]}")
    if W_COZA.search(url):
        weak.append(".co.za apply URL")
    if W_PHONE.search(text):
        weak.append("+27 phone")
    if W_SACO.search(desc):
        weak.append("South African company")
    if W_UIF.search(desc):
        weak.append("UIF/PAYE")
    nw = len(weak) + len(strong)  # strong signals neutralised by foreign pay still count as weak evidence
    weak = weak + [f"{x} (foreign pay stated)" for x in strong]
    if nw:
        net = nw - n_over
        if net >= 2 or (nw == 1 and n_over == 0 and loc_city):
            return "sa_local", "sa_local: " + " + ".join(weak)
    if strong_over:
        return "overseas_direct", "overseas: " + ", ".join(over[:3])
    if weak:
        return "unknown", "weak SA signal (" + ", ".join(weak[:2]) + ") offset by overseas evidence - check where the employer is based"
    return "unknown", "no clear employer location - check where the employer is based"


def sa_local(job):
    """Back-compat: True when employer() says a South African local employer or SA staffing aggregator."""
    try:
        return employer(job, load_config())[0] in ("sa_local", "sa_aggregator")
    except Exception:
        return False


# ------------------------------------------------------------ time zone fit
_Z = {
    "ET": (-4, "US Eastern", r"\b(?:EST|EDT|ET|(?i:eastern|us east|new york))\b"),
    "CT": (-5, "US Central", r"\b(?:CST|CDT|CT|(?i:central(?! europe)|us central))\b"),
    "MT": (-6, "US Mountain", r"\b(?:MST|MDT|MT|(?i:mountain))\b"),
    "PT": (-7, "US Pacific", r"\b(?:PST|PDT|PT|(?i:pacific|us west|california))\b"),
    "UK": (1, "UK", r"\b(?:GMT|BST|(?i:uk|u\.k\.|london|british))\b"),
    "CET": (2, "CET", r"\b(?:CET|CEST|(?i:central european))\b"),
    "IST": (5.5, "India", r"\b(?:IST|(?i:indian standard|india))\b"),
    "AEST": (10, "Australian Eastern", r"\b(?:AEST|AEDT|(?i:australian|sydney|melbourne))\b"),
}
_ZRE = {k: re.compile(v[2]) for k, v in _Z.items()}
_ZALL = "(?:" + "|".join(v[2] for v in _Z.values()) + ")"
_CTX = r"\s*(?:time ?zones?|business hours|working hours|work hours|office hours|core hours|hours|time\b|overlap|aligned|based hours)"
TZ_GENERIC = re.compile(_ZALL + _CTX, 0)
TZ_GENERIC2 = re.compile(r"(?:work(?:ing)?|available|availability|overlap|aligned?|alignment|hours)\w*\s+(?:with|during|in|on|to|of)?\s*(?:the\s+)?" + _ZALL + r"\b")
TZ_OVL1 = re.compile(r"(\d{1,2})\s*\+?\s*(?:hours?|hrs?)\s*(?:of\s*)?(?:daily\s*)?(?:overlap|overlapping)\b(?P<rest>.{0,50})", re.I | re.S)
TZ_OVL2 = re.compile(r"overlap(?:ping)?\s*(?:of\s*)?(?:at least\s*|min(?:imum)?\s*)?(\d{1,2})\s*\+?\s*(?:hours?|hrs?)\b(?P<rest>.{0,50})", re.I | re.S)


def _zone_in(txt):
    best = None
    for k, rx in _ZRE.items():
        m = rx.search(txt)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), k)
    return best[1] if best else None


def _fmt(h):
    h = h % 24
    return f"{int(h):02d}:{'30' if h % 1 else '00'}"


def _parse_window(w):
    try:
        a, b = w.split("-")
        f = lambda t: int(t.split(":")[0]) + int(t.split(":")[1]) / 60
        s, e = f(a.strip()), f(b.strip())
        return s, (e if e > s else e + 24)
    except Exception:
        return 7.0, 22.0


def timezone_fit(job, cfg=None):
    """(ok, reason). ok True/False, or None when the posting states no time-zone requirement."""
    cfg, g = _cfg_geo(cfg)
    ws, we = _parse_window(g.get("work_window_sast", "07:00-22:00"))
    desc = (job.get("description") or "")[:8000]
    zone, hours, partial = None, 8, False
    for rx in (TZ_OVL1, TZ_OVL2):
        m = rx.search(desc)
        if m:
            z = _zone_in(m.group("rest"))
            if z:
                zone, hours, partial = z, int(m.group(1)), True
                break
    if not zone:
        cands = [m for m in (TZ_GENERIC.search(desc), TZ_GENERIC2.search(desc)) if m]
        if cands:
            m = min(cands, key=lambda x: x.start())
            zone = _zone_in(m.group(0))
    if not zone:
        return None, "no time-zone requirement stated"
    off, label, _ = _Z[zone]
    s = 9 + 2 - off
    hours = min(max(hours, 1), 8)
    e = s + hours
    span = f"({_fmt(s)}-{_fmt(e)} SAST)"
    if s >= ws and e <= we:
        return True, (f"{hours}h overlap with {label} fits " if partial else f"{label} hours fit ") + span
    if partial:
        return False, f"needs {hours}h overlap with {label} {span}"
    return False, f"needs {label} hours {span}"


def geo(job, track="remote"):
    """Returns (ok, reason). ok: 1 eligible, 0 not eligible, None = check the apply page."""
    cfg = load_config()["geo"]
    me = [c.lower() for c in cfg["my_countries"]]
    loc = (job.get("location") or "").strip()
    desc = job.get("description") or ""
    countries = job.get("countries")

    if track == "relocation":
        if re.search(r"visa sponsorship|sponsor (your|a) visa|relocation (support|package|assistance)", desc, re.I) \
                or job.get("visa"):
            return 1, "relocation: sponsorship/relocation mentioned"
        return None, "relocation: no sponsorship wording, check"

    if countries:
        cl = [c.lower() for c in countries if c]
        if any(c in me for c in cl):
            return 1, f"listed countries include {', '.join(c for c in countries if c.lower() in me)}"
        if any(re.search(r"worldwide|anywhere|africa|emea", c) for c in cl):
            return 1, "listed region covers you"
        return 0, "countries listed exclude you: " + ", ".join(countries[:6]) + ("..." if len(countries) > 6 else "")

    m = NO_DESC.search(desc)
    if m:
        return 0, f'description: "{m.group(0)[:80]}"'
    if YES.search(loc):
        if re.search(r"HQ: .*\b(usa?|united states)\b", loc, re.I) and re.search(r"anywhere", loc, re.I):
            return None, "board says Anywhere but company is US-remote - check apply page"
        return 1, f'location "{loc[:60]}"'
    if loc and NO_LOC.search(loc):
        return 0, f'location "{loc[:60]}"'
    m = YES_DESC.search(desc[:6000])
    if m:
        return 1, f'description mentions "{m.group(0)}"'
    if not loc or REMOTE_ONLY.match(loc):
        return None, "just says Remote - check the apply page"
    if re.search(r",\s*[A-Z]", loc) or FOREIGN.search(loc):
        return 0, f'location "{loc[:60]}" is a place outside South Africa'
    return None, f'location "{loc[:60]}" unclear'


FOREIGN = re.compile(r"\b(united states|united kingdom|france|germany|spain|italy|india|canada|australia|netherlands|"
                     r"poland|portugal|brazil|mexico|ireland|greece|romania|bulgaria|serbia|croatia|ukraine|turkey|israel|egypt|"
                     r"nigeria|kenya|ghana|morocco|philippines|pakistan|bangladesh|vietnam|indonesia|malaysia|singapore|"
                     r"japan|china|korea|new zealand|argentina|colombia|chile|peru|sweden|norway|denmark|finland|"
                     r"belgium|austria|switzerland|czech|hungary|estonia|latvia|lithuania|cyprus|malta|uae|dubai|"
                     r"saudi|qatar|usa|us|uk|eu|europe|latam|apac|americas|north america|area|metropolitan|[A-Z]{2}$)\b", re.I)


# ------------------------------------------------- family / tier / fit
def family_of(title, cfg):
    t = title.lower()
    fams = cfg["families"]
    for fam in [f for f in ("admin", "design") if f in fams] + [f for f in fams if f not in ("admin", "design")]:
        spec = fams[fam]
        if any(re.search(p, t) for p in spec["title_patterns"]):
            return fam
    return None


def excluded(title, cfg):
    return any(re.search(p, title.lower()) for p in cfg["search"]["title_exclude"])


def title_ok(title, cfg=None):
    cfg = cfg or load_config()
    return bool(title) and not excluded(title, cfg) and family_of(title, cfg) is not None


def years_asked(text):
    nums = [int(n) for n in re.findall(r"(\d{1,2})\s*\+?\s*(?:-\s*\d+\s*)?(?:years|yrs)", text[:6000], re.I)
            if int(n) <= 15]
    return min(nums) if nums else None


def tier_of(title, desc, family, cfg):
    t = title.lower()
    tiers = cfg["families"][family]["tiers"]
    yrs = years_asked(desc or "")
    if re.search(r"\b(lead|staff|principal|architect)\b", t):
        want = "S"
    elif re.search(r"\b(senior|sr\.?|snr)\b", t):
        want = "M-S"
    elif re.search(r"\b(intern|entry|graduate|trainee|junior|jr\.?|jnr)\b", t):
        want = "J" if not (yrs and yrs >= 2) else "J-M"
    elif re.search(r"\b(mid|intermediate|ii)\b", t):
        want = "HM"
    elif yrs is not None:
        want = "J" if yrs <= 1 else "J-M" if yrs <= 2 else "HM" if yrs <= 4 else "M-S" if yrs <= 6 else "S"
    else:
        want = "HM"
    order = ["J", "J-M", "HM", "M-S", "S"]
    if want in tiers:
        return want, yrs
    # fall to the nearest tier this family has (e.g. Admin stops at HM)
    idx = order.index(want)
    for d in range(1, 5):
        for cand in (order[max(0, idx - d)], order[min(4, idx + d)]):
            if cand in tiers:
                return cand, yrs
    return tiers[0], yrs


TECH = re.compile(r"\b([A-Z][A-Za-z0-9+#.\-]{1,24}|[a-z]+\.js|AWS|SQL|API|CRM|SEO|CRO|UX|UI)\b")


CORE = {
    "dev": r"\b(react|next\.?js|shopify|liquid|javascript|typescript|node(\.?js)?|wordpress|webflow|front[- ]?end|html|css|tailwind)\b",
    "design": r"\b(figma|ux|ui|wireframe|prototyp|design system|adobe)\b",
    "admin": r"\b(customer|client|admin|schedul|email|calendar|support|data entry|crm|e-?commerce|order|inbox|virtual assistant)\b",
}


def core_ok(job, family, cfg=None):
    text = (job.get("title") or "") + " " + (job.get("description") or "")
    if len(job.get("description") or "") < 200:
        return True  # can't judge yet
    pat = (cfg or load_config())["families"].get(family, {}).get("core") or CORE.get(family)
    return True if not pat else bool(re.search(pat, text, re.I))


def fit_score(job, family, vocab, track="remote"):
    """0-100. vocab = set of lowercased skills from that family's master resume."""
    desc = job.get("description") or ""
    reasons = []
    terms = {m.group(1).lower().strip(".") for m in TECH.finditer(desc[:8000])}
    terms = {t for t in terms if len(t) > 1 and t not in STOP}
    hits = sorted(t for t in terms if t in vocab)
    tech = min(45, int(45 * len(hits) / max(6, min(len(terms), 20)))) if terms else 15
    reasons.append(f"skills match {len(hits)}: {', '.join(hits[:10])}")
    s = tech
    g = job.get("geo_ok")
    s += 25 if g == 1 else 8 if g is None else 0
    try:
        age = (datetime.date.today() - datetime.date.fromisoformat((job.get("posted_at") or "")[:10])).days
    except Exception:
        age = None
    if age is not None:
        s += 15 if age <= 2 else 10 if age <= 7 else 4 if age <= 14 else -10
        reasons.append(f"{age}d old")
    else:
        s += 5
    if job.get("salary"):
        s += 5
    if re.search(r"contract|freelance|part[- ]time|hourly", (job.get("employment_type") or "") + " " + desc[:3000], re.I):
        s += 5
        reasons.append("contract/part-time (stackable)")
    if re.search(r"\b(shopify|liquid|hydrogen|e-?commerce|klaviyo)\b", desc, re.I):
        s += 5
        reasons.append("e-commerce/Shopify edge")
    return max(0, min(100, s)), reasons


STOP = {"the", "and", "you", "our", "we", "this", "for", "with", "are", "will", "your", "team", "work", "about",
        "role", "job", "remote", "company", "in", "of", "to", "a", "an", "is", "be", "as", "at", "on", "or",
        "if", "it", "us", "all", "what", "who", "why", "how", "requirements", "responsibilities", "benefits",
        "experience", "skills", "strong", "ability", "excellent", "must", "plus", "nice", "have", "years",
        "full", "time", "part", "salary", "location", "apply", "join", "help", "build", "new", "monday", "friday"}
