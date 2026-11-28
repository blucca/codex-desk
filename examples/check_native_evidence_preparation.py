#!/usr/bin/env python3
"""Installed daily journey: remembered original → preparation → cold return → Run recovery."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import codex_desk
from codex_desk import server as product
from codex_desk.evidence_reference import parse_evidence_blocks, format_evidence_block
from codex_desk.followups import edit_followup
from playwright.async_api import async_playwright
from native_workbench_fixture import (
    WorkbenchFixture, SOURCE, TURN, ITEM, QUOTE, NEWER,
    INSTRUCTION_ITEM, RESPONSE_ITEM, INSTRUCTION, RESPONSE,
)


async def frames(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def ready(page):
    await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")


async def backward_quote(page, target):
    mark = target.locator('mark')
    await mark.scroll_into_view_if_needed()
    rects = await mark.evaluate('n=>[...n.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))')
    first, last = rects[0], rects[-1]
    await page.mouse.move(last['right']-.5, (last['top']+last['bottom'])/2)
    await page.mouse.down()
    await page.mouse.move(first['left']+.5, (first['top']+first['bottom'])/2, steps=12)
    await page.mouse.up()
    assert await page.evaluate('getSelection().toString()') == QUOTE


async def run():
    source = Path(os.environ['DESK_SOURCE']).resolve()
    assert not Path(codex_desk.__file__).resolve().is_relative_to(source)
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']); evidence.mkdir(parents=True, exist_ok=True)
    fixture = WorkbenchFixture(); fixture.start(); result = {'result': 'RUNNING'}
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1250, 'height': 900})
        page = await context.new_page(); page.set_default_timeout(12000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        with patch.object(product, '_NativeReader', fixture.reader_type):
            try:
                await page.goto(fixture.url)
                await page.locator(f'.session-row[data-session="{fixture.identifier}"] .session').click()
                await page.wait_for_function('id=>selected===id&&!opening', arg=fixture.identifier)
                original_preparation = fixture.prepared()
                await page.locator('#search-saved-content').click()
                await page.locator('#recall-query').fill('retry budget')
                await page.locator('#recall-query').press('Enter')
                await page.wait_for_function("$('recall-summary').textContent.includes('not indexed yet')")
                await page.locator('#recall-index').click()
                await page.locator('#recall-results .recall-read').click(); await ready(page)
                assert fixture.prepared() == original_preparation and fixture.requests == []
                # Read this result's own instruction, response and command before reusing it.
                reads = len(fixture.history_calls); changes = fixture.desk.store.db.total_changes
                await page.locator(f'.history-reader-item[data-item-id="{ITEM}"] .history-reader-task-open').click()
                task = page.locator('.history-reader-task-context')
                assert f'Turn {TURN}' in await task.inner_text()
                await task.get_by_role('button', name='Read full instruction', exact=True).click()
                instruction = page.locator(f'.history-reader-target[data-item-id="{INSTRUCTION_ITEM}"]')
                assert await instruction.locator('.history-reader-text').inner_text() == 'User\n'+INSTRUCTION
                await page.locator('#history-reader-task-return').click()
                await task.get_by_role('button', name='Read this task response', exact=True).click()
                response = page.locator(f'.history-reader-target[data-item-id="{RESPONSE_ITEM}"]')
                assert await response.locator('.history-reader-text').inner_text() == 'Codex\n'+RESPONSE
                await page.locator('#history-reader-task-return').click()
                await task.get_by_role('button', name='Read this task’s evidence', exact=True).click()
                rows = page.locator('.history-reader-task-evidence-row')
                assert await rows.evaluate_all('ns=>ns.map(n=>[n.dataset.turnId,n.dataset.itemId])') == [
                    [TURN, INSTRUCTION_ITEM], [TURN, ITEM], [TURN, RESPONSE_ITEM]]
                await page.locator(f'.history-reader-task-evidence-row[data-item-id="{ITEM}"]').get_by_role('button', name='Read full original item', exact=True).click()
                command = page.locator(f'.history-reader-target[data-item-id="{ITEM}"] .history-reader-text')
                assert (await command.inner_text()).startswith('Command\ninspect retry\nStatus: completed\nExit: 1\nOriginal beginning')
                assert fixture.prepared() == original_preparation and fixture.requests == []
                assert len(fixture.history_calls) == reads and fixture.desk.store.db.total_changes == changes
                await page.locator('#history-reader-find-query').fill(QUOTE)
                await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')")
                target = page.locator(f'.history-reader-item[data-item-id="{ITEM}"]')
                await backward_quote(page, target)
                await page.set_viewport_size({'width': 390, 'height': 844}); await frames(page)
                assert await page.evaluate('getSelection().toString()') == QUOTE
                review = target.locator('.history-reader-review-evidence')
                for _ in range(16):
                    await page.keyboard.press('Tab')
                    if await review.evaluate('n=>n===document.activeElement'): break
                assert await review.evaluate('n=>n===document.activeElement')
                await page.keyboard.press('Enter')
                await page.wait_for_function("DeskEvidencePreparation.state()?.status==='review'")
                await page.locator('#evidence-preparation-note').fill('Use this check:\n~~~sh\npytest -q')
                changes = fixture.desk.store.db.total_changes; boundary = len(fixture.http)
                await page.locator('#evidence-preparation-append').click()
                assert 'Close the unfinished' in await page.locator('#evidence-preparation-status').inner_text()
                assert fixture.desk.store.db.total_changes == changes
                assert not [method for method, _ in fixture.http[boundary:] if method == 'POST']
                await page.locator('#evidence-preparation-note').fill('Use this check:\n~~~sh\npytest -q\n~~~')
                await page.locator('#evidence-preparation-append').click()
                await page.wait_for_function("!$('evidence-preparation').open")
                saved = fixture.prepared(); blocks = parse_evidence_blocks(saved['draft']['text'])
                assert len(blocks) == 1 and blocks[0]['reference']['quote'] == QUOTE
                assert blocks[0]['reference']['thread_id'] == SOURCE and saved['queue'] == original_preparation['queue']
                await page.locator('#history-reader-back').click(); await page.locator('#recall-close').click()
                storage = await context.storage_state(); await context.close()
                context = await browser.new_context(viewport={'width': 390, 'height': 844}, storage_state=storage)
                page = await context.new_page(); page.set_default_timeout(12000)
                page.on('pageerror', lambda error: errors.append(str(error)))
                reads = len(fixture.history_calls); changes = fixture.desk.store.db.total_changes
                await page.goto(fixture.url)
                await page.wait_for_function('id=>selected===id&&!opening', arg=fixture.identifier)
                assert not [c for c in fixture.history_calls[reads:] if c['method'] == 'thread/read']
                assert fixture.desk.store.db.total_changes == changes
                await page.locator('#draft-evidence > summary').click()
                await page.locator('#draft-evidence-list button').click(); await ready(page)
                assert await page.locator('#history-reader-saved-evidence-quote').text_content() == QUOTE
                assert fixture.history_calls[reads:] == [{'method': 'thread/read', 'params': {'threadId': SOURCE, 'includeTurns': True}}]
                await page.locator('#history-reader-back').click()
                assert fixture.prepared() == saved
                # The same saved evidence remains reachable after an unrelated ordinary queue poll.
                entry, other = saved['queue']['entries']
                edit_followup(fixture.desk.store, fixture.identifier, entry['id'], 'Follow the original\n\n'+format_evidence_block(blocks[0]['reference']), 'plan', entry['revision'])
                if not await page.locator('#followups').evaluate('n=>n.open'): await page.locator('#followups > summary').click()
                control = page.locator(f'.followup-entry[data-followup="{entry["id"]}"] .followup-evidence-references button')
                await control.wait_for(); await control.press('Enter'); await ready(page)
                edit_followup(fixture.desk.store, fixture.identifier, other['id'], 'Other tab updated the later instruction', 'plan', other['revision'])
                expected = fixture.prepared(); reads = len(fixture.history_calls); changes = fixture.desk.store.db.total_changes
                await page.wait_for_function('id=>document.querySelector(`.followup-entry[data-followup="${id}"]`).textContent.includes("Other tab updated")', arg=other['id'])
                await page.locator('#history-reader-back').click(); await frames(page)
                assert await control.evaluate('n=>n===document.activeElement')
                assert fixture.prepared() == expected and len(fixture.history_calls) == reads and fixture.desk.store.db.total_changes == changes
                # Completed native admission with a lost local reply must not consume newer typing or run twice.
                fixture.hold_reply = fixture.drop_reply = True; fixture.reply_release.clear()
                await page.locator('#send').click()
                assert await asyncio.to_thread(fixture.reply_entered.wait, 10)
                await page.locator('#prompt').fill(NEWER)
                for _ in range(80):
                    if fixture.prepared()['draft']['text'] == NEWER: break
                    await asyncio.sleep(.025)
                assert fixture.prepared()['draft']['text'] == NEWER
                fixture.reply_release.set()
                await page.wait_for_function('id=>!submitting.has(id)', arg=fixture.identifier)
                assert len(fixture.requests) == 1 and fixture.requests[0]['params']['input'][0]['text'] == saved['draft']['text']
                await page.reload(); await page.wait_for_function('id=>selected===id&&!opening', arg=fixture.identifier)
                assert await page.locator('#prompt').input_value() == NEWER and len(fixture.requests) == 1
                assert fixture.prepared()['queue'] == expected['queue'] and fixture.prepared()['other'] == original_preparation['other']
                assert not errors and await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                await page.screenshot(path=str(evidence/'core-workflow.png'))
                result = {'result': 'PASS', 'journey': 'Index remembered original, read its own instruction/response/command, retain preparation, cold source return, recover one completed Run without replay'}
            except Exception as error:
                result = {'result': 'FAIL', 'error': str(error)}
                await page.screenshot(path=str(evidence/'failed.png'))
                raise
            finally:
                fixture.reply_release.set(); await context.close(); await browser.close(); fixture.stop()
                (evidence/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result['journey'])


if __name__ == '__main__':
    asyncio.run(run())
