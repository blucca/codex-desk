#!/usr/bin/env python3
"""Connected maintained sample: Changed/first-new, linked original and local Plan return."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from build_browser_preview import CHILD, CHILD_TURN, CHILD_ITEM, CHILD_QUOTE
from check_browser_preview import static_server
from check_browser_preview_links import open_app
from check_browser_preview_session_reading import A, B, C, PRIOR, COMMAND, DRAFT, B_DRAFT, frames

LINK = 'sample-checkout-collaboration'


async def check(p, site, evidence, chromium, embedded, width, ordinary=False):
    mode = ('ordinary' if ordinary else 'rich') + ('-iframe' if embedded else '-direct')
    prefix = f'{width}-{mode}'
    report = {'passed': False, 'width': width, 'actual_iframe': embedded,
              'ordinary_distribution': ordinary, 'checks': []}
    errors, external = [], []
    with static_server(site) as (url, received, escaped):
        browser = await p.chromium.launch(executable_path=chromium, headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(viewport={'width': width, 'height': 900 if width == 1250 else 844},
            permissions=['clipboard-read', 'clipboard-write'])
        page = await context.new_page()
        page.set_default_timeout(15000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        async def isolate(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                await route.abort()
            else:
                await route.continue_()
        await context.route('**/*', isolate)
        app = None
        async def saved():
            return await app.evaluate('DeskBrowserPreview.snapshot()')
        async def navigate(session):
            button = app.locator(f'.session-row[data-session="{session}"] .session')
            await button.evaluate('n=>n.focus({preventScroll:true})')
            await button.press('Enter')
            await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending', arg=session)
            await frames(app)
        async def review():
            return await app.evaluate('DeskNewActivityView.state()')
        async def parent():
            return await app.evaluate('''id=>{const n=nodes.get(id),group=n.closest('details.activity-collaboration');return {
                selected,thread:nativeThreadId,generation,window:scrollY,windowLeft:scrollX,open:group.open,
                item:n.dataset.itemId,turn:n.dataset.turnId,top:n.getBoundingClientRect().top,
                review:DeskNewActivityView.state(),overview:!$('changed-work-back').hidden};}''', LINK)
        async def editor():
            return await app.evaluate('''()=>({window:scrollY,text:$('prompt').value,mode:$('turn-mode').value,
                start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,
                scroll:$('prompt').scrollTop})''')
        async def ready():
            await app.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
            await frames(app)
        def target():
            return app.locator(f'.history-reader-item[data-turn-id="{CHILD_TURN}"][data-item-id="{CHILD_ITEM}"]')
        async def checkpoint(name, data=None):
            assert not errors and not external and not escaped, (errors, external, escaped)
            snapshot = await saved()
            assert {s['id'] for s in snapshot['sessions']} == {A, B, C}
            assert 'desk-' + CHILD not in snapshot['drafts'] and 'desk-' + CHILD not in snapshot['followups']
            assert snapshot['followups'] == original['followups']
            assert snapshot['drafts'][B] == original['drafts'][B]
            assert await app.evaluate('selected') == A
            assert await app.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
            report['checks'].append(name)
            if data is not None:
                report[name] = data
            await page.screenshot(path=str(evidence / f'{prefix}-{name}.png'))
            print(json.dumps({'passed': name, 'width': width, 'mode': mode}), flush=True)
        try:
            app = await open_app(page, context, url, embedded)
            await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate('DeskPreviewThreads.length') == 4
            assert await app.evaluate('!!DeskBrowserPreview.fixture') == (not ordinary)
            assert await app.evaluate("document.documentElement.dataset.previewEmbedded==='true'") == embedded
            await app.evaluate('''async data=>{
                for(const name of ['checkout','docs','mobile'])await api('/api/import',{thread:'sample-'+name+'-thread'});
                for(const [id,text] of [[data.a,data.draft],[data.b,data.bDraft]]){
                    await api('/api/draft',{session:id,text,mode:'plan',revision:0});
                    await api('/api/followups',{session:id,text:id+' first retained instruction',mode:'native'});
                    await api('/api/followups',{session:id,text:id+' second retained Plan instruction',mode:'plan'});}
                await refresh();}''', {'a': A, 'b': B, 'draft': DRAFT, 'bDraft': B_DRAFT})
            original = await saved()
            await navigate(A)
            baseline = 0 if ordinary else 3
            assert (await review())['reviewed_seq'] == baseline
            if not ordinary:
                await app.locator(f'#activity [data-item-id="{COMMAND}"] summary').click()
                await app.evaluate('''id=>{const n=nodes.get(id);n.querySelector('pre').scrollTop=283;
                    window.scrollTo({top:scrollY+n.getBoundingClientRect().top-145,behavior:'instant'});}''', COMMAND)
                await frames(app)
            await navigate(B)
            sequence = baseline
            if not ordinary:
                sequence = await app.evaluate('DeskBrowserPreview.fixture.updateLinkedOriginal()')
                await app.evaluate('DeskBrowserPreview.fixture.appendIgnored()')
            await app.evaluate('refresh()')
            await app.locator('#session-filter').fill('Sample')
            await app.locator('#show-changed-work').click()
            await app.wait_for_function("$('changed-work').open")
            await app.locator('#changed-work-mode').select_option('changed')
            assert await app.locator('#changed-work-list .changed-work-row').count() == (0 if ordinary else 1)
            if ordinary:
                await app.locator('#changed-work-mode').select_option('all')
            project = await app.locator('#changed-work-project').evaluate("n=>Array.from(n.options).find(o=>o.textContent.includes('/sample/projects/checkout')&&!o.textContent.includes('checkout-child')).value")
            await app.locator('#changed-work-project').select_option(project)
            scope = await app.evaluate("({project:$('changed-work-project').value,mode:$('changed-work-mode').value,title:$('session-filter').value,archived:$('show-archived').checked,previous:$('changed-work-previous').disabled,next:$('changed-work-next').disabled})")
            await app.evaluate('id=>globalThis.sampleLinkedOverviewButton=document.querySelector(`#changed-work-list [data-session="${id}"] button`)', A)
            await app.locator(f'#changed-work-list [data-session="{A}"] button').click()
            await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending', arg=A)
            await frames(app)
            assert (await review())['reviewed_seq'] == baseline
            if not ordinary:
                assert (await review())['first']['item_id'] == LINK
                await app.locator('#native-activity-first').evaluate('n=>n.focus({preventScroll:true})')
                await app.locator('#native-activity-first').press('Enter')
                await frames(app)
                assert await app.evaluate('id=>document.activeElement===nodes.get(id)', LINK)
                assert (await review())['reviewed_seq'] == baseline
            else:
                assert (await review())['first'] is None and (await review())['status'] == 'up_to_date'
            await checkpoint('real-parent-overview-first-new-keeps-frozen-baseline-and-existing-B-plan', {'scope': scope, 'sequence': sequence})
            group = app.locator('#activity > details.activity-collaboration')
            if not await group.evaluate('n=>n.open'):
                await group.locator('summary').evaluate('n=>n.focus({preventScroll:true})')
                await group.locator('summary').press('Enter')
            button = app.locator('.linked-agent-original').filter(has_text=CHILD)
            await app.wait_for_function("document.querySelector('.linked-agent-original')&&!document.querySelector('.linked-agent-original').disabled")
            await button.evaluate("n=>{n.focus({preventScroll:true});window.scrollTo({top:scrollY+n.closest('[data-item-id]').getBoundingClientRect().top-180,behavior:'instant'})}")
            await frames(app)
            retained = await parent()
            before = await saved()
            boundary = await app.evaluate('DeskBrowserPreview.requests.length')
            await button.press('Enter')
            await ready()
            assert await app.locator('#history-reader-back').text_content() == 'Return to parent activity'
            assert await saved() == before
            home = await app.evaluate("DeskNewActivityView.state().owner.native_home")
            calls = await app.evaluate('start=>DeskBrowserPreview.requests.slice(start)', boundary)
            assert [r['path'] for r in calls if urlsplit(r['path']).path == '/api/native/evidence-source'] == [f'/api/native/evidence-source?home={home}&thread={CHILD}']
            assert all(r['method'] == 'GET' for r in calls)
            await checkpoint('one-exact-existing-evidence-source-GET-distinct-child-no-admission')
            await app.locator('#history-reader-find-query').fill(CHILD_QUOTE)
            await app.locator('#history-reader-find-query').press('Enter')
            await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')")
            await page.keyboard.press('F3')
            await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
            await frames(app)
            await target().get_by_role('button', name='Copy full item text', exact=True).click()
            await target().locator('.history-reader-copy-status').filter(has_text='copied').wait_for()
            copied = await app.evaluate('navigator.clipboard.readText()')
            source_text = await app.evaluate("id=>DeskPreviewThreads.find(t=>t.id===id).turns[0].items.find(i=>i.type==='agentMessage').text", CHILD)
            assert copied == 'Codex\n' + source_text
            mark = target().locator('mark')
            await mark.evaluate("n=>n.scrollIntoView({block:'center',inline:'nearest'})")
            await frames(app)
            rects = await mark.evaluate('''n=>{const r=document.createRange();r.selectNodeContents(n);
                return [...r.getClientRects()].filter(x=>x.width>0&&x.height>0).map(x=>({left:x.left,right:x.right,top:x.top,bottom:x.bottom}));}''')
            assert rects
            first, last = rects[0], rects[-1]
            start = (first['left'] + .5, (first['top'] + first['bottom']) / 2)
            end = (last['right'] - .5, (last['top'] + last['bottom']) / 2)
            height = 900 if width == 1250 else 844
            assert all(0 < x < width and 0 < y < height for x, y in (start, end)), (start, end)
            if width == 390:
                start, end = end, start
            if embedded:
                box = await page.locator('iframe').bounding_box()
                start = (start[0] + box['x'], start[1] + box['y'])
                end = (end[0] + box['x'], end[1] + box['y'])
            await page.mouse.move(*start)
            await page.mouse.down()
            await page.mouse.move(*end, steps=12)
            await page.mouse.up()
            assert await app.evaluate('getSelection().toString()') == CHILD_QUOTE
            report['pointer_selection'] = {'direction': 'backward' if width == 390 else 'forward', 'rects': len(rects), 'quote': CHILD_QUOTE}
            source_view = await target().evaluate("n=>({start:n.dataset.windowStart,scroll:n.querySelector('pre').scrollTop,selection:getSelection().toString()})")
            assert source_view['selection'] == CHILD_QUOTE
            await target().locator('.history-reader-review-evidence').click()
            await app.wait_for_function("$('evidence-preparation').open&&!DeskEvidencePreparation.state().pending")
            reviewed = await app.evaluate('DeskEvidencePreparation.state()')
            reference = reviewed['reference']
            assert reviewed['destination']['session'] == A and reviewed['destination']['mode'] == 'plan'
            assert reference['thread_id'] == CHILD and reference['turn_id'] == CHILD_TURN and reference['item_id'] == CHILD_ITEM
            assert reference['native_home'] == home and reference['quote'] == CHILD_QUOTE
            assert reference['quote_start'] == copied.rfind(CHILD_QUOTE)
            await checkpoint('Unicode-second-Find-full-Copy-exact-child-quote-reviewed-for-existing-B', {'reference': reference, 'full_copy_characters': len(copied)})
            boundary = await app.evaluate('DeskBrowserPreview.requests.length')
            await app.locator('#evidence-preparation-append').click()
            await app.wait_for_function("!$('evidence-preparation').open")
            await frames(app)
            after = await saved()
            assert after['drafts'][A]['revision'] == before['drafts'][A]['revision'] + 1
            assert after['drafts'][A]['mode'] == 'plan' and after['drafts'][A]['text'].startswith(before['drafts'][A]['text'])
            parsed = await app.evaluate('DeskEvidencePreparation.parse($("prompt").value)')
            assert len(parsed) == 1 and parsed[0]['reference'] == reference
            calls = await app.evaluate('start=>DeskBrowserPreview.requests.slice(start)', boundary)
            assert [urlsplit(r['path']).path for r in calls if r['method'] == 'POST'] == ['/api/draft']
            assert not [r for r in calls if urlsplit(r['path']).path.startswith('/api/native/')]
            assert await target().evaluate("n=>({start:n.dataset.windowStart,scroll:n.querySelector('pre').scrollTop,selection:getSelection().toString()})") == source_view
            await checkpoint('single-local-B-draft-append-keeps-quote-window-and-both-queues')
            await app.locator('#history-reader-back').evaluate('n=>n.focus({preventScroll:true})')
            await app.locator('#history-reader-back').press('Enter')
            await app.wait_for_function("!$('history-reader').open&&!sessionReadingPending")
            await frames(app)
            assert await parent() == retained, (retained, await parent())
            await checkpoint('linked-return-restores-exact-parent-passage-and-frozen-review')
            if not await app.locator('#draft-evidence').evaluate('n=>n.open'):
                await app.locator('#draft-evidence summary').evaluate('n=>n.focus({preventScroll:true})')
                await app.locator('#draft-evidence summary').press('Enter')
            await app.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(12,24,'backward');n.scrollTop=35}")
            await frames(app)
            editor_before, parent_before, saved_before = await editor(), await parent(), await saved()
            boundary = await app.evaluate('DeskBrowserPreview.requests.length')
            await app.locator('#draft-evidence-list button').evaluate('n=>n.focus({preventScroll:true})')
            await app.locator('#draft-evidence-list button').press('Enter')
            await ready()
            assert await app.locator('#history-reader-saved-evidence-quote').text_content() == CHILD_QUOTE
            assert await target().locator('mark').text_content() == CHILD_QUOTE
            calls = await app.evaluate('start=>DeskBrowserPreview.requests.slice(start)', boundary)
            assert [r['path'] for r in calls if urlsplit(r['path']).path == '/api/native/evidence-source'] == [f'/api/native/evidence-source?home={home}&thread={CHILD}']
            assert all(r['method'] == 'GET' for r in calls)
            await app.locator('#history-reader-back').evaluate('n=>n.focus({preventScroll:true})')
            await app.locator('#history-reader-back').press('Enter')
            await app.wait_for_function("!$('history-reader').open")
            await frames(app)
            assert await editor() == editor_before and await parent() == parent_before
            assert await app.evaluate('document.activeElement.id') == 'prompt'
            assert await saved() == saved_before
            await checkpoint('actual-child-reference-return-keeps-exact-B-editor-and-parent')
            await app.locator('#changed-work-back').evaluate('n=>n.focus({preventScroll:true})')
            await app.locator('#changed-work-back').press('Enter')
            await app.wait_for_function("$('changed-work').open")
            assert await app.evaluate("({project:$('changed-work-project').value,mode:$('changed-work-mode').value,title:$('session-filter').value,archived:$('show-archived').checked,previous:$('changed-work-previous').disabled,next:$('changed-work-next').disabled})") == scope
            assert await app.evaluate('document.activeElement===sampleLinkedOverviewButton')
            assert (await review())['reviewed_seq'] == baseline
            assert await saved() == saved_before
            calls = await app.evaluate('DeskBrowserPreview.requests')
            assert not [r for r in calls if r['method'] == 'POST' and urlsplit(r['path']).path not in ('/api/import', '/api/open', '/api/draft', '/api/followups')]
            assert not [r for r in calls if r['method'] == 'POST' and (r['data'].get('thread') == CHILD or r['data'].get('session') == 'desk-' + CHILD)]
            await checkpoint('exact-overview-row-scope-page-return-no-child-store-or-queues')
            report.update(passed=True, native_admissions=0, child_task_rows=0, sample_histories=4,
                          javascript_errors=errors, external_requests=external, escaped_api_requests=escaped)
        except Exception as error:
            import traceback
            report.update(error=str(error), traceback=traceback.format_exc(), javascript_errors=errors)
            await page.screenshot(path=str(evidence / f'{prefix}-failure.png'))
            if app:
                report['body'] = await app.locator('body').inner_text()
        finally:
            await context.close()
            await browser.close()
    (evidence / f'{prefix}.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    assert report['passed'], report.get('traceback')
    return report


async def main(args):
    from playwright.async_api import async_playwright
    args.evidence.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        reports = [await check(p, args.site, args.evidence, args.chromium, args.embedded, int(width), args.ordinary)
                   for width in args.widths.split(',')]
    (args.evidence / 'summary.json').write_text(json.dumps({'result': 'PASS', 'reports': reports}, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--chromium', default=os.environ.get('DESK_CHROMIUM'))
    parser.add_argument('--embedded', action='store_true')
    parser.add_argument('--ordinary', action='store_true')
    parser.add_argument('--widths', default='1250,390')
    asyncio.run(main(parser.parse_args()))
