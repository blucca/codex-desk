"""Proposed-plan streaming, original reading and reuse through local HTTP/Chromium."""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import traceback
from urllib.parse import urlsplit

SOURCE = Path(os.environ.get('DESK_SOURCE', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(SOURCE / 'tests'))
if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(SOURCE))
from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright

OUT = Path(os.environ['DESK_TEST_EVIDENCE'])
OUT.mkdir(parents=True, exist_ok=True)
FINAL = '# Final proposed plan — résumé 保留\n1. Inspect <script>literal</script>.\n2. Run parser unit tests.\n' + ''.join(
    f'Exact plan evidence line {i:04d}: preserve Unicode résumé 保留 and literal <&> text.\n' for i in range(450))


async def one(browser, width):
    f = NativeHTTPFixture(); f.setUp()
    context = None; result = {'width': width, 'passed': False, 'checks': []}
    requests = []; errors = []
    try:
        session = f.identifier
        f.desk.store.update(session, status='ready', thread_saved=1, mode='plan', name_pending=0)
        save_draft(f.desk.store, session, 'Unsent Plan stays exact résumé', 'plan', 0, 'fixture', 1)
        add_followup(f.desk.store, session, 'Prepared Work stays paused', 'native')
        add_followup(f.desk.store, session, 'Prepared Plan stays paused', 'plan')
        def preparation():
            return {'draft': load_draft(f.desk.store, session), 'queue': followup_snapshot(f.desk.store, session),
                    'mode': f.desk.store.get(session)['mode']}
        before = preparation()
        thread = {'id': 'native-original', 'cwd': str(f.path), 'modelProvider': 'fixture', 'turns': []}
        class Catalog:
            def request(self, method, params):
                assert method == 'thread/list'
                return {'data': [], 'nextCursor': None}
        f.desk.catalog = lambda: Catalog()
        f.desk.open = lambda target: {'thread': copy.deepcopy(thread), 'model': 'fixture', 'modelProvider': 'fixture'}
        f.desk.history = lambda identifier: copy.deepcopy(thread)
        def event(method, params):
            with f.runtime.lifecycle_lock:
                f.runtime._message({'method': method, 'params': params})
        def start(turn):
            event('turn/started', {'threadId': 'native-original', 'turn': {'id': turn, 'status': 'inProgress', 'items': []}})
        scope = {'threadId': 'native-original', 'turnId': 'plan-turn'}
        context = await browser.new_context(viewport={'width': width, 'height': 900})
        await context.grant_permissions(['clipboard-read', 'clipboard-write'])
        page = await context.new_page(); page.set_default_timeout(18000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append({'method': request.method, 'path': urlsplit(request.url).path}))
        async def drained():
            seq = f.desk.store.events(session)[-1]['seq']
            await page.wait_for_function('(seq)=>after>=seq', arg=seq)
        await page.goto(f'http://127.0.0.1:{f.server.server_port}/')
        await page.locator(f'.session-row[data-session="{session}"] .session').click()
        await page.wait_for_function('(s)=>selected===s&&!opening', arg=session)
        boundary = len(requests)
        start('plan-turn')
        event('item/started', {**scope, 'item': {'id': 'proposal', 'type': 'plan', 'text': ''}})
        event('item/plan/delta', {**scope, 'itemId': 'proposal', 'delta': '# Provisional plan — résumé\n' + 'Inspect exact tokenizer decision.\n' * 450})
        await drained()
        body = page.locator('[data-item-id="proposal"] .activity-plan')
        assert (await body.inner_text()).startswith('# Provisional plan — résumé')
        await body.focus(); await body.evaluate('''(n)=>{
          n.scrollTop=140;n.scrollLeft=0;const range=document.createRange();
          range.setStart(n.firstChild,2);range.setEnd(n.firstChild,20);
          const s=window.getSelection();s.removeAllRanges();s.addRange(range);
        }''')
        selected_text = await page.evaluate('window.getSelection().toString()')
        count_before = await page.evaluate('latestUpdates')
        event('item/plan/delta', {**scope, 'itemId': 'proposal', 'delta': 'Next reported plan step.\n'})
        await drained()
        assert await body.evaluate('(n)=>document.activeElement===n && n.scrollTop===140')
        assert await page.evaluate('window.getSelection().toString()') == selected_text
        await page.wait_for_function('(n)=>latestUpdates>n', arg=count_before)
        assert 'Streaming' in await page.locator('[data-item-id="proposal"] .activity-plan-label').inner_text()
        result['checks'].append('actual HTTP native deltas stream literal text, preserve DOM Range/focus/scroll and register Latest output without following')

        event('turn/plan/updated', {**scope, 'explanation': 'Separate native work checklist',
            'plan': [{'step': 'Inspect original', 'status': 'inProgress'}, {'step': 'Verify', 'status': 'pending'}]})
        final_item = {'id': 'proposal', 'type': 'plan', 'text': FINAL}
        event('item/completed', {**scope, 'item': final_item})
        event('turn/completed', {'threadId': 'native-original', 'turn': {'id': 'plan-turn', 'status': 'completed', 'items': [final_item]}})
        thread['turns'] = [{'id': 'plan-turn', 'status': 'completed', 'items': [final_item]}]
        f.desk.native_index.replace_snapshot(thread)
        await drained()
        assert await body.text_content() == FINAL
        assert 'Final native item' in await page.locator('[data-item-id="proposal"] .activity-plan-label').inner_text()
        assert await page.evaluate("DeskNativeSteps.state().reported.plan[0].step==='Inspect original' && DeskNativeSteps.state().reported.plan[0].status==='inProgress'")
        assert await page.locator('#turn-mode').input_value() == 'plan'
        result['checks'].append('final native item exactly replaces provisional text; task checklist and Plan preparation remain separate')

        await page.locator('#read-original').click()
        await page.wait_for_function("$('history-reader').open && $('history-reader-body').textContent.includes('Final proposed plan')")
        assert 'No readable text renderer' not in await page.locator('#history-reader-body').inner_text()
        await page.locator('#history-reader-find-query').fill('evidence line 0449')
        await page.locator('#history-reader-find-submit').click()
        await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')")
        await page.locator('.history-reader-target .history-reader-copy-text').click()
        await page.wait_for_function("document.querySelector('.history-reader-target .history-reader-copy-status').textContent.includes('copied')")
        assert await page.evaluate('navigator.clipboard.readText()') == 'Proposed plan\n' + FINAL
        await page.locator('#history-reader-back').click()
        await page.locator('#handoff').click()
        await page.wait_for_function("$('preview').open && $('handoff-text').value.includes('Proposed plan')")
        handoff = await page.locator('#handoff-text').input_value()
        assert 'Item proposal\nProposed plan\n' + FINAL[:1000] in handoff
        assert '[This item was shortened at the handoff character limit.]' in handoff
        await page.locator('#preview-close').click()
        response = await page.request.get(f'http://127.0.0.1:{f.server.server_port}/api/recall?q=evidence%20line%200449')
        hits = await response.json()
        assert response.status == 200 and hits['total'] == 1 and hits['results'][0]['item_id'] == 'proposal'
        result['checks'].append('full original Find/clipboard and reviewed handoff include exact Plan; combined recall retains one exact native identity')

        await page.reload(); await page.wait_for_function('(s)=>selected===s&&!opening', arg=session)
        assert await page.locator('[data-item-id="proposal"] .activity-plan').text_content() == FINAL
        start('partial-turn')
        partial_scope = {'threadId': 'native-original', 'turnId': 'partial-turn'}
        event('item/started', {**partial_scope, 'item': {'id': 'partial-proposal', 'type': 'plan', 'text': ''}})
        event('item/plan/delta', {**partial_scope, 'itemId': 'partial-proposal', 'delta': 'Partial next reported plan.'})
        event('turn/completed', {'threadId': 'native-original', 'turn': {'id': 'partial-turn', 'status': 'interrupted', 'items': []}})
        event('item/plan/delta', {**partial_scope, 'itemId': 'partial-proposal', 'delta': 'LATE MUST NOT APPEND'})
        await drained()
        assert await page.locator('[data-item-id="partial-proposal"] .activity-plan').inner_text() == 'Partial next reported plan.'
        assert 'Task interrupted' in await page.locator('[data-item-id="partial-proposal"] .activity-plan-label').inner_text()
        assert preparation() == before
        assert errors == []
        assert f.requests == [] and f.sent == []
        blocked = {'/api/turn', '/api/followups/send', '/api/stop', '/api/steer', '/api/handoff/start', '/api/approval', '/api/answer'}
        assert not [q for q in requests[boundary:] if q['method'] == 'POST' and q['path'] in blocked]
        assert await page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        await page.screenshot(path=str(OUT / f'case-{width}.png'), full_page=True)
        result['checks'].append('cold page replay and next interrupted partial retain honest evidence; modes/two queues/draft exact, zero native sends and mobile overflow')
        result.update(passed=True, finalChars=len(FINAL), nativeRequests=0, nativeSends=0, errors=errors, http=requests)
    except Exception as error:
        result.update(error=str(error), traceback=traceback.format_exc())
    finally:
        if context: await context.close()
        f.doCleanups()
    (OUT / f'case-{width}.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('http', 'traceback')}), flush=True)
    return result


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'])
        try: rows = [await one(browser, 1250), await one(browser, 390)]
        finally: await browser.close()
    (OUT / 'result.json').write_text(json.dumps({'passed': all(row['passed'] for row in rows), 'results': rows}, indent=2) + '\n')
    for row in rows:
        if not row['passed']: print(row.get('traceback'))
    assert all(row['passed'] for row in rows)


if __name__ == '__main__':
    asyncio.run(main())
