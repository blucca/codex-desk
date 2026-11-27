"""Explicit older indexing, durable cancellation and project-complete recall.

DESK_TEST_TEMP=/workspace/temp DESK_CHROMIUM=/usr/bin/chromium \\
    python tests/browser_history_older.py
DESK_OLDER_CASES and DESK_OLDER_WIDTHS select comma-separated acceptance paths.
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
from codex_desk.drafts import load_draft, save_draft
from playwright.async_api import async_playwright


async def check(width, case, playwright, evidence):
    root = Path(os.environ['DESK_TEST_TEMP'])
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-history-older-') as temporary:
        folder = Path(temporary)
        home = folder / 'native-home'; home.mkdir()
        (home / 'config.toml').write_text('model="fixture-only"\n')
        original_config = (home / 'config.toml').read_bytes()
        threads = []
        for position in range(1, 261):
            threads.append({'id': f'native-{position:03}', 'cwd': str(folder / f'missing-project-{position:03}'),
                'name': f'Conversation {position}', 'modelProvider': 'fixture', 'updatedAt': 1795601000-position,
                'turns': [{'id': f'turn-{position}', 'status': 'completed', 'items': [
                    {'id': f'answer-{position}', 'type': 'agentMessage',
                     'text': ('OLDER-230 exact retry budget. ' if position == 230 else '') +
                             f'Original evidence decision {position}.'}]}]})
        originals = copy.deepcopy(threads)
        calls, http, errors, external = [], [], [], []
        entered, release = threading.Event(), threading.Event()
        hold = {'enabled': case != 'older-return'}
        cursors = {}
        def token(offset):
            value = f'native / opaque+页 ={offset}'; cursors[value] = offset; return value

        class Catalog:
            def request(self, method, params):
                calls.append({'method': method, 'params': copy.deepcopy(params)})
                assert method in ('thread/list', 'thread/read'), method
                if method == 'thread/list':
                    assert params['modelProviders'] == [] and params['sortKey'] == 'updated_at'
                    offset = cursors[params['cursor']] if 'cursor' in params else 0
                    if case == 'cancel-list' and hold['enabled'] and offset == 200:
                        entered.set(); assert release.wait(30), 'Unreleased native list'
                    end = min(offset + params['limit'], len(threads))
                    return {'data': [{k: v for k, v in t.items() if k != 'turns'} for t in threads[offset:end]],
                            'nextCursor': token(end) if end < len(threads) else None}
                if case == 'cancel-read' and hold['enabled'] and params['threadId'] == 'native-203':
                    entered.set(); assert release.wait(30), 'Unreleased native read'
                assert params['includeTurns'] is True
                return {'thread': copy.deepcopy(next(t for t in threads if t['id'] == params['threadId']))}

        def launch():
            desk = Desk('never-executed', home, folder / 'state')
            desk.catalog = lambda: Catalog()
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk))
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            return desk, server, worker

        def stop(desk, server, worker):
            server.shutdown(); server.server_close(); worker.join(5)
            desk.close(); desk.store.db.close()

        desk, server, worker = launch()
        saved = desk.store.create(str(folder / 'prepared-project'), 'default',
                                 identifier='saved-work', name='Retained preparation')
        desk.store.update(saved, thread_id='saved-native', status='saved', thread_saved=1, name_pending=0)
        save_draft(desk.store, saved, 'Retain this unsent Plan.', 'plan', 0)
        saved_sessions, saved_draft = desk.store.sessions(), load_draft(desk.store, saved)
        browser = None
        try:
            browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = await browser.new_page(viewport={'width': width, 'height': 900 if width > 390 else 844})
            page.set_default_timeout(15000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            def requested(request):
                parsed = urlsplit(request.url)
                http.append({'path': parsed.path, 'method': request.method, 'post': request.post_data,
                             'query': parsed.query})
                if parsed.hostname != '127.0.0.1': external.append(request.url)
            page.on('request', requested)
            async def open_recall():
                await page.goto(f'http://127.0.0.1:{server.server_port}')
                await page.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
                await page.locator('#home-content').click()
                await page.wait_for_function("!$('recall-index').disabled")
            async def submit(q):
                await page.locator('#recall-query').fill(q)
                await page.locator('#recall-query').press('Enter')
                await page.wait_for_function("!$('recall-search').disabled")
            async def completed():
                await page.wait_for_function("$('recall-index-status').textContent.includes('scan completed')")
                await page.wait_for_function("!$('recall-index').disabled")
            def searches(): return sum(row['path'] == '/api/recall' for row in http)

            await open_recall()
            assert not any(row['method'] == 'POST' for row in http)
            assert not any(row['method']=='thread/read' for row in calls)
            assert desk.native_index.stats()['indexed_threads'] == 0, 'Reopen/status automatically indexed native history'
            assert await page.locator('#recall-index-older').is_hidden()
            await page.locator('#recall-index').click(); await completed()
            assert desk.native_index.stats()['indexed_threads'] == 200
            assert len(desk.native_index.projects()) == 200
            assert await page.locator('#recall-project option').count() == 202
            assert await page.locator('#recall-index-older').is_visible()
            assert desk.recall('OLDER-230')['total'] == 0

            if case == 'older-return':
                await submit('original evidence decision')
                await page.locator('#recall-next').click()
                await page.wait_for_function("$('recall-summary').textContent.includes('31–60') && !$('recall-search').disabled")
                kept_ids = await page.locator('.recall-result').evaluate_all('(rows)=>rows.map(n=>n.dataset.thread)')
                before_searches = searches()
                await page.locator('#recall-index-older').click(); await completed()
                await page.wait_for_function("$('recall-summary').textContent.includes('260') && !$('recall-search').disabled")
                assert searches() == before_searches + 1
                assert await page.locator('.recall-result').evaluate_all('(rows)=>rows.map(n=>n.dataset.thread)') == kept_ids
                assert '31–60' in await page.locator('#recall-summary').inner_text()
            else:
                await submit('OLDER-230')
                await page.locator('#recall-index-older').click()
                assert await asyncio.to_thread(entered.wait, 10), 'Native cancellation boundary not reached'
                await page.locator('#recall-index-cancel').click()
                assert desk.history_scanner.cancelled.is_set()
                release.set()
                await asyncio.to_thread(desk.history_scanner.worker.join, 10)
                await page.wait_for_function("$('recall-index-status').textContent.includes('Indexing cancelled')")
                assert desk.history_scanner.status()['seen'] == (3 if case == 'cancel-read' else 0)
                pending = desk.history_scanner._load()['continuation']['pending']
                assert [row['id'] for row in pending] == [f'native-{i:03}' for i in range(204 if case == 'cancel-read' else 201, 231)]
                assert await page.locator('.recall-result').count() == 0
                await page.wait_for_timeout(900)
                before_restart = len(calls)
                stop(desk, server, worker)
                desk, server, worker = launch(); hold['enabled'] = False
                await open_recall()
                await page.wait_for_timeout(900)
                assert all(row['method']=='thread/list' and 'cursor' not in row['params']
                           for row in calls[before_restart:]), 'Restart consumed saved indexing progress'
                before_resume = len(calls)
                assert await page.locator('#recall-index-retry').inner_text() == 'Continue indexing'
                assert await page.locator('#recall-index-older').is_visible()
                await submit('OLDER-230')
                assert await page.locator('.recall-result').count() == 0
                await page.locator('#recall-index-retry').click(); await completed()
                await page.wait_for_function("$('recall-results').children.length===1 && !$('recall-search').disabled")
                resumed = calls[before_resume:]
                expected = list(range(204 if case == 'cancel-read' else 201, 231))
                assert [row['params']['threadId'] for row in resumed[:len(expected)]] == [f'native-{i:03}' for i in expected]
                assert resumed[len(expected)]['method'] == 'thread/list'
                assert resumed[len(expected)]['params']['cursor'] == token(230)

            assert desk.native_index.stats()['indexed_threads'] == 260
            assert len(desk.native_index.projects()) == 260
            await page.wait_for_function("$('recall-project').options.length===262")
            assert await page.locator('#recall-index-older').is_hidden()
            await page.locator('#recall-project').select_option(threads[229]['cwd'])
            await submit('OLDER-230')
            assert await page.locator('.recall-result').count() == 1
            assert await page.locator('.recall-result').get_attribute('data-thread') == 'native-230'
            row = page.locator('.recall-result')
            await row.evaluate('(n)=>globalThis.returnedRow=n')
            await page.locator('.recall-read').focus(); await page.keyboard.press('Enter')
            await page.wait_for_function("$('history-reader-body').getAttribute('aria-busy')==='false'")
            assert 'OLDER-230 exact retry budget.' in await page.locator('#history-reader-body').inner_text()
            assert desk.runtimes == {}, 'Read-only evidence navigation started native work'
            await page.keyboard.press('Escape')
            assert await row.evaluate('(n)=>n===globalThis.returnedRow')
            assert await page.locator('.recall-read').evaluate('(n)=>n===document.activeElement')
            assert await page.locator('#recall-query').input_value() == 'OLDER-230'
            assert await page.locator('#recall-project').input_value() == threads[229]['cwd']
            assert desk.store.sessions() == saved_sessions and load_draft(desk.store, saved) == saved_draft
            assert await page.evaluate('selected===null && generation===0')
            assert not any(row['method'] == 'POST' and row['path'] not in ('/api/history/index', '/api/history/index/cancel') for row in http)
            assert not errors and not external
            assert threads == originals and (home / 'config.toml').read_bytes() == original_config
            assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && $('recall').scrollWidth<=$('recall').clientWidth")
            data = {'viewport': width, 'case': case, 'passed': True, 'indexed': 260, 'projects': 260,
                    'http': http, 'native': calls, 'errors': errors, 'external': external}
            (evidence / f'{case}-{width}.json').write_text(json.dumps(data, indent=2) + '\n')
            await page.screenshot(path=str(evidence / f'{case}-{width}.png'))
            print(json.dumps({'viewport': width, 'case': case, 'passed': True, 'indexed': 260}), flush=True)
            return data
        except Exception:
            if browser is not None:
                await page.screenshot(path=str(evidence / f'failure-{case}-{width}.png'))
                (evidence / f'failure-{case}-{width}.json').write_text(json.dumps({'native': calls, 'http': http,
                    'errors': errors, 'page': await page.locator('body').inner_text()}, indent=2) + '\n')
            raise
        finally:
            release.set()
            if browser is not None: await browser.close()
            stop(desk, server, worker)


async def main():
    root = Path(os.environ['DESK_TEST_TEMP']); root.mkdir(parents=True, exist_ok=True)
    evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(root / 'history-older-evidence')))
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    cases = os.environ.get('DESK_OLDER_CASES', 'older-return,cancel-read,cancel-list').split(',')
    widths = [int(w) for w in os.environ.get('DESK_OLDER_WIDTHS', '1250,390').split(',')]
    async with async_playwright() as playwright:
        results = [await check(width, case, playwright, evidence) for width in widths for case in cases]
    print(json.dumps({'older_history': 'PASS', 'checks': len(results)}), flush=True)


if __name__ == '__main__': asyncio.run(main())
