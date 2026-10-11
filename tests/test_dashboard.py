"""Browser regressions with synthetic API responses; never touches personal jobs or services.
Run: python tests/test_dashboard.py (requires Playwright and installed Chrome).
"""
import asyncio, json, pathlib, sys, threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'data' / 'test-deps'))
from playwright.async_api import async_playwright

class Static(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'ui'), **kwargs)
    def log_message(self, *args): pass

async def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Static)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    overview = dict(counts={'ready': 3, 'approved': 1, 'needs_you': 2}, applied_week=8, contacts_pending=4,
                    boards=[dict(board='Acme "Jobs"', never_run=True)], not_scraped=[])
    contact = dict(id=1, name="Pat O'Neil", kind='recruiter', company='Acme', title='Designer',
                   note='Hi Pat, I\'m interested in your "Design" role.', followup="Let's talk.", url='https://example.com', sent=0)
    responses = {'overview': overview, 'jobs': [], 'contacts': [contact], 'runs': [],
        'features': {'referrals': True}, 'presets': {'families': {'design': ['ONE']}, 'presets': {}},
        'profile': dict(fields={'first_name': 'Test'}, rates={}, international_only=True,
                        work_window='07:00-23:00', notion_database='', resume_copies='out'),
        'keys': {}, 'config': {'text': '{}'},
        'health': dict(searxng=False, notion='ok', pdf='LibreOffice', ollama=None, masters=['design_ONE.docx'], resume_copies='out')}
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='chrome', headless=True)
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors, calls = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        delay_settings = False
        fail_contacts = False
        async def route(r):
            key = r.request.url.split('/api/')[1].split('?')[0]
            calls.append((key, r.request.post_data))
            if key == 'health' or (delay_settings and key == 'profile'):
                await asyncio.sleep(.7)
            if key == 'contacts' and fail_contacts:
                await r.fulfill(status=500, json={'error': 'Fixture connection failed'})
            elif key == 'run':
                await r.fulfill(json={'ok': True, 'id': 'test'})
            else:
                await r.fulfill(json=responses.get(key, {}))
        await page.route('**/api/**', route)
        # Simulate an already-running server that has no routes for new assets.
        await page.route('**/theme.css', lambda route: route.fulfill(status=404))
        await page.route('**/seed.svg', lambda route: route.fulfill(status=404))
        await page.goto(base)
        assert await page.locator('.metrics').evaluate('(el)=>getComputedStyle(el).display') == 'grid'
        assert await page.locator('.brand svg').count() == 1
        assert await page.locator('link[rel=stylesheet]').count() == 0
        await page.locator('#view[aria-busy=false]').wait_for()
        # Settings is useful before slow health completes.
        await page.get_by_role('button', name='Settings', exact=True).click()
        await page.locator('#p_win').wait_for(timeout=1500)
        assert 'Checking your connections' in await page.locator('#health-status').inner_text()
        await page.get_by_role('button', name='Referrals', exact=False).filter(has=page.locator('.badge')).click()
        await page.get_by_text("Pat O'Neil", exact=False).first.wait_for()
        await page.wait_for_timeout(900)
        assert await page.locator('#page-title').inner_text() == 'Referrals'
        assert await page.locator('#p_win').count() == 0
        # Also leave while the settings data itself is pending.
        delay_settings = True
        await page.get_by_role('button', name='Settings', exact=True).click()
        await page.locator('#tabs button').filter(has_text='Referrals').click()
        await page.wait_for_timeout(900)
        assert await page.locator('#p_win').count() == 0
        assert "Pat O'Neil" in await page.locator('#view').inner_text()
        delay_settings = False
        # Quotes and apostrophes survive event attributes.
        await page.evaluate('window.copy = async text => { window.copied = text }; window.copyOpen = async (text,url) => {window.copied=text}')
        await page.get_by_role('button', name='Copy note + open profile').click()
        assert await page.evaluate('window.copied') == contact['note']
        await page.get_by_role('button', name='Copy follow-up').click()
        assert await page.evaluate('window.copied') == contact['followup']
        await page.get_by_role('button', name='Boards', exact=True).click()
        await page.get_by_role('button', name='Run', exact=True).click()
        await page.wait_for_function("document.querySelector('#page-title').textContent==='Runs'")
        assert any(k == 'run' and json.loads(body)['arg'] == 'Acme "Jobs"' for k, body in calls)
        # Hash navigation / history.
        await page.evaluate("location.hash='applied'")
        await page.wait_for_function("document.querySelector('#page-title').textContent==='Applied'")
        await page.go_back()
        await page.wait_for_function("document.querySelector('#page-title').textContent==='Runs'")
        # Failure is visible and retry recovers.
        fail_contacts = True
        await page.evaluate("go('referrals')")
        await page.get_by_role('alert').wait_for()
        assert 'Fixture connection failed' in await page.locator('#view').inner_text()
        fail_contacts = False
        await page.get_by_role('button', name='Try again', exact=True).click()
        await page.get_by_text("Pat O'Neil", exact=False).first.wait_for()
        # Theme persistence, all views and responsive overflow.
        await page.locator('#theme-toggle').click()
        theme = await page.evaluate('document.documentElement.dataset.theme')
        await page.reload()
        assert await page.evaluate('document.documentElement.dataset.theme') == theme
        for key in ['add','review','needs','applied','referrals','found','boards','run','settings']:
            await page.evaluate('(key)=>go(key)', key)
            await page.locator('#view[aria-busy=false]').wait_for()
            assert await page.get_by_role('alert').count() == 0, key
        await page.evaluate("go('review');document.documentElement.dataset.theme='light';syncTheme()")
        await page.locator('#view[aria-busy=false]').wait_for()
        await page.screenshot(path=str(ROOT/'out/dashboard-light.png'), full_page=True)
        await page.evaluate("document.documentElement.dataset.theme='dark';syncTheme()")
        await page.screenshot(path=str(ROOT/'out/dashboard-dark.png'), full_page=True)
        await page.set_viewport_size({'width':390,'height':844})
        for key in ['add','referrals','boards','settings']:
            await page.evaluate('(key)=>go(key)', key)
            await page.locator('#view[aria-busy=false]').wait_for()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'overflow: {key}'
        await page.screenshot(path=str(ROOT/'out/dashboard-mobile.png'), full_page=True)
        assert not errors, errors
        await browser.close()
    server.shutdown()
    print('PASS: navigation races, settings, quotes, history, error recovery, themes, 9 views, mobile; no JS errors')

if __name__ == '__main__': asyncio.run(main())
