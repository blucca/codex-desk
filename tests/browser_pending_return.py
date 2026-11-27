"""Independent actual-open cross-session native interaction/viewport acceptance."""
import asyncio
import json
import os
from pathlib import Path
import sys
import threading
import traceback
from unittest.mock import Mock

S = Path(os.environ.get('DESK_SOURCE', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(S / 'tests'))
if os.environ.get('DESK_USE_INSTALLED') != '1': sys.path.insert(0, str(S))
import codex_desk
if os.environ.get('DESK_USE_INSTALLED') == '1':
    assert not Path(codex_desk.__file__).resolve().is_relative_to(S)
from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.runtime import Runtime
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright

OUT = Path(os.environ['DESK_TEST_EVIDENCE']); OUT.mkdir(parents=True, exist_ok=True)

async def one(browser, width):
    f = NativeHTTPFixture(); f.setUp(); context = None
    report = {'width': width, 'passed': False, 'checks': {}}
    errors = []; http = []
    try:
        a = f.identifier; b = 'session-b'
        f.desk.store.update(a, status='ready', thread_saved=1, name_pending=0)
        f.desk.store.create(str(f.path), 'default', identifier=b, name='Independent B')
        f.desk.store.update(b, thread_id='native-b', status='ready', thread_saved=1, name_pending=0)
        rb = object.__new__(Runtime)
        rb.store, rb.id, rb.home = f.desk.store, b, f.path
        rb.approvals = {}; rb.persisted = rb.closing = False
        rb.lifecycle_lock = threading.Lock(); rb.process = Mock(); rb.process.poll.return_value = None
        rb.send = f.send_native; rb._flush_name = lambda: None
        f.desk.runtimes[b] = rb
        for sid in (a, b):
            save_draft(f.desk.store, sid, 'Unsent Plan preparation ' + sid, 'plan', 0)
            add_followup(f.desk.store, sid, 'Prepared Work ' + sid, 'native')
            add_followup(f.desk.store, sid, 'Prepared Plan ' + sid, 'plan')
        def preparation():
            return {sid: {'draft': load_draft(f.desk.store, sid), 'queue': followup_snapshot(f.desk.store, sid)} for sid in (a, b)}
        before = preparation()
        threads = {a: 'native-original', b: 'native-b'}
        class Catalog:
            def request(self, method, params):
                assert method == 'thread/list'; return {'data': [], 'nextCursor': None}
        f.desk.catalog = lambda: Catalog()
        f.desk.open = lambda sid: {'thread': {'id': threads[sid], 'turns': []}, 'model': 'fixture', 'modelProvider': 'fixture'}
        def receive(runtime, message):
            with runtime.lifecycle_lock: runtime._message(message)
        def question(runtime, request_id, label):
            receive(runtime, {'id': request_id, 'method': 'item/tool/requestUserInput', 'params': {
                'threadId': threads[runtime.id], 'turnId': 'turn-' + label,
                'questions': [{'id': 'answer', 'header': label, 'question': 'Decision?'},
                              {'id': 'secret', 'header': label, 'question': 'Private answer?', 'isSecret': True}]}})
        context = await browser.new_context(viewport={'width': width, 'height': 900})
        page = await context.new_page(); page.set_default_timeout(16000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: http.append({'method': request.method, 'url': request.url}))
        async def select(sid):
            await page.locator(f'.session-row[data-session="{sid}"] .session').click()
            await page.wait_for_function('(sid)=>selected===sid&&!opening', arg=sid)
        async def drained(sid):
            seq = f.desk.store.events(sid)[-1]['seq']
            await page.wait_for_function('(seq)=>after>=seq', arg=seq)
            await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        await page.goto(f'http://127.0.0.1:{f.server.server_port}/'); await select(a)
        question(f.runtime, 201, 'A'); question(rb, 201, 'B'); await drained(a); await page.evaluate('refresh()')
        note_a = page.get_by_label('A — Decision?', exact=True); secret_a = page.get_by_label('A — Private answer?', exact=True)
        await note_a.fill('A exact pending correction'); await secret_a.fill('A ephemeral private text')
        await note_a.evaluate('(e)=>{e.setSelectionRange(3,8);window.oldANote=e;window.oldASecret=e.form.querySelector("input[type=password]")}')
        await select(b)
        note_b = page.get_by_label('B — Decision?', exact=True); secret_b = page.get_by_label('B — Private answer?', exact=True)
        await note_b.fill('B independent response'); await secret_b.fill('B ephemeral private text')
        await select(a)
        report['checks']['actualOpenABAExactAnswer'] = await note_a.input_value() == 'A exact pending correction' and await secret_a.input_value() == 'A ephemeral private text'
        report['checks']['actualOpenABAExactNode'] = await note_a.evaluate('(e)=>e===window.oldANote&&e.selectionStart===3&&e.selectionEnd===8')
        report['actualReturnValues'] = {'answer': await note_a.input_value(), 'secret': await secret_a.input_value()}

        # Test hidden-owner retirement independently, even when the first return loses its editor.
        await note_a.fill('Second A pending correction'); await secret_a.fill('Second A private text')
        await secret_a.evaluate('(e)=>{window.retiredSecret=e;window.retiredForm=e.form}')
        await select(b); await note_b.focus(); await page.evaluate('()=>window.scrollTo(0,document.documentElement.scrollHeight)')
        await note_b.scroll_into_view_if_needed()
        position = await note_b.evaluate('(e)=>e.getBoundingClientRect().top')
        latest = await page.evaluate('latestUpdates')
        receive(rb, {'method': 'item/started', 'params': {'threadId': 'native-b', 'turnId': 'turn-B',
            'item': {'id': 'stream-b', 'type': 'agentMessage', 'text': 'Fresh native output\n' * 150}}})
        receive(rb, {'method': 'item/agentMessage/delta', 'params': {'threadId': 'native-b', 'turnId': 'turn-B', 'itemId': 'stream-b', 'delta': 'Later streamed output\n' * 120}})
        await drained(b)
        report['viewport'] = {'beforeTop': position, 'afterTop': await note_b.evaluate('(e)=>e.getBoundingClientRect().top'), 'focused': await note_b.evaluate('(e)=>document.activeElement===e')}
        report['checks']['questionFocusAndViewportDuringOutput'] = abs(report['viewport']['afterTop'] - position) < 3 and report['viewport']['focused']
        report['checks']['newOutputRegistersWithoutFollowing'] = await page.evaluate('latestUpdates') > latest
        receive(f.runtime, {'method': 'serverRequest/resolved', 'params': {'threadId': 'native-original', 'requestId': 201}})
        await page.evaluate('refresh()')
        report['checks']['resolvedHiddenAClearsDetachedSecret'] = await page.evaluate('window.retiredSecret.value==="" && !window.retiredForm.isConnected')
        report['checks']['sameNativeRequestIdBIndependent'] = await note_b.input_value() == 'B independent response' and await secret_b.input_value() == 'B ephemeral private text'
        if not report['checks']['sameNativeRequestIdBIndependent']:
            await note_b.fill('B independent response'); await secret_b.fill('B ephemeral private text')
        await page.get_by_role('button', name='Send answers', exact=True).click()
        await page.wait_for_function('()=>!requests.has("201")')
        report['checks']['answeredBExactOriginalTarget'] = f.sent == [{'id': 201, 'result': {'answers': {
            'answer': {'answers': ['B independent response']}, 'secret': {'answers': ['B ephemeral private text']}}}}]
        report['checks']['noSecretPersistence'] = not await page.evaluate('JSON.stringify({...localStorage,...sessionStorage}).includes("ephemeral private")')
        await select(a)
        report['checks']['resolvedAReturnDoesNotResurrect'] = await page.get_by_role('button', name='Send answers', exact=True).count() == 0
        report['checks']['preparationExactAndNoNativeTasks'] = preparation() == before and f.requests == []
        report['checks']['noBrowserErrors'] = errors == []
        report['passed'] = all(report['checks'].values())
        report.update(nativeResponses=f.sent, errors=errors)
        await page.screenshot(path=str(OUT / f'case-{width}.png'), full_page=True)
    except Exception as error:
        report.update(error=str(error), traceback=traceback.format_exc())
    finally:
        if context: await context.close()
        f.doCleanups()
    (OUT / f'case-{width}.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('traceback', 'nativeResponses')}), flush=True)
    return report

async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        try: rows = [await one(browser, width) for width in (1250, 390)]
        finally: await browser.close()
    (OUT / 'result.json').write_text(json.dumps({'passed': all(r['passed'] for r in rows), 'cases': rows}, indent=2) + '\n')
    assert all(r['passed'] for r in rows), rows

if __name__ == '__main__': asyncio.run(main())
