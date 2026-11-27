#!/usr/bin/env python3
"""Installed native task-response reader acceptance with synthetic native originals.

DESK_SOURCE=/absolute/source DESK_USE_INSTALLED=1 DESK_TEST_TEMP=/workspace/temp \
DESK_TEST_EVIDENCE=/private/evidence PLAYWRIGHT_BROWSERS_PATH=/isolated/chromium \
  /isolated/env/bin/python examples/check_native_task_response.py

Uses actual loopback HTTP, SQLite, installed static assets and isolated Chromium.
The controlled transport permits original reads only; no executable or model task.
"""
import asyncio
import copy
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

SOURCE = Path(os.environ.get('DESK_SOURCE', Path(__file__).resolve().parents[1])).resolve()
if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(SOURCE))
import codex_desk
from codex_desk import server as product
from codex_desk.runtime import Runtime
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright

PACKAGE = Path(codex_desk.__file__).resolve()
if os.environ.get('DESK_USE_INSTALLED') == '1':
    assert not PACKAGE.is_relative_to(SOURCE), 'Installed check imported the source checkout'
if os.environ.get('DESK_INSTALLED_ROOT'):
    assert PACKAGE.is_relative_to(Path(os.environ['DESK_INSTALLED_ROOT']).resolve())
if os.environ.get('DESK_EXPECT_VERSION'):
    assert codex_desk.__version__ == os.environ['DESK_EXPECT_VERSION']

PARENT, ORIGINAL, OTHER = 'native-parent', 'response-plan', 'other-work'
TURN, ITEM = 'captured-failed-turn', 'captured-last-final'
PHRASE = 'EXACT RESPONSE Café 项目 🚀'
TEXT = 'RESPONSE START\n' + '\n'.join(
    f'Native exact source line {i:04d}: keep unsent draft and queue — Café 项目 🚀'
    + (' ' + PHRASE if i in (450, 1200) else '') for i in range(1850)) + '\nRESPONSE END'


def assistant(identifier, text, phase='commentary'):
    return {'id': identifier, 'type': 'agentMessage', 'text': text, 'phase': phase}


def text_window(text, start, size=20000):
    """Match native reader UTF-16 character windows without splitting a surrogate."""
    value = text.encode('utf-16-le')
    total = len(value) // 2
    start = max(0, min(start, max(0, total - size)))
    unit = lambda n: int.from_bytes(value[n * 2:n * 2 + 2], 'little')
    if start and 0xDC00 <= unit(start) <= 0xDFFF and 0xD800 <= unit(start - 1) <= 0xDBFF:
        start -= 1
    end = min(total, start + size)
    if end < total and 0xD800 <= unit(end - 1) <= 0xDBFF and 0xDC00 <= unit(end) <= 0xDFFF:
        end -= 1
    return value[start * 2:end * 2].decode('utf-16-le')


def make_thread(project):
    items = [{'id': f'tool-{i}', 'type': 'commandExecution', 'command': 'synthetic inspect',
              'status': 'completed', 'exitCode': 0, 'aggregatedOutput': f'Original tool evidence {i}'}
             for i in range(95)]
    items[3] = assistant('earlier-final', 'EARLIER FINAL MUST NOT WIN', 'final_answer')
    items[44] = assistant('child-looking-commentary', 'CHILD LOOKING MUST NOT WIN', 'commentary')
    items[45] = assistant(ITEM, TEXT, 'final_answer')
    items[75] = assistant('later-commentary', 'LATER COMMENTARY MUST NOT WIN', 'commentary')
    return {'id': PARENT, 'cwd': str(project), 'name': 'Synthetic captured task response',
            'modelProvider': 'fixture-provider', 'turns': [
                {'id': 'earlier-turn', 'status': 'completed', 'items': [
                    assistant(ITEM, 'OTHER TURN SAME ITEM ID MUST NOT WIN', 'final_answer')]},
                {'id': TURN, 'status': 'failed', 'error': {'message': 'Native parser failed'}, 'items': items},
                {'id': 'later-turn', 'status': 'completed', 'items': [
                    assistant('later-turn-final', 'LATER TURN FINAL MUST NOT WIN', 'final_answer')]}]}


class Fixture:
    def __init__(self, root):
        self.home, self.project, self.state = root / 'native-home', root / 'project', root / 'state'
        self.home.mkdir(); self.project.mkdir()
        (self.home / 'config.toml').write_text('model="fixture-model"\n')
        (self.home / 'auth.json').write_text('{"fixture":"unchanged"}\n')
        self.protected = {path: path.read_bytes() for path in self.home.iterdir()}
        self.calls, self.opens, self.failures = [], [], set()
        self.threads = {PARENT: make_thread(self.project), 'native-other': {
            'id': 'native-other', 'cwd': str(self.project), 'name': 'Other Work',
            'turns': [{'id': 'other-turn', 'status': 'completed', 'items': [
                assistant('other-final', 'OTHER CURRENT READER STAYS OWNED', 'final_answer')]}]}}
        owner = self

        class Reader:
            def __init__(self, binary, home, cwd):
                assert binary == 'never-executed' and Path(home) == owner.home
                self.closing = False
                self.process = SimpleNamespace(poll=lambda: None)

            def request(self, method, params, timeout=30):
                owner.calls.append({'method': method, 'params': copy.deepcopy(params)})
                assert method == 'thread/read', 'Unexpected native method: ' + method
                assert params.get('includeTurns') is True
                if params['threadId'] in owner.failures:
                    raise RuntimeError('Synthetic native original read unavailable')
                return {'thread': copy.deepcopy(owner.threads[params['threadId']])}

            def close(self):
                self.closing = True
                self.process.poll = lambda: 0

        class Catalog:
            def request(self, method, params, timeout=30):
                if method == 'thread/read':
                    return Reader('never-executed', owner.home, owner.state).request(method, params, timeout)
                owner.calls.append({'method': method, 'params': copy.deepcopy(params)})
                assert method == 'thread/list', 'Unexpected catalog method: ' + method
                return {'data': [], 'nextCursor': None}

        self.reader_type, self.catalog_type = Reader, Catalog
        self.start()
        for sid, thread, mode in [(ORIGINAL, PARENT, 'plan'), (OTHER, 'native-other', 'native')]:
            self.desk.store.create(str(self.project), 'default', identifier=sid, name='Saved ' + sid)
            self.desk.store.update(sid, thread_id=thread, status='ready', thread_saved=1,
                                   name_pending=0, model='fixture-model', provider='fixture-provider', mode=mode)
            self.desk.store.recall_snapshot(sid, self.threads[thread])
            save_draft(self.desk.store, sid, 'Retained unsent draft — ' + sid + '\n' + 'Keep exact.\n' * 8, mode, 0)
            add_followup(self.desk.store, sid, 'Retained Work queue — ' + sid, 'native')
            add_followup(self.desk.store, sid, 'Retained Plan queue — ' + sid, 'plan')
        self.preparation = self.prepared()
        self.emitter = object.__new__(Runtime)
        self.emitter.store, self.emitter.id, self.emitter.home = self.desk.store, ORIGINAL, self.home
        self.emitter.closing, self.emitter.persisted, self.emitter.approvals = False, True, {}
        self.emitter._flush_name = lambda: None
        self.emitter.lifecycle_lock = threading.Lock()
        self.event('turn/started', {'threadId': PARENT, 'turn': {'id': TURN, 'status': 'inProgress', 'items': []}})
        self.event('turn/completed', {'threadId': PARENT, 'turn': copy.deepcopy(self.threads[PARENT]['turns'][1])})

    def start(self, port=0):
        self.desk = product.Desk('never-executed', self.home, self.state)
        self.desk.catalog = lambda: self.catalog_type()

        def opened(identifier):
            self.opens.append(identifier)
            row = self.desk.store.get(identifier)
            return {'thread': copy.deepcopy(self.threads[row['thread_id']]),
                    'model': 'fixture-model', 'modelProvider': 'fixture-provider'}

        self.desk.open = opened
        self.server = product.ThreadingHTTPServer(('127.0.0.1', port), product.handler(self.desk))
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join(3)
        self.desk.close(); self.desk.store.db.close()

    def prepared(self):
        return {sid: {'draft': load_draft(self.desk.store, sid),
                      'queue': followup_snapshot(self.desk.store, sid)} for sid in (ORIGINAL, OTHER)}

    def sql(self):
        with self.desk.store.lock:
            tables = [row[0] for row in self.desk.store.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {table: sorted(self.desk.store.db.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr)
                    for table in tables}

    def event(self, method, params):
        with self.emitter.lifecycle_lock:
            self.emitter._message({'method': method, 'params': params})

    def boundary(self, identifier, status='completed', items=None):
        turn = {'id': identifier, 'status': status, 'items': items or []}
        self.threads[PARENT]['turns'].append(copy.deepcopy(turn))
        self.event('turn/started', {'threadId': PARENT, 'turn': {**turn, 'status': 'inProgress'}})
        if status != 'inProgress':
            self.event('turn/completed', {'threadId': PARENT, 'turn': turn})


async def frames(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def check(browser, width, root, evidence):
    record = {'width': width, 'passed': False, 'checks': []}
    http, errors, external = [], [], []
    with tempfile.TemporaryDirectory(dir=root, prefix=f'task-response-{width}-') as temporary:
        f = Fixture(Path(temporary)); context = None
        with patch.object(product, '_NativeReader', f.reader_type), patch.object(
                product, 'Runtime', side_effect=AssertionError('Task runtime is forbidden')):
            try:
                context = await browser.new_context(viewport={'width': width, 'height': 900 if width > 390 else 844})
                await context.add_init_script("""Object.defineProperty(navigator,'clipboard',{configurable:true,
                  value:{async writeText(text){(window.__responseCopies ||= []).push(text)}}});""")
                page = await context.new_page(); page.set_default_timeout(12000)
                page.on('pageerror', lambda error: errors.append(str(error)))

                async def isolated(route):
                    if urlsplit(route.request.url).hostname != '127.0.0.1':
                        external.append(route.request.url); await route.abort()
                    else:
                        await route.continue_()

                await context.route('**/*', isolated)

                def requested(request):
                    parsed = urlsplit(request.url)
                    http.append({'path': parsed.path, 'method': request.method, 'query': parse_qs(parsed.query)})

                page.on('request', requested)

                async def checkpoint(name):
                    assert not errors and not external, (errors, external)
                    assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)"), name + ' overflow'
                    assert f.prepared() == f.preparation
                    sid = await page.evaluate('selected')
                    assert await page.locator('#prompt').input_value() == f.preparation[sid]['draft']['text']
                    assert await page.locator('#turn-mode').input_value() == f.preparation[sid]['draft']['mode']
                    assert f.desk.runtimes == {}
                    record['checks'].append(name)
                    await page.screenshot(path=str(evidence / f'{width}-{name}.png'))

                async def poll():
                    await page.evaluate('pollActivity()')
                    seq = f.desk.store.events(ORIGINAL)[-1]['seq']
                    await page.wait_for_function('seq=>after>=seq', arg=seq)

                async def ready():
                    await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
                    await frames(page)

                async def select(sid):
                    # Selection behind a modal is an explicit host-selection action,
                    # exercised by its actual session control rather than browser hit testing.
                    control = page.locator(f'.session-row[data-session="{sid}"] .session')
                    if await page.locator('#history-reader').evaluate('n=>n.open'):
                        await control.evaluate('n=>n.click()')
                    else:
                        await control.click()
                    await page.wait_for_function('sid=>selected===sid&&!opening', arg=sid)

                async def read():
                    if not await page.locator('#native-outcome').evaluate('n=>n.open'):
                        await page.locator('#native-outcome summary').click()
                    await page.locator('#read-task-response').click()
                    await ready()

                async def back():
                    await page.locator('#history-reader-back').click()
                    await page.wait_for_function("!$('history-reader').open")
                    await frames(page)

                def target(turn=TURN, item=ITEM):
                    return page.locator(f'.history-reader-item[data-turn-id="{turn}"][data-item-id="{item}"]')

                async def initial_text_visible(turn=TURN, item=ITEM):
                    value = await target(turn, item).evaluate("""n=>{
                        const pre=n.querySelector('pre'),box=pre.getBoundingClientRect(),
                            body=document.getElementById('history-reader-body').getBoundingClientRect(),
                            reader=document.getElementById('history-reader').getBoundingClientRect();
                        return {preTop:box.top,preBottom:box.bottom,bodyTop:body.top,bodyBottom:body.bottom,
                            readerTop:reader.top,readerBottom:reader.bottom,
                            visible:box.top+40<=Math.min(body.bottom,reader.bottom-12,innerHeight)
                                && box.top+40>=Math.max(body.top,reader.top+12,0)};
                    }""")
                    record.setdefault('initial_target_viewports', []).append({'turn': turn, 'item': item, **value})
                    assert value['visible'], value

                await page.goto(f'http://127.0.0.1:{f.server.server_port}/')
                await select(ORIGINAL)
                await page.wait_for_function("!$('native-outcome').hidden&&$('native-outcome-identity').textContent.includes('captured-failed-turn')")
                await page.locator('#native-outcome summary').click()
                await page.locator('#read-task-response').focus()
                await page.evaluate("scrollTo({top:Math.max(0,$('native-outcome').getBoundingClientRect().top+scrollY-150),behavior:'instant'})")
                await frames(page)
                return_view = await page.evaluate('({scroll:scrollY,focus:document.activeElement.id})')
                before, boundary, native_boundary = f.sql(), len(http), len(f.calls)
                await page.locator('#read-task-response').press('Enter'); await ready()
                assert await target().count() == 1 and await target().evaluate('n=>n.open&&n.classList.contains("history-reader-target")')
                await initial_text_visible()
                assert 'failed' in await page.locator('#history-reader-response').inner_text()
                assert 'Final answer' in await page.locator('#history-reader-response').inner_text()
                assert 'native history read' in await page.locator('#history-reader-response').inner_text()
                assert 'items 41' in await page.locator('#history-reader-coverage').inner_text()
                assert await target().locator('pre').text_content() == text_window('Codex\n' + TEXT, 0)
                assert len([q for q in http[boundary:] if q['path'] == '/api/native/task-response']) == 1
                assert not [q for q in http[boundary:] if q['path'] in ('/api/native/thread', '/api/open')]
                assert f.calls[native_boundary:] == [{'method': 'thread/read', 'params': {'threadId': PARENT, 'includeTurns': True}}]
                await target().get_by_role('button', name='Later text', exact=True).click()
                assert await target().get_attribute('data-window-start') == '20000'
                assert await target().locator('pre').text_content() == text_window('Codex\n' + TEXT, 20000)
                await target().locator('.history-reader-copy-text').click()
                assert await page.evaluate('__responseCopies.at(-1)') == 'Codex\n' + TEXT
                await target().locator('.history-reader-copy-source').click()
                copied = await page.evaluate('__responseCopies.at(-1)')
                assert f'Thread: {PARENT}\nTurn: {TURN}\nItem: {ITEM}\n' in copied
                assert 'Project folder: ' + str(f.project) in copied
                assert f.sql() == before
                await checkpoint('captured-original-window-full-copy-source')
                await back()
                assert await page.evaluate('({scroll:scrollY,focus:document.activeElement.id})') == return_view
                await checkpoint('native-outcome-return-focus-scroll')

                # Reader ownership survives ordinary activity and both refresh outcomes.
                await read()
                f.boundary('new-streamed-parent', 'inProgress', [assistant('new-streamed-final', 'NEWER ANSWER MUST NOT REPLACE', 'final_answer')])
                await poll(); await frames(page)
                await page.locator('#history-reader-find-query').fill(PHRASE)
                await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')")
                await page.keyboard.press('F3')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
                await frames(page)
                assert await target().locator('mark').text_content() == PHRASE
                await target().locator('pre').evaluate("n=>{const text=[...n.childNodes].find(n=>n.nodeType===Node.TEXT_NODE&&n.length>40);const r=document.createRange();r.setStart(text,8);r.setEnd(text,30);const s=getSelection();s.removeAllRanges();s.addRange(r);n.scrollTop=80;n.closest('details').focus({preventScroll:true})}")
                await frames(page)

                async def reading():
                    return await page.evaluate("""()=>({focus:document.activeElement.className,selection:getSelection().toString(),
                        window:scrollY,outer:$('history-reader').scrollTop,body:$('history-reader-body').scrollTop,
                        query:$('history-reader-find-query').value,status:$('history-reader-find-status').textContent,
                        selectionTop:getSelection().rangeCount?getSelection().getRangeAt(0).getBoundingClientRect().top:null,
                        target:[...document.querySelectorAll('.history-reader-target')].map(n=>({turn:n.dataset.turnId,item:n.dataset.itemId,start:n.dataset.windowStart,open:n.open,scroll:n.querySelector('pre').scrollTop,
                            top:n.getBoundingClientRect().top,preTop:n.querySelector('pre').getBoundingClientRect().top}))})""")

                def same_position(left, right):
                    # Inserted status controls can change outer scroll anchoring
                    # without moving the text being read; its viewport rect wins.
                    left, right = copy.deepcopy(left), copy.deepcopy(right)
                    left.pop('outer'); right.pop('outer')
                    return left == right

                retained = await reading()
                record['continuity_before'] = retained
                f.event('item/completed', {'threadId': PARENT, 'turnId': 'new-streamed-parent', 'item': assistant('live-output', 'Active output\n' * 80)})
                await poll(); await frames(page)
                record['continuity_after_output'] = await reading()
                assert record['continuity_after_output'] == retained, (retained, record['continuity_after_output'])
                f.failures.add(PARENT); before = f.sql()
                await page.locator('#history-reader-refresh').evaluate('n=>n.click()')
                await page.wait_for_function("$('history-reader-status').textContent.includes('Refresh failed')")
                record['continuity_after_failed_refresh'] = await reading()
                if not same_position(record['continuity_after_failed_refresh'], retained):
                    record.setdefault('observed_failures', []).append('Failed Refresh changed retained reader position')
                assert f.sql() == before
                f.failures.clear()
                # Newer final in the captured turn must not reselect the response on Refresh.
                f.threads[PARENT]['turns'][1]['items'].append(assistant('added-final', 'ADDED FINAL MUST NOT RESELECT', 'final_answer'))
                before = f.sql()
                await page.locator('#history-reader-refresh').evaluate('n=>n.click()')
                await page.wait_for_function("$('history-reader-status').textContent.includes('Original refreshed')&&!$('history-reader-refresh').disabled")
                await frames(page)
                record['continuity_after_successful_refresh'] = await reading()
                if not same_position(record['continuity_after_successful_refresh'], retained):
                    record.setdefault('observed_failures', []).append('Successful Refresh changed retained reader position')
                assert f.sql() == before
                await checkpoint('active-output-failed-successful-refresh-retains-reader')
                await back()

                # Held task response captures one exact outcome even if parent advances.
                held, release, delivered = asyncio.Event(), asyncio.Event(), asyncio.Event()

                async def hold(route):
                    response = await route.fetch(); held.set()
                    await asyncio.wait_for(release.wait(), 30)
                    await route.fulfill(response=response); delivered.set()

                async def hold_start():
                    nonlocal held, release, delivered
                    held, release, delivered = asyncio.Event(), asyncio.Event(), asyncio.Event()
                    await page.route('**/api/native/task-response?*', hold)
                    await page.locator('#read-task-response').click()
                    await asyncio.wait_for(held.wait(), 12)

                async def hold_end():
                    release.set(); await asyncio.wait_for(delivered.wait(), 12)
                    await page.unroute('**/api/native/task-response?*', hold)
                    await frames(page)

                await hold_start()
                f.boundary('held-newer-parent', 'inProgress', [assistant('held-newer-final', 'HELD NEWER MUST NOT WIN', 'final_answer')])
                await poll(); before = f.sql(); await hold_end(); await ready()
                assert await target('new-streamed-parent', 'new-streamed-final').count() == 1
                assert 'new-streamed-parent' in await page.locator('#history-reader-response').inner_text()
                assert f.sql() == before
                await checkpoint('held-read-keeps-captured-parent-turn')
                await back()

                # Closing/reader replacement and switching invalidate the original ticket.
                await hold_start(); await page.locator('#history-reader-close').click()
                await page.wait_for_function("!$('history-reader').open")
                await page.locator('#read-original').click(); await ready()
                new_body = await page.locator('#history-reader-body').inner_text()
                before = f.sql(); await hold_end(); await page.wait_for_timeout(100)
                assert await page.locator('#history-reader-body').inner_text() == new_body
                assert await page.locator('#history-reader-response').is_hidden()
                assert f.sql() == before
                await checkpoint('closed-held-response-cannot-replace-newer-original-reader')
                await back()
                await hold_start(); await select(OTHER)
                await page.wait_for_function("!$('history-reader').open")
                before = f.sql(); await hold_end(); await page.wait_for_timeout(100)
                assert await page.evaluate('selected') == OTHER
                assert not await page.locator('#history-reader').evaluate('n=>n.open')
                assert f.sql() == before
                await checkpoint('held-response-suppressed-after-session-switch')
                await select(ORIGINAL)

                # Fallback phase labels retain their observed phase and exact native status.
                for phase in ('commentary', None, 'future_native_phase'):
                    turn = 'fallback-' + (phase or 'unknown')
                    item = 'fallback-item-' + (phase or 'unknown')
                    f.boundary(turn, 'interrupted', [assistant(item, 'Exact fallback response — ' + (phase or 'unknown'), phase)])
                    await poll(); before = f.sql(); await read()
                    label = await page.locator('#history-reader-response').inner_text()
                    assert ('Commentary' if phase == 'commentary' else 'Last assistant message') in label
                    assert 'interrupted' in label and turn in label
                    assert (phase or 'unreported') in label
                    assert await target(turn, item).count() == 1 and f.sql() == before
                    await initial_text_visible(turn, item)
                    await checkpoint('observed-phase-' + (phase or 'unknown'))
                    await back()

                # No response/absent turn shows no substituted answer; optional original is preloaded.
                for unavailable in ('response', 'turn'):
                    turn = 'unavailable-' + unavailable
                    f.boundary(turn, 'failed'); await poll()
                    if unavailable == 'turn':
                        f.threads[PARENT]['turns'] = [t for t in f.threads[PARENT]['turns'] if t['id'] != turn]
                    before, boundary = f.sql(), len(http)
                    await read()
                    assert await page.locator('#history-reader-body').inner_text() == ''
                    assert ('No readable assistant response' if unavailable == 'response' else 'captured native turn is not present') in await page.locator('#history-reader-status').inner_text()
                    assert turn in await page.locator('#history-reader-response').inner_text()
                    assert 'No other turn' in await page.locator('#history-reader-match').inner_text()
                    assert turn in await page.locator('#native-outcome-identity').text_content()
                    await checkpoint('unavailable-' + unavailable + '-no-substitution')
                    await page.locator('#history-reader-original').click(); await ready()
                    assert await page.locator('#history-reader-body').inner_text()
                    assert not [q for q in http[boundary:] if q['path'] == '/api/native/thread']
                    assert f.sql() == before
                    await back()

                # Read failure and explicit Retry cannot follow a later displayed outcome.
                f.boundary('failed-read-capture', 'failed', [assistant('failed-read-item', 'RETRY EXACT CAPTURE', 'final_answer')]); await poll()
                f.failures.add(PARENT); before, boundary = f.sql(), len(http); await read()
                assert 'Retry keeps this same native thread and turn' in await page.locator('#history-reader-status').inner_text()
                assert 'failed-read-capture' in await page.locator('#history-reader-binding').inner_text()
                assert f.sql() == before
                f.failures.clear(); f.boundary('later-than-failed-read', 'completed', [assistant('retry-newer-final', 'RETRY MUST NOT FOLLOW NEWER', 'final_answer')]); await poll()
                before = f.sql(); await page.locator('#history-reader-retry').click(); await ready()
                assert await target('failed-read-capture', 'failed-read-item').count() == 1
                assert f.sql() == before
                retry_requests = [q for q in http[boundary:] if q['path'] == '/api/native/task-response']
                assert len(retry_requests) == 2 and all(q['query'] == {'thread': [PARENT], 'turn': ['failed-read-capture']} for q in retry_requests)
                await checkpoint('failed-read-retry-keeps-exact-turn-drafts-queues')
                await back()

                # Server/SQLite cold replacement, same browser, removed project original read.
                old_sql, port = f.sql(), f.server.server_port
                f.stop(); f.start(port); f.emitter.store = f.desk.store
                assert f.sql() == old_sql and f.desk.runtimes == {}
                await page.reload(); await page.wait_for_function('selected===\"response-plan\"&&!opening')
                f.project.rmdir(); before, boundary = f.sql(), len(http)
                await read(); assert await target('later-than-failed-read', 'retry-newer-final').count() == 1
                assert f.sql() == before
                assert not [q for q in http[boundary:] if q['method'] != 'GET' or q['path'] == '/api/open']
                await checkpoint('cold-same-browser-removed-project-read-only')
                assert f.prepared() == f.preparation and f.desk.runtimes == {}
                assert {path: path.read_bytes() for path in f.protected} == f.protected
                assert not [q for q in http if q['method'] == 'POST' and q['path'] != '/api/open']
                assert all(q['method'] in ('thread/read', 'thread/list') for q in f.calls)
                record.update(passed=not record.get('observed_failures'), native_calls=f.calls, http=http, javascript_errors=errors,
                              model_tasks=0, native_admissions=0, owned_task_runtimes=0,
                              preparation_exact=True, full_copy_characters=len('Codex\n' + TEXT))
            except Exception as error:
                record.update(error=str(error), traceback=traceback.format_exc(), native_calls=f.calls, http=http, javascript_errors=errors)
                if 'page' in locals():
                    try:
                        record['observed'] = await page.evaluate("({selected,opening,after,generation,currentTurn,nativeThreadId,reader:$('history-reader').open,status:$('history-reader-status').textContent,response:$('history-reader-response').textContent,coverage:$('history-reader-coverage').textContent})")
                        await page.screenshot(path=str(evidence / f'{width}-failed.png'))
                    except Exception as diagnostic:
                        record['diagnostic_error'] = str(diagnostic)
            finally:
                if context:
                    await context.close()
                f.stop()
    path = evidence / f'case-{width}.json'
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n'); path.chmod(0o600)
    print(json.dumps({k: record[k] for k in ('width', 'passed', 'checks', 'error') if k in record}), flush=True)
    return record


async def main():
    root = Path(os.environ['DESK_TEST_TEMP']).resolve(); root.mkdir(parents=True, exist_ok=True)
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']).resolve(); evidence.mkdir(parents=True, exist_ok=True, mode=0o700); evidence.chmod(0o700)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                                          args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            records = [await check(browser, width, root, evidence) for width in (1250, 390)]
        finally:
            await browser.close()
    summary = {'result': 'PASS' if all(row['passed'] for row in records) else 'FAIL',
               'version': codex_desk.__version__, 'package': str(PACKAGE),
               'source': str(SOURCE), 'installed': os.environ.get('DESK_USE_INSTALLED') == '1',
               'playwright': importlib.metadata.version('playwright'), 'widths': [1250, 390], 'results': records}
    (evidence / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: summary[k] for k in ('result', 'version', 'package', 'installed', 'playwright', 'widths')}), flush=True)
    for row in records:
        if not row['passed']:
            print(row.get('traceback', ''), flush=True)
    if summary['result'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
