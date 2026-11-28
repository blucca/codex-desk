#!/usr/bin/env python3
"""WebKit genuine-event clipboard regression: keyboard Copy → physical native paste."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

from codex_desk import server as product
from codex_desk.evidence_reference import parse_evidence_blocks, format_evidence_block
from playwright.async_api import async_playwright
from native_workbench_fixture import WorkbenchFixture, QUOTE, SOURCE, ITEM
from check_native_evidence_preparation import backward_quote, ready


async def run():
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']); evidence.mkdir(parents=True, exist_ok=True)
    fixture = WorkbenchFixture(); fixture.start()
    async with async_playwright() as p:
        browser = await p.webkit.launch(headless=True)
        context = await browser.new_context(viewport={'width': 390, 'height': 844})
        page = await context.new_page(); page.set_default_timeout(12000)
        result = {'result': 'RUNNING'}
        with patch.object(product, '_NativeReader', fixture.reader_type):
            try:
                await page.goto(fixture.url)
                await page.locator(f'.session-row[data-session="{fixture.identifier}"] .session').click()
                await page.wait_for_function('id=>selected===id&&!opening', arg=fixture.identifier)
                await page.locator('#browse').click()
                await page.locator('#history-id').fill(SOURCE); await page.locator('#history-id-read').click()
                await ready(page)
                await page.locator('#history-reader-find-query').fill(QUOTE)
                await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')")
                target = page.locator(f'.history-reader-item[data-item-id="{ITEM}"]')
                await backward_quote(page, target)
                copy = target.locator('.history-reader-copy-excerpt')
                before = fixture.prepared(); changes = fixture.desk.store.db.total_changes
                for _ in range(12):
                    await page.keyboard.press('Tab')
                    if await copy.evaluate('n=>n===document.activeElement'): break
                assert await copy.evaluate('n=>n===document.activeElement')
                await page.keyboard.press('Enter')
                await page.wait_for_function("document.querySelector('.history-reader-copy-status').textContent==='Excerpt with source copied.'")
                paste_url = f'http://127.0.0.1:{fixture.server.server_port}/native-paste'
                await context.route(paste_url, lambda route: route.fulfill(content_type='text/html', body='<textarea id="paste"></textarea>'))
                paste = await context.new_page(); await paste.goto(paste_url)
                await paste.locator('#paste').focus(); await paste.keyboard.press('Control+V')
                actual = await paste.locator('#paste').input_value()
                block, = parse_evidence_blocks(actual)
                assert block['reference']['quote'] == QUOTE and block['reference']['thread_id'] == SOURCE
                assert actual == format_evidence_block(block['reference'])
                assert fixture.prepared() == before and fixture.desk.store.db.total_changes == changes and fixture.requests == []
                result = {'result': 'PASS', 'journey': 'Genuine WebKit keyboard Copy survives namespace fetch and pastes exact canonical source'}
            except Exception as error:
                result = {'result': 'FAIL', 'error': str(error)}
                await page.screenshot(path=str(evidence/'failed.png'))
                raise
            finally:
                await context.close(); await browser.close(); fixture.stop()
                (evidence/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result['journey'])


if __name__ == '__main__':
    asyncio.run(run())
