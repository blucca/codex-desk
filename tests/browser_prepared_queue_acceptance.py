#!/usr/bin/env python3
"""Prepared queue ordinary edges through actual SQLite/HTTP/isolated Chromium.

Uses the retained request fixture's controlled native transport only. Run with
DESK_SOURCE, DESK_CHROMIUM, DESK_TEST_TEMP and DESK_TEST_EVIDENCE. Every assertion
group and completed case writes a durable checkpoint; one Chromium per batch,
fresh nonpersistent contexts. Also supports the installed-artifact fixture flags.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import traceback
from urllib.parse import urlsplit
from unittest.mock import patch

SOURCE = Path(os.environ.get('DESK_SOURCE', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(SOURCE / 'tests'))
import browser_prepared_queue_editor as baseline
c = baseline.c
from codex_desk.followups import reserve_followup, record_followup_receipt

RESULTS = []


def checkpoint(result=None):
    summary = {'passed': all(r['passed'] for r in RESULTS), 'completed_cases': len(RESULTS),
               'results': RESULTS, 'current': result, 'source': str(SOURCE),
               'package': str(c.PACKAGE)}
    target = c.OUT / 'checkpoint.json'
    staged = c.SCRATCH / 'prepared-queue-checkpoint.new.json'
    staged.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    staged.replace(target)
    # The remote launcher mirrors this receipt after every assertion group.
    compact = {**summary, 'results': [{k: v for k, v in r.items() if k != 'http'} for r in RESULTS],
               'current': result and {k: v for k, v in result.items() if k != 'http'}}
    print('CHECKPOINT_JSON ' + json.dumps(compact, ensure_ascii=False), flush=True)


def checked(result, message):
    result['checks'].append(message)
    checkpoint(result)


async def idle(page):
    await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")


async def refresh(page):
    await page.locator('#preparation-refresh').evaluate('n=>n.click()')
    await idle(page)


def row(page, identifier):
    return page.locator(f'.preparation-followup[data-followup="{identifier}"]')


async def queue_view(box):
    return await box.locator('textarea').evaluate("""n=>({text:n.value,
        mode:n.parentElement.querySelector('select').value,
        caret:[n.selectionStart,n.selectionEnd,n.selectionDirection],scroll:n.scrollTop})""")


async def edit_queue(page, identifier, value='Local correction 保留  \n' + 'scroll line\n' * 60):
    box = row(page, identifier)
    await box.locator('[data-control="queue-edit"]').click()
    await box.locator('textarea').fill(value)
    await box.locator('select').select_option('plan')
    await box.locator('textarea').evaluate("n=>{n.focus();n.setSelectionRange(7,23,'backward');n.scrollTop=73;}")
    return box, await queue_view(box)


async def independent(page, session):
    await page.locator(f'.preparation-session[data-session="{session}"] [data-control="review"]').click()
    await page.wait_for_function("!$('preparation-text').disabled")
    await page.locator('#preparation-text').fill(c.MODAL_EDIT * 35)
    await page.locator('#preparation-mode').select_option('plan')
    await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(7,35,'backward');n.scrollTop=61;}")
    return await baseline.draft_snapshot(page)


async def intact(page, f, main, draft):
    await c.unchanged_main(page, f, main)
    assert await baseline.draft_snapshot(page) == draft


def other_window(f, operation, **payload):
    status, result = f.request('/api/followups/' + operation, {'session': f.original, **payload})
    assert status == 200, (status, result)
    return result


async def release_response(page, gate):
    async with page.expect_event('requestfinished', predicate=lambda r: urlsplit(r.url).path == gate['path']) as pending:
        gate['release'].set()
    await pending.value
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def cold_scope(page, f, result):
    main = await c.prepare_main(page, f)
    await c.overview(page)
    assert not await page.locator(f'.preparation-session[data-session="{f.original}"]').count()
    await page.locator('#preparation-archived').check()
    await idle(page)
    assert await page.locator(f'.preparation-session[data-session="{f.original}"]').count() == 1
    draft = await independent(page, f.original)
    first = c.followup_snapshot(f.desk.store, f.original)['entries'][0]
    box, view = await edit_queue(page, first['id'])
    before = c.load_draft(f.desk.store, f.original)
    checked(result, 'cold new Desk/Store: archived preparation from missing project folder is read/editable locally without native startup')

    boundary = len(f.http)
    await page.locator('#preparation-project').select_option(str(f.other_project))
    await idle(page)
    assert not await page.locator(f'.preparation-session[data-session="{f.original}"]').count()
    assert 'Not listed in the current scope' in await page.locator('#preparation-editor-binding').inner_text()
    assert await queue_view(box) == view
    await intact(page, f, main, draft)
    assert not any('/api/followups?' in request['path'] for request in f.http[boundary:])
    await page.locator('#preparation-project').select_option(str(f.missing_project))
    await idle(page)
    assert await queue_view(box) == view
    await page.locator('#preparation-archived').uncheck()
    await idle(page)
    assert not await page.locator(f'.preparation-session[data-session="{f.original}"]').count()
    assert await queue_view(box) == view
    await page.locator('#preparation-archived').check()
    await idle(page)
    await intact(page, f, main, draft)
    checked(result, 'project/archive scoped omission is not queue removal; exact unsent queue text/mode/caret/scroll and independent draft survive scope round-trip')

    async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/followups/edit') as saved_response:
        await box.locator('[data-control="queue-save"]').click()
    assert (await saved_response.value).status == 200
    await page.wait_for_function("!document.querySelector('[data-control=queue-save]').disabled")
    entry = c.followup_snapshot(f.desk.store, f.original)['entries'][0]
    assert entry['text'] == view['text'] and entry['mode'] == 'plan' and entry['revision'] == first['revision'] + 1
    assert c.load_draft(f.desk.store, f.original) == before
    await intact(page, f, main, draft)
    assert not f.desk.runtimes and f.native_open == [c.SELECTED] and len(f.requests) == 1
    checked(result, 'explicit queue Save works on cold archived missing-folder session; no original native Open/turn, no draft save, other selected Plan/queue unchanged')


async def conflicts_reserved(page, f, result):
    main = await c.prepare_main(page, f)
    await c.overview(page)
    draft = await independent(page, f.original)
    entries = c.followup_snapshot(f.desk.store, f.original)['entries']
    first, second = entries
    box, view = await edit_queue(page, first['id'])
    remote = other_window(f, 'edit', id=first['id'], revision=first['revision'], text='Other window exact Work 保留  ', mode='native')['entries'][0]
    async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/followups/edit') as conflict:
        await box.locator('[data-control="queue-save"]').click()
    assert (await conflict.value).status == 409
    await box.locator('[data-control="queue-load"]').wait_for()
    assert await queue_view(box) == view
    assert await box.locator('[data-control="queue-save"]').is_disabled()
    assert await box.locator('pre').last.text_content() == remote['text']
    # The selected task's background state/event GETs can finish during
    # this local conflict choice; neither Load nor Keep may write.
    boundary = sum(request['method'] == 'POST' for request in f.http)
    await box.locator('[data-control="queue-load"]').click()
    assert await box.locator('textarea').input_value() == remote['text']
    assert await box.locator('select').input_value() == remote['mode']
    assert not await box.locator('[data-control="queue-keep"]').count()
    assert sum(request['method'] == 'POST' for request in f.http) == boundary
    await intact(page, f, main, draft)
    checked(result, 'real HTTP 409 preserves unsent queue edit; Load current adopts exact saved text/mode/revision with no write')

    local = 'Keep my exact edited Plan résumé 保留  \n' + 'scroll line\n' * 60
    await box.locator('textarea').fill(local)
    await box.locator('select').select_option('plan')
    await box.locator('textarea').evaluate("n=>{n.focus();n.setSelectionRange(7,23,'backward');n.scrollTop=73;}")
    view = await queue_view(box)
    remote2 = other_window(f, 'edit', id=first['id'], revision=remote['revision'], text='Another exact current Work  ', mode='native')['entries'][0]
    async with page.expect_response(lambda r: urlsplit(r.url).path == '/api/followups/edit') as conflict:
        await box.locator('[data-control="queue-save"]').click()
    assert (await conflict.value).status == 409
    await box.locator('[data-control="queue-keep"]').wait_for()
    boundary = sum(request['method'] == 'POST' for request in f.http)
    await box.locator('[data-control="queue-keep"]').click()
    assert await queue_view(box) == view
    assert sum(request['method'] == 'POST' for request in f.http) == boundary
    assert c.followup_snapshot(f.desk.store, f.original)['entries'][0] == remote2
    await box.locator('[data-control="queue-save"]').click()
    await page.wait_for_function("!document.querySelector('[data-control=queue-save]').disabled")
    latest = c.followup_snapshot(f.desk.store, f.original)['entries'][0]
    assert latest['text'] == local and latest['mode'] == 'plan' and latest['revision'] == remote2['revision'] + 1
    await intact(page, f, main, draft)
    checked(result, 'second real 409 Keep mine is read-only, retains exact local view; explicit Save replaces only reviewed newer revision')

    receipt = reserve_followup(f.desk.store, f.original, first['id'], latest['revision'])
    await refresh(page)
    assert await box.locator('textarea').input_value() == local
    assert await box.locator('textarea').is_disabled()
    assert await box.locator('[data-control="queue-save"]').is_disabled()
    for name in ('queue-edit', 'queue-remove', 'queue-up', 'queue-down', 'reuse-followup'):
        assert await box.locator(f'[data-control="{name}"]').count() == 0
    assert await page.locator('[data-control="queue-clear"]').is_disabled()
    second_box = row(page, second['id'])
    assert await second_box.locator('[data-control="queue-up"]').is_disabled()
    assert await second_box.locator('[data-control="queue-down"]').is_disabled()
    assert await second_box.locator('[data-control="queue-edit"]').is_enabled()
    assert await page.locator('.preparation-reservation pre').text_content() == receipt['text']
    second_box, second_view = await edit_queue(page, second['id'], 'Edit later queued Plan independently 保留  ')
    await second_box.locator('[data-control="queue-save"]').click()
    await page.wait_for_function("[...document.querySelectorAll('[data-control=queue-save]')].some(n=>!n.disabled)")
    assert c.followup_snapshot(f.desk.store, f.original)['reservation'] == receipt
    checked(result, 'pending reserved captured instruction is immutable in Prepared; Clear/Move disabled, later queued instruction remains independently editable and does not alter receipt')

    record_followup_receipt(f.desk.store, f.original, receipt['token'], first['id'], receipt['revision'], 'unknown')
    await refresh(page)
    assert await page.locator('.preparation-reservation h4').inner_text() == 'Start unconfirmed'
    assert 'Needs start review' in await box.locator('h4').inner_text()
    assert await box.locator('[data-control="queue-save"]').is_disabled()
    assert await page.locator('[data-control="queue-clear"]').is_disabled()
    record_followup_receipt(f.desk.store, f.original, receipt['token'], first['id'], receipt['revision'], 'rejected')
    await refresh(page)
    assert not await page.locator('.preparation-reservation').count()
    assert await box.locator('textarea').is_enabled()
    assert await box.locator('[data-control="queue-save"]').is_enabled()
    assert await box.locator('textarea').input_value() == local
    await intact(page, f, main, draft)
    checked(result, 'unknown receipt stays blocked and exact local edit retained; explicit external receipt resolution/Refresh re-enables queued edit without starting work')


async def delayed(page, f, result):
    main = await c.prepare_main(page, f)
    await c.overview(page)
    draft = await independent(page, f.original)
    first, second = c.followup_snapshot(f.desk.store, f.original)['entries']
    box, view = await edit_queue(page, first['id'])
    gate = f.gate('/api/followups/edit', method='POST')
    await box.locator('[data-control="queue-save"]').evaluate('n=>n.click()')
    assert await asyncio.to_thread(gate['entered'].wait, 10)
    saved = c.followup_snapshot(f.desk.store, f.original)['entries'][0]
    newer = other_window(f, 'edit', id=first['id'], revision=saved['revision'], text='Newer other-window queue after held save 保留  ', mode='native')['entries'][0]
    await refresh(page)
    assert await box.locator('[data-control="queue-keep"]').count() == 1
    await release_response(page, gate)
    assert await queue_view(box) == view
    assert await box.locator('[data-control="queue-save"]').is_disabled()
    assert await box.locator('pre').first.text_content() == newer['text']
    assert await box.locator('pre').last.text_content() == newer['text']
    await intact(page, f, main, draft)
    checked(result, 'held successful save after newer aggregate Refresh cannot roll back authoritative queue or clear newer conflict/local view')

    # Cancel/reopen the same instruction while a save is in flight. The old
    # edit object must not own the freshly created editor or its busy state.
    await box.locator('[data-control="queue-keep"]').click()
    gate2 = f.gate('/api/followups/edit', method='POST')
    await box.locator('[data-control="queue-save"]').evaluate('n=>n.click()')
    assert await asyncio.to_thread(gate2['entered'].wait, 10)
    await box.locator('[data-control="queue-cancel"]').click()
    await refresh(page)
    box, fresh_view = await edit_queue(page, first['id'], 'Fresh replacement unsent editor 保留  \n' + 'scroll line\n' * 60)
    await release_response(page, gate2)
    assert await queue_view(box) == fresh_view
    assert await box.locator('[data-control="queue-save"]').is_enabled()
    await intact(page, f, main, draft)
    checked(result, 'late save from cancelled editor cannot replace same-id freshly reopened unsent editor or own its controls')

    # Real stale revision conflict is held at HTTP reply, then a new queue
    # mutation and aggregate read become authoritative before that 409 lands.
    current = c.followup_snapshot(f.desk.store, f.original)['entries'][0]
    remote = other_window(f, 'edit', id=first['id'], revision=current['revision'], text='Current first before delayed conflict  ', mode='native')['entries'][0]
    conflict_gate = f.gate('/api/followups/edit', method='POST')
    await box.locator('[data-control="queue-save"]').evaluate('n=>n.click()')
    assert await asyncio.to_thread(conflict_gate['entered'].wait, 10)
    assert 'current' in conflict_gate['value']
    newest = other_window(f, 'edit', id=first['id'], revision=remote['revision'], text='Authoritative newest after delayed 409 保留  ', mode='plan')['entries'][0]
    await refresh(page)
    await release_response(page, conflict_gate)
    assert await queue_view(box) == fresh_view
    assert await box.locator('pre').first.text_content() == newest['text']
    assert await box.locator('pre').last.text_content() == newest['text']
    assert await box.locator('[data-control="queue-save"]').is_disabled()
    await intact(page, f, main, draft)
    checked(result, 'actual held HTTP 409 cannot roll back newer Refresh snapshot, newest conflict text or exact unsent replacement editor')

    # A stale removal's conflict includes all entries. Keep an authoritative
    # newer queue and a different Prepared editor visible while it returns.
    remove_gate = f.gate('/api/followups/remove', method='POST')
    other_window(f, 'edit', id=second['id'], revision=second['revision'], text='Second advanced to stale removal  ', mode='plan')
    await row(page, second['id']).locator('[data-control="queue-remove"]').evaluate('n=>n.click()')
    assert await asyncio.to_thread(remove_gate['entered'].wait, 10)
    assert 'current' in remove_gate['value']
    added = c.add_followup(f.desk.store, f.original, 'Newly queued after stale removal remains visible  ', 'native')
    await refresh(page)
    assert await row(page, added['id']).count() == 1
    other_draft = await independent(page, c.SELECTED)
    queue_other = c.followup_snapshot(f.desk.store, c.SELECTED)['entries'][0]
    other_box, other_view = await edit_queue(page, queue_other['id'], 'Different session unsent queue 保留  \n' + 'scroll line\n' * 60)
    await release_response(page, remove_gate)
    assert await queue_view(other_box) == other_view
    assert await baseline.draft_snapshot(page) == other_draft
    assert await page.locator('#preparation-editor-title').inner_text() == 'Preparation in Later selected Plan'
    await c.unchanged_main(page, f, main)
    await page.locator(f'.preparation-session[data-session="{f.original}"] [data-control="review"]').click()
    assert await row(page, added['id']).count() == 1
    assert await queue_view(box) == fresh_view
    await intact(page, f, main, draft)
    checked(result, 'actual delayed remove 409 cannot undo newer queue snapshot or draw over a different session editor; returning retains newly added row and both local editors')


async def run_case(browser, width, case):
    f = c.Fixture(); f.start('plan', prepared=True)
    c.add_followup(f.desk.store, f.original, 'Second exact queued Plan 保留  ', 'plan')
    result = {'case': case, 'width': width, 'passed': False, 'checks': []}
    context = page = old = None
    try:
        if case == 'cold-archived-missing-folder-scope':
            f.missing_project = f.path / 'no-longer-present-project'
            assert not f.missing_project.exists()
            f.desk.store.update(f.original, cwd=str(f.missing_project))
            f.desk.store.archive(f.original, True)
            old = f.cold()
        with patch.object(c.service, 'save_draft', side_effect=f.controlled_save), \
             patch.object(c.service, 'Runtime', side_effect=AssertionError('Prepared review started native Runtime')):
            context, page, errors, requests, external = await c.make_page(browser, f, width)
            if case == 'cold-archived-missing-folder-scope':
                await cold_scope(page, f, result)
            elif case == 'real-conflict-load-keep-reservation':
                await conflicts_reserved(page, f, result)
            else:
                await delayed(page, f, result)
            assert not errors and not external, (errors, external)
            assert len(f.requests) == 1 and f.native_open == [c.SELECTED]
            posts = [r for r in requests if r['method'] == 'POST']
            assert all(r['path'] in ('/api/open', '/api/draft', '/api/followups/edit', '/api/followups/remove') for r in posts), posts
            assert all(r['path'] != '/api/draft' or r['body']['session'] == c.SELECTED for r in posts), posts
            result.update(passed=True, http=requests, browser_errors=errors, external=external,
                          native_starts=1, extra_native_starts=0, installed=os.environ.get('DESK_USE_INSTALLED') == '1')
            await page.screenshot(path=str(c.OUT / f'{case}-{width}.png'))
    except Exception as error:
        result.update(error=repr(error), traceback=traceback.format_exc(), http=f.http)
        if page:
            try:
                await page.screenshot(path=str(c.OUT / f'{case}-{width}-failure.png'))
            except Exception:
                pass
    finally:
        f.draft_release.set()
        for gate in f.gates:
            gate['release'].set()
        if context:
            await context.close()
        f.finish()
        if old:
            old.store.db.close()
    return result


async def main():
    checkpoint({'stage': 'launching isolated Chromium', 'checks': []})
    async with c.async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                                         args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            for width in ((1250, 390) if os.environ.get('DESK_QUEUE_BASELINE', '1') == '1' else ()):
                result = await baseline.check(browser, width)
                result['case'] = 'ordinary-edit-move-save-remove-clear'
                RESULTS.append(result)
                checkpoint()
                if not result['passed']:
                    print(result.get('traceback', ''), flush=True)
                    return 1
            cases = os.environ.get('DESK_QUEUE_CASES', 'cold-archived-missing-folder-scope,real-conflict-load-keep-reservation,delayed-save-new-editor-and-409-refresh').split(',')
            for case in cases:
                for width in (1250, 390):
                    result = await run_case(browser, width, case)
                    RESULTS.append(result)
                    (c.OUT / f'{case}-{width}.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
                    checkpoint()
                    if not result['passed']:
                        print(result.get('traceback', ''), flush=True)
                        return 1
        finally:
            await browser.close()
    (c.OUT / 'result.json').write_text(json.dumps({'passed': True, 'results': RESULTS}, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'passed': True, 'cases': len(RESULTS), 'checks': sum(len(r['checks']) for r in RESULTS)}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
