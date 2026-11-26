"""Controlled native title-search checks through the shipped HTTP/browser UI.

DESK_TEST_TEMP=/your/workspace/temp DESK_CHROMIUM=/path/to/chromium \
  python tests/browser_search.py
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk import server as desk_server
from codex_desk.runtime import Runtime
from playwright.async_api import async_playwright


async def check(resume_only=False):
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-title-search-') as folder:
        folder = Path(folder)
        projects = {name: folder / name for name in ('project-a', 'project-b')}
        for directory in projects.values():
            directory.mkdir()
        home = folder / 'native-home'
        home.mkdir()
        (home / 'config.toml').write_text('model = "fixture"\n')
        (home / 'retained.config.toml').write_text('model = "retained-fixture"\nmodel_provider = "fixture"\n')
        settings_before = {p.name: p.read_bytes() for p in home.iterdir()}

        def saved(identifier, cwd, name):
            return {'id': identifier, 'cwd': str(cwd), 'modelProvider': 'fixture', 'name': name,
                    'turns': [{'id': 'turn-' + identifier, 'items': [
                        {'id': 'message-' + identifier, 'type': 'userMessage',
                         'content': [{'type': 'text', 'text': 'only-in-message'}]},
                        {'id': 'command-' + identifier, 'type': 'commandExecution',
                         'command': 'echo only-in-message', 'aggregatedOutput': 'only-in-message', 'exitCode': 0}]}]}

        threads = {
            'alpha-a': saved('alpha-a', projects['project-a'], 'Alpha release verification'),
            'alpha-old': saved('alpha-old', projects['project-a'], 'Alpha older handoff'),
            'beta-a': saved('beta-a', projects['project-a'], 'Beta project verification'),
            'special-a': saved('special-a', projects['project-a'], 'Release + status?'),
            'beta-b': saved('beta-b', projects['project-b'], 'Beta different project')}
        threads_before = json.dumps(threads, sort_keys=True)
        native_calls, http_calls, holds = [], [], {}

        def hold(method, cwd=None, search='', cursor=None):
            key = (method, cwd, search, cursor)
            entered, release = threading.Event(), threading.Event()
            holds[key] = (entered, release)
            return entered, release

        class ControlledRuntime(Runtime):
            def __init__(self, store, identifier, binary, native_home):
                assert binary == 'never-executed'
                self.store, self.id, self.home = store, identifier, native_home
                self.process = SimpleNamespace(poll=lambda: None)
                self.approvals = {}
                self.name_lock = threading.RLock()
                self.persisted = False

            def request(self, method, params):
                native_calls.append({'method': method, 'params': params})
                key = (method, params.get('cwd'), params.get('searchTerm', ''), params.get('cursor'))
                if method == 'thread/read':
                    key = (method, params['threadId'], '', None)
                if key in holds:
                    entered, release = holds[key]
                    entered.set()
                    assert release.wait(20), 'Held request was not released: ' + str(key)
                if method == 'thread/read':
                    return {'thread': threads[params['threadId']]}
                if method == 'thread/resume':
                    return {'thread': threads[params['threadId']], 'model': 'fixture', 'modelProvider': 'fixture'}
                assert method == 'thread/list', 'Unexpected native call: ' + method
                cwd, search = params.get('cwd'), params.get('searchTerm', '')
                if search == 'catalog-error':
                    raise RuntimeError('Fixture title catalog unavailable')
                if search.startswith(('slow-', 'closed-')) or search == 'folder-query':
                    title = search + (' current project' if cwd == str(projects['project-b']) else ' stale result')
                    return {'data': [saved('fixture-' + search, cwd or projects['project-a'], title)], 'nextCursor': None}
                rows = [t for t in threads.values() if (not cwd or t['cwd'] == cwd)
                        and (not search or search.casefold() in t['name'].casefold())]
                return {'data': rows[1:] if params.get('cursor') else rows[:1],
                        'nextCursor': None if params.get('cursor') or len(rows) <= 1 else 'fixture-next-page'}

            def close(self):
                pass

        with patch.object(desk_server, 'Runtime', ControlledRuntime):
            desk = desk_server.Desk('never-executed', home, folder / 'state')
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            url = f'http://127.0.0.1:{server.server_port}'

            def is_response(response, search, cwd=None, cursor=None):
                route = urlsplit(response.url)
                query = parse_qs(route.query)
                return route.path == '/api/native' and query.get('search', [''])[0] == search \
                    and query.get('cwd', [None])[0] == cwd and query.get('cursor', [None])[0] == cursor

            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                        headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                    try:
                        page = await browser.new_page(viewport={'width': 390, 'height': 844})
                        errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.on('request', lambda r: http_calls.append({'path': urlsplit(r.url).path,
                            'method': r.method, 'query': parse_qs(urlsplit(r.url).query)}))
                        await page.goto(url)
                        await page.wait_for_function('state.profiles.length === 2')
                        await page.wait_for_function('document.querySelector("#home-list").getAttribute("aria-busy") === "false"')
                        native_calls.clear()  # First-use discovery is covered by browser_home.py.

                        async def project_search(query):
                            await page.locator('#project-search').fill(query)
                            await page.locator('#project-search').press('Enter')
                            await page.wait_for_function("!$('project-find').disabled")

                        async def global_search(query):
                            await page.locator('#history-search').fill(query)
                            await page.locator('#history-search').press('Enter')
                            await page.wait_for_function("!$('history-search-submit').disabled")

                        def latest_list():
                            return next(c for c in reversed(http_calls) if c['path'] == '/api/native')

                        def assert_read_only_search():
                            assert not any(c['path'] in ('/api/sessions', '/api/import', '/api/open',
                                '/api/turn', '/api/handoff/start') for c in http_calls), http_calls
                            assert all(c['method'] in ('thread/list', 'thread/read') for c in native_calls), native_calls
                            assert [s for s in desk.store.sessions() if s['id'] != 'native-catalog'] == []

                        if not resume_only:
                            # Title scope, exact encoded query/folder and provider retention.
                            await page.locator('#new').click()
                            await page.locator('#cwd').fill(str(projects['project-a']))
                            await page.locator('#profile').select_option('sidecar:retained')
                            assert 'title text only, not messages or tool results' in await page.locator('#project-search-info').inner_text()
                            assert await page.get_by_label('Search conversation titles', exact=True).count() == 2
                            await project_search('  Release + status?  ')
                            assert latest_list()['query'] == {'search': ['Release + status?'], 'cwd': [str(projects['project-a'])]}
                            assert native_calls[-1]['params']['searchTerm'] == 'Release + status?'
                            assert 'Release + status?' in await page.locator('#project-list').inner_text()
                            assert await page.locator('#profile').input_value() == 'sidecar:retained'
                            assert await page.locator('#cwd').input_value() == str(projects['project-a'])

                            # Pagination keeps search/cwd. Editing the query removes old rows/cursor immediately.
                            await project_search('Alpha')
                            assert await page.locator('#project-list .native-row').count() == 1
                            await page.locator('#project-more').click()
                            await page.wait_for_function("$('project-list').children.length === 2 && !$('project-more').disabled")
                            assert latest_list()['query'] == {'search': ['Alpha'], 'cwd': [str(projects['project-a'])], 'cursor': ['fixture-next-page']}
                            await page.locator('#project-search').fill('Beta')
                            assert await page.locator('#project-list .native-row').count() == 0
                            assert await page.locator('#project-more').is_hidden()
                            await page.locator('#project-search').press('Enter')
                            await page.wait_for_function("!$('project-find').disabled")
                            assert 'cursor' not in latest_list()['query']
                            assert 'Beta project verification' in await page.locator('#project-list').inner_text()
                            await project_search('   ')
                            assert latest_list()['query'] == {'cwd': [str(projects['project-a'])]}
                            assert 'searchTerm' not in native_calls[-1]['params']
                            await project_search('only-in-message')
                            assert 'only-in-message' in await page.locator('#project-summary').inner_text()
                            assert 'No saved conversation titles match' in await page.locator('#project-summary').inner_text()
                            assert await page.locator('#project-list .native-row').count() == 0
                            assert await page.locator('#project-new').is_visible() and await page.locator('#project-new').is_enabled()
                            await project_search('catalog-error')
                            assert 'Fixture title catalog unavailable' in await page.locator('#project-error').inner_text()
                            assert await page.locator('#project-new').is_enabled()
                            assert await page.locator('#profile').input_value() == 'sidecar:retained'

                            # A response from the old title query cannot replace the newer results.
                            entered, release = hold('thread/list', str(projects['project-a']), 'slow-query-a')
                            await page.locator('#project-search').fill('slow-query-a')
                            await page.locator('#project-search').press('Enter')
                            assert await asyncio.to_thread(entered.wait, 5)
                            await project_search('Beta')
                            async with page.expect_response(lambda r: is_response(r, 'slow-query-a', str(projects['project-a']))) as response:
                                release.set()
                            await (await response.value).body()
                            await page.wait_for_timeout(100)
                            assert 'slow-query-a' not in await page.locator('#project-list').inner_text()
                            assert 'Beta project verification' in await page.locator('#project-list').inner_text()

                            # Closing/reopening rejects an older dialog's result even with the same folder.
                            entered, release = hold('thread/list', str(projects['project-a']), 'closed-query')
                            await page.locator('#project-search').fill('closed-query')
                            await page.locator('#project-search').press('Enter')
                            assert await asyncio.to_thread(entered.wait, 5)
                            await page.locator('#cancel').click()
                            await page.locator('#new').click()
                            await page.locator('#profile').select_option('sidecar:retained')
                            await project_search('Beta')
                            async with page.expect_response(lambda r: is_response(r, 'closed-query', str(projects['project-a']))) as response:
                                release.set()
                            await (await response.value).body()
                            await page.wait_for_timeout(100)
                            assert 'closed-query' not in await page.locator('#project-list').inner_text()

                            # Folder edits retain the query/provider and reject the old folder's lookup.
                            entered, release = hold('thread/list', str(projects['project-a']), 'folder-query')
                            await page.locator('#project-search').fill('folder-query')
                            await page.locator('#project-search').press('Enter')
                            assert await asyncio.to_thread(entered.wait, 5)
                            await page.locator('#cwd').fill(str(projects['project-b']))
                            assert await page.locator('#project-search').input_value() == 'folder-query'
                            await page.locator('#project-search').press('Enter')
                            await page.wait_for_function("!$('project-find').disabled")
                            async with page.expect_response(lambda r: is_response(r, 'folder-query', str(projects['project-a']))) as response:
                                release.set()
                            await (await response.value).body()
                            await page.wait_for_timeout(100)
                            assert 'current project' in await page.locator('#project-list').inner_text()
                            assert 'stale result' not in await page.locator('#project-list').inner_text()
                            assert await page.locator('#profile').input_value() == 'sidecar:retained'
                            assert await page.evaluate("$('project').scrollWidth <= $('project').clientWidth && document.documentElement.scrollWidth <= innerWidth")
                            assert_read_only_search()
                            await page.locator('#cancel').click()

                            # Global search omits cwd, supports Enter, and keeps query on each cursor page.
                            await page.locator('#browse').click()
                            await page.wait_for_function("!$('history-search-submit').disabled")
                            assert latest_list()['query'] == {}
                            assert 'title text only, not messages or tool results' in await page.locator('#history-search-info').inner_text()
                            assert await page.get_by_label('Search conversation titles', exact=True).count() == 2
                            await global_search('Alpha')
                            assert latest_list()['query'] == {'search': ['Alpha']}
                            await page.locator('#more').click()
                            await page.wait_for_function("$('native-list').children.length === 2 && !$('more').disabled")
                            assert latest_list()['query'] == {'search': ['Alpha'], 'cursor': ['fixture-next-page']}
                            await global_search('only-in-message')
                            assert 'No saved conversation titles match “only-in-message”' in await page.locator('#history-summary').inner_text()
                            assert await page.locator('#native-list .native-row').count() == 0
                            await global_search('catalog-error')
                            assert await page.locator('#history-error').is_visible()
                            assert await page.locator('#history').is_visible()
                            await global_search('Beta')
                            assert await page.locator('#history-error').is_hidden()
                            assert 'cursor' not in latest_list()['query']

                            # Input edits invalidate the old response even before Search/Enter is pressed.
                            entered, release = hold('thread/list', None, 'slow-global-a')
                            await page.locator('#history-search').fill('slow-global-a')
                            await page.locator('#history-search').press('Enter')
                            assert await asyncio.to_thread(entered.wait, 5)
                            await page.locator('#history-search').fill('Beta')
                            async with page.expect_response(lambda r: is_response(r, 'slow-global-a')) as response:
                                release.set()
                            await (await response.value).body()
                            await page.wait_for_timeout(100)
                            assert await page.locator('#native-list .native-row').count() == 0
                            assert await page.locator('#more').is_hidden()
                            await global_search('Beta')

                            # A late pagination page cannot append after a different search.
                            await global_search('Alpha')
                            entered, release = hold('thread/list', None, 'Alpha', 'fixture-next-page')
                            await page.locator('#more').click()
                            assert await asyncio.to_thread(entered.wait, 5)
                            await global_search('Beta')
                            async with page.expect_response(lambda r: is_response(r, 'Alpha', cursor='fixture-next-page')) as response:
                                release.set()
                            await (await response.value).body()
                            await page.wait_for_timeout(100)
                            assert 'Alpha' not in await page.locator('#native-list').inner_text()
                            assert 'Beta' in await page.locator('#native-list').inner_text()

                            # A late global dialog response cannot replace a reopened dialog's query.
                            entered, release = hold('thread/list', None, 'closed-global-query')
                            await page.locator('#history-search').fill('closed-global-query')
                            await page.locator('#history-search').press('Enter')
                            assert await asyncio.to_thread(entered.wait, 5)
                            await page.locator('#history-close').click()
                            await page.locator('#browse').click()
                            await global_search('Beta')
                            async with page.expect_response(lambda r: is_response(r, 'closed-global-query')) as response:
                                release.set()
                            await (await response.value).body()
                            await page.wait_for_timeout(100)
                            assert 'closed-global-query' not in await page.locator('#native-list').inner_text()
                            assert 'Beta' in await page.locator('#native-list').inner_text()
                            assert_read_only_search()

                            # Explicit handoff reading must also respect changes to its source search.
                            await global_search('Alpha')
                            entered, release = hold('thread/read', 'alpha-a')
                            await page.locator('#native-list').get_by_role('button', name='Review handoff', exact=True).first.click()
                            assert await asyncio.to_thread(entered.wait, 5)
                            await global_search('Beta')
                            async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/handoff') as response:
                                release.set()
                            await (await response.value).body()
                            await page.wait_for_timeout(100)
                            assert await page.locator('#preview').is_hidden()
                            assert await page.locator('#history').is_visible()
                            assert 'Beta' in await page.locator('#native-list').inner_text()
                            await global_search('  ')
                            assert latest_list()['query'] == {}
                            assert 'searchTerm' not in native_calls[-1]['params']
                            assert await page.evaluate("$('history').scrollWidth <= $('history').clientWidth && document.documentElement.scrollWidth <= innerWidth")
                            assert_read_only_search()
                            assert json.dumps(threads, sort_keys=True) == threads_before
                            assert {p.name: p.read_bytes() for p in home.iterdir()} == settings_before
                            assert not errors, errors
                            print(json.dumps({'projectAndGlobalTitleSearch': True, 'titleOnlyScope': True,
                                'encodedSearchAndCwd': True, 'blankSearchOmitted': True,
                                'sameSearchPagination': True, 'queryChangeResetsCursorAndRows': True,
                                'staleQueryAndPaginationRejected': True, 'staleClosedDialogRejected': True,
                                'staleFolderRejected': True, 'staleHandoffRejected': True,
                                'providerAndFolderRetained': True, 'emptyAndErrorAllowExplicitNew': True,
                                'globalErrorRetry': True, 'keyboardEnter': True, 'mobileOverflow': False,
                                'newImportOpenTurnRequests': 0, 'nativeInferenceCalls': 0,
                                'nativeSettingsAndHistoryUnchanged': True, 'javascriptErrors': errors}, indent=2), flush=True)
                        # Complete title-search -> resume: a late import cannot open the wrong query.
                        if await page.locator('#history').is_visible():
                            await page.locator('#history-close').click()
                        await page.locator('#browse').click()
                        await global_search('Beta')
                        entered, release = hold('thread/read', 'beta-a')
                        stale_button = page.locator('#native-list').get_by_role('button', name='Resume with current settings', exact=True).first
                        stale_node = await stale_button.element_handle()
                        await stale_button.click()
                        assert await asyncio.to_thread(entered.wait, 5)
                        await global_search('Alpha')
                        async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/import') as response:
                            release.set()
                        await (await response.value).body()
                        await page.wait_for_timeout(100)
                        assert await page.locator('#history').is_visible()
                        assert await page.locator('#task').is_hidden()
                        assert 'Alpha' in await page.locator('#native-list').inner_text()
                        assert not any(c['path'] == '/api/open' for c in http_calls)
                        assert not await stale_node.evaluate('(node) => node.disabled')
                        stale_imports = sum(c['path'] == '/api/import' for c in http_calls)
                        assert stale_imports == 1

                        # Rapidly activating the same result must import/open exactly once.
                        entered, release = hold('thread/read', 'alpha-a')
                        resume = page.locator('#native-list').get_by_role('button', name='Resume with current settings', exact=True).first
                        await resume.evaluate('(button) => { button.click(); button.click(); }')
                        assert await asyncio.to_thread(entered.wait, 5)
                        await page.wait_for_timeout(100)
                        pending_imports = sum(c['path'] == '/api/import' for c in http_calls) - stale_imports
                        disabled_while_pending = await resume.is_disabled()
                        async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/import') as response:
                            release.set()
                        await (await response.value).body()
                        await page.wait_for_function("!opening && selected && !$('task').hidden")
                        await page.wait_for_timeout(100)
                        positive = {
                            'rapidSameRowPendingImports': pending_imports,
                            'resumeButtonDisabledWhilePending': disabled_while_pending,
                            'searchResumeImportRequests': sum(c['path'] == '/api/import' for c in http_calls) - stale_imports,
                            'searchResumeOpenRequests': sum(c['path'] == '/api/open' for c in http_calls),
                            'searchResumeTurnRequests': sum(c['path'] == '/api/turn' for c in http_calls),
                            'resumedNativeThread': desk.store.get(await page.evaluate('selected'))['thread_id'],
                            'savedCommandVisible': 'echo only-in-message' in await page.locator('#activity').inner_text(),
                            'staleImportAfterChangedSearchIgnored': True,
                            'retiredResumeButtonEnabled': not await stale_node.evaluate('(node) => node.disabled'),
                            'nativeInferenceCalls': 0, 'javascriptErrors': errors}
                        print(json.dumps({'searchToResume': positive}, indent=2), flush=True)
                        assert positive['rapidSameRowPendingImports'] == 1, positive
                        assert positive['resumeButtonDisabledWhilePending'], positive
                        assert positive['searchResumeImportRequests'] == 1 and positive['searchResumeOpenRequests'] == 1, positive
                        assert positive['searchResumeTurnRequests'] == 0 and positive['resumedNativeThread'] == 'alpha-a', positive
                        assert positive['savedCommandVisible'] and positive['retiredResumeButtonEnabled'], positive
                        assert not any(c['path'] in ('/api/sessions', '/api/turn', '/api/handoff/start') for c in http_calls)
                        assert all(c['method'] in ('thread/list', 'thread/read', 'thread/resume') for c in native_calls)
                        assert json.dumps(threads, sort_keys=True) == threads_before
                        assert {p.name: p.read_bytes() for p in home.iterdir()} == settings_before
                        assert not errors, errors
                    finally:
                        await browser.close()
            finally:
                for _, release in holds.values():
                    release.set()
                server.shutdown()
                worker.join(timeout=5)
                server.server_close()
                desk.close()
                desk.store.db.close()


if __name__ == '__main__':
    asyncio.run(check(resume_only='--resume-only' in sys.argv))
