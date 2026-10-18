"""A site showing a 403 / human-check page: detect it, stop the board, rest it. Never solve or dodge it."""
import datetime, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render, pipeline

bad = 0


def check(name, cond):
    global bad
    print("PASS" if cond else "FAIL", name)
    bad += 0 if cond else 1


class Resp:
    def __init__(self, s): self.status = s


class Page:
    def __init__(self, title="", body="", captcha=False):
        self._t, self._b, self._c = title, body, captcha

    def title(self): return self._t
    def inner_text(self, sel): return self._b
    def query_selector(self, sel): return object() if self._c else None


g = render.blocked_page
check("403 title", g(Page("403 Forbidden", "403 Forbidden\nTransaction ID: 99edb8599bbee3e9")))
check("403 status alone", g(Page("Jobs", "x" * 3000), Resp(403)))
check("429 status", g(Page("Jobs", "x" * 3000), Resp(429)))
check("transaction id in a short page", g(Page("", "Request blocked. Transaction ID: abc")))
check("captcha frame on a short page", g(Page("Hold on", "Please wait", captcha=True)))
check("cloudflare title", g(Page("Access denied", "")))
check("normal listing page is fine", not g(Page("Job listings", "Developer jobs in Berlin. " * 200), Resp(200)))
check("long page mentioning captcha is fine", not g(Page("Careers", ("We build things. " * 200) + " captcha"), Resp(200)))
check("pop-up laid over a long normal page", g(Page("Job listings", ("Developer jobs in Berlin. " * 300) + " Suspicious Activity Detected! You might experience slowness while browsing, as you are being validated for suspicious bot activity."), Resp(200)))
check("empty/no response", not g(Page("Jobs", "x" * 2000)))

now = datetime.datetime.now()
h = lambda hrs: (now - datetime.timedelta(hours=hrs)).isoformat(timespec="seconds")
ok = lambda hrs: {"health": "ok", "started": h(hrs)}
bl = lambda hrs: {"health": "blocked", "started": h(hrs)}
check("no runs -> scan", pipeline.pause_hours([]) == 0)
check("healthy last run -> scan", pipeline.pause_hours([ok(1)]) == 0)
check("blocked 2 h ago -> rest ~22 h", 21 < pipeline.pause_hours([bl(2), ok(30)]) < 23)
check("blocked 25 h ago -> try again", pipeline.pause_hours([bl(25), ok(50)]) == 0)
check("3 blocked in a row -> rest 72 h", 45 < pipeline.pause_hours([bl(25), bl(50), bl(75)]) < 48)
check("old block, newer ok -> scan", pipeline.pause_hours([ok(1), bl(5)]) == 0)
print("FAILED" if bad else "block handling ok")
sys.exit(1 if bad else 0)


