"""Durable task preparation through real loopback HTTP and controlled native callbacks.

DESK_TEST_TEMP=/your/workspace/temp DESK_CHROMIUM=/path/to/chromium \
  python tests/browser_drafts.py
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
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk import server as desk_server
from codex_desk.drafts import load_draft
from codex_desk.runtime import Runtime, NativeRequestRejected, save_profile
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-drafts-') as temporary:
        folder = Path(temporary)
        evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(folder / 'evidence')))
        evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
        home, state_dir = folder / 'native-home', folder / 'state'
        home.mkdir()
        (home / 'config.toml').write_text('model="fixture"\n')
        profile = save_profile(home, 'retained', 'https://fixture.example/v1', 'fixture', 'synthetic-only')['id']
        settings_before = {p.name: p.read_bytes() for p in home.iterdir()}
        projects = {id: folder / name for id, name in (
            ('session-a', 'project-a'), ('session-b', 'project-b'))}
        for project in projects.values():
            project.mkdir()
        threads = {id: {'id': 'native-' + id, 'cwd': str(cwd), 'name': 'Project ' + id[-1].upper(),
            'turns': [{'id': 'earlier-turn', 'items': [
                {'id': 'earlier-message-' + id, 'type': 'agentMessage', 'text': 'Earlier project evidence retained.'}]}]}
            for id, cwd in projects.items()}
        native_calls, http_calls, holds, draft_holds, draft_reply_holds, errors, completed = [], [], {}, {}, {}, [], []
        original_save = desk_server.save_draft

        def controlled_save(store, session, text, mode, revision, *extra, **options):
            if text in draft_holds:
                entered, release = draft_holds[text]
                entered.set()
                assert release.wait(25), 'Held draft save was not released'
            saved = original_save(store, session, text, mode, revision, *extra, **options)
            if text in draft_reply_holds:
                entered, release = draft_reply_holds[text]
                entered.set()
                assert release.wait(25), 'Held draft reply was not released'
            return saved

        class ControlledRuntime(Runtime):
            def __init__(self, store, identifier, binary, native_home):
                assert binary == 'never-executed'
                self.store, self.id, self.home = store, identifier, native_home
                self.process = SimpleNamespace(poll=lambda: None)
                self.approvals = {}
                self.persisted = False
                self.name_lock = threading.RLock()
                self.lifecycle_lock, self.turn_lock = threading.Lock(), threading.Lock()

            def request(self, method, params):
                native_calls.append({'method': method, 'session': self.id, 'params': params})
                if method == 'thread/list':
                    return {'data': [], 'nextCursor': None}
                if method == 'thread/resume':
                    return {'thread': threads[self.id], 'model': 'fixture', 'modelProvider': 'desk_provider'}
                assert method == 'turn/start', 'Unexpected native request: ' + method
                text = params['input'][0]['text']
                if text == 'Fixture rejected task A':
                    raise NativeRequestRejected('Fixture turn rejected; keep preparation')
                if text in holds:
                    entered, release = holds[text]
                    entered.set()
                    assert release.wait(25), 'Held turn not released: ' + text
                return {'turn': {'id': 'controlled-turn-' + str(len(native_calls)), 'status': 'completed'}}

            def close(self):
                self.process.poll = lambda: 0

        def start_server(port=0, seed=False):
            desk = desk_server.Desk('never-executed', home, state_dir)
            if seed:
                for id, cwd in projects.items():
                    desk.store.create(str(cwd), profile, identifier=id, name=threads[id]['name'])
                    desk.store.update(id, thread_id=threads[id]['id'], status='completed', thread_saved=1,
                                      model='fixture', provider='desk_provider', name_pending=0)
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', port), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
            worker.start()
            return desk, server, worker

        def stop_server(desk, server, worker):
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            desk.close()
            desk.store.db.close()

        def turns():
            return [call for call in native_calls if call['method'] == 'turn/start']

        def checkpoint(name):
            completed.append(name)
            print(json.dumps({'passed': name, 'accepted_or_rejected_controlled_turns': len(turns())}), flush=True)

        with patch.object(desk_server, 'Runtime', ControlledRuntime), \
                patch.object(desk_server, 'save_draft', controlled_save):
            desk, server, worker = start_server(seed=True)
            port = server.server_port
            url = f'http://127.0.0.1:{port}'
            try:
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                        headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                    context = await browser.new_context(viewport={'width': 1280, 'height': 900})
                    pages = []

                    async def new_page():
                        page = await context.new_page()
                        page.set_default_timeout(10_000)
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('request', lambda request: http_calls.append({
                            'path': urlsplit(request.url).path, 'method': request.method}))
                        pages.append(page)
                        await page.goto(url)
                        await page.wait_for_function('state.sessions.length === 2')
                        return page

                    async def open_session(page, id):
                        await page.locator('#sessions button').filter(has_text=threads[id]['name']).click()
                        await page.wait_for_function("id => selected === id && !opening && !$('task').hidden", arg=id)

                    async def saved(page, id, text, mode):
                        await page.wait_for_function("""v => {
                            const s=draftSaved.get(v.id);
                            return s && s.text===v.text && s.mode===v.mode;
                        }""", arg={'id': id, 'text': text, 'mode': mode})
                        actual = load_draft(desk.store, id)
                        assert actual['text'] == text and actual['mode'] == mode, actual
                        return actual

                    async def prepare(page, id, text, mode):
                        await page.locator('#prompt').fill(text)
                        await page.locator('#turn-mode').select_option(mode)
                        return await saved(page, id, text, mode)

                    async def exact(page, id, text, mode):
                        assert await page.evaluate('selected') == id
                        assert await page.locator('#prompt').input_value() == text
                        assert await page.locator('#turn-mode').input_value() == mode

                    async def held_send(page, text):
                        holds[text] = (threading.Event(), threading.Event())
                        await page.locator('#send').click()
                        assert await asyncio.to_thread(holds[text][0].wait, 10), 'Turn did not reach native callback'
                        return holds[text][1]

                    async def release_send(page, release):
                        async with page.expect_response(lambda response:
                                urlsplit(response.url).path == '/api/turn') as response:
                            release.set()
                        assert (await response.value).status == 200
                        await page.wait_for_function('submitting.size === 0')

                    try:
                        page = await new_page()
                        await open_session(page, 'session-a')
                        text_a = '  Inspect parser "接口" next\nKeep changes unsent. 🔧\n'
                        text_b = 'Verify only project B\n  trailing prep  '
                        await prepare(page, 'session-a', text_a, 'plan')
                        await open_session(page, 'session-b')
                        await prepare(page, 'session-b', text_b, 'native')
                        await open_session(page, 'session-a')
                        await exact(page, 'session-a', text_a, 'plan')
                        assert not turns()
                        checkpoint('isolated A/B autosave and cached Plan restore')

                        await page.reload()
                        await page.wait_for_function("selected==='session-a' && !opening && !$('task').hidden")
                        await exact(page, 'session-a', text_a, 'plan')
                        await open_session(page, 'session-b')
                        await exact(page, 'session-b', text_b, 'native')
                        assert not turns()
                        checkpoint('browser refresh restores exact text and mode without submission')

                        await open_session(page, 'session-a')
                        text_a = 'A preparation survives closing its page during autosave'
                        draft_holds[text_a] = (threading.Event(), threading.Event())
                        await page.locator('#prompt').fill(text_a)
                        assert await asyncio.to_thread(draft_holds[text_a][0].wait, 10)
                        await page.close()
                        draft_holds[text_a][1].set()
                        deadline = asyncio.get_running_loop().time() + 10
                        while load_draft(desk.store, 'session-a')['text'] != text_a:
                            assert asyncio.get_running_loop().time() < deadline, 'Closed-page draft was lost'
                            await asyncio.sleep(0.03)
                        page = await new_page()
                        await page.wait_for_function("selected==='session-a' && !opening && !$('task').hidden")
                        await exact(page, 'session-a', text_a, 'plan')
                        await open_session(page, 'session-b')
                        await exact(page, 'session-b', text_b, 'native')
                        assert not turns()
                        checkpoint('page close during in-flight autosave restores without submission')

                        # Let a second autosave queue behind a committed save whose
                        # HTTP reply is delayed, then reload after its timer expires.
                        await open_session(page, 'session-a')
                        first = 'First committed preparation with delayed reply'
                        newest = 'Latest queued preparation before reload'
                        draft_reply_holds[first] = (threading.Event(), threading.Event())
                        await page.locator('#prompt').fill(first)
                        assert await asyncio.to_thread(draft_reply_holds[first][0].wait, 10)
                        assert load_draft(desk.store, 'session-a')['text'] == first
                        await page.locator('#prompt').fill(newest)
                        await page.locator('#turn-mode').select_option('native')
                        await page.wait_for_function("!draftTimers.has('session-a')")
                        assert load_draft(desk.store, 'session-a')['text'] == first
                        await page.reload()
                        await page.wait_for_function("selected==='session-a' && !opening && !$('task').hidden")
                        draft_reply_holds[first][1].set()
                        await exact(page, 'session-a', newest, 'native')
                        assert load_draft(desk.store, 'session-a')['text'] == newest
                        text_a = newest
                        assert not turns()
                        checkpoint('reload flushes newer queued autosave after debounce expires')
                        await prepare(page, 'session-a', newest, 'plan')
                        await open_session(page, 'session-b')

                        await page.goto('about:blank')
                        await asyncio.to_thread(stop_server, desk, server, worker)
                        desk, server, worker = start_server(port=port)
                        await page.goto(url)
                        await page.wait_for_function("selected==='session-b' && !opening && !$('task').hidden")
                        await exact(page, 'session-b', text_b, 'native')
                        await open_session(page, 'session-a')
                        await exact(page, 'session-a', text_a, 'plan')
                        assert not turns()
                        checkpoint('actual Desk and SQLite restart retains both preparations')

                        await prepare(page, 'session-a', 'Fixture rejected task A', 'native')
                        async with page.expect_response(lambda response:
                                urlsplit(response.url).path == '/api/turn') as response:
                            await page.locator('#send').click()
                        reply = await response.value
                        assert reply.status == 200
                        rejected = await reply.json()
                        assert rejected['request']['status'] == 'rejected', rejected
                        await page.wait_for_function("submitting.size===0 && turnRequest(selected)?.status==='rejected' && !$('turn-request-error').hidden")
                        assert 'Fixture turn rejected' in await page.locator('#turn-request-error').inner_text()
                        assert rejected['request']['payload']['text'] == 'Fixture rejected task A'
                        assert rejected['request']['payload']['mode'] == 'native'
                        assert await page.evaluate('turnRequest(selected).token') == rejected['token']
                        await exact(page, 'session-a', 'Fixture rejected task A', 'native')
                        retained = await saved(page, 'session-a', 'Fixture rejected task A', 'native')
                        assert rejected['request']['payload']['revision'] == retained['revision']
                        assert await page.evaluate('turnRequest(selected).body.writer===draftWriter && turnRequest(selected).body.sequence===draftEdits.get(selected)')
                        await page.locator('#send').click()
                        await page.wait_for_function('!turnRequest(selected).reading')
                        assert len(turns()) == 1
                        await exact(page, 'session-a', 'Fixture rejected task A', 'native')
                        checkpoint('known rejected receipt preserves exact provenance and repeated Run only checks')

                        await prepare(page, 'session-a', 'Accepted exact task A', 'plan')
                        assert await page.evaluate('turnRequest(selected).token') == rejected['token']
                        assert len(turns()) == 1
                        await page.locator('#turn-request-new').click()
                        await page.wait_for_function('!turnRequest(selected)')
                        await exact(page, 'session-a', 'Accepted exact task A', 'plan')
                        await page.locator('#send').click()
                        await page.wait_for_function("submitting.size===0 && $('prompt').value===''")
                        await saved(page, 'session-a', '', 'plan')
                        assert load_draft(desk.store, 'session-b')['text'] == text_b
                        assert len(turns()) == 2
                        checkpoint('accepted unchanged version clears only A')

                        await prepare(page, 'session-a', 'Delayed original task A', 'native')
                        release = await held_send(page, 'Delayed original task A')
                        newer_a, newer_b = 'A newer preparation while its turn waits', 'B different project preparation'
                        await page.locator('#prompt').fill(newer_a)
                        await saved(page, 'session-a', newer_a, 'native')
                        await open_session(page, 'session-b')
                        await prepare(page, 'session-b', newer_b, 'plan')
                        await page.locator('#prompt').focus()
                        await release_send(page, release)
                        await exact(page, 'session-b', newer_b, 'plan')
                        assert await page.evaluate("document.activeElement===$('prompt')")
                        assert load_draft(desk.store, 'session-a')['text'] == newer_a
                        await open_session(page, 'session-a')
                        await exact(page, 'session-a', newer_a, 'native')
                        assert len(turns()) == 3
                        checkpoint('delayed A acceptance retains newer A and selected B')

                        # Retained acceptance cannot turn a newer editor into an
                        # implicit replay. A new task requires explicit identity.
                        await page.wait_for_function("turnRequest(selected)?.status==='accepted'")
                        await page.locator('#turn-request-new').click()
                        await page.wait_for_function('!turnRequest(selected)')
                        await exact(page, 'session-a', newer_a, 'native')
                        assert len(turns()) == 3

                        # A newer revision must survive even if edits return to identical text.
                        repeated = 'Same text, newly reviewed preparation A'
                        sent = await prepare(page, 'session-a', repeated, 'native')
                        release = await held_send(page, repeated)
                        await page.locator('#prompt').fill('Intermediate new preparation A')
                        changed = await saved(page, 'session-a', 'Intermediate new preparation A', 'native')
                        await page.locator('#prompt').fill(repeated)
                        latest = await saved(page, 'session-a', repeated, 'native')
                        assert sent['revision'] < changed['revision'] < latest['revision']
                        await page.locator('#prompt').focus()
                        await page.locator('#prompt').evaluate('(node)=>node.setSelectionRange(3,9)')
                        await release_send(page, release)
                        await exact(page, 'session-a', repeated, 'native')
                        assert await page.evaluate("document.activeElement===$('prompt') && $('prompt').selectionStart===3 && $('prompt').selectionEnd===9")
                        assert load_draft(desk.store, 'session-a') == latest
                        assert len(turns()) == 4
                        checkpoint('accepted old version does not clear a newer identical-text revision')

                        # Both tabs first load the same saved revision.
                        await page.reload()
                        await page.wait_for_function("selected==='session-a' && !opening && !$('task').hidden")
                        second = await new_page()
                        await second.wait_for_function("selected==='session-a' && !opening && !$('task').hidden")
                        tab_newest, tab_candidate = 'Newest saved in second tab', 'First tab candidate not yet chosen'
                        await prepare(second, 'session-a', tab_newest, 'plan')
                        await page.locator('#prompt').fill(tab_candidate)
                        await page.wait_for_function("!$('draft-conflict').hidden")
                        await exact(page, 'session-a', tab_candidate, 'native')
                        assert load_draft(desk.store, 'session-a')['text'] == tab_newest
                        assert await page.evaluate("draftConflicts.get(selected).text") == tab_newest
                        assert len(turns()) == 4
                        await page.set_viewport_size({'width': 390, 'height': 844})
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        await page.screenshot(path=str(evidence / 'draft-conflict-390.png'), full_page=True)
                        await page.locator('#draft-keep').click()
                        await saved(page, 'session-a', tab_candidate, 'native')
                        assert await page.locator('#draft-conflict').is_hidden()
                        checkpoint('two-tab conflict keeps candidate and saved newest until explicit Keep')

                        await second.locator('#prompt').fill('Second tab new candidate before Load')
                        await second.wait_for_function("!$('draft-conflict').hidden")
                        assert await second.locator('#prompt').input_value() == 'Second tab new candidate before Load'
                        assert load_draft(desk.store, 'session-a')['text'] == tab_candidate
                        await second.locator('#draft-load').click()
                        await exact(second, 'session-a', tab_candidate, 'native')
                        assert await second.locator('#draft-conflict').is_hidden()
                        assert len(turns()) == 4
                        checkpoint('explicit Load restores chosen saved text/mode without submitting')

                        await page.set_viewport_size({'width': 1280, 'height': 900})
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        await page.screenshot(path=str(evidence / 'draft-restored-1280.png'), full_page=True)
                        assert not errors, errors
                        assert {p.name: p.read_bytes() for p in home.iterdir()} == settings_before
                        result = {'passed': completed, 'controlled_turns': len(turns()),
                            'native_processes': 0, 'provider_inference_turns': 0, 'javascript_errors': errors,
                            'overflow_390': False, 'overflow_1280': False, 'drafts': {
                                id: load_draft(desk.store, id) for id in projects}}
                        (evidence / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
                        print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
                    except Exception:
                        diagnostic = {'passed': completed, 'javascript_errors': errors,
                            'drafts': {id: load_draft(desk.store, id) for id in projects},
                            'recent_http_calls': http_calls[-15:], 'controlled_turns': turns()}
                        if pages:
                            try:
                                diagnostic['page'] = await pages[0].evaluate("""() => ({selected,
                                    text:$('prompt').value,mode:$('turn-mode').value,
                                    status:$('draft-status').textContent,conflict:!$('draft-conflict').hidden})""")
                                await pages[0].screenshot(path=str(evidence / 'failure.png'), full_page=True)
                            except Exception:
                                pass
                        (evidence / 'failure.json').write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False) + '\n')
                        print(json.dumps({'failure': diagnostic}, indent=2, ensure_ascii=False), flush=True)
                        raise
                    finally:
                        for _, release in [*holds.values(), *draft_holds.values(), *draft_reply_holds.values()]:
                            release.set()
                        await context.close()
                        await browser.close()
                        for path in evidence.iterdir():
                            if path.is_file():
                                path.chmod(0o600)
            finally:
                for _, release in [*holds.values(), *draft_holds.values(), *draft_reply_holds.values()]:
                    release.set()
                stop_server(desk, server, worker)


if __name__ == '__main__':
    asyncio.run(check())
