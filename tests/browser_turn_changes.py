"""Turn changes through Runtime._message, retained SQLite/HTTP and Chromium."""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import threading
import traceback
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit
import uuid

S = Path(os.environ.get('DESK_SOURCE', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(S / 'tests'))
if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(S))
import codex_desk
PACKAGE = Path(codex_desk.__file__).resolve()
if os.environ.get('DESK_USE_INSTALLED') == '1':
    assert not PACKAGE.is_relative_to(S)
if os.environ.get('DESK_INSTALLED_ROOT'):
    assert PACKAGE.is_relative_to(Path(os.environ['DESK_INSTALLED_ROOT']).resolve())
if os.environ.get('DESK_EXPECT_VERSION'):
    assert codex_desk.__version__ == os.environ['DESK_EXPECT_VERSION']
from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.drafts import save_draft, load_draft
from codex_desk.followups import add_followup, followup_snapshot
from codex_desk.server import Desk, handler
from codex_desk.turn_dispatch import _binding
from playwright.async_api import async_playwright

OUT = Path(os.environ.get('DESK_TEST_EVIDENCE', Path(os.environ.get('DESK_TEST_TEMP', Path.cwd() / 'temp')) / 'turn-changes'))
OUT.mkdir(parents=True, exist_ok=True, mode=0o700)
OUT.chmod(0o700)

def aggregate(revision):
    rows = ''.join(f'+    retained_{i:03d} = "literal 保留 résumé {i} ' + 'x' * 90 + '"\n' for i in range(90))
    return ('diff --git a/parser.py b/parser.py\n'
            'index 1234567..abcdef0 100644\n--- a/parser.py\n+++ b/parser.py\n'
            '@@ -1,2 +1,93 @@\n-old = "original"\n'
            f'+new = "aggregate revision {revision} — exact replacement"\n'
            '+markup = "<script>window.__diffExecuted = true</script><img src=x onerror=alert(1)>"\n' + rows +
            ' context = "unchanged"\n'
            'diff --git a/tests/保留.txt b/tests/保留.txt\n'
            'index 2345678..bcdef01 100644\n--- a/tests/保留.txt\n+++ b/tests/保留.txt\n'
            '@@ -1 +1,2 @@\n-old assertion\n'
            f'+new assertion revision {revision}\n+emoji 👩🏽‍💻 & <tag>\t trailing spaces  \n'
            '\\ No newline at end of file\n')

DIFF_ONE, DIFF_TWO, DIFF_THREE = (aggregate(i) for i in (1, 2, 3))
STEPS = [{'step': 'Inspect, edit, and test actual reported native work', 'status': 'inProgress'},
         {'step': 'Verify both changed files', 'status': 'pending'}]
READING = """()=>({focus:document.activeElement.id,inner:$('turn-changes-body').scrollTop,
    left:$('turn-changes-body').scrollLeft,window:scrollY,open:$('turn-changes').open})"""

def save_json(name, value):
    path = OUT / name
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    path.chmod(0o600)

async def one(browser, width):
    f = NativeHTTPFixture()
    f.setUp()
    context = None
    result = {'width': width, 'passed': False, 'checks': [], 'package': str(PACKAGE)}
    requests, errors = [], []
    try:
        original, other = f.identifier, 'other-plan'
        f.desk.store.update(original, status='ready', thread_saved=1, name_pending=0)
        other_path = f.path / 'other-project'
        other_path.mkdir()
        f.desk.store.create(str(other_path), 'default', identifier=other, name='Other selected Plan')
        f.desk.store.update(other, thread_id='native-other', status='ready', thread_saved=1, name_pending=0)
        for sid in (original, other):
            save_draft(f.desk.store, sid, 'Retained unsent Plan ' + sid + ' 保留', 'plan', 0, 'fixture', 1)
            add_followup(f.desk.store, sid, 'Retained next verification ' + sid, 'native')
        threads = {original: {'id': 'native-original', 'turns': []}, other: {'id': 'native-other', 'turns': []}}
        opened = []

        class Catalog:
            def request(self, method, params):
                assert method == 'thread/list'
                return {'data': [], 'nextCursor': None}

        def opened_task(sid):
            opened.append(sid)
            return {'thread': copy.deepcopy(threads[sid]), 'model': 'fixture', 'modelProvider': 'fixture'}

        f.desk.catalog = lambda: Catalog()
        f.desk.open = opened_task

        def event(method, params):
            with f.runtime.lifecycle_lock:
                f.runtime._message({'method': method, 'params': params})

        def start(turn):
            event('turn/started', {'threadId': 'native-original', 'turn': {'id': turn, 'status': 'inProgress', 'items': []}})

        def diff(turn, value, thread='native-original'):
            event('turn/diff/updated', {'threadId': thread, 'turnId': turn, 'diff': value})

        def plan(turn):
            event('turn/plan/updated', {'threadId': 'native-original', 'turnId': turn,
                                      'explanation': 'Independent native inspect/edit/test checklist', 'plan': copy.deepcopy(STEPS)})

        def finish(turn, status):
            event('turn/completed', {'threadId': 'native-original', 'turn': {'id': turn, 'status': status, 'items': []}})

        def saved():
            return {sid: {'draft': load_draft(f.desk.store, sid), 'queue': followup_snapshot(f.desk.store, sid),
                          'binding': _binding(f.desk, sid)} for sid in (original, other)}

        context = await browser.new_context(viewport={'width': width, 'height': 900},
                                            permissions=['clipboard-read', 'clipboard-write'])
        page = await context.new_page()
        page.set_default_timeout(12000)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda q: requests.append({'method': q.method, 'path': urlsplit(q.url).path}))

        async def select(sid):
            await page.locator(f'.session-row[data-session="{sid}"] .session').click()
            await page.wait_for_function('(s)=>selected===s&&!opening', arg=sid)

        async def drained():
            seq = f.desk.store.events(original)[-1]['seq']
            await page.wait_for_function('(seq)=>after>=seq&&!opening', arg=seq)
            await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')

        async def expect_diff(value):
            await page.wait_for_function('(v)=>DeskTurnChanges.state().diff===v', arg=value)
            assert await page.locator('#turn-changes-body').text_content() == value

        async def read_position():
            await page.locator('#turn-changes-body').evaluate('n=>{n.focus({preventScroll:true});n.scrollTop=170;n.scrollLeft=110;}')
            await page.evaluate("()=>window.scrollTo(0,$('turn-changes-body').getBoundingClientRect().top+scrollY-300)")
            await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            assert await page.evaluate('document.documentElement.scrollHeight-innerHeight-scrollY') > 140
            position = await page.evaluate(READING)
            assert position['focus'] == 'turn-changes-body' and position['inner'] == 170 and position['left'] > 0
            return position

        async def hidden_reader_follows(turn, identity):
            assert await page.locator('#turn-changes').evaluate('n=>n.hidden&&n.open')
            assert await page.locator('#native-steps').evaluate('n=>n.hidden&&n.open')
            await page.locator('#latest-output').click()
            assert await page.evaluate('nearLatest()')
            event('item/completed', {'threadId': 'native-original', 'turnId': turn, 'item': {
                'id': identity, 'type': 'agentMessage', 'text': '\n\n'.join('Ordinary quiet-turn output ' + str(i) for i in range(30))}})
            await drained()
            assert await page.evaluate('latestUpdates') == 0
            assert await page.evaluate('nearLatest()')
            assert await page.evaluate('Math.abs(scrollY-(document.documentElement.scrollHeight-innerHeight))') <= 1

        await page.goto(f'http://127.0.0.1:{f.server.server_port}/')
        await select(original)
        before, boundary = saved(), len(requests)
        start('turn-one')
        plan('turn-one')
        event('item/completed', {'threadId': 'native-original', 'turnId': 'turn-one', 'item': {
            'id': 'older-readable-output', 'type': 'agentMessage', 'text': '\n\n'.join('Earlier inspect/edit/test output paragraph ' + str(i) for i in range(100))}})
        diff('turn-one', DIFF_ONE)
        await expect_diff(DIFF_ONE)
        await drained()
        assert await page.locator('#turn-changes').evaluate('n=>n.open') is False
        native_before = await page.evaluate('()=>DeskNativeSteps.state()')
        assert native_before['reported']['plan'] == STEPS
        await page.locator('#turn-changes summary').click()
        assert await page.locator('#turn-changes-body script,#turn-changes-body img').count() == 0
        assert await page.evaluate('window.__diffExecuted===undefined')
        assert DIFF_ONE.count('diff --git') == 2
        await page.locator('#turn-changes-copy').click()
        await page.wait_for_function("$('turn-changes-message').textContent==='Complete diff copied.'")
        assert await page.evaluate('navigator.clipboard.readText()') == DIFF_ONE
        result['checks'].append('actual Runtime/SQLite/HTTP displays exact two-file aggregate literally without auto-open; full Unicode/markup clipboard copy')

        reading = await read_position()
        latest_before = await page.evaluate('latestUpdates')
        diff('turn-one', DIFF_TWO)
        await expect_diff(DIFF_TWO)
        await drained()
        assert await page.evaluate(READING) == reading
        assert await page.evaluate('latestUpdates') == latest_before + 1
        assert await page.locator('#latest-output').text_content() == f'{latest_before + 1} new update' + ('s' if latest_before else '') + ' · Latest output ↓'
        assert await page.evaluate('()=>DeskNativeSteps.state()') == native_before
        result['reading_before'], result['reading_after'] = reading, await page.evaluate(READING)
        result['checks'].append('replacement aggregate preserves expanded body focus/vertical+horizontal scroll/window >140px above bottom; accepted diff increments Latest exactly once; native steps exact')

        count = await page.evaluate('latestUpdates')
        diff('turn-one', DIFF_TWO)
        retained = len(f.desk.store.events(original))
        diff('turn-one', 'CHILD MUST NOT APPEAR', 'native-child')
        assert len(f.desk.store.events(original)) == retained
        diff('turn-one', 'FOREIGN MUST NOT APPEAR', 'native-other')
        assert len(f.desk.store.events(original)) == retained
        await drained()
        assert await page.evaluate('latestUpdates') == count
        assert await page.evaluate(READING) == reading
        await page.locator('#turn-changes-copy').click()
        await page.wait_for_function("$('turn-changes-message').textContent==='Complete diff copied.'")
        assert await page.evaluate('navigator.clipboard.readText()') == DIFF_TWO
        result['checks'].append('duplicate/child/foreign updates add no Latest count and cannot replace aggregate; clipboard contains complete replacement, not appended old diff')

        # Delay only clipboard promise completion after writing the real captured text.
        await page.evaluate("""()=>{window.originalClipboardWrite=navigator.clipboard.writeText.bind(navigator.clipboard);
            navigator.clipboard.writeText=async value=>{await originalClipboardWrite(value);await new Promise(r=>window.releaseCopy=r);};}""")
        await page.locator('#turn-changes-copy').click()
        await page.wait_for_function('typeof window.releaseCopy==="function"')
        diff('turn-one', DIFF_THREE)
        await expect_diff(DIFF_THREE)
        await drained()
        await page.evaluate('()=>{releaseCopy();navigator.clipboard.writeText=originalClipboardWrite;}')
        assert await page.evaluate('navigator.clipboard.readText()') == DIFF_TWO
        assert await page.locator('#turn-changes-message').text_content() == ''
        await page.evaluate("()=>{navigator.clipboard.writeText=async()=>{throw new Error('fixture clipboard unavailable');};}")
        await page.locator('#turn-changes-copy').click()
        await page.wait_for_function("$('turn-changes-message').textContent==='Copy failed: fixture clipboard unavailable'")
        await page.evaluate('()=>navigator.clipboard.writeText=originalClipboardWrite')
        await page.locator('#turn-changes-copy').click()
        await page.wait_for_function("$('turn-changes-message').textContent==='Complete diff copied.'")
        assert await page.evaluate('navigator.clipboard.readText()') == DIFF_THREE
        result['checks'].append('pending copy writes immutable displayed snapshot; newer diff clears stale completion; local copy failure recovers with full current clipboard and no work sent')

        reading = await read_position()
        finish('turn-one', 'interrupted')
        await page.wait_for_function("$('turn-changes-status').textContent==='Task interrupted'")
        await drained()
        assert await page.evaluate(READING) == reading
        count = await page.evaluate('latestUpdates')
        diff('turn-one', 'LATE INTERRUPTED MUST NOT APPEAR')
        await drained()
        assert await page.evaluate('latestUpdates') == count
        await expect_diff(DIFF_THREE)
        result['checks'].append('native interruption retains exact last aggregate and deliberate reading position; late retired diff contributes no Latest')

        await page.locator('#native-steps summary').click()
        assert await page.locator('#native-steps').evaluate('n=>n.open')
        start('turn-two')
        await page.wait_for_function("$('turn-changes').hidden&&$('native-steps').hidden")
        await drained()
        await hidden_reader_follows('turn-two', 'newturn-visible-output')
        diff('turn-two', '')
        await expect_diff('')
        assert await page.locator('#turn-changes').is_hidden()
        old_window = await page.evaluate('scrollY')
        diff('turn-two', DIFF_TWO)
        await expect_diff(DIFF_TWO)
        await drained()
        assert await page.locator('#turn-changes').evaluate('n=>n.open&&!n.hidden')
        assert await page.evaluate('scrollY') == old_window
        assert await page.evaluate('latestUpdates') == 1
        count = await page.evaluate('latestUpdates')
        diff('turn-two', '')
        await expect_diff('')
        await drained()
        assert await page.locator('#turn-changes').is_hidden()
        assert await page.evaluate('latestUpdates') == count + 1
        diff('turn-two', '')
        await drained()
        assert await page.evaluate('latestUpdates') == count + 1
        await hidden_reader_follows('turn-two', 'emptydiff-visible-output')
        result['checks'].append('hidden-open changes/native-steps after newturn and empty diff allow ordinary near-latest output following; returning visible expanded diff preserves window and pauses again')
        diff('turn-two', DIFF_TWO)
        await expect_diff(DIFF_TWO)
        await select(other)
        assert await page.locator('#turn-changes').is_hidden()
        assert await page.locator('#prompt').input_value() == before[other]['draft']['text']
        diff('turn-two', DIFF_THREE)
        await page.wait_for_timeout(650)
        assert await page.locator('#turn-changes').is_hidden()
        await select(original)
        await expect_diff(DIFF_THREE)
        assert await page.locator('#prompt').input_value() == before[original]['draft']['text']
        assert await page.locator('#turn-mode').input_value() == 'plan'
        finish('turn-two', 'completed')
        await page.wait_for_function("$('turn-changes-status').textContent==='Task completed'")
        await expect_diff(DIFF_THREE)
        result['checks'].append('new turn clears old report; empty newer aggregate clears and counts once; quiet other project stays hidden; return replays exact latest aggregate and native completion with original Plan/mode')

        threads[original]['turns'] = [{'id': 'turn-two', 'status': 'completed', 'items': []}]
        await select(other)
        held, release, delivered = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def hold_open(route):
            if route.request.post_data_json.get('session') != original:
                await route.continue_()
                return
            response = await route.fetch()
            held.set()
            await asyncio.wait_for(release.wait(), 15)
            await route.fulfill(response=response)
            delivered.set()

        await page.route('**/api/open', hold_open)
        await page.locator(f'.session-row[data-session="{original}"] .session').click()
        await asyncio.wait_for(held.wait(), 10)
        await select(other)
        release.set()
        await asyncio.wait_for(delivered.wait(), 10)
        await page.unroute('**/api/open', hold_open)
        await page.wait_for_timeout(650)
        assert await page.evaluate('selected') == other
        assert await page.locator('#turn-changes').is_hidden()
        result['checks'].append('actual held old-generation /api/open receipt cannot bind Turn changes after another project wins')

        held, release, delivered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        await page.route('**/api/open', hold_open)
        await page.locator(f'.session-row[data-session="{original}"] .session').click()
        await asyncio.wait_for(held.wait(), 10)
        start('turn-three')
        plan('turn-three')
        diff('turn-three', DIFF_ONE)
        diff('turn-three', DIFF_TWO)
        release.set()
        await asyncio.wait_for(delivered.wait(), 10)
        await page.unroute('**/api/open', hold_open)
        await page.wait_for_function('(s)=>selected===s&&!opening&&DeskTurnChanges.state().turn==="turn-three"', arg=original)
        await expect_diff(DIFF_TWO)
        assert await page.locator('#turn-changes-status').text_content() == 'Task in progress'
        assert await page.evaluate('()=>DeskNativeSteps.state().reported.plan') == STEPS
        result['checks'].append('held older native snapshot cannot replace newer streamed turn/two aggregate replacements during same-project opening replay')

        await page.locator('#turn-changes summary').click()
        reading = await read_position()
        finish('turn-three', 'failed')
        await page.wait_for_function("$('turn-changes-status').textContent==='Task failed'")
        await drained()
        assert await page.evaluate(READING) == reading
        result['failure_reading_before'], result['failure_reading_after'] = reading, await page.evaluate(READING)
        count = await page.evaluate('latestUpdates')
        diff('turn-three', 'LATE FAILURE MUST NOT APPEAR')
        diff('turn-two', 'LATE OLDER TURN MUST NOT APPEAR')
        await drained()
        assert await page.evaluate('latestUpdates') == count
        await expect_diff(DIFF_TWO)
        result['checks'].append('native failure preserves complete last diff and expanded focus/inner/window reading; late failed/older turn reports stay retired and add no Latest')

        start('turn-state-only')
        plan('turn-state-only')
        diff('turn-state-only', DIFF_TWO)
        await expect_diff(DIFF_TWO)
        await drained()
        reading = await read_position()
        count = await page.evaluate('latestUpdates')
        event_count = len(f.desk.store.events(original))
        f.desk.store.update(original, status='failed', error='Native owner failure without terminal notification')
        await page.wait_for_function("$('turn-changes-status').textContent==='Task failed'&&$('native-steps-status').textContent==='Task failed'")
        assert len(f.desk.store.events(original)) == event_count
        assert await page.evaluate(READING) == reading
        assert await page.evaluate('latestUpdates') == count + 1
        await page.evaluate('()=>refresh()')
        assert await page.evaluate('latestUpdates') == count + 1
        result['checks'].append('real SQLite state-only terminal via HTTP poll preserves exact diff/reading and increments Latest once across native steps+changes, not again on repeated refresh')
        await page.screenshot(path=str(OUT / f'turn-changes-{width}.png'))

        retained_events, port = f.desk.store.events(original), f.server.server_port
        f.close_server()
        f.desk.store.db.close()
        f.desk = Desk('unused-fake-native', f.path, f.path / 'state')
        f.addCleanup(f.desk.store.db.close)
        f.desk.catalog, f.desk.open = lambda: Catalog(), opened_task
        f.server = ThreadingHTTPServer(('127.0.0.1', port), handler(f.desk))
        f.server_thread = threading.Thread(target=f.server.serve_forever, daemon=True)
        f.server_thread.start()
        assert f.desk.store.events(original) == retained_events
        await page.reload()
        await page.wait_for_function('(s)=>selected===s&&!opening', arg=original)
        await expect_diff(DIFF_TWO)
        assert await page.locator('#turn-changes-status').text_content() == 'Task failed'
        assert await page.locator('#turn-changes').evaluate('n=>n.open') is False
        assert await page.evaluate('()=>DeskNativeSteps.state().reported.plan') == STEPS
        result['cold_report'] = await page.evaluate('()=>DeskTurnChanges.state()')
        result['checks'].append('real HTTP/SQLite owner close/reopen and reload restores exact terminal aggregate from retained events plus independent native steps')

        token = str(uuid.uuid4())
        payload = {'session': original, 'token': token, 'text': 'Retained captured request independent of Plan',
                   'mode': 'native', 'revision': before[original]['draft']['revision'], 'writer': 'fixture', 'sequence': 1}
        f.desk.store.event(original, {'method': 'desk/turnIntent', 'params': {
            'token': token, 'payload': payload, 'binding': _binding(f.desk, original)}})
        retained_events = f.desk.store.events(original)
        request_boundary, opened_boundary = len(requests), len(opened)
        await page.reload()
        await page.wait_for_function('(s)=>selected===s&&!opening&&turnRequest()?.status==="needs_review"', arg=original)
        await expect_diff(DIFF_TWO)
        assert await page.locator('#turn-changes-status').text_content() == 'Task failed'
        assert len(opened) == opened_boundary
        assert not [q for q in requests[request_boundary:] if q['method'] == 'POST']
        assert f.desk.store.events(original) == retained_events
        result['checks'].append('retained-request-only cold recovery replays exact terminal aggregate using GETs only: no /api/open, native attach, or event write')

        assert saved() == before
        assert not [q for q in requests[boundary:] if q['method'] == 'POST' and q['path'] != '/api/open']
        assert not f.requests and not f.sent and not errors
        result['checks'].append('two original Plans/drafts/modes/revisions/queues/bindings exact; zero native requests/model sends/unexpected mutations/browser errors')
        result.update(passed=True, http=requests, native_requests=0, native_sends=0, unexpected_mutations=0,
                      errors=errors, retained_event_count=len(retained_events), aggregate_lengths=[len(DIFF_ONE), len(DIFF_TWO)],
                      saved_before=before, saved_after=saved())
    except Exception as error:
        result.update(error=str(error), traceback=traceback.format_exc(), http=requests, errors=errors)
        if context:
            try:
                result['observed'] = await page.evaluate("()=>({selected,opening,after,latestUpdates,report:DeskTurnChanges.state(),reading:({focus:document.activeElement.id,window:scrollY,max:document.documentElement.scrollHeight-innerHeight})})")
                await page.screenshot(path=str(OUT / f'failure-{width}.png'))
            except Exception:
                pass
    finally:
        if context:
            await context.close()
        f.doCleanups()
    for path in OUT.glob('*.png'):
        path.chmod(0o600)
    save_json(f'case-{width}.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('http', 'traceback', 'cold_report', 'observed', 'saved_before', 'saved_after')}, ensure_ascii=False), flush=True)
    return result

async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM', '/usr/bin/chromium'),
                                                  headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            rows = [await one(browser, width) for width in (1250, 390)]
        finally:
            await browser.close()
    save_json('result.json', {'passed': all(row['passed'] for row in rows), 'results': rows})
    for row in rows:
        if not row['passed']:
            print(row.get('traceback'), flush=True)
    assert all(row['passed'] for row in rows)

if __name__ == '__main__':
    asyncio.run(main())
