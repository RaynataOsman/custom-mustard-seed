"""Candidate accounts on job portals, created and used for you (you switched this on).

- Signs in with a saved account for that site, or creates one with your email and a strong new password.
- Reads the confirmation code / verification link from your Gmail (read-only, newest mail only).
- Saves every account in data/accounts.json (this PC only, never in git) and emails you the details.
- Stops and hands the role to you (Needs you) on a CAPTCHA, a phone/SMS check or anything it can't read.
"""
import datetime, email, email.header, email.utils, imaplib, json, re, secrets, smtplib, string, time, urllib.parse
from email.message import EmailMessage
from util import DATA, load_config, load_keys, strip_html

VAULT = DATA / "accounts.json"
SIGNUP_LINK = re.compile(r"create (an )?account|sign ?up|register|new (user|candidate)|don'?t have an account|join now|get started", re.I)
SUBMIT_TEXT = re.compile(r"^(create (my )?account|sign ?up|register|continue|next|get started|submit|verify|confirm|sign ?in|log ?in|send (me )?(a )?(code|link)|apply)\b", re.I)
CHECK_MAIL = re.compile(r"check your (e-?mail|inbox)|we('ve| have)? sent|verification (code|link|email)|confirm your (e-?mail|account)|"
                        r"enter the (\d+-digit )?code|one-?time (code|password)|magic link", re.I)
EMAIL_ENTRY = re.compile(r"^\s*((sign|log) ?in|continue|sign ?up|register) with e-?mail|^\s*use (my )?e-?mail|^\s*create account\s*$", re.I)
PHONE_CHECK = re.compile(r"(sms|text message).{0,40}code|verify your (phone|mobile)", re.I)


def _load():
    try:
        return json.loads(VAULT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(v):
    VAULT.write_text(json.dumps(v, indent=1), encoding="utf-8")


def site_key(url):
    h = urllib.parse.urlparse(url).netloc.lower()
    h = re.sub(r"^(www\.|apply\.|jobs\.|careers\.|career\.)", "", h)
    return h


def saved(url):
    return _load().get(site_key(url))


def new_password():
    alpha = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alpha) for _ in range(14))
    return core[:5] + secrets.choice("!@#$%*") + core[5:10] + secrets.choice("23456789") + core[10:] + "Aa"


def _remember(url, mail, password, job, how):
    v = _load()
    key = site_key(url)
    fresh = key not in v
    v[key] = {"email": mail, "password": password, "site": url.split("?")[0], "created": datetime.datetime.now().isoformat(timespec="seconds"),
              "first_job": f"{job.get('company')} - {job.get('title')}", "how": how}
    _save(v)
    if fresh:
        _email_owner(key, v[key])


def _email_owner(key, rec):
    """Send the new account's details to your own inbox (Gmail SMTP with your app password)."""
    k = load_keys()
    addr, pw = k.get("GMAIL_ADDRESS"), (k.get("GMAIL_APP_PASSWORD") or "").replace(" ", "")
    to = load_config()["profile"].get("email") or addr
    if not (addr and pw and to):
        return
    msg = EmailMessage()
    msg["Subject"] = f"Job Engine: new candidate account on {key}"
    msg["From"], msg["To"] = addr, to
    msg.set_content(f"The job engine created a candidate account for you.\n\nSite: {rec['site']}\nEmail: {rec['email']}\n"
                    f"Password: {rec['password'] or '(no password - this site signs you in with an emailed code)'}\n"
                    f"Created: {rec['created']}\nFirst application: {rec['first_job']}\n\n"
                    "It is also saved on your PC in data/accounts.json. Change the password on the site any time "
                    "and update it there.")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(addr, pw)
            s.send_message(msg)
    except Exception:
        pass


# ------------------------------------------------------------------ Gmail (read-only)
def _imap():
    k = load_keys()
    M = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
    M.login(k["GMAIL_ADDRESS"], (k.get("GMAIL_APP_PASSWORD") or "").replace(" ", ""))
    M.select("INBOX", readonly=True)
    return M


def _recent_mails(since_ts, host_tokens, limit=15):
    M = _imap()
    try:
        day = datetime.datetime.fromtimestamp(since_ts - 86400).strftime("%d-%b-%Y")
        typ, data = M.search(None, f'(SINCE "{day}")')
        ids = (data[0] or b"").split()[-limit:]
        out = []
        for i in reversed(ids):
            typ, msg = M.fetch(i, "(BODY.PEEK[])")
            m = email.message_from_bytes(msg[0][1])
            try:
                when = email.utils.parsedate_to_datetime(m["Date"]).timestamp()
            except Exception:
                when = 0
            if when < since_ts - 60:
                continue
            frm = (m.get("From") or "").lower()
            subj = str(email.header.make_header(email.header.decode_header(m.get("Subject") or "")))
            body = ""
            for part in m.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    try:
                        body += part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace") + "\n"
                    except Exception:
                        pass
            related = any(t in frm or t in subj.lower() or t in body.lower()[:3000] for t in host_tokens)
            if related or re.search(r"verif|confirm|code|activate|sign.?in|log.?in|password", subj, re.I):
                out.append({"from": frm, "subject": subj, "body": body, "when": when, "related": related})
        return out
    finally:
        try:
            M.logout()
        except Exception:
            pass


def _tokens(url):
    h = site_key(url)
    return [t for t in re.split(r"[.\-]", h) if len(t) >= 4 and t not in ("com", "careers", "jobs", "apply", "recruit", "hire")]


def wait_for_code(url, since_ts, log, timeout_s=240):
    toks = _tokens(url)
    end = time.time() + timeout_s
    while time.time() < end:
        for m in sorted(_recent_mails(since_ts, toks), key=lambda x: (not x["related"], -x["when"])):
            text = strip_html(m["body"]) if "<" in m["body"] else m["body"]
            hit = re.search(r"(?:code|otp|pin|passcode)[^0-9A-Z]{0,40}\b([0-9]{4,8}|[A-Z0-9]{6})\b", text, re.I) or \
                re.search(r"\b([0-9]{6})\b", m["subject"] + " " + text[:1500])
            if hit:
                log(f"    got a {len(hit.group(1))}-character code from {m['from'][:60]}")
                return hit.group(1)
        time.sleep(10)
    return None


def wait_for_link(url, since_ts, log, timeout_s=240):
    toks = _tokens(url)
    end = time.time() + timeout_s
    while time.time() < end:
        for m in sorted(_recent_mails(since_ts, toks), key=lambda x: (not x["related"], -x["when"])):
            for href in re.findall(r'href=["\'](https?://[^"\']+)', m["body"]) + re.findall(r"(https?://\S+)", m["body"]):
                h = href.replace("&amp;", "&").rstrip(").,>\"'")
                if re.search(r"verif|confirm|activat|validat|magic|token|login|signin|auth", h, re.I) and \
                        not re.search(r"unsubscribe|privacy|terms|help", h, re.I):
                    log(f"    got a verification link from {m['from'][:60]}")
                    return h
        time.sleep(10)
    return None


# ------------------------------------------------------------------ page helpers
def _visible(page, sel):
    out = []
    for e in page.query_selector_all(sel):
        try:
            if e.is_visible():
                out.append(e)
        except Exception:
            pass
    return out


def _entry_buttons(page):
    out = []
    for e in _visible(page, "button, a, [role=button]"):
        try:
            if EMAIL_ENTRY.search((e.inner_text() or "")[:60]):
                out.append(e)
        except Exception:
            pass
    return out


def is_wall(page):
    """A sign-in / sign-up / email-first gate standing in front of the application."""
    if _visible(page, 'input[type="password"]'):
        return True
    if not _visible(page, 'input[type="file"]') and _entry_buttons(page):
        return True  # e.g. Workday: "Sign in with Google | Sign in with email"
    if _visible(page, 'input[type="file"]'):
        return False
    emails = _visible(page, 'input[type="email"], input[name*="email" i], input[autocomplete="email"]')
    others = [e for e in _visible(page, 'input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]), textarea')
              if e not in emails]
    try:
        txt = page.inner_text("body")[:4000]
    except Exception:
        txt = ""
    return bool(emails) and len(others) <= 1 and bool(re.search(r"enter your e-?mail|get started|sign ?in|log ?in|create (an )?account|"
                                                                r"continue with e-?mail|register", txt, re.I))


def _code_inputs(page):
    els = _visible(page, 'input[autocomplete="one-time-code"], input[name*="code" i], input[id*="code" i], input[name*="otp" i], '
                         'input[aria-label*="code" i], input[placeholder*="code" i], input[inputmode="numeric"][maxlength="1"], '
                         'input[maxlength="1"]')
    return els


def _click_submit(page, near=None):
    """Press the submit button of the form we just filled (never a header 'Login to portal' button)."""
    scopes = []
    if near is not None:
        try:
            form = near.evaluate_handle("e => e.closest('form') || e.closest('[role=dialog], main, section, div[class*=card], div[class*=form]')")
            if form and form.as_element():
                scopes.append(form.as_element())
        except Exception:
            pass
    scopes.append(page)
    for scope in scopes:
        btns = []
        for e in scope.query_selector_all('button[type=submit], input[type=submit], button, [role=button]'):
            try:
                if not e.is_visible() or not e.is_enabled():
                    continue
                inside_header = e.evaluate("e => !!e.closest('header, nav, footer')")
                if inside_header:
                    continue
                t = (e.inner_text() or e.get_attribute("value") or "").strip()
                typ = (e.get_attribute("type") or "").lower()
                if SUBMIT_TEXT.match(t) or typ == "submit":
                    btns.append((0 if typ == "submit" else 1, e, t))
            except Exception:
                pass
        if btns:
            btns.sort(key=lambda x: x[0])
            btns[0][1].click()
            return btns[0][2] or "submit"
    try:
        page.keyboard.press("Enter")
        return "Enter"
    except Exception:
        return None


def _fill_names(page, prof):
    for e in _visible(page, 'input[type=text], input:not([type])'):
        try:
            if (e.input_value() or "").strip():
                continue
            lab = (e.get_attribute("name") or "") + " " + (e.get_attribute("placeholder") or "") + " " + \
                  (e.get_attribute("aria-label") or "") + " " + (e.get_attribute("id") or "")
            if re.search(r"first", lab, re.I):
                e.fill(prof["first_name"])
            elif re.search(r"last|surname", lab, re.I):
                e.fill(prof["last_name"])
            elif re.search(r"full.?name|^name|\bname\b", lab, re.I):
                e.fill(prof["name"])
            elif re.search(r"phone|mobile", lab, re.I):
                e.fill(prof["phone"])
        except Exception:
            pass


def _tick_terms(page):
    for e in _visible(page, 'input[type=checkbox]'):
        try:
            box = e.evaluate("e => (e.closest('label,div,li') || e.parentElement).innerText.slice(0,200)") or ""
            if re.search(r"terms|privacy|agree|consent|policy", box, re.I) and not e.is_checked():
                try:
                    e.check(timeout=2000)
                except Exception:
                    e.evaluate("e => (e.labels && e.labels[0] ? e.labels[0] : e).click()")
        except Exception:
            pass


def get_past_wall(page, job, cfg, log, captcha):
    """Sign in or create an account until the application form shows. Returns (ok, note)."""
    prof = cfg["profile"]
    url = page.url
    rec = saved(url)
    created = None
    tried = set()
    since = time.time()
    import os
    dbg = os.environ.get("MS_DEBUG_ACCOUNTS")
    for step in range(8):
        page.wait_for_timeout(2500)
        if dbg:
            try:
                page.screenshot(path=f"out/proofs/acct_step{step}.png", full_page=True)
                print(f"    [debug] step {step}: {page.url[:90]} | pw={len(_visible(page, 'input[type=password]'))} "
                      f"mail={len(_visible(page, 'input[type=email]'))} codes={len(_code_inputs(page))}")
            except Exception:
                pass
        try:
            body = page.inner_text("body")[:6000]
        except Exception:
            body = ""
        if not is_wall(page) and not _code_inputs(page) and not CHECK_MAIL.search(body):
            if created:
                _remember(url, prof["email"], created, job, "created")
            return True, ("created an account" if created else "signed in") + f" on {site_key(url)}"
        if captcha(page):
            return False, "CAPTCHA on the sign-in / sign-up page"
        if PHONE_CHECK.search(body):
            return False, "this site wants a phone / SMS check"
        codes = _code_inputs(page)
        if codes and (CHECK_MAIL.search(body) or len(codes) >= 4 or step > 0):
            code = wait_for_code(url, since, log)
            if not code:
                return False, "waited 4 minutes for the email code - none arrived"
            if len(codes) >= len(code) > 1 and all((c.get_attribute("maxlength") or "") == "1" for c in codes[:len(code)]):
                for c, ch in zip(codes, code):
                    c.fill(ch)
            else:
                codes[0].fill(code)
            _click_submit(page, codes[0])
            continue
        if CHECK_MAIL.search(body) and not _visible(page, 'input[type="password"], input[type="email"]'):
            link = wait_for_link(url, since, log)
            if not link:
                return False, "waited 4 minutes for the verification email - none arrived"
            page.goto(link, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            if job.get("_form_url"):
                page.goto(job["_form_url"], wait_until="domcontentloaded", timeout=60000)
            continue
        pws = _visible(page, 'input[type="password"]')
        mails = _visible(page, 'input[type="email"], input[name*="email" i], input[autocomplete="email"], input[name*="user" i]')
        if re.search(r"(account|user|e-?mail)[^.?!\n]{0,40}already (exists|registered|in use|taken)|already (been )?registered|"
                     r"an account (already )?exists|e-?mail (address )?(is )?already (registered|in use|taken)", body, re.I):
            return False, (f"you already have an account on {site_key(url)} - sign in once in the applying browser "
                           "(Boards > Sign-ins) and the engine will use it")
        if re.search(r"invalid (credentials|password|e-?mail or password)|incorrect (password|credentials)|wrong password", body, re.I) and tried:
            if created and "signup" not in tried:
                link = next((e for e in _visible(page, "a, button") if SIGNUP_LINK.search((e.inner_text() or "")[:60])), None)
                if link:
                    tried.add("signup")
                    link.click()
                    continue
            return False, f"sign-in rejected on {site_key(url)} - " + ("the saved password no longer works" if rec else
                                                                        "an account with your email may already exist")
        if pws:
            heading = " ".join((e.inner_text() or "") for e in _visible(page, "h1, h2, h3, button[type=submit], input[type=submit]"))[:400]
            signup_page = len(pws) >= 2 or bool(re.search(r"create (an |your )?account|sign ?up|register|join", heading, re.I))
            login_page = not signup_page
            if login_page and rec:
                if mails:
                    mails[0].fill(rec["email"])
                pws[0].fill(rec["password"])
                log(f"    signing in to {site_key(url)} with your saved account")
                tried.add("login")
            elif login_page:
                link = next((e for e in _visible(page, "a, button") if SIGNUP_LINK.search((e.inner_text() or "")[:60])), None)
                if link and "signup" not in tried:
                    tried.add("signup")
                    link.click()
                    continue
                return False, f"sign-in page on {site_key(url)} with no saved account and no sign-up link"
            else:
                created = created or new_password()
                if mails:
                    mails[0].fill(prof["email"])
                for p_ in pws:
                    p_.fill(created)
                _fill_names(page, prof)
                _tick_terms(page)
                log(f"    creating an account on {site_key(url)}")
                if ("create", page.url) in tried:
                    return False, f"the sign-up form on {site_key(url)} would not accept the details (a required field the engine can't fill?)"
                tried.add(("create", page.url))
            _click_submit(page, pws[0])
            continue
        if not pws and not mails:
            btns = _entry_buttons(page)
            create = next((b for b in btns if re.search(r"create account|sign ?up|register", b.inner_text() or "", re.I)), None)
            pick = (create if (create and not rec) else None) or next((b for b in btns if re.search(r"e-?mail", b.inner_text() or "", re.I)), None) or (btns[0] if btns else None)
            if pick:
                pick.click()
                continue
        if mails:  # email-first gate (e.g. "Enter your email to get started")
            mails[0].fill(rec["email"] if rec else prof["email"])
            _fill_names(page, prof)
            _tick_terms(page)
            created = created or (None if rec else "")
            _click_submit(page, mails[0])
            continue
        link = next((e for e in _visible(page, "a, button") if SIGNUP_LINK.search((e.inner_text() or "")[:60])), None)
        if link:
            link.click()
            continue
        break
    if created is not None and not is_wall(page):
        _remember(url, prof["email"], created, job, "created")
        return True, f"created an account on {site_key(url)}"
    return False, "could not get past the sign-in / sign-up page"
