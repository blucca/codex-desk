#!/usr/bin/env python3
"""Maintained sample: exact tool evidence -> its task -> its response -> passage.

The three primary shipped sample histories supply addressed command evidence. A targeted
sample-data wrapper appends a no-input mobile task for the availability check;
it does not change the shipped sample's latest response or simulate task sending.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from check_browser_preview import static_server, normalized_request

OWNER = 'desk-sample-docs-thread'
DRAFT = 'Plan tomorrow’s documentation task; keep this preparation unsent.'
QUEUED = ['Check the launch command first.', 'Review configuration after the launch command.']
MISSING_TURN = 'sample-mobile-no-input-turn'
MISSING_TOOL = 'sample-mobile-no-input-evidence'
MISSING_ANSWER = 'sample-mobile-no-input-answer'
MISSING_OUTPUT = 'Mobile task without supplied input — café🙂.'
WRAPPER = '''(() => {
 let threads;
 Object.defineProperty(window,'DeskPreviewThreads',{configurable:true,get:()=>threads,set:value=>{
  threads=value;
  const mobile=threads.find(t=>t.id==='sample-mobile-thread');
  mobile.turns.push({id:'sample-mobile-no-input-turn',status:'failed',error:{message:'No user instruction was supplied in this sample task.'},items:[
   {id:'sample-mobile-no-input-evidence',type:'commandExecution',command:'printf sample-no-input',status:'completed',exitCode:0,aggregatedOutput:'Mobile task without supplied input — café🙂.'},
   {id:'sample-mobile-no-input-answer',type:'agentMessage',phase:'commentary',text:'This task supplied a response without a readable user instruction.'}
  ]});
 }});
 Object.defineProperty(navigator,'clipboard',{configurable:true,value:{async writeText(text){(window.__deskTaskCopies ||= []).push(text);}}});
})();'''


async def check(playwright, site, evidence, width, chromium, embedded, public_url=None):
    errors, console, external, failed, phases = [], [], [], [], []
    with static_server(site) as (url, received, escaped):
        url = public_url or url
        browser = await playwright.chromium.launch(executable_path=chromium,
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(viewport={'width': width, 'height': 900 if width > 390 else 844})
        await context.add_init_script(WRAPPER)
        page = await context.new_page()
        page.set_default_timeout(12000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: console.append(message.text) if message.type == 'error' else None)
        page.on('requestfailed', lambda request: failed.append({'url': request.url, 'error': request.failure}))

        async def isolated(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                await route.abort()
            else:
                await route.continue_()

        await context.route('**/*', isolated)
        app = None
        try:
            if embedded:
                host = url + 'task-context-frame-host.html'
                await context.route(host, lambda route: route.fulfill(content_type='text/html', body=(
                    '<!doctype html><html><head><title>Embedded task context</title>'
                    '<style>html,body{margin:0;height:100%;overflow:hidden}iframe{display:block;width:100%;height:100%;border:0}</style>'
                    '</head><body><iframe title="Codex Desk sample" src="' + url + '"></iframe></body></html>')))
                await page.goto(host)
                app = await (await page.locator('iframe').element_handle()).content_frame()
            else:
                await page.goto(url)
                app = page.main_frame
            await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate("document.documentElement.dataset.previewEmbedded==='true'") == embedded
            threads = await app.evaluate('DeskPreviewThreads')
            assert len(threads) == 4

            async def snapshot():
                return await app.evaluate('DeskBrowserPreview.snapshot()')

            async def log():
                return [normalized_request(row) for row in await app.evaluate('DeskBrowserPreview.requests')]

            async def saved(text):
                await app.wait_for_function("v=>DeskBrowserPreview.snapshot().drafts[v.id]?.text===v.text && DeskBrowserPreview.snapshot().drafts[v.id]?.mode==='plan'", arg={'id': OWNER, 'text': text})

            async def frames():
                await app.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')

            async def checkpoint(name):
                assert not errors and not console, (errors, console)
                assert not external and not failed and not escaped, (external, failed, escaped)
                assert await app.evaluate("document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)"), name + ' sample overflow'
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), name + ' host overflow'
                assert await snapshot() == baseline, name + ' changed preparation'
                assert await app.evaluate("({selected,text:$('prompt').value,mode:$('turn-mode').value,nativeThreadId,generation,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop})") == owner, name + ' changed outer task'
                phases.append(name)
                await page.screenshot(path=str(evidence / f'{width}-{name}.png'))

            # The outer task is prepared once; all original reading stays independent.
            await app.locator('#browse').click()
            await app.locator('#native-list .native-row').filter(has_text='Sample documentation review').get_by_role('button', name='Resume with current settings', exact=True).click()
            await app.wait_for_function('id=>selected===id&&!opening', arg=OWNER)
            await app.locator('#turn-mode').select_option('plan')
            for count, text in enumerate(QUEUED, 1):
                await app.locator('#prompt').fill(text)
                await app.locator('#prepare-followup').click()
                await app.wait_for_function("count=>$('followup-count').textContent===String(count) && !$('prepare-followup').disabled", arg=count)
            await app.locator('#prompt').fill(DRAFT)
            await saved(DRAFT)
            baseline = await snapshot()
            await app.locator('#prompt').evaluate("n=>{n.focus();n.setSelectionRange(5,20,'backward')}")
            owner = await app.evaluate("({selected,text:$('prompt').value,mode:$('turn-mode').value,nativeThreadId,generation,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop})")
            await checkpoint('unsent-outer-plan-and-two-queued-instructions')
            paths = []

            async def original(thread):
                await app.locator('#browse').click()
                await app.locator('#native-list .native-row').filter(has_text=thread['name']).locator('.native-read').click()
                await app.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
                assert await app.evaluate('getComputedStyle(document.documentElement).overflowAnchor') == 'none'
                assert thread['id'] in await app.locator('#history-reader-binding').inner_text()

            async def reveal(turn, item):
                target = app.locator(f'.history-reader-item[data-turn-id="{turn["id"]}"][data-item-id="{item["id"]}"]')
                if not await target.evaluate('n=>n.open'):
                    await target.locator('summary').click()
                return target

            async def selected_passage(turn, tool):
                await app.locator('#history-reader-find-query').fill(tool['aggregatedOutput'])
                await app.locator('#history-reader-find-query').press('Enter')
                await app.wait_for_function("!$('history-reader-find-submit').disabled && $('history-reader-find-status').textContent.startsWith('Match ')")
                target = await reveal(turn, tool)
                assert await target.locator('mark').text_content() == tool['aggregatedOutput']
                await target.locator('.history-reader-task-open').scroll_into_view_if_needed()
                await target.locator('.history-reader-task-open').focus()
                await frames()
                await target.locator('pre').evaluate("""(n,quote)=>{
                 const walker=document.createTreeWalker(n,NodeFilter.SHOW_TEXT);let node;
                 while(node=walker.nextNode()){const at=node.textContent.indexOf(quote);if(at<0)continue;
                  getSelection().setBaseAndExtent(node,at+quote.length,node,at);return;}
                 throw Error('Exact sample passage missing');
                }""", tool['aggregatedOutput'])
                return target

            async def passage_view():
                return await app.evaluate("""()=>{
                 const body=$('history-reader-body'),dialog=$('history-reader'),selection=getSelection();
                 const target=document.activeElement?.closest('.history-reader-item') || document.querySelector('.history-reader-target');
                 const pre=target?.querySelector('pre');
                 const offset=(node,at)=>{if(!pre || !node || !pre.contains(node))return null;
                  const range=document.createRange();range.selectNodeContents(pre);range.setEnd(node,at);return range.toString().length;};
                 return {query:$('history-reader-find-query').value,find:$('history-reader-find-status').textContent,
                  turn:target?.dataset.turnId,item:target?.dataset.itemId,open:target?.open,
                  text:selection?.toString(),anchor:offset(selection?.anchorNode,selection?.anchorOffset),focus:offset(selection?.focusNode,selection?.focusOffset),
                  body:body.scrollTop,dialog:dialog.scrollTop,pre:pre?.scrollTop,
                  window:scrollY};
                }""")

            for thread in threads:
                turn = thread['turns'][0]
                tool = next(item for item in turn['items'] if item['type'] == 'commandExecution')
                question = next(item for item in turn['items'] if item['type'] == 'userMessage')
                answer = next(item for item in reversed(turn['items']) if item['type'] == 'agentMessage')
                await original(thread)
                target = await selected_passage(turn, tool)
                passage = await passage_view()
                boundary = len(await log())
                await target.locator('.history-reader-task-open').press('Enter')
                await app.locator('.history-reader-task-context').wait_for()
                context_text = await app.locator('.history-reader-task-context').inner_text()
                assert turn['id'] in context_text and thread['id'] in context_text
                assert 'Native turn status: ' + turn['status'] in context_text
                assert question['id'] in context_text
                assert await app.locator('.history-reader-task-instruction').count() == 1
                await app.locator(f'[data-task-action="instruction:{question["id"]}"]').click()
                await app.locator(f'.history-reader-target[data-turn-id="{turn["id"]}"][data-item-id="{question["id"]}"]').wait_for()
                instruction = app.locator('.history-reader-target')
                expected_instruction = await app.evaluate('(item)=>DeskHistoryReader.textForItem(item)', question)
                assert await instruction.locator('pre').text_content() == expected_instruction
                await instruction.locator('.history-reader-copy-text').click()
                await app.wait_for_function('text=>window.__deskTaskCopies?.at(-1)===text', arg=expected_instruction)
                await app.locator('#history-reader-task-return').click()
                await app.locator('.history-reader-task-context').wait_for()
                await app.locator('[data-task-action="response"]').click()
                await app.locator(f'.history-reader-target[data-turn-id="{turn["id"]}"][data-item-id="{answer["id"]}"]').wait_for()
                expected_response = await app.evaluate('(item)=>DeskHistoryReader.textForItem(item)', answer)
                if answer.get('id') == 'sample-child-answer':
                    # The long child uses the shipped bounded source window; Copy
                    # below still compares its complete original response exactly.
                    window = await app.locator('.history-reader-target').evaluate('''n=>({start:Number(n.dataset.windowStart),
                        range:n.querySelector('.history-reader-text-coverage').textContent,text:n.querySelector('pre').textContent})''')
                    import re
                    match = re.fullmatch(r'Text characters (\d+)–(\d+) of (\d+)\.', window['range'])
                    assert match, window
                    start, end, total = map(int, match.groups())
                    assert start == window['start'] + 1 and 0 < end - window['start'] <= 24000
                    assert total == await app.evaluate('text=>text.length', expected_response)
                    assert window['text'] == await app.evaluate('(data)=>data.text.slice(data.start,data.end)',
                        {'text': expected_response, 'start': window['start'], 'end': end})
                else:
                    assert await app.locator('.history-reader-target pre').text_content() == expected_response
                assert 'Native status at selection: ' + turn['status'] in await app.locator('#history-reader-task-status').inner_text()
                assert 'Phase: ' + (answer.get('phase') or 'unreported') in await app.locator('#history-reader-task-status').inner_text()
                await app.locator('.history-reader-target .history-reader-copy-text').click()
                await app.wait_for_function('text=>window.__deskTaskCopies?.at(-1)===text', arg=expected_response)
                await app.locator('#history-reader-task-return').click()
                await app.locator('#history-reader-task-passage').click()
                await frames()
                restored = await passage_view()
                assert restored == passage, (passage, restored)
                assert not any(row['path'].startswith('/api/native') or row['method']=='POST' for row in (await log())[boundary:]), 'Local task/instruction/response navigation made a source request or write'
                await checkpoint(thread['id'] + '-own-instruction-response-exact-passage-return')
                paths.append({'thread': thread['id'], 'turn': turn['id'], 'tool': tool['id'], 'instruction': question['id'],
                    'response': answer['id'], 'quote': tool['aggregatedOutput'], 'exact_passage_restored': True,
                    'task_navigation_api_requests': 0})
                await app.locator('#history-reader-back').click()
                await app.locator('#history-close').click()
                assert await snapshot() == baseline

            mobile = next(thread for thread in threads if thread['id'] == 'sample-mobile-thread')
            missing = next(turn for turn in mobile['turns'] if turn['id'] == MISSING_TURN)
            tool = next(item for item in missing['items'] if item['id'] == MISSING_TOOL)
            await original(mobile)
            target = await selected_passage(missing, tool)
            passage = await passage_view()
            boundary = len(await log())
            await target.locator('.history-reader-task-open').press('Enter')
            await app.locator('.history-reader-task-context').wait_for()
            context_text = await app.locator('.history-reader-task-context').inner_text()
            assert MISSING_TURN in context_text and 'Native turn status: failed' in context_text
            assert 'No user instruction was supplied for this task.' in context_text
            assert await app.locator('.history-reader-task-instruction').count() == 0
            assert 'Review the mobile decision' not in context_text
            assert await app.locator('[data-task-action="next"]').is_disabled()
            await app.locator('[data-task-action="response"]').click()
            await app.locator(f'.history-reader-target[data-turn-id="{MISSING_TURN}"][data-item-id="{MISSING_ANSWER}"]').wait_for()
            assert 'Phase: commentary' in await app.locator('#history-reader-task-status').inner_text()
            assert 'Native status at selection: failed' in await app.locator('#history-reader-task-status').inner_text()
            await app.locator('#history-reader-task-return').click()
            await app.locator('[data-task-action="previous"]').click()
            assert 'sample-mobile-turn' in await app.locator('.history-reader-task-context').inner_text()
            assert 'sample-mobile-question' in await app.locator('.history-reader-task-context').inner_text()
            assert await app.locator('[data-task-action="previous"]').is_disabled()
            await app.locator('[data-task-action="next"]').click()
            assert 'No user instruction was supplied for this task.' in await app.locator('.history-reader-task-context').inner_text()
            await app.locator('#history-reader-task-passage').click()
            await frames()
            assert await passage_view() == passage
            assert not any(row['path'].startswith('/api/native') or row['method']=='POST' for row in (await log())[boundary:])
            await app.locator('#history-reader-back').click()
            await app.locator('#history-close').click()
            assert await app.evaluate('getComputedStyle(document.documentElement).overflowAnchor') == 'auto'
            await checkpoint('missing-input-own-response-supplied-order-no-neighbor-substitution')
            requests = await log()
            assert not any(row['method'] == 'POST' and row['path'] in {'/api/turn', '/api/followups/send', '/api/steer', '/api/stop'} for row in requests)
            receipt = {'passed': True, 'viewport': width, 'embedded': embedded, 'actual_iframe': embedded,
                'phases': phases, 'source': str(site), 'public_url': public_url, 'paths': paths,
                'targeted_sample_data_extension': MISSING_TURN, 'missing_instruction_not_borrowed': True,
                'same_turn_response': True, 'reader_root_anchor_policy': 'scoped-none-then-auto', 'local_task_navigation_requests': 0, 'outer_plan_and_queues_unchanged': True,
                'simulated_api_requests': requests, 'static_http_requests': received, 'escaped_api_requests': escaped,
                'external_requests': external, 'native_model_calls': 0, 'javascript_errors': errors,
                'console_errors': console, 'failed_requests': failed, 'horizontal_overflow': False}
            (evidence / f'receipt-{width}.json').write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
            print(json.dumps({'passed': True, 'embedded': embedded, 'viewport': width, 'phases': phases}), flush=True)
            return receipt
        except Exception:
            await page.screenshot(path=str(evidence / f'failure-{width}.png'))
            diagnostic = {'phases': phases, 'errors': errors, 'console': console, 'external': external,
                'failed': failed, 'escaped_api': escaped}
            if app:
                diagnostic.update(snapshot=await app.evaluate('DeskBrowserPreview.snapshot()'),
                    requests=await app.evaluate('DeskBrowserPreview.requests'), body=await app.locator('body').inner_text())
            (evidence / f'failure-{width}.json').write_text(json.dumps(diagnostic, indent=2, ensure_ascii=False) + '\n')
            raise
        finally:
            await context.close()
            await browser.close()


async def main(args):
    from playwright.async_api import async_playwright
    site, evidence = args.site.resolve(), args.evidence.resolve()
    assert (site / 'index.html').is_file(), f'Build the sample first: {site}'
    evidence.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        results = [await check(playwright, site, evidence, int(width), args.chromium, args.embedded, args.url)
                   for width in args.widths.split(',')]
    (evidence / 'acceptance.json').write_text(json.dumps({'passed': True, 'embedded': args.embedded, 'viewports': results}, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--embedded', action='store_true', help='Check an embedded build in a real iframe')
    parser.add_argument('--url', help='Verify at an already-deployed sample URL')
    parser.add_argument('--widths', default='1250,390')
    parser.add_argument('--chromium', default=os.environ.get('DESK_CHROMIUM'))
    asyncio.run(main(parser.parse_args()))
