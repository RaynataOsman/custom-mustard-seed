"""Run: python3 tests/test_email_alerts.py  (no network)"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import email_alerts, util

BOARD = {"name": "Email job alerts (Gmail)", "kind": "email_alerts"}

INDEED = """<html><body><table>
<tr><td><a href="https://www.indeed.com/rc/clk?jk=abc123&fccid=1">Senior Shopify Developer</a><br>
<span>Acme Stores</span><br><span>Remote</span></td></tr>
<tr><td><a href="https://www.indeed.com/viewjob?jk=def456">Front End Engineer</a><br>
<span>Globex</span><br><span>Cape Town</span></td></tr>
<tr><td><a href="https://www.indeed.com/rc/clk?jk=ghi789">Web Developer (React)</a><br>
<span>Initech</span><br><span>Remote, South Africa</span></td></tr>
<tr><td><a href="https://www.indeed.com/m/unsubscribe?x=1">Unsubscribe</a>
<a href="https://www.indeed.com/privacy">Privacy</a>
<a href="https://www.indeed.com/jobs?q=dev">See more jobs</a></td></tr>
</table></body></html>"""

LINKEDIN = """<html><body><table><tr><td>
<a href="https://www.linkedin.com/comm/redirect?url=https%3A%2F%2Fwww.linkedin.com%2Fcomm%2Fjobs%2Fview%2F123456789%3FtrackingId%3Dxyz&amp;trk=eml">Full Stack Developer</a>
<p>Pied Piper</p><p>Johannesburg, South Africa</p></td></tr>
<tr><td><a href="https://www.linkedin.com/e/v2/unsubscribe?x=1">Unsubscribe</a>
<a href="https://www.linkedin.com/help">Help</a></td></tr></table></body></html>"""

SUBSTACK = """<html><body>
<h2>This week in African remote jobs</h2>
<p><a href="https://example-co.com/careers/senior-backend-engineer">Senior Backend Engineer at ExampleCo</a> - Remote, Africa</p>
<p><a href="https://startup.io/jobs/product-designer">Product Designer, Startup.io</a> - Nairobi</p>
<p><a href="https://twitter.com/share?x=1">Share</a>
<a href="https://news.substack.com/subscribe">Subscribe now</a>
<a href="https://news.substack.com/action/unsubscribe?x">Unsubscribe</a>
<a href="https://news.substack.com/p/privacy">Privacy policy</a>
<a href="mailto:hi@x.com">Contact</a></p></body></html>"""


def titles(jobs):
    return [j["title"] for j in jobs]


def check(jobs, n, name):
    assert len(jobs) == n, f"{name}: expected {n} jobs, got {len(jobs)}: {titles(jobs)}"
    for j in jobs:
        assert j["title"].strip(), f"{name}: empty title"
        low = (j["title"] + j["url"]).lower()
        assert "unsubscribe" not in low and "privacy" not in low, f"{name}: junk link {j}"
        assert j["source_email"] == name and j["posted_at"] == "2026-10-10"


ind = email_alerts.parse_alert_html(BOARD, INDEED, "indeed", "2026-10-10")
check(ind, 3, "indeed")
assert ind[0]["company"] == "Acme Stores" and ind[0]["location"] == "Remote", ind[0]

li = email_alerts.parse_alert_html(BOARD, LINKEDIN, "linkedin", "2026-10-10")
check(li, 1, "linkedin")
assert li[0]["url"] == "https://www.linkedin.com/jobs/view/123456789", li[0]["url"]

sub = email_alerts.parse_alert_html(BOARD, SUBSTACK, "substack", "2026-10-10")
check(sub, 2, "substack")

# missing credentials
util.load_keys = lambda: {}
try:
    email_alerts.fetch(BOARD, {}, print)
    raise AssertionError("expected RuntimeError")
except RuntimeError as e:
    assert str(e) == "Gmail not connected: add GMAIL_ADDRESS and GMAIL_APP_PASSWORD in Settings", str(e)

# INBOX opened read-only (fake IMAP)
calls = {}
class FakeIMAP:
    def __init__(self, host, **kw): calls["host"] = host
    def login(self, a, p): calls["login"] = (a, p)
    def select(self, folder, readonly=False):
        calls["select"] = (folder, readonly); return "OK", [b"0"]
    def search(self, *a): return "OK", [b""]
    def logout(self): pass
email_alerts.imaplib.IMAP4_SSL = FakeIMAP
util.load_keys = lambda: {"GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop"}
assert email_alerts.fetch(BOARD, {}, lambda *a: None) == []
assert calls["select"] == ("INBOX", True), calls
assert calls["login"][1] == "abcdefghijklmnop"
print(email_alerts.test_connection())
print("ALL TESTS PASSED")
