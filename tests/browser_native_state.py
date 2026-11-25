"""Native retry/error/capacity presentation through real loopback event replay.

DESK_TEST_TEMP=/your/workspace/temp DESK_CHROMIUM=/path/to/chromium \
  python tests/browser_native_state.py

Retains Runtime's incoming-event lifecycle with controlled metadata attachment.
No native process, model task, provider request or account operation is started.
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

if not os.environ.get('DESK_USE_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk import server as desk_server
from codex_desk.runtime import Runtime, save_profile
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-native-state-') as temporary:
        folder = Path(temporary)
        evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(folder / 'evidence')))
        evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
        home = folder / 'native-home'
        home.mkdir()
        (home / 'config.toml').write_text('model="fixture-model"\n')
        (home / 'auth.json').write_text('{"synthetic":"unchanged"}\n')
        profile = save_profile(home, 'retained', 'https://fixture.example/v1',
                               'fixture-model', 'synthetic-only-key')['id']
        settings = {p.name: p.read_bytes() for p in home.iterdir()}
        threads, native_calls, errors, external, passed = {}, [], [], [], []

        class ControlledRuntime(Runtime):
            def __init__(self, store, identifier, binary, native_home):
                assert binary == 'never-executed'
                self.store, self.id, self.home = store, identifier, native_home
                self.process = SimpleNamespace(poll=lambda: None)
                self.pending, self.approvals = {}, {}
                self.lock, self.write_lock = threading.Lock(), threading.Lock()
                self.name_lock = threading.RLock()
                self.lifecycle_lock, self.turn_lock = threading.Lock(), threading.Lock()
                self.closing, self.persisted = False, False

            def request(self, method, params, timeout=30):
                native_calls.append({'method': method, 'session': self.id})
                assert method == 'thread/resume', 'Unexpected native request: ' + method
                return {'thread': threads[self.id], 'model': 'fixture-model',
                        'modelProvider': 'desk_provider'}

            def close(self):
                with self.lifecycle_lock:
                    self.closing = True
                    self._mark_exited()
                    self.process.poll = lambda: 0

        with patch.object(desk_server, 'Runtime', ControlledRuntime):
            desk = desk_server.Desk('never-executed', home, folder / 'state')
            for identifier, name in (('session-a', 'Native task A'), ('session-b', 'Separate project B')):
                cwd = folder / identifier
                cwd.mkdir()
                desk.store.create(str(cwd), profile, identifier=identifier, name=name)
                desk.store.update(identifier, thread_id='native-' + identifier,
                    status='completed', thread_saved=1, model='fixture-model',
                    provider='desk_provider', name_pending=0)
                threads[identifier] = {'id': 'native-' + identifier, 'cwd': str(cwd),
                    'name': name, 'turns': [{'id': 'prior-turn', 'items': [{
                        'id': 'prior-' + identifier, 'type': 'agentMessage',
                        'text': 'Earlier evidence for ' + identifier}]}]}
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever,
                kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            url = f'http://127.0.0.1:{server.server_port}'

            def emit(method, params, identifier='session-a', request_id=None):
                message = {'method': method, 'params': {
                    'threadId': threads[identifier]['id'], **params}}
                if request_id is not None:
                    message['id'] = request_id
                runtime = desk.runtimes[identifier]
                with runtime.lifecycle_lock:
                    runtime._message(message)

            def checkpoint(name):
                passed.append(name)
                print(json.dumps({'passed': name, 'provider_inference_turns': 0}), flush=True)

            try:
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(
                        executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                        args=['--no-sandbox', '--disable-dev-shm-usage'])
                    page = await browser.new_page(viewport={'width': 1250, 'height': 900})
                    page.set_default_timeout(10_000)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: external.append(request.url)
                        if urlsplit(request.url).hostname != '127.0.0.1' else None)

                    async def open_session(identifier):
                        await page.locator(f'.session-row[data-session="{identifier}"] .session').click()
                        await page.wait_for_function(
                            'id=>selected===id && !opening && !$("task").hidden', arg=identifier)

                    async def replay():
                        await page.evaluate('pollActivity()')
                        await page.evaluate('refresh()')

                    async def layout(label, width):
                        await page.set_viewport_size({'width': width,
                            'height': 900 if width == 1250 else 844})
                        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
                        await page.screenshot(path=str(evidence / f'{label}-{width}.png'), full_page=True)

                    try:
                        await page.goto(url)
                        await page.wait_for_function('state.sessions.length===2')
                        await open_session('session-a')
                        assert 'Usage appears after native Codex reports it' in await page.locator('#usage').inner_text()
                        emit('thread/tokenUsage/updated', {'tokenUsage': {
                            'total': {'inputTokens': 380_000, 'cachedInputTokens': 310_000,
                                      'outputTokens': 50_000},
                            'last': {'inputTokens': 1_200, 'cachedInputTokens': 200, 'outputTokens': 80},
                            'modelContextWindow': 32_768}})
                        await replay()
                        usage = await page.locator('#usage').inner_text()
                        assert '380,000' in usage and '310,000' in usage and '50,000' in usage
                        assert 'Latest request input · 1,200 tokens' in usage
                        assert 'reported model context window 32,768' in usage
                        assert not any(word in usage.lower() for word in ('remaining', 'occupied', 'percent', '%'))
                        emit('thread/tokenUsage/updated', {'tokenUsage': {
                            'total': {'inputTokens': 381_200, 'cachedInputTokens': 310_200, 'outputTokens': 50_080},
                            'last': {'inputTokens': 800}, 'modelContextWindow': 32_768}})
                        await replay()
                        usage = await page.locator('#usage').inner_text()
                        assert '381,200' in usage and '761,200' not in usage
                        assert 'Latest request input · 800 tokens' in usage
                        checkpoint('native cumulative totals replace snapshots; latest request and window remain separate')

                        for malformed in (None, '{broken', 'null', '[]', '{"total":42,"last":[]}',
                                '{"total":{"inputTokens":"bad","outputTokens":-1},"modelContextWindow":"bad"}'):
                            desk.store.update('session-a', usage=malformed)
                            await page.evaluate('refresh()')
                            assert await page.locator('#usage').inner_text()
                            assert not errors, errors
                        checkpoint('missing and malformed usage is harmless and does not invent capacity')

                        emit('turn/started', {'turn': {'id': 'fixture-active-turn', 'status': 'inProgress'}})
                        partial = 'Partial native answer retained before retry and failure.\n接口检查完成第一步。'
                        emit('item/agentMessage/delta', {'itemId': 'partial-native-output', 'delta': partial})
                        emit('item/commandExecution/requestApproval', {
                            'turnId': 'fixture-active-turn', 'command': 'fixture-read-only-check'}, request_id=301)
                        emit('error', {'willRetry': True, 'error': {
                            'message': 'Native transient rate limit; retrying the original task',
                            'codexErrorInfo': 'rateLimitExceeded'}})
                        await replay()
                        retry = page.locator('#activity .native-error-card').filter(has_text='Native retry in progress')
                        assert await retry.count() >= 1
                        assert 'Native Codex is retrying this turn' in await retry.first.inner_text()
                        assert await page.locator('#status').inner_text() == 'approval'
                        assert await page.locator('#send').is_disabled()
                        assert await page.locator('#native-failure').is_hidden()
                        assert ' '.join(partial.splitlines()) in (await page.locator('#activity').inner_text()).replace('\n', ' ')
                        assert await page.locator('#approvals').get_by_role('button', name='Allow once', exact=True).count() == 1
                        checkpoint('willRetry native error stays distinct and preserves partial output and approval state')

                        emit('serverRequest/resolved', {'requestId': 301})
                        malicious = '<img src="https://invalid.example/pixel" onerror="globalThis.nativeStatePwned=true">\n<script>globalThis.nativeStatePwned=true</script>\n' + 'long-details-token-' * 35
                        cases = (
                            ('contextWindowExceeded', 'Native model context window exceeded', 'continue in a new conversation', None),
                            ('modelNotFound', 'The selected native model was not found', 'model name', None),
                            ('unauthorized', 'Native provider authorization rejected', 'profile’s key', None),
                            ('responseStreamDisconnected', 'Native response stream disconnected', 'provider connection', 502),
                        )
                        for index, (code, message, action, http) in enumerate(cases):
                            if index:
                                emit('turn/started', {'turn': {'id': 'fixture-error-' + str(index), 'status': 'inProgress'}})
                            info = {code: {'httpStatusCode': http}} if http is not None else code
                            error = {'message': message, 'codexErrorInfo': info, 'additionalDetails': malicious}
                            emit('error', {'willRetry': False, 'error': error})
                            emit('turn/completed', {'turn': {'id': 'fixture-error-' + str(index),
                                'status': 'failed', 'items': [], 'error': error}})
                            await replay()
                            failure = page.locator('#native-failure .native-error-card')
                            assert await failure.count() == 1
                            text = await failure.inner_text()
                            assert 'Native task failed' in text and message in text and code in text
                            assert action in text
                            assert '"codexErrorInfo"' not in text and '"message":' not in text
                            if http is not None:
                                assert 'HTTP 502' in text
                            assert await page.locator('#status').inner_text() == 'failed'
                            assert ' '.join(partial.splitlines()) in (await page.locator('#activity').inner_text()).replace('\n', ' ')
                            await failure.locator('summary').click()
                            assert await failure.locator('pre').text_content() == malicious
                            assert await failure.locator('img,script').count() == 0
                            assert await page.evaluate('globalThis.nativeStatePwned') is None
                            assert not external, external
                            if index in (0, len(cases) - 1):
                                await layout(code, 1250)
                                await layout(code, 390)
                        checkpoint('typed final context/model/auth/HTTP-stream failures show useful actions and preserve literal details')

                        await open_session('session-b')
                        assert await page.locator('#native-failure').is_hidden()
                        assert await page.locator('#activity .native-error-card').count() == 0
                        assert partial.splitlines()[0] not in await page.locator('#activity').inner_text()
                        assert 'Usage appears after native Codex reports it' in await page.locator('#usage').inner_text()
                        await open_session('session-a')
                        await replay()
                        assert ' '.join(partial.splitlines()) in (await page.locator('#activity').inner_text()).replace('\n', ' ')
                        assert 'Native response stream disconnected' in await page.locator('#native-failure').inner_text()
                        desk.store.update('session-a', status='failed', error='Native app-server exited; reopen this session')
                        await page.evaluate('refresh()')
                        assert 'Native app-server exited; reopen this session' in await page.locator('#native-failure').inner_text()
                        assert not errors, errors
                        checkpoint('session switch clears old failure; same-session replay retains output and plain native message')

                        assert all(call['method'] == 'thread/resume' for call in native_calls)
                        assert not external and not errors
                        assert {p.name: p.read_bytes() for p in home.iterdir()} == settings
                        result = {'passed': passed, 'javascript_errors': errors, 'external_requests': external,
                            'native_processes': 0, 'provider_inference_turns': 0, 'native_turn_callbacks': 0,
                            'metadata_callbacks': native_calls, 'overflow_1250': False, 'overflow_390': False}
                        (evidence / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
                        print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
                    except Exception:
                        diagnostic = {'passed': passed, 'javascript_errors': errors, 'external_requests': external,
                            'sessions': desk.store.sessions(), 'native_calls': native_calls}
                        try:
                            diagnostic['page'] = await page.evaluate('({selected,usage:$("usage").textContent,failure:$("native-failure").textContent,activity:$("activity").textContent})')
                            await page.screenshot(path=str(evidence / 'failure.png'), full_page=True)
                        except Exception:
                            pass
                        (evidence / 'failure.json').write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False) + '\n')
                        print(json.dumps({'failure': diagnostic}, ensure_ascii=False), flush=True)
                        raise
                    finally:
                        await browser.close()
                        for path in evidence.iterdir():
                            if path.is_file():
                                path.chmod(0o600)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)
                desk.close()
                desk.store.db.close()


if __name__ == '__main__':
    asyncio.run(check())
