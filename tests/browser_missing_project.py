"""Exact removed-project title scope over an active Plan, without importing.

DESK_TEST_TEMP and DESK_TEST_EVIDENCE must point to workspace temp directories.
DESK_CHROMIUM selects the serialized local browser executable.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright


async def check(width, browser, root, evidence):
    with tempfile.TemporaryDirectory(dir=root, prefix='missing-project-') as temporary:
        folder = Path(temporary)
        home = folder / 'home'; home.mkdir()
        active = folder / 'active'; active.mkdir()
        removed = folder / 'removed project + 决策'; removed.mkdir(); removed.rmdir()
        ordinary_file = folder / 'ordinary-file'; ordinary_file.write_text('fixture')
        (home / 'config.toml').write_text('model="fixture-only"\n')
        settings = (home / 'config.toml').read_bytes()
        active_thread = {'id': 'native-active', 'cwd': str(active), 'name': 'Retained active Plan',
            'modelProvider': 'fixture', 'turns': [{'id': 'active-turn', 'status': 'inProgress', 'items': [
                {'id': 'active-answer', 'type': 'agentMessage', 'text': 'Planning the active task.'}]}]}
        title = '决策 + résumé ?'
        threads = [{'id': f'native-{i:03}', 'cwd': str(removed), 'name': f'{title} original {i}',
            'modelProvider': 'fixture', 'turns': [{'id': f'original-turn-{i}', 'status': 'completed', 'items': [
                {'id': f'original-answer-{i}', 'type': 'agentMessage',
                 'text': f'ORIGINAL DECISION {i}: keep three retries and inspect the exact saved command.'},
                {'id': f'original-command-{i}', 'type': 'commandExecution', 'command': 'check --retained',
                 'status': 'completed', 'exitCode': 0, 'aggregatedOutput': 'ORIGINAL COMMAND evidence\nretained output'}]}]}
            for i in range(1, 33)]
        # Same titles in another project and a child must not leak into scope.
        threads += [dict(threads[0], id='other-project', cwd=str(active)),
                    dict(threads[0], id='child-project', cwd=str(removed / 'child'))]
        originals = copy.deepcopy(threads)
        native, http, errors, external = [], [], [], []
        cursor = 'opaque+页 / =30'

        class Catalog:
            def request(self, method, params):
                native.append({'method': method, 'params': copy.deepcopy(params)})
                assert method in ('thread/list', 'thread/read'), method
                if method == 'thread/list':
                    assert params['modelProviders'] == [] and params['sortKey'] == 'updated_at'
                    rows = threads
                    if 'cwd' in params: rows = [t for t in rows if t['cwd'] == params['cwd']]
                    if 'searchTerm' in params: rows = [t for t in rows if params['searchTerm'] in t['name']]
                    offset = 30 if params.get('cursor') == cursor else 0
                    assert not params.get('cursor') or params['cursor'] == cursor
                    return {'data': [{k: v for k, v in t.items() if k != 'turns'}
                                     for t in rows[offset:offset + params['limit']]],
                            'nextCursor': cursor if len(rows) > offset + params['limit'] else None}
                assert params == {'threadId': 'native-032', 'includeTurns': True}, params
                return {'thread': copy.deepcopy(threads[31])}

        desk = Desk('never-executed', home, folder / 'state')
        desk.catalog = lambda: Catalog()
        def opened(identifier):
            native.append({'method': 'explicit-open', 'session': identifier})
            assert identifier == 'active'
            desk.store.update(identifier, status='running', provider='fixture', model='fixture')
            return {'thread': copy.deepcopy(active_thread), 'model': 'fixture', 'modelProvider': 'fixture'}
        desk.open = opened
        desk.store.create(str(active), 'default', identifier='active', name='Retained active Plan')
        desk.store.update('active', thread_id='native-active', status='saved', thread_saved=1, mode='plan', name_pending=0)
        draft_text = '  Exact unsent Plan — 保留\nDo not change these next checks. 🔧\n'
        save_draft(desk.store, 'active', draft_text, 'plan', 0)
        add_followup(desk.store, 'active', 'First queued native check.', 'native')
        add_followup(desk.store, 'active', 'Second queued Plan clarification.', 'plan')
        desk.store.event('active', {'method': 'turn/started', 'params': {
            'threadId': 'native-active', 'turn': {'id': 'active-turn'}}})
        saved_draft, saved_queue = load_draft(desk.store, 'active'), followup_snapshot(desk.store, 'active')
        access = secrets.token_urlsafe(32)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk, access_token=access))
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        context = await browser.new_context(viewport={'width': width, 'height': 900 if width > 390 else 844})
        page = await context.new_page(); page.set_default_timeout(15000)
        page.on('pageerror', lambda e: errors.append(str(e)))
        def requested(request):
            parsed = urlsplit(request.url)
            http.append({'path': parsed.path, 'query': parsed.query, 'method': request.method})
            if parsed.hostname != '127.0.0.1': external.append(request.url)
        page.on('request', requested)
        async def snapshot():
            return await page.evaluate("({selected,generation,nativeThreadId,currentTurn,prompt:$('prompt').value,mode:$('turn-mode').value,caret:[$('prompt').selectionStart,$('prompt').selectionEnd,$('prompt').selectionDirection]})")
        async def unchanged(before):
            assert await snapshot() == before
            assert load_draft(desk.store, 'active') == saved_draft
            assert followup_snapshot(desk.store, 'active') == saved_queue
            assert await page.locator('#followup-count').inner_text() == '2'
            assert await page.locator('#send').is_disabled() and await page.locator('#followup-send').is_disabled()
        async def find():
            await page.locator('#project-find').click()
            await page.wait_for_function("!$('project-find').disabled")
        def scoped_lists():
            return [call for call in native if call['method'] == 'thread/list' and 'cwd' in call['params']]

        try:
            await page.goto(f'http://127.0.0.1:{server.server_port}#access={access}')
            await page.locator('.session-row[data-session="active"] .session').click()
            await page.wait_for_function("selected==='active' && !opening && !$('task').hidden && $('followup-count').textContent==='2' && currentTurn==='active-turn'")
            before = await snapshot(); post_before = [r for r in http if r['method'] == 'POST']
            await page.locator('#new').click()
            await page.locator('#cwd').fill(str(removed))
            await page.locator('#project-search').fill('  ' + title + '  ')
            await find()
            assert await page.locator('#project-list .native-row').count() == 30
            assert await page.locator('#project-new').is_disabled()
            assert 'Project folder unavailable' in await page.locator('#project-summary').inner_text()
            assert await page.locator('#project-list').get_by_role('button', name='Resume this conversation', exact=True).count() == 0
            await page.locator('#project-more').click()
            await page.wait_for_function("!$('project-more').disabled && $('project-list').children.length===32")
            ids = await page.locator('#project-list .native-row').evaluate_all('(rows)=>rows.map(n=>n.dataset.thread)')
            assert ids == [f'native-{i:03}' for i in range(1, 33)]
            assert len(scoped_lists()) == 2
            assert scoped_lists()[1]['params'] == {'limit': 30, 'modelProviders': [], 'sortKey': 'updated_at',
                'cwd': str(removed), 'searchTerm': title, 'cursor': cursor}
            row = page.locator('#project-list .native-row[data-thread="native-032"]')
            rows_text = await page.locator('#project-list').inner_text()
            await row.locator('.native-read').focus(); await page.keyboard.press('Enter')
            await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            assert await page.locator('#history-reader-binding').inner_text() == f'Thread native-032\n{removed}\nProvider: fixture'
            item = page.locator('#history-reader-body [data-item-id="original-answer-32"]')
            assert await item.get_attribute('data-turn-id') == 'original-turn-32'
            if not await item.evaluate('(n)=>n.open'): await item.locator('summary').click()
            assert 'ORIGINAL DECISION 32' in await item.locator('.history-reader-text').inner_text()
            await unchanged(before)
            desk.store.event('active', {'method': 'item/agentMessage/delta', 'params': {
                'threadId': 'native-active', 'turnId': 'active-turn', 'itemId': 'active-answer',
                'delta': ' Live progress while reading exact project history.'}})
            desk.store.update('active', status='approval')
            await page.wait_for_function("$('activity').textContent.includes('Live progress while reading') && $('status').textContent==='approval'")
            await unchanged(before)
            await page.screenshot(path=str(evidence / f'original-{width}.png'))
            assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && $('project').scrollWidth<=$('project').clientWidth && $('history-reader').scrollWidth<=$('history-reader').clientWidth")
            await page.locator('#history-reader-back').click()
            await page.wait_for_function("!$('history-reader').open && $('project').open")
            assert await row.locator('.native-read').evaluate('(n)=>n===document.activeElement')
            assert await row.get_attribute('data-cursor') == cursor
            assert await page.locator('#project-list').inner_text() == rows_text
            assert await page.locator('#cwd').input_value() == str(removed)
            assert await page.locator('#project-search').input_value() == '  ' + title + '  '
            assert len(scoped_lists()) == 2
            await unchanged(before)
            await page.screenshot(path=str(evidence / f'return-{width}.png'))
            # Empty title hit set still describes this exact read-only scope.
            await page.locator('#project-search').fill('UNMATCHED')
            await find()
            assert await page.locator('#project-list .native-row').count() == 0
            assert 'No saved conversation titles match' in await page.locator('#project-summary').inner_text()
            assert 'Project folder unavailable' in await page.locator('#project-summary').inner_text()
            assert await page.locator('#project-new').is_disabled()
            assert scoped_lists()[-1]['params']['cwd'] == str(removed)
            assert not removed.exists()
            # Required blank input never issues a scoped request; whitespace and
            # an existing ordinary file retain the backend's project error.
            count = len(scoped_lists())
            await page.locator('#cwd').fill(''); await find()
            assert len(scoped_lists()) == count
            assert await page.locator('#cwd').evaluate('(n)=>!n.validity.valid')
            for invalid in ('   ', str(ordinary_file)):
                await page.locator('#cwd').fill(invalid); await find()
                assert await page.locator('#project-error').inner_text() == 'Select a project directory'
                assert len(scoped_lists()) == count
            # Restoring the directory and explicitly searching is enough to
            # recover normal Resume/New choices; no automatic creation/resume.
            removed.mkdir()
            await page.locator('#cwd').fill(str(removed)); await page.locator('#project-search').fill(title)
            await find()
            assert await page.locator('#project-new').is_enabled()
            assert await page.locator('#project-list').get_by_role('button', name='Resume this conversation', exact=True).count() == 30
            removed.rmdir()
            await page.locator('#cancel').click()
            await unchanged(before)
            assert [r for r in http if r['method'] == 'POST'] == post_before
            assert [r['path'] for r in post_before] == ['/api/open']
            assert not any(r['path'] in ('/api/import', '/api/turn', '/api/followups/send', '/api/sessions') for r in http)
            # Global title browsing has the same read-only folder guidance.
            await page.locator('#browse').click()
            await page.wait_for_function("!$('history-search-submit').disabled && $('native-list').children.length===30")
            await page.locator('#history-search').fill(title)
            await page.locator('#history-search-submit').click()
            await page.wait_for_function("!$('history-search-submit').disabled && $('native-list').children.length===30")
            assert await page.locator('#native-list').get_by_role('button',name='Resume with current settings',exact=True).count()==0
            await page.locator('#more').click()
            await page.wait_for_function("!$('more').disabled && $('native-list').children.length===34")
            original_row=page.locator('#native-list .native-row').nth(31)
            await original_row.locator('.native-read').click()
            await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            assert 'ORIGINAL DECISION 32' in await page.locator('#history-reader-body').inner_text()
            await page.locator('#history-reader-back').click()
            await page.locator('#history-close').click()
            await unchanged(before)
            assert [r for r in http if r['method']=='POST']==post_before
            assert len([c for c in native if c['method'] == 'thread/read']) == 2
            assert threads == originals and (home / 'config.toml').read_bytes() == settings
            assert not removed.exists() and desk.runtimes == {}
            assert not errors and not external
            data = {'width': width, 'passed': True, 'exact_scoped_title_pages': 32,
                'same_query_row_back': True, 'active_plan_queue_unchanged': True,
                'live_progress_while_reading': True, 'missing_empty_file_blank_restore_checked': True, 'global_title_folder_guidance': True,
                'imports': 0, 'native_resumes': 0, 'model_turns': 0,
                'native': native, 'http': http, 'errors': errors, 'external': external}
            (evidence / f'acceptance-{width}.json').write_text(json.dumps(data, indent=2) + '\n')
            print(json.dumps({'width': width, 'passed': True, 'exact_scoped_rows': 32, 'model_turns': 0}), flush=True)
            return data
        except Exception:
            await page.screenshot(path=str(evidence / f'failure-{width}.png'))
            (evidence / f'failure-{width}.json').write_text(json.dumps({'native': native, 'http': http,
                'errors': errors, 'page': await page.locator('body').inner_text()}, indent=2) + '\n')
            raise
        finally:
            await context.close()
            server.shutdown(); server.server_close(); worker.join(3)
            desk.close(); desk.store.db.close()


async def main():
    root = Path(os.environ['DESK_TEST_TEMP']); root.mkdir(parents=True, exist_ok=True)
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']); evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        try: checks = [await check(width, browser, root, evidence) for width in (1250, 390)]
        finally: await browser.close()
    (evidence / 'summary.json').write_text(json.dumps({'result': 'PASS', 'checks': checks}, indent=2) + '\n')
    print(json.dumps({'result': 'PASS', 'viewports': [1250, 390]}), flush=True)


if __name__ == '__main__': asyncio.run(main())
