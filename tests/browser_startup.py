"""Loopback startup recovery and same-conversation return; no native/model calls.

DESK_TEST_TEMP=/your/workspace/temp DESK_CHROMIUM=/path/to/chromium \
  python tests/browser_startup.py
Set DESK_USE_INSTALLED=1 to exercise an installed release instead of source.
"""
import asyncio
from collections import Counter
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
from codex_desk.drafts import load_draft, save_draft
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-startup-') as temporary:
        folder = Path(temporary)
        desk = Desk('never-executed', folder / 'home', folder / 'state')
        threads = {}
        for identifier in ('a', 'b', 'archived', 'active-archived'):
            project = folder / ('project-' + identifier)
            project.mkdir()
            desk.store.create(str(project), 'default', identifier=identifier,
                              name='Project ' + identifier.upper())
            desk.store.update(identifier, status='running' if identifier == 'active-archived' else 'ready',
                              thread_id='native-' + identifier, thread_saved=1)
            if 'archived' in identifier:
                desk.store.archive(identifier, True)
            save_draft(desk.store, identifier, 'Prepared next task for ' + identifier, 'plan', 0)
            threads[identifier] = {'id': 'native-' + identifier, 'cwd': str(project),
                'turns': [{'id': 'prior-turn-' + identifier, 'items': [
                    {'id': 'command-' + identifier, 'type': 'commandExecution',
                     'command': 'existing-verification', 'aggregatedOutput': '4 tests passed for ' + identifier,
                     'exitCode': 0}]}]}

        http_calls, open_calls, errors, results = [], [], [], []
        controls = {}

        def controlled_open(identifier):
            open_calls.append(identifier)
            if controls.get('permanent_open') == identifier:
                raise RuntimeError('Saved Codex conversation unavailable (no rollout found). Restore its history.')
            if controls.get('hold_open') == identifier:
                controls['open_entered'].set()
                assert controls['open_release'].wait(15), 'Held saved open was not released'
            return {'thread': threads[identifier], 'model': 'fixture', 'modelProvider': 'fixture'}

        desk.open = controlled_open
        ordinary_handler = handler(desk)

        class ControlledHandler(ordinary_handler):
            def do_GET(self):
                path = urlsplit(self.path).path
                http_calls.append(('GET', path))
                if path == '/api/state':
                    if controls.pop('fail_state', False):
                        return self.reply({'error': 'Fixture state temporarily unavailable'}, 503)
                    if controls.get('hold_state'):
                        controls['state_entered'].set()
                        assert controls['state_release'].wait(15), 'Held state was not released'
                super().do_GET()

            def do_POST(self):
                path = urlsplit(self.path).path
                http_calls.append(('POST', path))
                if path == '/api/open' and controls.get('fail_open'):
                    open_calls.append(controls.pop('fail_open'))
                    return self.reply({'error': 'Fixture saved conversation temporarily unavailable'}, 503)
                super().do_POST()

        server = ThreadingHTTPServer(('127.0.0.1', 0), ControlledHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                    headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                try:
                    async def page_for(last='a', **settings):
                        controls.clear()
                        controls.update(settings)
                        context = await browser.new_context(viewport={'width': 390, 'height': 844})
                        await context.add_init_script('localStorage.setItem("codex-desk-session", ' + json.dumps(last) + ');')
                        page = await context.new_page()
                        page.set_default_timeout(9_000)
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        await page.goto(url)
                        return context, page

                    async def restored(page, identifier):
                        await page.wait_for_function("id => selected === id && !opening && !$('task').hidden",
                                                     arg=identifier)
                        assert await page.locator('#prompt').input_value() == 'Prepared next task for ' + identifier
                        assert await page.locator('#turn-mode').input_value() == 'plan'
                        if not await page.locator('#activity details').first.evaluate('d => d.open'):
                            await page.locator('#activity summary').first.click()
                        assert '4 tests passed for ' + identifier in await page.locator('#activity').inner_text()
                        assert await page.evaluate('nativeThreadId') == 'native-' + identifier
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')

                    async def case(name, run):
                        try:
                            await run()
                            results.append({'check': name, 'passed': True})
                        except Exception as failure:
                            results.append({'check': name, 'passed': False,
                                            'error': str(failure).splitlines()[0] if str(failure) else type(failure).__name__})
                        finally:
                            for key in ('state_release', 'open_release'):
                                if key in controls:
                                    controls[key].set()
                            for context in list(browser.contexts):
                                await context.close()
                        print(json.dumps(results[-1]), flush=True)

                    async def state_retry():
                        entered, release = threading.Event(), threading.Event()
                        _, page = await page_for(fail_state=True, hold_state=True,
                                                state_entered=entered, state_release=release)
                        await page.locator('#error:not([hidden])').wait_for()
                        assert await asyncio.to_thread(entered.wait, 8), 'Initial state failure was never retried'
                        assert await page.locator('#error').is_visible(), 'Error cleared before state recovery'
                        controls['hold_state'] = False
                        release.set()
                        await restored(page, 'a')
                        assert await page.locator('#error').is_hidden()

                    async def open_retry():
                        entered, release = threading.Event(), threading.Event()
                        _, page = await page_for(fail_open='a', hold_open='a',
                                                open_entered=entered, open_release=release)
                        await page.locator('#error:not([hidden])').wait_for()
                        assert await asyncio.to_thread(entered.wait, 8), 'Failed saved conversation was never retried'
                        assert 'Fixture saved conversation' in await page.locator('#error').inner_text()
                        assert await page.locator('#error').is_visible(), 'Error cleared before saved open recovery'
                        controls.pop('hold_open')
                        release.set()
                        await restored(page, 'a')
                        assert await page.locator('#error').is_hidden()

                    async def superseded_return():
                        entered, release = threading.Event(), threading.Event()
                        before = Counter(open_calls)
                        _, page = await page_for(fail_open='a', hold_open='a',
                                                open_entered=entered, open_release=release)
                        await page.locator('#error:not([hidden])').wait_for()
                        assert await asyncio.to_thread(entered.wait, 8), 'Saved open was never retried'
                        await page.get_by_role('button', name='Project B', exact=False).first.click()
                        await restored(page, 'b')
                        controls.pop('hold_open')
                        release.set()
                        await page.wait_for_timeout(3_300)
                        await restored(page, 'b')
                        assert await page.evaluate('localStorage.getItem("codex-desk-session")') == 'b'
                        assert Counter(open_calls)['a'] - before['a'] == 2, 'Superseded restore retried again'

                    async def unrelated_error():
                        entered, release = threading.Event(), threading.Event()
                        _, page = await page_for(last='not-a-session', fail_state=True, hold_state=True,
                                                state_entered=entered, state_release=release)
                        await page.locator('#error:not([hidden])').wait_for()
                        assert await asyncio.to_thread(entered.wait, 8), 'Initial state failure was never retried'
                        await page.evaluate('error(new Error("Fixture unrelated user error"))')
                        controls['hold_state'] = False
                        release.set()
                        await page.wait_for_function('state.profiles.length > 0')
                        await page.wait_for_timeout(1_000)
                        assert await page.locator('#error').is_visible()
                        assert await page.locator('#error').inner_text() == 'Fixture unrelated user error'

                    async def archive_eligibility():
                        before = len(open_calls)
                        context, page = await page_for(last='archived')
                        await page.wait_for_function('state.profiles.length > 0')
                        await page.wait_for_timeout(1_000)
                        assert await page.evaluate('selected') is None
                        assert len(open_calls) == before, 'Idle archive was automatically reopened'
                        await context.close()
                        _, page = await page_for(last='active-archived')
                        await restored(page, 'active-archived')

                    async def permanent_rejection():
                        before = Counter(open_calls)
                        _, page = await page_for(permanent_open='a')
                        await page.locator('#error:not([hidden])').wait_for()
                        state_before = sum(path == '/api/state' for _, path in http_calls)
                        await page.wait_for_timeout(5_000)
                        assert Counter(open_calls)['a'] - before['a'] == 1, 'Permanent native rejection was automatically retried'
                        assert sum(path == '/api/state' for _, path in http_calls) > state_before, 'Ordinary state polling stopped'
                        assert await page.locator('#error').is_visible()
                        assert 'no rollout found' in await page.locator('#error').inner_text()
                        assert await page.locator('#task').is_hidden()
                        assert desk.store.get('a')['thread_id'] == 'native-a'

                    await case('initial state retry and exact saved return', state_retry)
                    await case('saved open retry preserves error and preparation', open_retry)
                    await case('manual selection supersedes delayed startup return', superseded_return)
                    await case('recovery preserves an unrelated user error', unrelated_error)
                    await case('saved return retains archive eligibility', archive_eligibility)
                    await case('permanent native rejection stays explicit without repeated opens', permanent_rejection)
                    for identifier in threads:
                        assert load_draft(desk.store, identifier)['text'] == 'Prepared next task for ' + identifier
                    assert not errors, errors
                    assert not desk.runtimes, 'Startup recovery must not create a native runtime in this fixture'
                    assert not any(path in ('/api/turn', '/api/sessions', '/api/import', '/api/followups/send')
                                   for _, path in http_calls), http_calls
                    print(json.dumps({'results': results, 'openCalls': open_calls,
                        'stateRequests': sum(path == '/api/state' for _, path in http_calls),
                        'nativeModelTurns': 0, 'draftsIntact': True, 'viewportWidth': 390,
                        'javascriptErrors': errors}), flush=True)
                    assert all(result['passed'] for result in results), results
                finally:
                    await browser.close()
        finally:
            for key in ('state_release', 'open_release'):
                if key in controls:
                    controls[key].set()
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()
            desk.close()
            desk.store.db.close()


if __name__ == '__main__':
    asyncio.run(check())
