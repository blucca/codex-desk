"""Fresh-home guidance reaches read-only history when project folders are gone.

DESK_TEST_TEMP=/workspace/temp DESK_TEST_EVIDENCE=/workspace/.private/home-read \
  DESK_CHROMIUM=/usr/bin/chromium python tests/browser_home_read_guidance.py
DESK_USE_INSTALLED=1 exercises installed assets instead of the source checkout.
All histories are synthetic; native calls are controlled list/read requests only.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from playwright.async_api import async_playwright


async def check(width, case, playwright, evidence):
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-home-read-') as temporary:
        folder = Path(temporary)
        home, current_project = folder / 'native-home', folder / 'current-project'
        home.mkdir(); current_project.mkdir()
        (home / 'config.toml').write_text('model="fixture-only"\n')
        settings = (home / 'config.toml').read_bytes()
        old = {'id': 'original-deleted-thread', 'cwd': str(folder / 'removed-project'),
               'name': 'Recover the old answer', 'modelProvider': 'fixture-provider',
               'turns': [{'id': 'original-turn', 'status': 'completed', 'items': [
                   {'id': 'original-answer', 'type': 'agentMessage',
                    'text': 'ORIGINAL ANSWER: keep the retry decision readable.'}]}]}
        current = {**old, 'id': 'current-thread', 'cwd': str(current_project),
                   'name': 'Current project work'}
        threads = {'unavailable': [old], 'mixed': [old, current], 'empty': []}[case]
        pristine = copy.deepcopy(threads)
        calls, http, errors, external = [], [], [], []
        desk = Desk('never-executed', home, folder / 'desk-state')

        class Catalog:
            def request(self, method, params):
                calls.append({'method': method, 'params': copy.deepcopy(params)})
                assert method in ('thread/list', 'thread/read'), method
                if method == 'thread/read':
                    assert params == {'threadId': old['id'], 'includeTurns': True}
                    return {'thread': copy.deepcopy(old)}
                return {'data': [{key: value for key, value in thread.items() if key != 'turns'}
                                 for thread in threads], 'nextCursor': None}

        desk.catalog = lambda: Catalog()
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        browser = None
        try:
            browser = await playwright.chromium.launch(
                executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = await browser.new_page(viewport={'width': width,
                                                    'height': 900 if width > 390 else 844})
            page.set_default_timeout(10_000)
            page.on('pageerror', lambda error: errors.append(str(error)))

            def requested(request):
                parsed = urlsplit(request.url)
                http.append({'path': parsed.path, 'method': request.method})
                if parsed.hostname != '127.0.0.1':
                    external.append(request.url)

            page.on('request', requested)
            await page.goto(f'http://127.0.0.1:{server.server_port}')
            await page.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            message = await page.locator('#home-status').inner_text()
            assert [call['method'] for call in calls] == ['thread/list']
            assert not any(call['method'] == 'POST' for call in http)
            assert await page.locator('#home-list .native-row').count() == (1 if case == 'mixed' else 0)
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            await page.screenshot(path=str(evidence / f'home-{case}-{width}.png'))
            if case == 'empty':
                guidance = 'No saved conversations' in message and 'Open a project' in message
            else:
                phrase = ('read the original conversations' if case == 'unavailable'
                          else 'read their original conversations')
                guidance = phrase in message and (case != 'unavailable' or 'only to resume' in message)
                # Follow the offered catalog entry entirely through the shipped UI.
                await page.locator('#home-browse').focus()
                await page.keyboard.press('Enter')
                await page.locator('#native-list .native-row').first.wait_for()
                row = page.locator('#native-list .native-row').filter(
                    has=page.get_by_text(old['name'], exact=True))
                await row.get_by_role('button', name='Read original conversation', exact=True).focus()
                await page.keyboard.press('Enter')
                await page.wait_for_function("$('history-reader').open && "
                    "$('history-reader-body').getAttribute('aria-busy')==='false'")
                assert 'ORIGINAL ANSWER' in await page.locator('#history-reader-body').inner_text()
                assert await page.evaluate('selected===null')
                assert await page.locator('#task').is_hidden()
                assert not desk.store.sessions()
                assert [call['method'] for call in calls] == ['thread/list', 'thread/list', 'thread/read']
                await page.keyboard.press('Escape')
                await page.wait_for_function("!$('history-reader').open && $('history').open")
                assert await row.get_by_role('button', name='Read original conversation', exact=True).evaluate(
                    '(node)=>node===document.activeElement')
            assert not any(call['method'] == 'POST' for call in http)
            assert not errors and not external
            assert threads == pristine and (home / 'config.toml').read_bytes() == settings
            assert not desk.store.sessions()
            result = {'viewport': width, 'case': case, 'guidance_correct': guidance,
                      'visible_home_message': message, 'native_calls': calls,
                      'http_calls': http, 'javascript_errors': errors,
                      'external_requests': external, 'native_model_turns': 0,
                      'imported_bindings': 0}
            (evidence / f'acceptance-{case}-{width}.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps({'viewport': width, 'case': case, 'guidance_correct': guidance,
                              'native_calls': len(calls), 'native_model_turns': 0}), flush=True)
            return result
        finally:
            if browser is not None:
                await browser.close()
            server.shutdown(); server.server_close(); worker.join(timeout=5)
            desk.close(); desk.store.db.close()


async def main():
    evidence = Path(os.environ.get('DESK_TEST_EVIDENCE',
                                   str(Path(os.environ['DESK_TEST_TEMP']) / 'home-read-evidence')))
    evidence.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        results = [await check(width, case, playwright, evidence)
                   for width in (1250, 390) for case in ('unavailable', 'mixed', 'empty')]
    failures = [f"{row['case']} at {row['viewport']}" for row in results if not row['guidance_correct']]
    assert not failures, 'Home guidance did not expose the read-only original path: ' + ', '.join(failures)
    print(json.dumps({'home_original_read_guidance': 'PASS', 'cases': len(results),
                      'native_model_turns': 0, 'imported_bindings': 0}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
