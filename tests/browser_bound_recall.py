"""Explicit index recovers answers added outside an already-bound Desk session.

DESK_USE_INSTALLED=1 selects the installed package. Histories are controlled;
no native executable, model turn, or external request is used.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, ThreadingHTTPServer, handler
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright


async def check(width, cached, playwright, evidence):
    root = Path(os.environ['DESK_TEST_TEMP']); root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-bound-recall-') as temporary:
        folder = Path(temporary)
        project, home = folder / 'project', folder / 'home'
        project.mkdir(); home.mkdir()
        (home / 'config.toml').write_text('model="controlled-only"\n')
        (home / 'auth.json').write_text('{"synthetic":"unchanged"}\n')
        settings = {p.name: p.read_bytes() for p in home.iterdir()}
        old = {'id': 'original-thread', 'cwd': str(project), 'name': 'Existing decision',
               'modelProvider': 'fixture', 'updatedAt': 1000, 'turns': [
                   {'id': 'old-turn', 'status': 'completed', 'items': [
                       {'id': 'old-item', 'type': 'agentMessage', 'text': 'Old preserved evidence'}]}]}
        fresh = copy.deepcopy(old); fresh['updatedAt'] = 1010
        fresh['turns'].append({'id': 'outside-turn', 'status': 'completed', 'items': [
            {'id': 'outside-item', 'type': 'agentMessage',
             'text': 'Fresh outside decision: retry budget remains three attempts.'}]})
        original = copy.deepcopy(fresh)
        calls, requests, errors = [], [], []
        desk = Desk('never-executed', home, folder / 'state')
        saved = desk.store.create(str(project), 'default', name='Existing decision')
        desk.store.update(saved, thread_id=old['id'], status='saved', thread_saved=1)
        desk.store.recall_snapshot(saved, old)
        save_draft(desk.store, saved, 'Unsent retained Plan', 'plan', 0)
        add_followup(desk.store, saved, 'Unsent retained next check')
        prep = (desk.store.sessions(), load_draft(desk.store, saved), followup_snapshot(desk.store, saved))
        events = desk.store.events(saved)
        # Model a pre-fix scan: native cache is current, but the bound Desk
        # activity still contains only the old snapshot and hides native hits.
        if cached: desk.native_index.replace_snapshot(fresh)

        class Catalog:
            def request(self, method, params):
                calls.append({'method': method, 'params': copy.deepcopy(params)})
                assert method in ('thread/list', 'thread/read'), method
                if method == 'thread/list':
                    return {'data': [{k: v for k, v in fresh.items() if k != 'turns'}], 'nextCursor': None}
                assert params == {'threadId': old['id'], 'includeTurns': True}, params
                return {'thread': copy.deepcopy(fresh)}

        desk.catalog = lambda: Catalog()

        def paths(path, method=None):
            return [r for r in requests if urlsplit(r['url']).path == path
                    and (method is None or r['method'] == method)]

        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk))
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start(); browser = None
        try:
            browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = await browser.new_page(viewport={'width': width, 'height': 900 if width > 390 else 844})
            page.set_default_timeout(10_000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append({'url': request.url, 'method': request.method}))
            await page.goto(f'http://127.0.0.1:{server.server_port}')
            await page.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            selected_state = await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
            await page.locator('#home-content').click()
            await page.locator('#recall-query').fill('fresh outside decision')
            await page.locator('#recall-query').press('Enter')
            await page.wait_for_function("!$('recall-search').disabled")
            assert await page.locator('.recall-result').count() == 0
            assert not paths('/api/history/index', 'POST')
            assert not any(c['method'] == 'thread/read' for c in calls)
            before = len(paths('/api/recall'))
            await page.wait_for_function("!$('recall-index').disabled")
            await page.locator('#recall-index').click()
            await page.wait_for_function("$('recall-index-status').textContent.includes('scan completed')")
            await page.wait_for_function("$('recall-results').children.length===1 && !$('recall-search').disabled")
            assert 'Fresh outside decision' in await page.locator('#recall-results').inner_text()
            after = len(paths('/api/recall'))
            assert after == before + 1, (before, after)
            job = desk.history_scanner.status()
            assert (job['seen'], job['indexed'], job['skipped'], job['failed']) == (1, 0 if cached else 1, 1 if cached else 0, 0), job
            reads_before_original = sum(c['method'] == 'thread/read' for c in calls)
            assert reads_before_original == (0 if cached else 1), calls
            hit = desk.recall('fresh outside decision')['results'][0]
            assert (hit['session_id'], hit['thread_id'], hit['turn_id'], hit['item_id']) == (saved, old['id'], 'outside-turn', 'outside-item'), hit
            row = page.locator('.recall-result')
            assert await row.get_attribute('data-session') == saved
            assert await row.get_attribute('data-thread') == old['id']
            assert await row.get_attribute('data-item') == 'outside-item'
            assert await row.get_attribute('data-kind') == 'activity'
            results_before = await page.locator('#recall-results').inner_text()
            await row.locator('.recall-read').click()
            await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            assert len(paths('/api/native/thread')) == 1
            assert parse_qs(urlsplit(paths('/api/native/thread')[0]['url']).query) == {'id': [old['id']]}
            assert sum(c['method'] == 'thread/read' for c in calls) == reads_before_original + 1
            assert await page.locator('#history-reader-binding').inner_text() == f"Thread {old['id']}\n{project}\nProvider: fixture"
            # These are the maintained reader's actual DOM identity attributes,
            # rather than a phrase-only check against any rendered conversation.
            target = page.locator('#history-reader-body .history-reader-target')
            assert await target.count() == 1
            assert await target.get_attribute('data-turn-id') == 'outside-turn'
            assert await target.get_attribute('data-item-id') == 'outside-item'
            assert await target.evaluate('(node)=>node.open')
            assert await target.evaluate("(node)=>node.closest('.history-reader-turn').dataset.turnId") == 'outside-turn'
            assert await target.locator('mark').inner_text() == hit['match_text']
            assert 'retry budget remains three attempts' in await target.locator('.history-reader-text').inner_text()
            assert 'Old preserved evidence' in await page.locator('#history-reader-body').inner_text()
            assert await page.locator('#recall').evaluate('(node)=>node.open')
            assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && $('history-reader').scrollWidth<=$('history-reader').clientWidth && $('history-reader-body').scrollWidth<=$('history-reader-body').clientWidth")
            screenshot = evidence / f'original-{width}-{int(cached)}.png'
            await page.screenshot(path=str(screenshot)); screenshot.chmod(0o600)
            await page.locator('#history-reader-back').click()
            await page.wait_for_function("!$('history-reader').open && $('recall').open")
            assert await page.locator('.recall-read').evaluate('(n)=>n===document.activeElement')
            assert await page.locator('#recall-query').input_value() == 'fresh outside decision'
            assert await page.locator('#recall-results').inner_text() == results_before
            assert len(paths('/api/recall')) == after
            assert await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})") == selected_state
            assert (desk.store.sessions(), load_draft(desk.store, saved), followup_snapshot(desk.store, saved)) == prep
            assert desk.store.events(saved) == events
            assert {p.name: p.read_bytes() for p in home.iterdir()} == settings and fresh == original
            assert not errors and all(urlsplit(r['url']).hostname == '127.0.0.1' for r in requests)
            assert [urlsplit(r['url']).path for r in requests if r['method'] == 'POST'] == ['/api/history/index']
            assert not paths('/api/open') and not paths('/api/import')
            assert desk.runtimes == {}
            return {'width': width, 'already_indexed': cached, 'job': job,
                    'automatic_query_refreshes': after - before, 'reads_before_original': reads_before_original,
                    'exact_original': {'thread_id': old['id'], 'turn_id': 'outside-turn', 'item_id': 'outside-item'},
                    'back_retains_search_and_focus': True, 'preparation_and_settings_preserved': True,
                    'native_tasks': 0, 'errors': errors}
        finally:
            if browser: await browser.close()
            server.shutdown(); server.server_close(); worker.join(3)
            desk.close(); desk.store.db.close()


async def main():
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']); evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence.chmod(0o700)
    async with async_playwright() as playwright:
        checks = [await check(width, cached, playwright, evidence)
                  for width in (1250, 390) for cached in (False, True)]
    summary = evidence / 'summary.json'
    summary.write_text(json.dumps({'result': 'PASS', 'checks': checks}, indent=2) + '\n'); summary.chmod(0o600)
    print(json.dumps({'result': 'PASS', 'bound_recall_cases': len(checks)}), flush=True)


if __name__ == '__main__': asyncio.run(main())
