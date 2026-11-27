"""Real native dialog close/Escape and unsaved editor return at 1250/390."""
import asyncio
import json
import os
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

SOURCE = Path(os.environ.get('DESK_SOURCE', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(SOURCE / 'tests'))
if os.environ.get('DESK_USE_INSTALLED')!='1':sys.path.insert(0, str(SOURCE))
import codex_desk
if os.environ.get('DESK_USE_INSTALLED')=='1':assert not Path(codex_desk.__file__).resolve().is_relative_to(SOURCE)
import browser_read_prepared_continuity as continuity
completion = continuity.completion


async def frames(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def view(node):
    return await node.evaluate('n=>({text:n.value,range:[n.selectionStart,n.selectionEnd,n.selectionDirection],scroll:n.scrollTop})')


async def refine(page, desk, source, width, evidence):
    original = await continuity.refine(page, desk, source, width, evidence)
    current = await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
    saved = {id: (completion.load_draft(desk.store, id), completion.followup_snapshot(desk.store, id)) for id in ('today', 'yesterday')}
    await page.evaluate("""()=>{
        window.preparedCloses=[];window.preparedCancels=[];
        const snapshot=()=>({open:$('preparation').open,draftScroll:$('preparation-text').scrollTop,
            queueScroll:document.querySelector('#preparation-followups textarea')?.scrollTop??null});
        $('preparation').addEventListener('close',()=>preparedCloses.push(snapshot()));
        $('preparation').addEventListener('cancel',()=>preparedCancels.push(snapshot()));
    }""")
    results = []

    async def close_return(kind, node, desired, mode_node=None):
        before = await view(node)
        assert before['scroll'] > 0, before
        before_mode = await mode_node.input_value() if mode_node else None
        previous = await page.evaluate('preparedCloses.length')
        if kind == 'Escape':
            await node.focus()
            await page.keyboard.press('Escape')
        else:
            await page.locator('#preparation-close').click()
        await page.wait_for_function('count=>!$("preparation").open && preparedCloses.length>count', arg=previous)
        await frames(page)
        closed = await page.evaluate('preparedCloses.at(-1)')
        # Deliberately let the real queued close event and hidden geometry settle.
        await page.locator('#show-preparation').evaluate('n=>n.click()')
        await page.wait_for_function('$("preparation").open && $("preparation-list").getAttribute("aria-busy")==="false"')
        await frames(page)
        after = await view(node)
        after_mode = await mode_node.input_value() if mode_node else None
        result = {'kind': kind, 'editor': desired, 'passed': before == after and before_mode == after_mode,
                  'before': {k:v for k,v in before.items() if k != 'text'},
                  'closed_event': closed, 'after': {k:v for k,v in after.items() if k != 'text'},
                  'exact_unsaved_text': before['text'] == after['text'], 'exact_mode': before_mode == after_mode}
        results.append(result)
        (evidence / f'{width}-close-progress.json').write_text(json.dumps(results, indent=2) + '\n')
        screenshot = evidence / f'{width}-{desired}-{kind}-return.png'
        await page.screenshot(path=str(screenshot)); screenshot.chmod(0o600)

    await page.locator('#show-preparation').evaluate('n=>n.click()')
    await page.wait_for_function('$("preparation-list").getAttribute("aria-busy")==="false"')
    draft = page.locator('#preparation-text')
    await draft.fill('Unsent prepared close acceptance.\n' * 160)
    await draft.evaluate("n=>{n.focus();n.setSelectionRange(410,445,'backward');n.scrollTop=280}")
    await frames(page)
    await close_return('Close', draft, 'draft')
    await draft.fill('Unsent prepared Escape acceptance.\n' * 180)
    await draft.evaluate("n=>{n.focus();n.setSelectionRange(530,580,'forward');n.scrollTop=355}")
    await frames(page)
    await close_return('Escape', draft, 'draft')

    await page.get_by_role('button', name='Review preparation in Today', exact=True).click()
    entry = completion.followup_snapshot(desk.store, 'today')['entries'][0]
    box = page.locator(f'.preparation-followup[data-followup="{entry["id"]}"]')
    await box.locator('[data-control="queue-edit"]').click()
    queue = box.locator('textarea')
    mode = box.locator('select')
    await queue.fill('Unsent exact local queued correction.\n' * 150)
    await mode.select_option('plan')
    await queue.evaluate("n=>{n.focus();n.setSelectionRange(210,255,'backward');n.scrollTop=185}")
    await frames(page)
    await close_return('Close', queue, 'queue', mode)
    await queue.fill('Unsent exact local queued Escape correction.\n' * 160)
    await queue.evaluate("n=>{n.focus();n.setSelectionRange(310,360,'forward');n.scrollTop=255}")
    await frames(page)
    await close_return('Escape', queue, 'queue', mode)
    assert {id: (completion.load_draft(desk.store, id), completion.followup_snapshot(desk.store, id)) for id in ('today', 'yesterday')} == saved
    assert await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})") == current
    layout = await page.evaluate('({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,preparedWidth:$("preparation").clientWidth,preparedScrollWidth:$("preparation").scrollWidth,headings:[...document.querySelectorAll(".preparation-group h3")].map(n=>({text:n.textContent,right:n.getBoundingClientRect().right,width:n.getBoundingClientRect().width}))})')
    assert layout['documentWidth']<=layout['viewport']
    assert layout['preparedScrollWidth']<=layout['preparedWidth']+1
    result = {'existing_continuity': original, 'closed_events': await page.evaluate('preparedCloses'),
              'cancel_events': await page.evaluate('preparedCancels'), 'close_acceptance': results, 'long_project_heading_layout': layout,
              'implicit_saves': 0, 'selected_plan_and_two_queues_unchanged': True}
    (evidence / f'{width}-close.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'width':width, 'close_cases':results}), flush=True)
    return result


async def main():
    root = Path(os.environ['DESK_TEST_TEMP']); root.mkdir(parents=True, exist_ok=True)
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']); evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    results=[]
    with patch('codex_desk.server.Runtime', side_effect=AssertionError('Native runtime forbidden')):
        async with completion.async_playwright() as p:
            browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                for width in (1250,390):
                    try:
                        results.append(await completion.check(width,browser,root,evidence,refine=refine))
                    except Exception as e:
                        results.append({'width':width,'error':str(e),'traceback':traceback.format_exc()})
                        print(traceback.format_exc(),flush=True)
            finally:
                await browser.close()
    passed=all('error' not in r and all(c['passed'] for c in r['refinement']['close_acceptance']) for r in results)
    summary={'result':'PASS' if passed else 'FAIL','widths':[1250,390], 'results':results}
    (evidence/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({'result':summary['result'],'close_cases':8,'widths':[1250,390]}),flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
