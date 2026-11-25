"""Project grouping and reversible local archive through real loopback HTTP.

Uses 25 saved sessions and three project folders. Native results/approvals are
controlled fixtures; no Codex process or provider turn is started.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace

if not os.environ.get('DESK_USE_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, ThreadingHTTPServer, handler
from codex_desk.runtime import save_profile
from codex_desk.drafts import load_draft
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    result = {'passed': [], 'javascriptErrors': [], 'externalRequests': [], 'nativeProcesses': 0}
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-organization-') as temporary:
        folder = Path(temporary)
        evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(folder / 'evidence')))
        evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
        projects = [folder / 'alpha' / 'project', folder / 'beta' / 'project', folder / 'gamma' / '验证项目']
        for project in projects:
            project.mkdir(parents=True)
        home, state_dir = folder / 'home', folder / 'state'
        home.mkdir()
        (home / 'config.toml').write_text('model="fixture"\n')
        (home / 'auth.json').write_text('{"synthetic": "unchanged"}\n')
        save_profile(home, 'retained', 'https://fixture.example/v1', 'fixture-model', 'synthetic-only-key')
        settings = {p.name: p.read_bytes() for p in home.iterdir()}
        threads, controls, history_calls = {}, [], []

        class Loaded:
            def __init__(self, desk, row):
                self.desk, self.row = desk, row
                self.process = SimpleNamespace(poll=lambda: None)
                self.thread_result = {'thread': threads[row['thread_id']]}
                self.approvals = {'approval-0': {'id': 'approval-0',
                    'method': 'item/commandExecution/requestApproval',
                    'params': {'command': 'fixture verification'}}} if row['id'] == 'session-00' else {}

            def approve(self, request, decision):
                controls.append(('approve', self.row['id'], request, decision))
                self.approvals.pop(str(request))
                self.desk.store.update(self.row['id'], status='running')
                return {'accepted': True}

            def interrupt(self):
                controls.append(('stop', self.row['id']))
                self.approvals.clear()
                self.desk.store.update(self.row['id'], status='completed')
                return {'stopped': True}

            def close(self):
                self.process.poll = lambda: 0

        class Catalog:
            def request(self, method, params):
                assert method == 'thread/list'
                history_calls.append((method, params))
                return {'data': [threads['native-04']], 'nextCursor': None}

        def start(port=0, seed=False):
            desk = Desk('never-executed', home, state_dir)
            if seed:
                for i in range(25):
                    id, native = f'session-{i:02}', f'native-{i:02}'
                    cwd = projects[i % 3]
                    profile = 'default' if i == 4 else 'sidecar:retained'
                    name = 'Needle parser verification' if i == 3 else f'Saved task {i:02}'
                    desk.store.create(str(cwd), profile, id, name)
                    desk.store.update(id, thread_id=native, thread_saved=1,
                        status=['approval', 'running', 'starting'][i] if i < 3 else 'completed',
                        model='fixture-model', provider='desk_provider')
                    desk.store.event(id, {'method': 'item/completed', 'params': {'item': {
                        'id': 'prior-' + id, 'type': 'agentMessage', 'text': 'Saved evidence ' + id}}})
                    threads[native] = {'id': native, 'cwd': str(cwd), 'name': name, 'modelProvider': 'desk_provider',
                        'turns': [{'id': 'prior-turn', 'items': [{'id': 'prior-' + id, 'type': 'agentMessage',
                            'text': 'Saved evidence ' + id}]}]}
                for i in (1, 2, 4, 7):
                    desk.store.archive(f'session-{i:02}', True)
            for row in desk.store.sessions():
                desk.runtimes[row['id']] = Loaded(desk, row)
            desk.catalog = lambda: Catalog()

            def history(id):
                history_calls.append(('thread/read', id))
                return threads[id]

            desk.history = history
            server = ThreadingHTTPServer(('127.0.0.1', port), handler(desk))
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            return desk, server, worker

        def stop(desk, server, worker):
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            desk.close()
            desk.store.db.close()

        desk, server, worker = start(seed=True)
        port = server.server_port
        url = f'http://127.0.0.1:{port}'
        bindings = {s['id']: {k: s[k] for k in ('cwd', 'profile', 'thread_id', 'name', 'model', 'provider')}
                    for s in desk.store.sessions()}
        prior_events = {s['id']: desk.store.events(s['id']) for s in desk.store.sessions()}
        native_before = json.dumps(threads, sort_keys=True)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                    headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                try:
                    page = await browser.new_page(viewport={'width': 1250, 'height': 900})
                    page.set_default_timeout(10_000)
                    page.on('pageerror', lambda e: result['javascriptErrors'].append(str(e)))
                    http_calls = []

                    def requested(request):
                        from urllib.parse import urlsplit
                        route = urlsplit(request.url)
                        http_calls.append((request.method, route.path))
                        if route.hostname != '127.0.0.1':
                            result['externalRequests'].append(request.url)

                    page.on('request', requested)
                    await page.add_init_script("""if(location.hostname==='127.0.0.1' && !localStorage.getItem('organization-fixture-initialized')) {
                        localStorage.setItem('organization-fixture-initialized','1');
                        localStorage.setItem('codex-desk-session','session-04');
                    }""")
                    await page.goto(url)
                    await page.wait_for_function('state.sessions.length===25')
                    assert await page.evaluate('selected') is None
                    assert not any(path == '/api/open' for method, path in http_calls)
                    assert await page.locator('.project-group').count() == 3
                    assert await page.locator('.session-row').count() == 23
                    result['passed'].append('three canonical groups and no archived-idle automatic reopen')

                    async def visible():
                        return set(await page.locator('.session-row').evaluate_all('rows=>rows.map(r=>r.dataset.session)'))

                    async def open_session(id):
                        await page.locator(f'.session-row[data-session="{id}"] .session').click()
                        await page.wait_for_function('id=>selected===id && !opening && !$("task").hidden', arg=id)

                    async def archive_row(id, archived):
                        await page.locator(f'.session-row[data-session="{id}"] .session-archive').click()
                        await page.wait_for_function('v=>state.sessions.find(s=>s.id===v.id).archived===v.archived && !archiving.has(v.id)',
                            arg={'id': id, 'archived': archived})

                    async def layout(width):
                        await page.set_viewport_size({'width': width, 'height': 900 if width == 1250 else 844})
                        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        assert await page.locator('#sessions').evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
                        await page.screenshot(path=str(evidence / f'organization-{width}.png'), full_page=True)

                    await page.locator('#session-filter').fill('needle')
                    assert await visible() == {'session-00', 'session-01', 'session-02', 'session-03'}
                    await page.locator('#session-filter').fill('no-matching-title')
                    assert await visible() == {'session-00', 'session-01', 'session-02'}
                    await page.locator('#session-filter').fill('alpha')
                    expected = {s['id'] for s in desk.store.sessions() if s['status'] in ('approval', 'running', 'starting')
                                or ('alpha' in s['cwd'] and not s['archived'])}
                    assert await visible() == expected
                    assert await page.evaluate('state.sessions.length') == 25
                    await page.locator('#session-filter').fill('')
                    result['passed'].append('title/project text filtering never removes active work or internal rows')
                    await layout(1250)
                    await layout(390)

                    await open_session('session-03')
                    text = 'Unsent organization task\n保留这个准备  '
                    await page.locator('#prompt').fill(text)
                    await page.locator('#turn-mode').select_option('plan')
                    await page.wait_for_function('v=>draftSaved.get("session-03")?.text===v', arg=text)
                    prepared = load_draft(desk.store, 'session-03')
                    before_archive = desk.store.get('session-03')
                    await page.locator('#archive-session').click()
                    await page.wait_for_function('state.sessions.find(s=>s.id==="session-03").archived && !archiving.has("session-03")')
                    assert 'session-03' not in await visible()
                    assert await page.locator('#prompt').input_value() == text
                    assert await page.locator('#turn-mode').input_value() == 'plan'
                    assert await page.evaluate('selected') == 'session-03'
                    assert await page.locator('#archive-session').inner_text() == 'Restore session'
                    assert load_draft(desk.store, 'session-03') == prepared
                    assert desk.store.get('session-03')['updated'] == before_archive['updated']
                    await page.locator('#archive-session').click()
                    await page.wait_for_function('!state.sessions.find(s=>s.id==="session-03").archived && !archiving.has("session-03")')
                    assert 'session-03' in await visible() and not controls
                    result['passed'].append('archive/restore keeps selected reader, exact draft/mode, activity time and bindings')

                    await archive_row('session-00', True)
                    assert 'session-00' in await visible()
                    assert await page.locator('#prompt').input_value() == text
                    await open_session('session-00')
                    assert await page.locator('#stop').is_enabled()
                    await page.get_by_role('button', name='Allow once', exact=True).click()
                    await page.wait_for_function('state.sessions.find(s=>s.id==="session-00").status==="running"')
                    assert controls == [('approve', 'session-00', 'approval-0', 'accept')]
                    await open_session('session-01')
                    assert await page.locator('#stop').is_enabled()
                    await page.locator('#stop').click()
                    await page.wait_for_function('state.sessions.find(s=>s.id==="session-01").status==="completed"')
                    assert 'session-01' not in await visible()
                    assert controls[-1] == ('stop', 'session-01')
                    assert await page.locator('#archive-session').inner_text() == 'Restore session'
                    await page.locator('#session-filter').fill('still-no-match')
                    assert await visible() == {'session-00', 'session-02'}
                    await page.locator('#session-filter').fill('')
                    assert 'session-02' in await visible()
                    result['passed'].append('archived approval/running controls stay reachable; starting remains visible')

                    await page.locator('#show-archived').check()
                    assert await page.locator('.session-row').count() == 25
                    await archive_row('session-07', False)
                    assert desk.store.get('session-07')['archived'] is False
                    await page.locator('#show-archived').uncheck()
                    assert 'session-07' in await visible()
                    await page.locator('#browse').click()
                    await page.wait_for_selector('#native-list .native-row button')
                    await page.locator('#native-list .native-row button').first.click()
                    await page.wait_for_function('selected==="session-04" && !opening && !$("task").hidden')
                    assert len(desk.store.sessions()) == 25
                    assert desk.store.get('session-04')['archived'] is False
                    assert desk.store.get('session-04')['profile'] == 'default'
                    assert desk.store.get('session-04')['thread_id'] == 'native-04'
                    result['passed'].append('show/restore and explicit native history reuse the archived binding')

                    response = await page.request.get(url + '/api/organized?include_archived=true')
                    assert response.status == 200 and len(await response.json()) == 3
                    response = await page.request.get(url + '/api/organized?title=needle')
                    groups = await response.json()
                    assert [row['id'] for g in groups for row in [*g['active'], *g['recent'], *g['archived']]] == ['session-03']
                    invalid = await page.request.post(url + '/api/archive', data={'session': 'session-03', 'archived': 'true'})
                    assert invalid.status == 400
                    result['passed'].append('organized GET and strict local archive POST use real Store methods')

                    await open_session('session-03')
                    assert await page.locator('#prompt').input_value() == text
                    assert await page.locator('#turn-mode').input_value() == 'plan'
                    await page.locator('#archive-session').click()
                    await page.wait_for_function('state.sessions.find(s=>s.id==="session-03").archived && !archiving.has("session-03")')
                    await page.goto('about:blank')
                    await asyncio.to_thread(stop, desk, server, worker)
                    desk, server, worker = start(port=port)
                    await page.goto(url)
                    await page.wait_for_function('state.sessions.length===25')
                    assert await page.evaluate('selected') is None
                    assert desk.store.get('session-03')['archived'] is True
                    assert load_draft(desk.store, 'session-03') == prepared
                    await page.locator('#show-archived').check()
                    await open_session('session-03')
                    assert await page.locator('#prompt').input_value() == text
                    assert await page.locator('#turn-mode').input_value() == 'plan'
                    assert 'Saved evidence session-03' in await page.locator('#activity').inner_text()
                    result['passed'].append('actual Desk/SQLite restart retains archive, history and exact preparation')
                    await layout(390)
                    await layout(1250)
                    assert {p.name: p.read_bytes() for p in home.iterdir()} == settings
                    assert {s['id']: {k: s[k] for k in bindings[s['id']]} for s in desk.store.sessions()} == bindings
                    assert {s['id']: desk.store.events(s['id']) for s in desk.store.sessions()} == prior_events
                    assert json.dumps(threads, sort_keys=True) == native_before
                    assert not result['javascriptErrors'] and not result['externalRequests'], result
                    result['nativeTurnRequests'] = sum(path in ('/api/turn', '/api/handoff/start', '/api/sessions') for method, path in http_calls)
                    assert result['nativeTurnRequests'] == 0
                    result['controlledActions'] = controls
                    result['savedSessions'] = len(desk.store.sessions())
                finally:
                    await browser.close()
        finally:
            stop(desk, server, worker)
            (evidence / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
            for file in evidence.iterdir():
                if file.is_file():file.chmod(0o600)
            print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(check())
