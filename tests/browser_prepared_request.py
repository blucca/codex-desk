#!/usr/bin/env python3
"""Independent retained Prepared request paths through product SQLite/HTTP/Chromium.

Run on an isolated browser host with DESK_SOURCE, DESK_EVIDENCE, DESK_TEST_TEMP,
DESK_CHROMIUM and optional DESK_USE_INSTALLED=1/PYTHONPATH for an installed wheel.
Only the native RPC transport/catalog is controlled; UI and admission stay real.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import threading
import traceback
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

SOURCE = Path(os.environ.get('DESK_SOURCE', Path(__file__).resolve().parents[1])).resolve()
SCRATCH = Path(os.environ.get('DESK_TEST_TEMP', Path.cwd() / 'temp')).resolve()
OUT = Path(os.environ.get('DESK_TEST_EVIDENCE', os.environ.get('DESK_EVIDENCE', SCRATCH / 'browser-prepared-request'))).resolve()
os.environ['DESK_TEST_TEMP'] = str(SCRATCH)
for folder in (OUT, SCRATCH):
    folder.mkdir(parents=True, exist_ok=True)
os.umask(0o077)
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE / 'tests'))
if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(SOURCE))
from test_turn_request_integration import TurnRequestIntegrationTests, ACCESS
import codex_desk
PACKAGE = Path(codex_desk.__file__).resolve()
if os.environ.get('DESK_USE_INSTALLED') == '1':
    assert not PACKAGE.is_relative_to(SOURCE), 'Installed acceptance imported source checkout'
if os.environ.get('DESK_INSTALLED_ROOT'):
    assert PACKAGE.is_relative_to(Path(os.environ['DESK_INSTALLED_ROOT']).resolve()), 'Installed package origin differs from target artifact'
if os.environ.get('DESK_EXPECT_VERSION'):
    assert codex_desk.__version__ == os.environ['DESK_EXPECT_VERSION']
from codex_desk import server as service
from codex_desk.server import Desk, handler
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright

SELECTED = 'later-plan-selected'
SAVED = 'Previously saved Plan — retains separate revision. 保留  '
UNSAVED = ('Another selected unsaved Plan — résumé 保留\t  \n' * 70) + 'UNSENT END  '
MODAL_EDIT = 'Separate Prepared editor unsaved Plan — preserve exact local edits. 保留  '
CAPTURED = lambda mode: ('Captured exact ' + ('Plan' if mode == 'plan' else 'Work') +
    ' — résumé Straße 保留\t  \n') * 320 + 'ORIGINAL END  '


class Fixture(TurnRequestIntegrationTests):
    def start(self, mode='native', prepared=False):
        self.setUp()
        self.original = self.identifier
        self.desk.store.update(self.original, name='Original ' + mode, thread_saved=1)
        order = [e['id'] for e in self.preparation['entries']]
        assert self.request('/api/followups/clear', {'session': self.original, 'order': order})[0] == 200
        self.captured = self.capture(CAPTURED(mode), mode)
        self.native_mode = 'unknown'
        assert self.request('/api/turn', self.captured)[1]['request']['status'] == 'needs_review'
        saved = load_draft(self.desk.store, self.original)
        assert self.request('/api/draft', {'session': self.original, 'text': '', 'mode': 'plan',
            'revision': saved['revision'], 'writer': self.captured['writer'], 'sequence': 2})[0] == 200
        self.other_project = self.path / 'other-project'
        self.other_project.mkdir()
        self.desk.store.create(str(self.other_project), 'default', identifier=SELECTED, name='Later selected Plan')
        self.desk.store.update(SELECTED, thread_id='native-later', thread_saved=1, status='saved', name_pending=0)
        save_draft(self.desk.store, SELECTED, SAVED, 'plan', 0, 'other-writer', 1)
        add_followup(self.desk.store, SELECTED, '1. Exact retained Work — first  ', 'native')
        add_followup(self.desk.store, SELECTED, '2. Exact retained Plan — second  ', 'plan')
        if prepared:
            add_followup(self.desk.store, self.original, 'Later original follow-up must stay  ', 'native')
        self.other_before = {'draft': load_draft(self.desk.store, SELECTED),
                             'queues': followup_snapshot(self.desk.store, SELECTED)}
        self.original_before = {'draft': load_draft(self.desk.store, self.original),
                                'queues': followup_snapshot(self.desk.store, self.original)}
        self.initial_receipt = self.request('/api/turn/request?' + urlencode({
            'session': self.original, 'token': self.captured['token']}))[1]
        self.native_open = []
        self.catalog_calls = []
        self.gates = []
        self.http = []
        self.draft_entered = threading.Event()
        self.draft_release = threading.Event()
        self.draft_release.set()
        self.browser_writer = None
        self.close_server()
        self.start_logged_server()

    def install_store_only_catalog(self):
        owner = self
        class Catalog:
            def request(self, method, params):
                owner.catalog_calls.append({'method': method, 'params': copy.deepcopy(params)})
                assert method == 'thread/list', 'Unexpected native catalog operation ' + method
                return {'data': [], 'nextCursor': None}
        self.desk.catalog = lambda: Catalog()
        def explicit_open(session):
            assert session == SELECTED, 'Request review attempted native open of original'
            owner.native_open.append(session)
            return {'thread': {'id': 'native-later', 'cwd': str(owner.other_project), 'turns': []},
                    'model': 'fixture', 'modelProvider': 'fixture'}
        self.desk.open = explicit_open

    def start_logged_server(self, port=0):
        self.install_store_only_catalog()
        owner = self
        class Handler(handler(self.desk, ACCESS)):
            def do_GET(self):
                owner.http.append({'method': 'GET', 'path': self.path})
                super().do_GET()
            def do_POST(self):
                owner.http.append({'method': 'POST', 'path': self.path})
                super().do_POST()
            def reply(self, value, status=200):
                for gate in owner.gates:
                    if gate['armed'] and self.command == gate['method'] and urlsplit(self.path).path == gate['path']:
                        query = parse_qs(urlsplit(self.path).query)
                        if gate.get('session') and query.get('session') != [gate['session']]:
                            continue
                        gate['armed'] = False
                        gate['value'] = copy.deepcopy(value)
                        gate['entered'].set()
                        assert gate['release'].wait(45), 'Held real HTTP reply was not released'
                        break
                super().reply(value, status)
        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever,
            kwargs={'poll_interval': .01}, daemon=True)
        self.server_thread.start()

    def gate(self, path='/api/turn/request', method='GET', session=None):
        value = {'path': path, 'method': method, 'session': session,
                 'entered': threading.Event(), 'release': threading.Event(), 'armed': True}
        self.gates.append(value)
        return value

    def controlled_save(self, store, session, text, mode, revision, writer=None, sequence=None):
        if session == SELECTED and text == UNSAVED and writer == self.browser_writer:
            self.draft_entered.set()
            assert self.draft_release.wait(45), 'Held main editor autosave was not released'
        return save_draft(store, session, text, mode, revision, writer, sequence)

    def cold(self):
        self.close_server()
        old = self.desk
        state = Path(old.store.db.execute('PRAGMA database_list').fetchone()[2]).parent
        self.desk = Desk(old.binary, old.home, state)
        assert not self.desk.runtimes
        self.start_logged_server()
        return old

    def finish(self):
        for gate in self.gates:
            gate['release'].set()
        self.draft_release.set()
        self.native_hold.set()
        self.reply_hold.set()
        self.doCleanups()


async def make_page(browser, f, width):
    context = await browser.new_context(viewport={'width': width, 'height': 844})
    page = await context.new_page()
    page.set_default_timeout(12_000)
    errors, requests, external = [], [], []
    url = f'http://127.0.0.1:{f.server.server_port}'
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: requests.append({'method': r.method,
        'path': urlsplit(r.url).path, 'query': parse_qs(urlsplit(r.url).query),
        'body': r.post_data_json if r.method == 'POST' else None}) if '/api/' in r.url else None)
    async def isolated(route):
        if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
            external.append(route.request.url)
            await route.abort()
        else:
            await route.continue_()
    await context.route('**/*', isolated)
    await page.goto(url + '/#access=' + ACCESS)
    await page.wait_for_function('state.sessions.length===2')
    await page.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
    assert not f.native_open and len(f.requests) == 1
    assert not any(r['method'] == 'POST' for r in requests), requests
    return context, page, errors, requests, external


async def overview(page):
    await page.locator('#show-preparation').evaluate('n=>n.click()')
    await page.wait_for_function("$('preparation').open && $('preparation-list').getAttribute('aria-busy')==='false'")


def review(page, session):
    return page.locator(f'.preparation-session[data-session="{session}"] button[data-control="request"]')


async def open_review(page, session):
    row = review(page, session)
    await row.focus()
    await page.keyboard.press('Enter')
    await page.wait_for_function("$('preparation-request').open && !$('preparation-request-refresh').disabled && !$('preparation-request-status').textContent.startsWith('Reading')")
    # Body is authoritative GET evidence, not overview summary or an empty editor.
    await page.wait_for_function("!$('preparation-request-captured').hidden")


async def exact_view(page, f, mismatch=False):
    captured = page.locator('#preparation-request-captured')
    if not await captured.evaluate('n=>n.open'):
        await page.locator('#preparation-request-captured-title').click()
    assert await page.locator('#preparation-request-captured-text').text_content() == f.captured['text']
    assert ('Plan' if f.captured['mode'] == 'plan' else 'Work') in await page.locator('#preparation-request-captured-title').text_content()
    for key in ('thread_id', 'cwd', 'native_home', 'profile'):
        assert str(f.initial_receipt['request']['binding'][key]) in await page.locator('#preparation-request-original-binding').text_content(), key
    assert ('native-replacement' if mismatch else 'native-original') in await page.locator('#preparation-request-current-binding').text_content()
    # Exact long instructions must remain ordinary selectable text, not executable/editable HTML.
    assert await page.locator('#preparation-request-captured-text').evaluate("n=>n.tagName==='PRE' && n.getAttribute('contenteditable')!=='true'")
    assert not await page.locator('#preparation-request textarea').count()
    assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && $('preparation-request').scrollWidth<=$('preparation-request').clientWidth")
    assert 'review' in (await page.locator('#preparation-request-status').inner_text()).lower()


async def snapshot_main(page):
    return await page.evaluate("""() => ({session:selected,thread:nativeThreadId,edit:draftEdits.get(selected),
        revision:draftRevisions.get(selected), text:$('prompt').value,mode:$('turn-mode').value,
        caret:[$('prompt').selectionStart,$('prompt').selectionEnd,$('prompt').selectionDirection],
        promptScroll:$('prompt').scrollTop,windowScroll:scrollY,
        queue:[...$('followup-list').querySelectorAll('.followup-entry')].map(n=>({id:n.dataset.followup,text:n.textContent}))})""")


async def prepare_main(page, f):
    await page.locator(f'.session-row[data-session="{SELECTED}"] .session').click()
    await page.wait_for_function('s=>selected===s && !opening && !$(' + json.dumps('task') + ').hidden', arg=SELECTED)
    assert f.native_open == [SELECTED]
    assert await page.locator('#prompt').input_value() == SAVED
    await page.locator('#followups').evaluate('n=>n.open=true')
    await page.wait_for_function("$('followup-list').querySelectorAll('.followup-entry').length===2")
    f.browser_writer = await page.evaluate('draftWriter')
    f.draft_release.clear()
    await page.locator('#prompt').fill(UNSAVED)
    await page.locator('#turn-mode').select_option('plan')
    await page.locator('#prompt').focus()
    await page.locator('#prompt').evaluate("n=>{n.setSelectionRange(9,42,'backward');n.scrollTop=184;}")
    assert await asyncio.to_thread(f.draft_entered.wait, 10)
    assert load_draft(f.desk.store, SELECTED) == f.other_before['draft']
    return await snapshot_main(page)


async def unchanged_main(page, f, before, window_scroll=False):
    current = await snapshot_main(page)
    expected = copy.deepcopy(before)
    if not window_scroll:
        current.pop('windowScroll'); expected.pop('windowScroll')
    assert current == expected, {key: {'expected': expected[key], 'actual': current[key]} for key in expected if current.get(key) != expected[key]}
    assert load_draft(f.desk.store, SELECTED) == f.other_before['draft']
    assert followup_snapshot(f.desk.store, SELECTED) == f.other_before['queues']
    assert f.native_open == [SELECTED] and len(f.requests) == 1


async def ordinary(browser, width, mode, outcome):
    f = Fixture(); f.start(mode)
    result = {'case': 'request-only-cross-session', 'width': width, 'mode': mode, 'outcome': outcome,
              'passed': False, 'checks': []}
    context = page = None
    try:
        with patch.object(service, 'save_draft', side_effect=f.controlled_save):
            context, page, errors, requests, external = await make_page(browser, f, width)
            before = await prepare_main(page, f)
            boundary = len(requests); writes = f.desk.store.db.total_changes
            await overview(page)
            assert await review(page, f.original).count() == 1
            assert await page.locator(f'.preparation-session[data-session="{f.original}"] button[data-control="review"]').count() == 0
            assert await page.locator('#preparation-editor').is_hidden()
            await open_review(page, f.original)
            await exact_view(page, f)
            assert all(r['method'] == 'GET' for r in requests[boundary:]), requests[boundary:]
            assert f.desk.store.db.total_changes == writes
            await unchanged_main(page, f, before)
            await page.screenshot(path=str(OUT / f'{width}-{mode}-exact-request.png'))
            result['checks'].append('request-only row: exact long captured text/mode/original/current, private GET-only no empty editor')

            # Browser Range and captured-body scroll/disclosure survive authoritative refresh.
            await page.locator('#preparation-request-captured-text').evaluate("""n=>{
                n.focus({preventScroll:true});n.scrollTop=160;
                const r=document.createRange();r.setStart(n.firstChild,11);r.setEnd(n.firstChild,47);
                const s=getSelection();s.removeAllRanges();s.addRange(r);
            }""")
            body_before = await page.evaluate("({selection:getSelection().toString(),scroll:$('preparation-request-captured-text').scrollTop,open:$('preparation-request-captured').open})")
            await page.locator('#preparation-request-refresh').evaluate('n=>n.click()')
            await page.wait_for_function("!$('preparation-request-refresh').disabled && !$('preparation-request-status').textContent.startsWith('Reading')")
            body_after = await page.evaluate("({selection:getSelection().toString(),scroll:$('preparation-request-captured-text').scrollTop,open:$('preparation-request-captured').open})")
            assert body_after == body_before, {'before': body_before, 'after': body_after}
            await unchanged_main(page, f, before)
            result['checks'].append('read refresh keeps captured disclosure/selection/scroll and selected Plan/caret/ordered queues')

            await page.locator('#preparation-request-return').focus(); await page.keyboard.press('Enter')
            await page.wait_for_function("!$('preparation-request').open")
            assert await review(page, f.original).evaluate('n=>n===document.activeElement')
            await unchanged_main(page, f, before)
            await page.locator('#preparation-close').evaluate('n=>n.click()')
            await page.wait_for_function("!$('preparation').open")
            assert await page.evaluate('document.activeElement.id') == 'prompt'
            await unchanged_main(page, f, before, window_scroll=True)
            result['checks'].append('keyboard Return restores exact request row; outer Close returns prompt origin without losing editor')

            # Close a viewer whose authoritative HTTP read is delayed, then enter another editor.
            await overview(page)
            late = f.gate(session=f.original)
            await review(page, f.original).focus(); await page.keyboard.press('Enter')
            assert await asyncio.to_thread(late['entered'].wait, 10)
            await page.locator('#preparation-request-return').click()
            await page.locator(f'.preparation-session[data-session="{SELECTED}"] button[data-control="review"]').click()
            await page.locator('#preparation-text').fill(MODAL_EDIT)
            await page.locator('#preparation-mode').select_option('plan')
            await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(3,17);n.scrollTop=22;}")
            modal_before = await page.locator('#preparation-text').evaluate('n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,scroll:n.scrollTop})')
            async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/turn/request' and parse_qs(urlsplit(r.url).query).get('session') == [f.original]) as late_response:
                late['release'].set()
            await (await late_response.value).body()
            await page.evaluate('() => new Promise(r=>requestAnimationFrame(r))')
            await page.wait_for_function("!$('preparation-request').open")
            assert await page.locator('#preparation-text').evaluate('n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,scroll:n.scrollTop})') == modal_before
            assert await page.evaluate('document.activeElement.id') == 'preparation-text'
            await unchanged_main(page, f, before)
            result['checks'].append('late request GET after Return cannot reopen viewer or replace another unsaved Prepared editor')

            # Scope refresh and request resolution must retain the separate local Prepared editor.
            await page.locator('#preparation-project').select_option(str(f.path))
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            assert await page.locator('#preparation-text').input_value() == MODAL_EDIT
            await page.locator('#preparation-project').select_option('')
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            await open_review(page, f.original)
            await exact_view(page, f)
            resolve_boundary = len(requests)
            await page.locator('#preparation-request-' + outcome).click()
            await page.wait_for_function("!$('preparation-request-refresh').disabled && $('preparation-request-status').textContent.toLowerCase().includes('" + outcome + "')")
            if await page.locator('#preparation-request').evaluate('n=>n.open'):
                await page.locator('#preparation-request-return').click()
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            assert await review(page, f.original).count() == 0
            assert await page.locator(f'.preparation-session[data-session="{SELECTED}"]').count() == 1
            assert await page.locator('#preparation-text').input_value() == MODAL_EDIT
            sent = [r for r in requests[resolve_boundary:] if r['method'] == 'POST']
            assert len(sent) == 1 and sent[0]['path'] == '/api/turn/resolve'
            assert sent[0]['body'] == {'session': f.original, 'token': f.captured['token'], 'outcome': outcome}
            assert f.request('/api/turn/request?' + urlencode({'session': f.original, 'token': f.captured['token']}))[1]['request']['status'] == outcome
            assert f.original_before == {'draft': load_draft(f.desk.store, f.original), 'queues': followup_snapshot(f.desk.store, f.original)}
            await unchanged_main(page, f, before)
            assert not errors and not external, (errors, external)
            result['checks'].append('explicit existing resolution POST removes only original unresolved request; other local draft/queue edits retained')
            result.update(passed=True, http=requests, captured_chars=len(f.captured['text']), native_starts=1,
                          additional_native_starts=0, javascriptErrors=errors, external=external)
    except Exception as e:
        result.update(error=repr(e), traceback=traceback.format_exc(), http=f.http)
        if page:
            await page.screenshot(path=str(OUT / f'{width}-{mode}-failure.png'))
    finally:
        f.draft_release.set()
        if context:
            await context.close()
        f.finish()
    return result


async def cold_scoped(browser, width):
    f = Fixture(); f.start('plan', prepared=True)
    context = page = None
    old = None
    result = {'case': 'cold-scope-binding-request-and-preparation', 'width': width, 'passed': False, 'checks': []}
    try:
        f.desk.store.archive(f.original, True)
        old = f.cold()
        with patch.object(service, 'Runtime', side_effect=AssertionError('Review auto-started native Runtime')):
            context, page, errors, requests, external = await make_page(browser, f, width)
            await overview(page)
            assert await review(page, f.original).count() == 0
            await page.locator('#preparation-archived').check()
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            assert await review(page, f.original).count() == 1
            assert await page.locator(f'.preparation-session[data-session="{f.original}"] button[data-control="review"]').count() == 1
            await page.locator('#preparation-project').select_option(str(f.other_project))
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            assert await review(page, f.original).count() == 0
            await page.locator('#preparation-project').select_option(str(f.path))
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            await open_review(page, f.original)
            await exact_view(page, f)
            assert not await page.evaluate('selected')
            assert not f.desk.runtimes and not f.native_open and len(f.requests) == 1
            assert all(r['method'] == 'GET' for r in requests)
            result['checks'].append('actual new Desk+Store+HTTP handler cold GET-only; default/archive/exact project scopes; dual review controls')
            f.desk.store.update(f.original, thread_id='native-replacement')
            await page.locator('#preparation-request-refresh').click()
            await page.wait_for_function("!$('preparation-request-refresh').disabled && !$('preparation-request-status').textContent.startsWith('Reading')")
            await exact_view(page, f, mismatch=True)
            for outcome in ('accepted', 'rejected'):
                control = page.locator('#preparation-request-' + outcome)
                assert await control.is_hidden() or await control.is_disabled()
                await control.evaluate('n=>n.click()')
            assert all(r['method'] == 'GET' for r in requests)
            result['checks'].append('original/current mismatch evidence exact, both resolutions unavailable and forced activation sends no POST')
            await page.screenshot(path=str(OUT / f'{width}-cold-binding-mismatch.png'))
            await page.locator('#preparation-request-return').click()
            await page.locator('#preparation-close').click()
            await page.reload()
            await page.wait_for_function('state.sessions.length===2')
            await overview(page)
            await page.locator('#preparation-archived').check()
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            await open_review(page, f.original)
            await exact_view(page, f, mismatch=True)
            assert not f.desk.runtimes and not f.native_open and len(f.requests) == 1
            assert all(r['method'] == 'GET' for r in requests)
            assert not errors and not external
            result['checks'].append('fresh browser reload rediscovers exact original request with no retained token, no task select/open/turn POST')
            result.update(passed=True, http=requests, javascriptErrors=errors, external=external, native_starts=1,
                          additional_native_starts=0, actual_cold_store=True)
    except Exception as e:
        result.update(error=repr(e), traceback=traceback.format_exc(), http=f.http)
        if page:
            await page.screenshot(path=str(OUT / f'{width}-cold-failure.png'))
    finally:
        if context:
            await context.close()
        f.finish()
        if old:
            old.store.db.close()
    return result


async def late_resolution(browser, width):
    f = Fixture(); f.start('native', prepared=True)
    context = page = None
    result = {'case': 'late-resolution-return-then-refresh', 'width': width, 'passed': False, 'checks': []}
    try:
        context, page, errors, requests, external = await make_page(browser, f, width)
        await overview(page)
        await page.locator(f'.preparation-session[data-session="{f.original}"] button[data-control="review"]').click()
        await page.locator('#preparation-text').fill(MODAL_EDIT)
        await page.locator('#preparation-mode').select_option('plan')
        await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(4,19,'backward');n.scrollTop=20;}")
        modal_before = await page.locator('#preparation-text').evaluate('n=>({text:n.value,mode:document.querySelector("#preparation-mode").value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})')
        await open_review(page, f.original)
        await exact_view(page, f)
        late = f.gate('/api/turn/resolve', 'POST')
        await page.locator('#preparation-request-rejected').click()
        assert await asyncio.to_thread(late['entered'].wait, 10)
        assert late['value']['request']['status'] == 'rejected'
        await page.locator('#preparation-request-return').focus(); await page.keyboard.press('Enter')
        await page.wait_for_function("!$('preparation-request').open")
        assert await review(page, f.original).evaluate('n=>n===document.activeElement')
        await page.locator('#preparation-text').focus()
        async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/turn/resolve') as response_info:
            late['release'].set()
        await (await response_info.value).body()
        await page.evaluate('() => new Promise(r=>requestAnimationFrame(r))')
        assert not await page.locator('#preparation-request').evaluate('n=>n.open')
        assert await page.evaluate('document.activeElement.id') == 'preparation-text'
        assert await page.locator('#preparation-text').evaluate('n=>({text:n.value,mode:document.querySelector("#preparation-mode").value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})') == modal_before
        assert await review(page, f.original).count() == 1
        result['checks'].append('resolve already persisted, Return before reply invalidates late UI response without replacing local editor or stealing focus')
        # Another ordinary writer clears the saved draft while our local editor is unsaved.
        prior = load_draft(f.desk.store, f.original)
        assert f.request('/api/draft', {'session': f.original, 'text': '', 'mode': 'plan',
            'revision': prior['revision'], 'writer': 'another-ordinary-draft-writer', 'sequence': 1})[0] == 200
        await page.locator('#preparation-refresh').evaluate('n=>n.click()')
        await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
        assert await review(page, f.original).count() == 0
        assert await page.locator(f'.preparation-session[data-session="{f.original}"] button[data-control="review"]').count() == 1
        assert await page.locator('#preparation-text').input_value() == MODAL_EDIT
        assert await page.locator('#preparation-conflict').is_visible()
        assert await page.locator('#preparation-text').evaluate('n=>({text:n.value,mode:document.querySelector("#preparation-mode").value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})') == modal_before
        assert await page.evaluate('document.activeElement.id') == 'preparation-text'
        assert followup_snapshot(f.desk.store, f.original) == f.original_before['queues']
        assert f.other_before == {'draft': load_draft(f.desk.store, SELECTED), 'queues': followup_snapshot(f.desk.store, SELECTED)}
        assert len(f.requests) == 1 and not f.native_open
        posts = [r for r in requests if r['method'] == 'POST']
        assert len(posts) == 1 and posts[0]['body'] == {'session': f.original, 'token': f.captured['token'], 'outcome': 'rejected'}
        assert not errors and not external
        await page.screenshot(path=str(OUT / f'{width}-late-resolution-conflict-preserved.png'))
        result['checks'].append('explicit overview refresh drops only resolved request; current cleared draft revision becomes existing conflict, local Plan/caret/queue remain')
        result.update(passed=True, http=requests, javascriptErrors=errors, external=external, native_starts=1, additional_native_starts=0)
    except Exception as e:
        result.update(error=repr(e), traceback=traceback.format_exc(), http=f.http)
        if page:
            await page.screenshot(path=str(OUT / f'{width}-late-resolution-failure.png'))
    finally:
        if context:
            await context.close()
        f.finish()
    return result


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        results = []
        for width in (1250, 390):
            for mode, outcome in (('native', 'rejected'), ('plan', 'accepted')):
                result = await ordinary(browser, width, mode, outcome)
                results.append(result)
                print(json.dumps({k: result.get(k) for k in ('case', 'width', 'mode', 'outcome', 'passed', 'error')}, ensure_ascii=False), flush=True)
            result = await cold_scoped(browser, width)
            results.append(result)
            print(json.dumps({k: result.get(k) for k in ('case', 'width', 'passed', 'error')}, ensure_ascii=False), flush=True)
            result = await late_resolution(browser, width)
            results.append(result)
            print(json.dumps({k: result.get(k) for k in ('case', 'width', 'passed', 'error')}, ensure_ascii=False), flush=True)
        await browser.close()
    report = {'source': str(SOURCE), 'package': str(PACKAGE), 'version': codex_desk.__version__, 'installed': os.environ.get('DESK_USE_INSTALLED') == '1',
              'result': 'PASS' if all(r['passed'] for r in results) else 'FAIL', 'checks': results}
    (OUT / 'result.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    assert report['result'] == 'PASS', 'Real browser evidence contains failures'

if __name__ == '__main__':
    asyncio.run(main())
