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
from unittest.mock import patch

if not os.environ.get('DESK_USE_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, ThreadingHTTPServer, handler
from codex_desk.runtime import save_profile, active_turn_id
from codex_desk.drafts import load_draft
from codex_desk.followups import add_followup, followup_snapshot
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
                self.store, self.id, self.home = desk.store, row["id"], desk.home
                self.closing = False
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

            def interrupt(self, thread_id, expected_turn_id):
                assert thread_id == self.row["thread_id"]
                assert expected_turn_id == active_turn_id(self.store, self.id, thread_id)
                self.store.event(self.id, {"method": "turn/completed", "params": {
                    "threadId": thread_id, "turn": {"id": expected_turn_id, "status": "interrupted"}}})
                controls.append(('stop', self.row['id']))
                self.approvals.clear()
                self.desk.store.update(self.row['id'], status='completed')
                return {}

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
                for i in (0, 1):
                    identifier, native = f'session-{i:02}', f'native-{i:02}'
                    turn = {'id': 'active-' + identifier, 'status': 'inProgress', 'items': []}
                    threads[native]['turns'].append(turn)
                    desk.store.event(identifier, {'method': 'turn/started', 'params': {
                        'threadId': native, 'turn': turn}})
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
                    add_followup(desk.store,'session-03','Prepared Work remains paused.','native')
                    add_followup(desk.store,'session-03','Prepared Plan remains paused.','plan')
                    queued=followup_snapshot(desk.store,'session-03')

                    original_name=desk.store.get('session-03')['name']
                    async def held_rename(reopen=False, fail=False):
                        entered,release=threading.Event(),threading.Event()
                        def controlled(identifier,name):
                            assert identifier=='session-03'
                            entered.set();assert release.wait(30),'Held Rename was not released'
                            if fail:raise OSError('Naming temporarily unavailable')
                            desk.store.update(identifier,name=name)
                            return {'name':name,'namePending':False}
                        await page.locator('#rename').click()
                        await page.locator('#rename-name').fill('Submitted name')
                        try:
                            with patch.object(desk,'rename',side_effect=controlled):
                                await page.locator('#rename-save').click()
                                assert await asyncio.to_thread(entered.wait,10)
                                if reopen:
                                    await page.locator('#rename-cancel').click()
                                    await page.locator('#rename').click()
                                await page.locator('#rename-name').fill('Newer retained title')
                                assert await page.locator('#rename-save').is_disabled()
                                release.set()
                                await page.wait_for_function('!document.querySelector("#rename-save").disabled')
                                assert await page.locator('#rename-dialog').evaluate('n=>n.open')
                                assert await page.locator('#rename-name').input_value()=='Newer retained title'
                                if reopen:assert await page.locator('#rename-error').is_hidden()
                                elif fail:assert await page.locator('#rename-error').inner_text()=='Naming temporarily unavailable'
                                assert await page.evaluate('selected')=='session-03'
                                assert await page.locator('#prompt').input_value()==text
                                assert await page.locator('#turn-mode').input_value()=='plan'
                                assert load_draft(desk.store,'session-03')==prepared
                                assert followup_snapshot(desk.store,'session-03')==queued
                        finally:release.set()
                        await page.locator('#rename-cancel').click()
                        desk.store.update('session-03',name=original_name)
                        await page.evaluate('refresh()')
                    await held_rename()
                    await held_rename(reopen=True,fail=True)
                    result['passed'].append('held real Rename HTTP retains text typed after Submit and cancel/reopened edits, isolates old failures, preserves selected Plan and queues, and re-enables the exact current editor')

                    async def held_archive(archived, fail=False):
                        id='session-08';entered,release=threading.Event(),threading.Event()
                        original=desk.store.archive
                        def controlled(identifier, choice):
                            if identifier==id and choice==archived:
                                entered.set();assert release.wait(30),'Held sidebar archive was not released'
                                if fail:raise OSError('Local archive temporarily unavailable')
                            return original(identifier,choice)
                        rows=await page.locator('.session-row').evaluate_all('rows=>rows.map(row=>row.dataset.session)')
                        index=rows.index(id);remaining=[row for row in rows if row!=id]
                        expected=id if fail or not archived or await page.locator('#show-archived').is_checked() else remaining[min(index,len(remaining)-1)]
                        calls_before=sum(method=='POST' and path=='/api/archive' for method,path in http_calls)
                        try:
                            with patch.object(desk.store,'archive',side_effect=controlled):
                                await page.locator(f'.session-row[data-session="{id}"] .session-archive').focus()
                                await page.keyboard.press('Enter')
                                assert await asyncio.to_thread(entered.wait,10),'Archive HTTP request never entered'
                                assert await page.evaluate("id=>document.activeElement.closest('.session-row')?.dataset.session===id && document.activeElement.classList.contains('session-archive')",id)
                                assert await page.evaluate("document.activeElement.getAttribute('aria-disabled')==='true'")
                                await page.keyboard.press('Enter')
                                assert sum(method=='POST' and path=='/api/archive' for method,path in http_calls)==calls_before+1
                                release.set()
                                await page.wait_for_function('id=>!archiving.has(id)',arg=id)
                                assert await page.evaluate("id=>document.activeElement.closest('.session-row')?.dataset.session===id && document.activeElement.classList.contains('session-archive')",expected)
                                assert await page.evaluate("document.activeElement.getAttribute('aria-disabled')==='false'")
                                assert await page.locator('#prompt').input_value()==text
                                assert await page.locator('#turn-mode').input_value()=='plan'
                                assert await page.evaluate('selected')=='session-03'
                                assert load_draft(desk.store,'session-03')==prepared
                                assert followup_snapshot(desk.store,'session-03')==queued
                                if fail:
                                    assert await page.locator('#organization-error').inner_text()=='Local archive temporarily unavailable'
                                    assert desk.store.get(id)['archived'] is True
                                else:assert desk.store.get(id)['archived']==archived
                        finally:release.set()

                    await held_archive(True)
                    await page.locator('#show-archived').check()
                    await held_archive(False,fail=True)
                    await held_archive(False)
                    await page.locator('#show-archived').uncheck()
                    result['passed'].append('keyboard Archive/Restore through held real HTTP keeps pending action focus, rejects repeated Enter, restores failed-action focus or nearest visible action, and preserves the active unsent Plan plus both paused queued modes')

                    # Background native status completion must not strand keyboard focus.
                    for identifier, archived, query, control in (
                        ('session-10', False, '  Needle  ', '.session'),
                        ('session-11', True, '', '.session-archive'),
                    ):
                        original = desk.store.get(identifier)
                        desk.store.update(identifier, status='running')
                        desk.store.archive(identifier, archived)
                        await page.locator('#session-filter').fill(query)
                        await page.evaluate('refresh()')
                        rows = await page.locator('.session-row').evaluate_all('rs=>rs.map(r=>r.dataset.session)')
                        index = rows.index(identifier)
                        remaining = [row for row in rows if row != identifier]
                        destination = remaining[min(index, len(remaining)-1)]
                        await page.locator(f'.session-row[data-session="{identifier}"] {control}').focus()
                        desk.store.update(identifier, status='completed')
                        before_mutations = sum(method == 'POST' for method, path in http_calls)
                        await page.evaluate('refresh()')
                        assert identifier not in await visible()
                        assert await page.evaluate("v=>document.activeElement.closest('.session-row')?.dataset.session===v.id && document.activeElement.matches(v.control)", {'id':destination,'control':control})
                        assert await page.locator('#session-filter').input_value() == query
                        assert not await page.locator('#show-archived').is_checked()
                        assert await page.evaluate('selected') == 'session-03'
                        assert await page.locator('#prompt').input_value() == text
                        assert await page.locator('#turn-mode').input_value() == 'plan'
                        assert load_draft(desk.store, 'session-03') == prepared
                        assert followup_snapshot(desk.store, 'session-03') == queued
                        assert sum(method == 'POST' for method, path in http_calls) == before_mutations
                        desk.store.archive(identifier, original['archived'])
                        desk.store.update(identifier, status=original['status'])
                        await page.locator('#session-filter').fill('')
                        await page.evaluate('refresh()')
                    result['passed'].append('real HTTP Active completion under exact title/archive scope moves only keyboard focus to the nearest same control; selected Plan, two paused modes, scope and all task mutations stay unchanged')

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
                    await page.wait_for_function("!$('stop').disabled")
                    assert await page.locator('#stop').is_enabled()
                    await page.get_by_role('button', name='Allow once', exact=True).click()
                    await page.wait_for_function('state.sessions.find(s=>s.id==="session-00").status==="running"')
                    assert controls == [('approve', 'session-00', 'approval-0', 'accept')]
                    await open_session('session-01')
                    await page.wait_for_function("!$('stop').disabled")
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
                    assert followup_snapshot(desk.store,'session-03')==queued
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
                    for row in desk.store.sessions():
                        events = desk.store.events(row['id'])
                        if row['id'] == 'session-04':
                            # Explicit native-history import retains one compact outcome snapshot.
                            # All original message evidence stays byte-for-byte and no task is admitted.
                            original = prior_events[row['id']]
                            assert events[:len(original)] == original
                            assert [r['event'] for r in events[len(original):]] == [{
                                'method': 'desk/nativeTaskSnapshot', 'params': {
                                    'threadId': 'native-04', 'turn': {
                                        'id': 'prior-turn', 'status': 'unreported', 'error': None},
                                    'turnIds': ['prior-turn']}}]
                            continue
                        if row['id'] != 'session-01':
                            assert events == prior_events[row['id']]
                            continue
                        original = prior_events[row['id']]
                        assert events[:len(original)] == original
                        extra = [r['event'] for r in events[len(original):]]
                        assert [r['method'] for r in extra] == [
                            'desk/stopIntent', 'desk/stopReceipt', 'turn/completed', 'desk/stopReceipt']
                        assert extra[2]['params'] == {'threadId': 'native-01',
                            'turn': {'id': 'active-session-01', 'status': 'interrupted'}}
                        payload = extra[0]['params']['payload']
                        assert payload == {'session': 'session-01',
                            'token': extra[0]['params']['token'], 'threadId': 'native-01',
                            'expectedTurnId': 'active-session-01'}
                        binding = extra[0]['params']['binding']
                        assert binding == {'session': 'session-01',
                            'native_home': os.path.normcase(str(home.resolve())),
                            'cwd': bindings['session-01']['cwd'], 'profile': bindings['session-01']['profile'],
                            'thread_id': 'native-01', 'turn_id': 'active-session-01'}
                        assert extra[1]['params']['token'] == extra[3]['params']['token'] == payload['token']
                        assert extra[1]['params']['status'] == 'pending'
                        assert extra[3]['params']['status'] == 'accepted'
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
