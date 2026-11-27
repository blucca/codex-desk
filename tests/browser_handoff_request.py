"""Real loopback browser acceptance for one-target reviewed Handoff admission.

DESK_TEST_TEMP and DESK_TEST_EVIDENCE keep state and receipts isolated. Native
runtime.turn is controlled; Desk.send_followup and every HTTP route are real.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, ThreadingHTTPServer, handler
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from handoff_native_fixture import HandoffNative
from playwright.async_api import async_playwright


async def acceptance(browser, width, root, evidence):
    result = {'width': width, 'checks': [], 'javascriptErrors': []}
    with tempfile.TemporaryDirectory(dir=root, prefix='handoff-request-') as tmp:
        folder = Path(tmp)
        project = folder / 'project'
        project.mkdir()
        home, state_dir = folder / 'home', folder / 'state'
        histories = {}
        desk = Desk('not-executed', home, state_dir)
        keys = ('selected', 'held', 'cancelled', 'newer', 'edited', 'lost', 'unknown', 'rejected', 'cold', 'unavailable-unknown')
        for key in keys:
            identifier, native = 'source-' + key, 'native-' + key
            desk.store.create(str(project), 'default', identifier=identifier, name='Source ' + key)
            desk.store.update(identifier, thread_id=native, status='completed', thread_saved=1)
            histories[native] = {'id': native, 'name': 'Source ' + key, 'cwd': str(project), 'turns': [
                {'id': 'prior-' + key, 'items': [{'id': 'evidence-' + key, 'type': 'agentMessage',
                                              'text': 'Original verified evidence ' + key}]}]}
        plan = 'Exact unsent source Plan — ' + str(width)
        save_draft(desk.store, 'source-selected', plan, 'plan', 0)
        add_followup(desk.store, 'source-selected', 'Paused exact Work', 'native')
        add_followup(desk.store, 'source-selected', 'Paused exact Plan', 'plan')
        original_draft = load_draft(desk.store, 'source-selected')
        original_queue = followup_snapshot(desk.store, 'source-selected')
        native = HandoffNative(desk, histories)
        http = []
        drop_reply = {'next': False}
        class Catalog:
            def request(self, method, params):
                assert method == 'thread/list'
                return {'data': list(histories.values()), 'nextCursor': None}
        def start_server(port=0):
            desk.catalog = lambda: Catalog()
            base = handler(desk, 'fixture-private-access')
            class Handler(base):
                def do_GET(self):
                    http.append({'method': 'GET', 'path': self.path})
                    return super().do_GET()
                def do_POST(self):
                    http.append({'method': 'POST', 'path': self.path})
                    return super().do_POST()
                def reply(self, value, status=200):
                    if self.path == '/api/handoff/start' and status == 200 and drop_reply['next']:
                        drop_reply['next'] = False
                        self.close_connection = True
                        return
                    return super().reply(value, status)
            server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            return server, worker
        def stop_server():
            server.shutdown()
            server.server_close()
            worker.join(5)
            desk.close()
            desk.store.db.close()
        server, worker = start_server()
        port = server.server_port
        url = f'http://127.0.0.1:{port}'
        context = await browser.new_context(viewport={'width': width, 'height': 844})
        page = await context.new_page()
        page.set_default_timeout(10000)
        page.on('pageerror', lambda e: result['javascriptErrors'].append(str(e)))
        posts = []
        def capture_request(request):
            if request.method == 'POST' and urlsplit(request.url).path == '/api/handoff/start':
                posts.append(request.post_data_json)
        page.on('request', capture_request)
        async def select_source():
            if await page.locator('#preview').evaluate('n=>n.open'):
                await page.locator('#preview-close').click()
            await page.locator('.session-row[data-session="source-selected"] .session').click()
            await page.wait_for_function('selected === "source-selected" && !opening')
        async def review(key, goal=None):
            await page.evaluate('key=>showHandoff("native-"+key,state.sessions.find(s=>s.id==="source-"+key).cwd)', key)
            await page.wait_for_function('key=>$("preview").open && handoffSource==="native-"+key', arg=key)
            if goal is not None:
                await page.locator('#handoff-goal').fill(goal)
                await page.locator('#handoff-text').fill('Exact reviewed ' + key + ' — ' + str(width))
        async def settled(key):
            await page.wait_for_function('key=>!handoffStarts.has("native-"+key)', arg=key)
        async def source_unchanged():
            assert load_draft(desk.store, 'source-selected') == original_draft
            assert followup_snapshot(desk.store, 'source-selected') == original_queue
        async def status(token):
            return await page.evaluate('token=>api("/api/handoff/request?token="+encodeURIComponent(token))', token)
        async def no_overflow():
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
        try:
            await page.goto(url + '/#access=fixture-private-access')
            await page.wait_for_function('state.sessions.length>=9')
            await select_source()
            assert await page.locator('#prompt').input_value() == plan
            assert await page.locator('#turn-mode').input_value() == 'plan'

            # The actual Send next admission is held after its private reservation.
            await review('held', 'Held reviewed admission')
            native.hold()
            before = len(native.starts)
            await page.locator('#handoff-start').focus()
            await page.keyboard.press('Enter')
            assert await asyncio.to_thread(native.entered.wait, 10)
            await page.keyboard.press('Enter')
            await page.keyboard.press('Space')
            token = posts[-1]['token']
            pending = await status(token)
            assert pending['handoff']['status'] == 'pending'
            assert pending['preparation']['reservation'] is not None
            assert len(native.starts) == before + 1
            assert posts[-1]['source'] == 'native-held'
            native.release.set()
            await settled('held')
            await page.wait_for_function('id=>selected===id && !opening && !$("preview").open', arg=pending['id'])
            assert (await status(token))['handoff']['status'] == 'accepted'
            assert len(native.starts) == before + 1
            await source_unchanged()
            await no_overflow()
            result['checks'].append({'case': 'held duplicate key activation', 'target': pending['id'],
                                     'starts': 1, 'currentAcceptedOpenedExactTarget': True})

            # Late replies cannot reopen the old task or close a newer source modal.
            for key, other_source in [('cancelled', True), ('edited', False)]:
                await select_source()
                await review(key, 'Submitted exact ' + key)
                native.hold()
                before = len(native.starts)
                await page.locator('#handoff-start').click()
                assert await asyncio.to_thread(native.entered.wait, 10)
                old_target = 'handoff-' + posts[-1]['token'].replace('-', '')
                if other_source:
                    await page.locator('#preview-close').click()
                    await review('newer')
                goal, text = 'Newer unsent goal ' + key, 'Newer exact evidence ' + key
                await page.locator('#handoff-goal').fill(goal)
                await page.locator('#handoff-text').fill(text)
                await page.locator('#handoff-text').focus()
                native.release.set()
                await settled(key)
                await page.wait_for_function('id=>state.sessions.some(s=>s.id===id)', arg=old_target)
                assert await page.locator('#preview').evaluate('n=>n.open')
                assert await page.locator('#handoff-goal').input_value() == goal
                assert await page.locator('#handoff-text').input_value() == text
                assert await page.evaluate('selected') == 'source-selected'
                assert await page.locator('#prompt').input_value() == plan
                assert await page.locator('#turn-mode').input_value() == 'plan'
                assert await page.evaluate('document.activeElement.id') == 'handoff-text'
                assert len(native.starts) == before + 1
                await source_unchanged()
                await no_overflow()
                await page.screenshot(path=str(evidence / f'{width}-{key}-later-editor.png'))
                result['checks'].append({'case': key + ' late accepted reply', 'target': old_target,
                                         'exactNewerEditorFocusSourcePlanAndTwoQueues': True, 'starts': 1})

            # A dropped accepted local response retains the body only in memory.
            await select_source()
            await review('lost', 'Lost response exact task')
            native.mode = 'accepted'
            before, post_before = len(native.starts), len(posts)
            drop_reply['next'] = True
            await page.locator('#handoff-start').click()
            await settled('lost')
            await page.locator('#handoff-retry').wait_for()
            captured = posts[-1]
            target = 'handoff-' + captured['token'].replace('-', '')
            await page.locator('#handoff-goal').fill('Later unsent changed goal')
            await page.locator('#handoff-text').fill('Later unsent changed reviewed evidence')
            assert len(native.starts) == before + 1 and len(posts) == post_before + 1
            await page.locator('#handoff-retry').click()
            await settled('lost')
            assert posts[-1] == captured and len(posts) == post_before + 2
            assert len(native.starts) == before + 1
            assert await page.locator('#preview').evaluate('n=>n.open')
            assert await page.locator('#handoff-goal').input_value() == 'Later unsent changed goal'
            assert await page.locator('#handoff-text').input_value() == 'Later unsent changed reviewed evidence'
            assert (await status(captured['token']))['id'] == target
            await page.screenshot(path=str(evidence / f'{width}-lost-reply-recovered.png'))
            await page.locator('#handoff-open').click()
            await page.wait_for_function('id=>selected===id && !opening', arg=target)
            await source_unchanged()
            result['checks'].append({'case': 'lost accepted response explicit exact retry', 'target': target,
                                     'postsSameTokenBody': 2, 'nativeStarts': 1, 'laterEditorUnsent': True})

            # HTTP200 is retained preparation, not admission success, on rejection.
            await select_source()
            await review('rejected', 'Known rejected reviewed task')
            native.mode = 'rejected'
            before = len(native.starts)
            await page.locator('#handoff-start').click()
            await settled('rejected')
            captured = posts[-1]
            rejected = await status(captured['token'])
            assert rejected['handoff']['admission']['outcome'] == 'rejected'
            assert rejected['preparation']['reservation'] is None
            assert rejected['preparation']['entries'][0]['state'] == 'queued'
            assert await page.locator('#preview').evaluate('n=>n.open')
            assert await page.evaluate('selected') == 'source-selected'
            await page.locator('#handoff-open').click()
            await page.wait_for_function('id=>selected===id && !opening', arg=rejected['id'])
            await page.locator('#followups').evaluate('n=>n.open=true')
            await page.wait_for_function('!$("followup-send").disabled')
            native.mode = 'accepted'
            await page.locator('#followup-send').click()
            await page.wait_for_function('$("followup-count").textContent==="0"')
            assert len(native.starts) == before + 2
            assert native.starts[-1]['session'] == rejected['id']
            assert native.starts[-1]['text'] == native.starts[-2]['text']
            await select_source()
            await review('rejected')
            assert (await status(captured['token']))['handoff']['admission']['outcome'] == 'accepted'
            assert not await page.locator('#handoff-new').is_disabled()
            result['checks'].append({'case': 'known rejection retained then explicit Send next',
                                     'target': rejected['id'], 'sameTargetAndText': True, 'attempts': 2})

            # Unknown remains a blocker until the retained admission is reviewed.
            await select_source()
            await review('unknown', 'Unknown admission reviewed task')
            native.mode = 'unknown'
            before, post_before = len(native.starts), len(posts)
            await page.locator('#handoff-start').click()
            await settled('unknown')
            captured = posts[-1]
            unknown = await status(captured['token'])
            assert unknown['handoff']['admission']['outcome'] == 'unknown'
            assert unknown['preparation']['reservation']['state'] == 'unknown'
            assert await page.locator('#handoff-start').is_disabled()
            assert await page.locator('#handoff-new').is_disabled()
            assert await page.locator('#preview').evaluate('n=>n.open')
            await page.locator('#handoff-recover').click()
            assert len(native.starts) == before + 1 and len(posts) == post_before + 1
            await page.locator('#handoff-open').click()
            await page.wait_for_function('id=>selected===id && !opening', arg=unknown['id'])
            await page.locator('#followups').evaluate('n=>n.open=true')
            await page.locator('#followup-review').wait_for()
            assert await page.locator('#send').is_disabled()
            assert await page.locator('#followup-send').is_disabled()
            blocked = await page.evaluate('id=>api("/api/turn",{session:id,text:"Never admit twice",mode:"native"}).then(()=>0,e=>e.status)', unknown['id'])
            assert blocked == 409 and len(native.starts) == before + 1
            await page.screenshot(path=str(evidence / f'{width}-unknown-admission-review.png'))
            await page.locator('#followup-confirm-started').click()
            await page.wait_for_function('$("followup-review").hidden && $("followup-count").textContent==="0"')
            assert len(native.starts) == before + 1
            await select_source()
            await review('unknown')
            assert (await status(captured['token']))['handoff']['admission']['outcome'] == 'accepted'
            assert not await page.locator('#handoff-new').is_disabled()
            result['checks'].append({'case': 'unknown blocked then explicit retained admission review',
                                     'target': unknown['id'], 'ordinaryTurnStatus': blocked,
                                     'nativeStartsBeforeAfterReview': 1})

            # Keep a separate unreviewed reservation for source-unavailable cold
            # recovery; the earlier unknown case deliberately resolved its own.
            await select_source()
            await review('unavailable-unknown', 'Unconfirmed source-unavailable task')
            native.mode = 'unknown'
            await page.locator('#handoff-start').click()
            await settled('unavailable-unknown')
            unavailable_unknown_body = posts[-1]
            unavailable_unknown = await status(unavailable_unknown_body['token'])
            assert unavailable_unknown['preparation']['reservation']['state'] == 'unknown'

            # Cold source return is the same tab, origin, state and opaque token.
            await select_source()
            await review('cold', 'Cold recovery original task')
            native.mode = 'accepted'
            before = len(native.starts)
            drop_reply['next'] = True
            await page.locator('#handoff-start').click()
            await settled('cold')
            cold_body = posts[-1]
            retained = await status(cold_body['token'])
            storage = await page.evaluate('Object.fromEntries(Object.entries(sessionStorage))')
            all_storage = json.dumps(storage)
            assert cold_body['token'] in all_storage
            for secret in (cold_body['goal'], cold_body['text'], 'fixture-private-access'):
                # Access already has its own existing storage key, never a new one.
                if secret == 'fixture-private-access':
                    assert storage['codex-desk-access'] == secret
                else:
                    assert secret not in all_storage
            assert len(native.starts) == before + 1
            # Return to Home before restarting, so ordinary saved-session auto
            # attachment is outside this admission-token recovery acceptance.
            await page.evaluate('localStorage.removeItem("codex-desk-session")')
            stop_server()
            desk = Desk('not-executed', home, state_dir)
            cold_native_calls = []
            desk.runtime = lambda id: cold_native_calls.append(id) or (_ for _ in ()).throw(AssertionError('Cold read invoked native work'))
            desk.history = lambda id: histories[id]
            desk.open = lambda id: (_ for _ in ()).throw(AssertionError('Cold recovery opened native target'))
            server, worker = start_server(port)
            boundary = len(http)
            post_before = len(posts)
            await page.reload()
            await page.wait_for_function('state.sessions.length>=9')
            await review('cold')
            await page.locator('#handoff-recover').click()
            await page.locator('#handoff-open').wait_for()
            assert len(posts) == post_before and cold_native_calls == []
            cold_http = http[boundary:]
            assert not any(entry['method'] == 'POST' and entry['path'] in ('/api/handoff/start', '/api/open', '/api/turn', '/api/followups/send') for entry in cold_http)
            assert any(entry['method'] == 'GET' and entry['path'].startswith('/api/handoff/request?') for entry in cold_http)
            assert await page.locator('#handoff-retry').is_hidden()
            assert (await status(cold_body['token']))['id'] == retained['id']
            await source_unchanged()
            await no_overflow()
            await page.screenshot(path=str(evidence / f'{width}-cold-same-port-state.png'))
            result['checks'].append({'case': 'cold same-port state opaque-token read', 'target': retained['id'],
                                     'samePort': port, 'taskPosts': 0, 'nativeCalls': 0,
                                     'browserStorageOnlyOpaqueToken': True, 'http': cold_http})

            # Loss of the source's native history cannot hide an already saved
            # target or turn the unconfirmed reservation into success.
            def unavailable_history(identifier):
                raise FileNotFoundError('Original source history no longer available')
            desk.history = unavailable_history
            explicit_opens = []
            def open_retained(identifier):
                explicit_opens.append(identifier)
                row = desk.store.get(identifier)
                return {'thread': {'id': row['thread_id'], 'cwd': row['cwd'], 'turns': []},
                        'model': 'fixture', 'modelProvider': 'fixture'}
            desk.open = open_retained
            for key, body, original in [('cold', cold_body, retained),
                                        ('unavailable-unknown', unavailable_unknown_body, unavailable_unknown)]:
                if await page.locator('#preview').evaluate('n=>n.open'):
                    await page.locator('#preview-close').click()
                boundary = len(http)
                await review(key)
                await page.locator('#handoff-error').wait_for()
                assert 'Original source history no longer available' in await page.locator('#handoff-error').inner_text()
                assert await page.locator('#handoff-open').is_enabled()
                assert await page.locator('#handoff-retry').is_hidden()
                assert await page.locator('#handoff-start').is_disabled()
                recover_boundary = len(http)
                await page.locator('#handoff-recover').click()
                await page.wait_for_function('!$("handoff-recover").disabled')
                recovered = await status(body['token'])
                assert recovered['id'] == original['id']
                assert len(posts) == post_before and cold_native_calls == []
                recovery_http = http[recover_boundary:]
                assert recovery_http and all(entry['method'] == 'GET' for entry in recovery_http)
                assert not any(entry['method'] == 'POST' and entry['path'] in ('/api/handoff/start', '/api/open', '/api/turn', '/api/followups/send') for entry in http[boundary:])
                if key == 'unavailable-unknown':
                    assert recovered['preparation']['reservation']['state'] == 'unknown'
                    assert await page.locator('#handoff-new').is_disabled()
                else:
                    assert recovered['handoff']['admission']['outcome'] == 'accepted'
                await page.screenshot(path=str(evidence / f'{width}-{key}-source-unavailable.png'))
                await page.locator('#handoff-open').click()
                await page.wait_for_function('id=>selected===id && !opening', arg=original['id'])
                assert explicit_opens[-1] == original['id']
                assert len(posts) == post_before and cold_native_calls == []
                if key == 'unavailable-unknown':
                    await page.locator('#followups').evaluate('n=>n.open=true')
                    await page.locator('#followup-review').wait_for()
                    assert await page.locator('#send').is_disabled()
                result['checks'].append({'case': key + ' retained target despite unavailable original source',
                                         'target': original['id'], 'recoveryGetsOnly': True,
                                         'explicitOpenReachedExactTarget': True, 'nativeStarts': 0})
            await source_unchanged()
            assert not result['javascriptErrors'], result['javascriptErrors']
        finally:
            native.release.set()
            await context.close()
            stop_server()
            result['handoffPosts'] = posts
            result['nativeBoundaryCalls'] = native.calls
            (evidence / f'result-{width}.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result), flush=True)
    return result


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    evidence = Path(os.environ['DESK_TEST_EVIDENCE'])
    root.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                                          args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            results = [await acceptance(browser, width, root, evidence) for width in (390, 1250)]
            (evidence / 'result.json').write_text(json.dumps({'cases': results}, indent=2) + '\n')
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(check())
