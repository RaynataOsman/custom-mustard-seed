"""Removed-role check: offline tests of what counts as closed (no network)."""
import sys, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import liveness

class R:
    def __init__(self, status=200, text="", url="https://x.test/job/1"):
        self.status_code, self.text, self.url, self.history = status, text, url, []

PAGES = {}
class S:
    def get(self, url, **kw):
        return PAGES.get(url, R(200, "<html><body>" + "A normal live job description. " * 200 + "</body></html>", url))
liveness.http = lambda: S()

def st(job):
    return liveness.check(job, ("somewhere.com",))[0]

bad = 0
def ok(name, got, want):
    global bad
    print(("PASS " if got == want else "FAIL ") + f"{name}: got {got}, want {want}")
    bad += got != want

live = "https://board.test/jobs/1"
PAGES["https://board.test/jobs/gone"] = R(404, "Not found")
PAGES["https://board.test/jobs/filled"] = R(200, "<p>Sorry, this position has been filled.</p>" + "x " * 2000)
PAGES["https://board.test/jobs/old"] = R(200, '<script type="application/ld+json">{"validThrough":"2020-01-01"}</script>' + "x " * 2000)
PAGES["https://board.test/jobs/captcha"] = R(200, "Please verify you are human (captcha)")
PAGES["https://board.test/jobs/forbidden"] = R(403, "")
PAGES["https://somewhere.com/jobs/123"] = R(404, "Page not found")
PAGES["https://employer.test/apply/9"] = R(404, "Page not found")
PAGES["https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4100000001"] = R(200, "<span>No longer accepting applications</span>" + "x " * 2000)

ok("live page", st({"url": live}), "open")
ok("board page 404", st({"url": "https://board.test/jobs/gone"}), "closed")
ok("says filled", st({"url": "https://board.test/jobs/filled"}), "closed")
ok("closing date passed", st({"url": "https://board.test/jobs/old"}), "closed")
ok("bot check is not closed", st({"url": "https://board.test/jobs/captcha"}), "blocked")
ok("403 is not closed", st({"url": "https://board.test/jobs/forbidden"}), "blocked")
ok("somewhere.com 404 is not closed", st({"url": "https://somewhere.com/jobs/123"}), None)
ok("employer link 404 while board live is not closed", st({"url": live, "apply_url": "https://employer.test/apply/9"}), "open")
ok("LinkedIn closed", st({"url": "https://www.linkedin.com/jobs/view/frontend-dev-at-acme-4100000001"}), "closed")
print("liveness ok" if not bad else f"{bad} liveness test(s) failed")
sys.exit(1 if bad else 0)
