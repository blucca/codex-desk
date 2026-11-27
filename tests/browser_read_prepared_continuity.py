"""Exact original selection refresh and session-bound Prepared editor return."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import browser_bound_recall_completion as completion


async def refine(page, desk, source, width, evidence):
    checks = []
    selected = await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
    preparation = (completion.load_draft(desk.store, 'today'), completion.followup_snapshot(desk.store, 'today'))
    await page.locator('.recall-result .recall-read').click()
    await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")

    async def select_text(identifier, phrase, backward=False):
        await page.locator(f'.history-reader-item[data-item-id="{identifier}"]').evaluate('n=>n.open=true')
        await page.locator(f'.history-reader-item[data-item-id="{identifier}"] .history-reader-text').evaluate("""(n,args)=>{
            const walker=document.createTreeWalker(n,NodeFilter.SHOW_TEXT);let text;
            while((text=walker.nextNode())){const at=text.data.indexOf(args.phrase);if(at<0)continue;
                const first=args.backward?at+args.phrase.length:at,last=args.backward?at:at+args.phrase.length;
                getSelection().setBaseAndExtent(text,first,text,last);return;}
            throw Error('The exact visible phrase was unavailable');
        }""", {'phrase': phrase, 'backward': backward})
        assert await page.evaluate('getSelection().toString()') == phrase

    async def refresh_original():
        await page.locator('#history-reader-refresh').evaluate('n=>n.click()')
        await page.wait_for_function("$('history-reader-status').textContent.startsWith('Original refreshed') && !$('history-reader-refresh').disabled")

    phrase = 'Skip retry reconstruction'
    await select_text('plan', phrase)
    source['turns'].append({'id': 'later-turn', 'status': 'completed', 'items': [
        {'id': 'later-answer', 'type': 'agentMessage', 'text': 'Later independent timeout investigation.'}]})
    await refresh_original()
    assert await page.evaluate('getSelection().toString()') == phrase
    checks.append('unchanged same native item selection retained while later evidence arrives')

    await select_text('plan', phrase, backward=True)
    await refresh_original()
    assert await page.evaluate('getSelection().toString()') == phrase
    assert await page.evaluate('getSelection().anchorOffset > getSelection().focusOffset')
    screenshot = evidence / f'{width}-retained-original-selection.png'
    await page.screenshot(path=str(screenshot)); screenshot.chmod(0o600)
    checks.append('backward original selection retains its direction')

    plan = next(item for item in source['turns'][0]['items'] if item['id'] == 'plan')
    plan['text'] = plan['text'].replace(phrase, 'Check retry reconstruction')
    # An identical phrase elsewhere cannot stand in for the selected source.
    source['turns'][-1]['items'][0]['text'] = phrase
    await refresh_original()
    assert await page.evaluate('getSelection().toString()') == ''
    assert 'selected original text changed' in await page.locator('#history-reader-status').inner_text()
    checks.append('changed selected text is reported without selecting another source')

    await select_text('command', 'retry budget remains three attempts')
    source['turns'][0]['items'] = [item for item in source['turns'][0]['items'] if item['id'] != 'command']
    await refresh_original()
    assert await page.evaluate('getSelection().toString()') == ''
    assert 'selected original text changed' in await page.locator('#history-reader-status').inner_text()
    checks.append('removed selected item is reported without substitution')
    await page.locator('#history-reader-back').click()
    await page.locator('#recall-close').click()

    long_text = 'Retained checkout evidence and next timeout check.\n' * 150
    completion.save_draft(desk.store, 'yesterday', long_text, 'plan', 0)
    await page.locator('#show-preparation').evaluate('n=>n.click()')
    await page.wait_for_function("$('preparation-list').textContent.includes('Yesterday')")
    await page.get_by_role('button', name='Review preparation in Yesterday', exact=True).click()
    await page.wait_for_function("!$('preparation-save').disabled")
    draft_text = long_text + 'Unsaved remaining timeout review.'
    await page.locator('#preparation-text').fill(draft_text)
    await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(190,240,'backward');n.scrollTop=145}")
    async def draft_view():
        return await page.locator('#preparation-text').evaluate('n=>({range:[n.selectionStart,n.selectionEnd,n.selectionDirection],scroll:n.scrollTop,text:n.value})')
    before = await draft_view()
    await page.get_by_role('button', name='Review preparation in Today', exact=True).click()
    await page.get_by_role('button', name='Review preparation in Yesterday', exact=True).click()
    assert await draft_view() == before
    checks.append('session return restores unsaved draft range direction and scroll')

    await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(310,345,'forward');n.scrollTop=195}")
    latest = await draft_view()
    await page.locator('#preparation-refresh').evaluate('n=>n.click()')
    await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
    assert await draft_view() == latest
    await page.locator('#preparation-close').click()
    await page.locator('#show-preparation').evaluate('n=>n.click()')
    await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
    assert await draft_view() == latest
    assert completion.load_draft(desk.store, 'yesterday')['text'] == long_text
    checks.append('Refresh and close/reopen retain latest editing position without an implicit save')
    assert await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})") == selected
    assert (completion.load_draft(desk.store, 'today'), completion.followup_snapshot(desk.store, 'today')) == preparation
    return {'checks': checks, 'prepared_return': {k: v for k, v in before.items() if k != 'text'},
            'prepared_latest': {k: v for k, v in latest.items() if k != 'text'},
            'current_plan_two_queues_unchanged': True, 'implicit_saves': 0}


async def main():
    root = Path(os.environ['DESK_TEST_TEMP']); root.mkdir(parents=True, exist_ok=True)
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']); evidence.mkdir(parents=True, exist_ok=True, mode=0o700); evidence.chmod(0o700)
    with patch('codex_desk.server.Runtime', side_effect=AssertionError('Native runtime forbidden')):
        async with completion.async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage'])
            try:
                results = [await completion.check(width, browser, root, evidence, refine=refine) for width in (1250, 390)]
            finally:
                await browser.close()
    summary = evidence / 'summary.json'
    summary.write_text(json.dumps({'result': 'PASS', 'groups': 12, 'checks': results}, indent=2) + '\n'); summary.chmod(0o600)
    print(json.dumps({'result': 'PASS', 'refinement_groups': 12, 'widths': [1250, 390]}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
