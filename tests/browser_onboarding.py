"""Controlled first-project chooser acceptance; no native executable or inference.

DESK_TEST_TEMP=/your/workspace/temp DESK_CHROMIUM=/path/to/chromium \
  python tests/browser_onboarding.py
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
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk import server as desk_server
from codex_desk.runtime import Runtime
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-onboarding-') as folder:
        folder = Path(folder)
        projects = {name: folder / name for name in ('used', 'empty', 'slow-old', 'current', 'reopen-old', 'unavailable')}
        for directory in projects.values():
            directory.mkdir()
        home = folder / 'native-home'
        home.mkdir()
        (home / 'config.toml').write_text('model = "fixture"\n')
        (home / 'retained.config.toml').write_text('model = "retained-fixture"\nmodel_provider = "fixture"\n')
        settings_before = {p.name: p.read_bytes() for p in home.iterdir()}

        def saved(identifier, project, title):
            return {'id': identifier, 'cwd': str(project), 'modelProvider': 'fixture', 'name': title,
                    'turns': [{'id': 'old-turn-' + identifier, 'items': [
                        {'id': 'old-task-' + identifier, 'type': 'userMessage',
                         'content': [{'type': 'text', 'text': 'Run the existing app verification'}]},
                        {'id': 'old-command-' + identifier, 'type': 'commandExecution',
                         'command': 'npm test', 'aggregatedOutput': '4 tests passed', 'exitCode': 0},
                        {'id': 'old-answer-' + identifier, 'type': 'agentMessage', 'text': title}]}]}

        threads = {
            'used-native': saved('used-native', projects['used'], 'Existing project verification'),
            'used-older': saved('used-older', projects['used'], 'Older project conversation'),
            'stale-native': saved('stale-native', projects['slow-old'], 'Stale project history'),
            'current-native': saved('current-native', projects['current'], 'Current project history'),
            'reopen-native': saved('reopen-native', projects['reopen-old'], 'Previous dialog history')}
        threads_before = json.dumps(threads, sort_keys=True)
        native_calls, http_calls = [], []
        held = {str(projects[name]): (threading.Event(), threading.Event()) for name in ('slow-old', 'reopen-old')}

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
                if method == 'thread/list':
                    cwd = params.get('cwd')
                    if cwd in held:
                        entered, release = held[cwd]
                        entered.set()
                        assert release.wait(10), 'Held chooser request was not released'
                    if cwd == str(projects['unavailable']):
                        raise RuntimeError('Fixture native catalog unavailable')
                    rows = [t for t in threads.values() if not cwd or t['cwd'] == cwd]
                    if cwd == str(projects['used']):
                        return {'data': rows[1:] if params.get('cursor') else rows[:1],
                                'nextCursor': None if params.get('cursor') else 'older-page'}
                    return {'data': rows, 'nextCursor': None}
                if method == 'thread/read':
                    return {'thread': threads[params['threadId']]}
                if method == 'thread/resume':
                    return {'thread': threads[params['threadId']], 'model': 'fixture', 'modelProvider': 'fixture'}
                if method == 'thread/start':
                    return {'thread': {'id': 'new-' + self.id, 'cwd': params['cwd'], 'turns': []},
                            'model': 'fixture', 'modelProvider': 'fixture'}
                raise AssertionError('Unexpected native method: ' + method)

            def close(self):
                pass

        with patch.object(desk_server, 'Runtime', ControlledRuntime), patch.dict(os.environ, {'HOME': str(folder)}):
            desk = desk_server.Desk('never-executed', home, folder / 'state')
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            url = f'http://127.0.0.1:{server.server_port}'

            def workspaces():
                return [s for s in desk.store.sessions() if s['id'] != 'native-catalog']

            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                        headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                    try:
                        page = await browser.new_page(viewport={'width': 390, 'height': 844})
                        errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.on('request', lambda r: http_calls.append({'path': urlsplit(r.url).path,
                            'method': r.method, 'data': r.post_data_json if r.method == 'POST' else None}))
                        await page.goto(url)
                        await page.wait_for_function('state.profiles.length === 2')

                        async def choose(project):
                            await page.locator('#new').click()
                            await page.locator('#cwd').fill(str(project))
                            await page.locator('#project-find').click()
                            await page.wait_for_function("!$('project-find').disabled")

                        # Default Enter searches existing context; listing never imports/starts a thread.
                        await page.locator('#new').click()
                        assert await page.locator('#project-new').is_visible()
                        await page.locator('#cwd').fill('~/used/../used')
                        await page.locator('#cwd').press('Enter')
                        await page.locator('#project-list .native-row').first.wait_for()
                        assert workspaces() == []
                        assert [c['method'] for c in native_calls] == ['thread/list']
                        assert native_calls[-1]['params']['cwd'] == str(projects['used'])
                        await page.locator('#project-more').click()
                        await page.wait_for_function("$('project-list').children.length === 2")
                        assert native_calls[-1]['params']['cwd'] == str(projects['used'])
                        assert native_calls[-1]['params']['cursor'] == 'older-page'
                        await page.locator('#profile').select_option('sidecar:retained')
                        await page.locator('#project-list button').first.click()
                        await page.locator('#task').wait_for()
                        assert '4 tests passed' in await page.locator('#activity').inner_text()
                        assert workspaces()[0]['thread_id'] == 'used-native'
                        assert workspaces()[0]['profile'] == 'sidecar:retained'
                        assert not any(c['path'] in ('/api/sessions', '/api/turn') for c in http_calls)
                        assert [c['method'] for c in native_calls] == ['thread/list', 'thread/list', 'thread/read', 'thread/resume']
                        assert native_calls[-1]['params']['config']['model'] == 'retained-fixture'
                        existing_result = {'thread': workspaces()[0]['thread_id'], 'profile': workspaces()[0]['profile'],
                                           'preservedCommandOutput': True, 'newConversationRequests': 0, 'turnRequests': 0}

                        # Creating another conversation is an explicit click, not opening the folder.
                        await choose(os.path.relpath(projects['used'], Path.cwd()))
                        assert await page.locator('#project-list .native-row').count() == 1
                        await page.locator('#session-name').fill('Separate project verification')
                        await page.locator('#project-new').click()
                        await page.wait_for_function("!opening && selected && $('title').textContent === 'Separate project verification'")
                        new_workspace = next(s for s in workspaces() if s['thread_id'] != 'used-native')
                        assert new_workspace['cwd'] == str(projects['used'])
                        assert new_workspace['thread_id'].startswith('new-')
                        assert await page.locator('#activity').inner_text() == ''
                        assert sum(c['path'] == '/api/sessions' for c in http_calls) == 1

                        await choose(projects['empty'])
                        assert 'No saved conversations' in await page.locator('#project-summary').inner_text()
                        assert await page.locator('#project-new').is_visible()
                        assert len(workspaces()) == 2
                        await page.locator('#cancel').click()

                        await choose(folder / 'missing')
                        assert await page.locator('#project-error').is_visible()
                        assert await page.locator('#project-results').is_hidden()
                        assert await page.locator('#project-new').is_enabled()
                        assert len(workspaces()) == 2
                        await page.locator('#cancel').click()

                        # Catalog failure does not block a selected provider's explicit new thread.
                        await choose(projects['unavailable'])
                        assert 'Fixture native catalog unavailable' in await page.locator('#project-error').inner_text()
                        assert await page.locator('#project-new').is_enabled()
                        await page.locator('#profile').select_option('sidecar:retained')
                        await page.locator('#session-name').fill('Catalog-independent new task')
                        await page.locator('#project-new').click()
                        await page.wait_for_function("!opening && $('title').textContent === 'Catalog-independent new task'")
                        assert any(s['cwd'] == str(projects['unavailable']) and s['profile'] == 'sidecar:retained' for s in workspaces())

                        # A late folder lookup must not replace the current folder's choices.
                        await page.locator('#new').click()
                        await page.locator('#cwd').fill(str(projects['slow-old']))
                        await page.locator('#project-find').click()
                        assert await asyncio.to_thread(held[str(projects['slow-old'])][0].wait, 5)
                        await page.locator('#cwd').fill(str(projects['current']))
                        await page.locator('#project-find').click()
                        await page.wait_for_function("$('project-list').textContent.includes('Current project history')")
                        async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/native' and 'slow-old' in r.url) as response:
                            held[str(projects['slow-old'])][1].set()
                        await (await response.value).body()
                        await page.wait_for_timeout(100)
                        assert 'Stale project history' not in await page.locator('#project-list').inner_text()
                        assert 'Current project history' in await page.locator('#project-list').inner_text()
                        await page.locator('#cancel').click()

                        # Closing/reopening the dialog also invalidates its outstanding response.
                        await page.locator('#new').click()
                        await page.locator('#cwd').fill(str(projects['reopen-old']))
                        await page.locator('#project-find').click()
                        assert await asyncio.to_thread(held[str(projects['reopen-old'])][0].wait, 5)
                        await page.locator('#cancel').click()
                        await choose(projects['used'])
                        async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/native' and 'reopen-old' in r.url) as response:
                            held[str(projects['reopen-old'])][1].set()
                        await (await response.value).body()
                        await page.wait_for_timeout(100)
                        assert 'Previous dialog history' not in await page.locator('#project-list').inner_text()
                        assert 'Existing project verification' in await page.locator('#project-list').inner_text()
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')

                        # Invalid filters fail before catalog access; aliases share create's canonical path.
                        calls_before = len(native_calls)
                        not_directory = folder / 'file'
                        not_directory.write_text('fixture')
                        for value in ('', str(folder / 'missing'), str(not_directory)):
                            response = await page.request.get(url + '/api/native?' + urlencode({'cwd': value}))
                            assert response.status == 400, await response.text()
                        assert len(native_calls) == calls_before
                        alias = folder / 'used-alias'
                        alias.symlink_to(projects['used'], target_is_directory=True)
                        response = await page.request.get(url + '/api/native?' + urlencode({'cwd': str(alias)}))
                        assert response.status == 200
                        assert native_calls[-1]['params']['cwd'] == str(projects['used'])
                        await page.locator('#cancel').click()
                        await page.locator('#browse').click()
                        await page.locator('#native-list .native-row').first.wait_for()
                        assert await page.get_by_role('button', name='Resume with current settings', exact=True).count() == len(threads)
                        assert not errors, errors
                        assert json.dumps(threads, sort_keys=True) == threads_before
                        assert {p.name: p.read_bytes() for p in home.iterdir()} == settings_before
                        assert not any(c['method'] == 'turn/start' for c in native_calls)
                        print(json.dumps({'existing': existing_result, 'explicitNewConversations': 2,
                            'emptyHistory': True, 'invalidFolderInline': True, 'catalogFailureAllowsNew': True,
                            'staleFolderResponseRejected': True, 'staleReopenedResponseRejected': True,
                            'canonicalCwdAndPagination': True, 'globalBrowseAvailable': True,
                            'mobileOverflow': False, 'nativeInferenceCalls': 0, 'nativeSettingsUnchanged': True,
                            'javascriptErrors': errors}, indent=2), flush=True)
                    finally:
                        await browser.close()
            finally:
                for _, release in held.values():
                    release.set()
                server.shutdown()
                worker.join(timeout=5)
                server.server_close()
                desk.close()
                desk.store.db.close()


if __name__ == '__main__':
    asyncio.run(check())
