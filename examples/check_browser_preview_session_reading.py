#!/usr/bin/env python3
"""Check ordinary session return and cold metadata in the maintained sample UI.

Build with --session-reading-fixture. --embedded hosts an actual iframe. The
synthetic browser transport supplies native-shaped sources; no Desk server runs.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from check_browser_preview import static_server
from check_browser_preview_links import open_app, reload_app

A, B, C = ('desk-sample-' + name + '-thread' for name in ('checkout', 'docs', 'mobile'))
PRIOR, LIVE = 'sample-checkout-turn', 'sample-checkout-live-turn'
COMMAND, MCP = 'sample-checkout-evidence', 'sample-checkout-mcp'
DRAFT = 'Keep A preparation unsent — Plan the remaining verification.'
B_DRAFT = 'Keep B independent preparation unsent.'
C_DRAFT = 'C newest unsent draft wins the delayed A open.'
ANSWER, CHOICE = 'B unsent pending answer keeps its own request.', 'Keep existing scope'


async def frames(app):
    await app.wait_for_function('!opening && !sessionReadingPending')
    await app.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def same_reading(before, after):
    for key in ('session', 'thread', 'collaborationOpen', 'windowLeft', 'latest', 'draft', 'mode', 'readouts'):
        assert after[key] == before[key], (key, before, after)
    for key in ('command', 'mcp'):
        for field in ('turn', 'item', 'open', 'top', 'left'):
            assert after[key][field] == before[key][field], (key, field, before, after)
        assert abs(after[key]['screenTop'] - before[key]['screenTop']) <= 1, (key, before, after)
    assert abs(after['windowTop'] - before['windowTop']) <= 1, (before, after)


def metadata_only(metadata):
    stored, limits = metadata['value'], metadata['limits']
    assert set(stored) == {'version', 'checkpoints'} and stored['version'] == 1
    assert len(stored['checkpoints']) <= limits['owners']
    assert len(metadata['raw']) <= limits['characters']
    for entry in stored['checkpoints']:
        assert set(entry) == {'version', 'owner', 'saved_at', 'view'}
        assert set(entry['owner']) == {'native_home', 'session', 'thread_id'}
        view = entry['view']
        assert set(view) == {'latest', 'anchor', 'window_scroll', 'item_views', 'turn_views'}
        assert len(view['item_views']) <= limits['item_views']
        assert len(view['turn_views']) <= limits['turn_views']
        for item in view['item_views']:
            assert set(item) == {'turn_id', 'item_id', 'open', 'window_start', 'scroll_top', 'scroll_left'}
        for turn in view['turn_views']:
            assert set(turn) == {'turn_id', 'kind', 'open', 'scroll_top', 'scroll_left'}
    for text in (DRAFT, B_DRAFT, ANSWER, CHOICE, 'Sample command line 0000', 'Sample MCP line 0000', '/sample/projects/'):
        assert text not in metadata['raw'], text
    assert any(entry['owner']['session'] == A for entry in stored['checkpoints'])
    assert metadata['key'] == 'codex-desk-browser-preview-reading-checkpoints-v1'


async def check(p, site, evidence, chromium, embedded, width):
    mode = 'embedded' if embedded else 'direct'
    report = {'passed': False, 'embedded': embedded, 'actual_iframe': embedded, 'width': width, 'checks': []}
    errors, external, requests = [], [], []
    with static_server(site) as (url, received, escaped):
        browser = await p.chromium.launch(executable_path=chromium, headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(viewport={'width': width, 'height': 900 if width == 1250 else 844})
        page = await context.new_page()
        page.set_default_timeout(12000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        await context.add_init_script("window.DeskPreviewReadingOverrides=JSON.parse(sessionStorage.getItem('reading-fixture-overrides') || '{}')")

        async def isolate(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                await route.abort()
            else:
                await route.continue_()
        await context.route('**/*', isolate)
        app = None

        async def checkpoint(name, data=None):
            report['checks'].append(name)
            if data is not None:
                report[name] = data
            await page.screenshot(path=str(evidence / f'{width}-{mode}-{name}.png'))
            print(json.dumps({'passed': name, 'width': width, 'embedded': embedded}), flush=True)

        async def navigate(session, settle=True):
            button = app.locator(f'.session-row[data-session="{session}"] .session')
            await button.evaluate('node => node.focus({preventScroll:true})')
            await button.press('Enter')
            await app.wait_for_function("id => selected===id && !opening && !$('task').hidden", arg=session)
            if settle:
                await frames(app)

        async def preparation():
            return await app.evaluate('''ids => {const saved=DeskBrowserPreview.snapshot();return {
                drafts:Object.fromEntries(ids.map(id=>[id,saved.drafts[id]])),followups:saved.followups};}''', [A, B])

        async def reading():
            return await app.evaluate('''ids => {
                const read=id=>{const row=nodes.get(id),detail=row.querySelector('.activity-tool'),pre=row.querySelector('.activity-evidence');
                    return {turn:row.dataset.turnId,item:row.dataset.itemId,open:detail?.open ?? null,top:pre?.scrollTop || 0,left:pre?.scrollLeft || 0,screenTop:row.getBoundingClientRect().top};};
                const pending=interactionCards.get(ids.b)?.get('801');
                return {session:selected,thread:nativeThreadId,command:read(ids.command),mcp:read(ids.mcp),
                    collaborationOpen:collaborationGroups.get(ids.prior)?.node.open,windowTop:scrollY,windowLeft:scrollX,
                    latest:DeskSessionReading.follow(),draft:$('prompt').value,mode:$('turn-mode').value,
                    pendingB:pending?Object.fromEntries([...pending.fields].map(([key,input])=>[key,input.value])):null,
                    readouts:{steps:{turn:DeskNativeSteps.state().turn,open:$('native-steps').open,top:$('native-steps-body').scrollTop},
                        changes:{turn:DeskTurnChanges.state().turn,open:$('turn-changes').open,top:$('turn-changes-body').scrollTop}}};
            }''', {'command': COMMAND, 'mcp': MCP, 'prior': PRIOR, 'b': B})

        async def open_evidence():
            for item in (COMMAND, MCP):
                detail = app.locator(f'#activity [data-item-id="{item}"] details')
                if not await detail.evaluate('node=>node.open'):
                    await detail.locator('summary').click()
            group = app.locator(f'.activity-collaboration[data-collaboration-turn="{PRIOR}"]')
            if not await group.evaluate('node=>node.open'):
                await group.locator(':scope > summary').click()
            for control in ('#native-steps', '#turn-changes'):
                if not await app.locator(control).evaluate('node=>node.open'):
                    await app.locator(control + ' > summary').click()
            await app.evaluate('''ids => {
                $('native-steps-body').scrollTop=95;$('turn-changes-body').scrollTop=137;
                nodes.get(ids.command).querySelector('.activity-evidence').scrollTop=283;
                nodes.get(ids.mcp).querySelector('.activity-evidence').scrollTop=431;
                const node=nodes.get(ids.command);window.scrollTo({top:scrollY+node.getBoundingClientRect().top-145,behavior:'instant'});
            }''', {'command': COMMAND, 'mcp': MCP})
            await frames(app)

        async def reload_with(overrides):
            nonlocal app
            requests.extend(await app.evaluate('DeskBrowserPreview.requests'))
            await app.evaluate('value=>sessionStorage.setItem("reading-fixture-overrides",JSON.stringify(value))', overrides)
            app = await reload_app(page, embedded)

        try:
            app = await open_app(page, context, url, embedded)
            await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate("!!DeskBrowserPreview.fixture && !!globalThis.DeskSessionReading && !!globalThis.DeskReadingCheckpoint"), 'Use the future maintained app and --session-reading-fixture build'
            assert await app.evaluate("document.documentElement.dataset.previewEmbedded==='true'") == embedded
            await app.evaluate('''async data => {
                for(const name of ['checkout','docs','mobile']){const id=(await api('/api/import',{thread:'sample-'+name+'-thread'})).id;
                    await api('/api/followups?session='+encodeURIComponent(id));}
                for(const [id,text] of [[data.a,data.draft],[data.b,data.bDraft]]){
                    await api('/api/draft',{session:id,text,mode:'plan',revision:0});
                    await api('/api/followups',{session:id,text:id+' first instruction remains queued.',mode:'native'});
                    await api('/api/followups',{session:id,text:id+' second instruction remains Plan.',mode:'plan'});
                }
                await refresh();
            }''', {'a': A, 'b': B, 'draft': DRAFT, 'bDraft': B_DRAFT})
            await navigate(A)
            await open_evidence()
            before = await reading()
            assert before['command']['top'] == 283 and before['mcp']['top'] == 431
            assert not before['latest'] and before['collaborationOpen'] and before['command']['turn'] == PRIOR
            assert before['readouts'] == {'steps': {'turn': LIVE, 'open': True, 'top': 95}, 'changes': {'turn': LIVE, 'open': True, 'top': 137}}
            saved = await preparation()
            await navigate(B)
            await app.get_by_label('Sample B answer — What check should remain?').fill(ANSWER)
            await app.get_by_label('Sample B choice — Which scope?').select_option(CHOICE)
            await navigate(A)
            after = await reading()
            same_reading(before, after)
            assert after['pendingB'] == {'sample-answer': ANSWER, 'sample-choice': CHOICE}
            assert await preparation() == saved
            await checkpoint('a-b-a-exact-source-disclosures-scroll-plan-queues-pending-answers', {'before': before, 'after': after})

            seq = await app.evaluate('DeskBrowserPreview.fixture.appendOutput()')
            await app.wait_for_function('seq=>after>=seq', arg=seq)
            await frames(app)
            same_reading(after, await reading())
            assert await app.locator('#activity [data-item-id="sample-checkout-new-output"]').count() == 1
            await app.locator('#latest-output').click()
            await frames(app)
            assert await app.evaluate('nearLatest() && DeskSessionReading.follow()')
            await navigate(B)
            assert await app.get_by_label('Sample B answer — What check should remain?').input_value() == ANSWER
            assert await app.get_by_label('Sample B choice — Which scope?').input_value() == CHOICE
            await navigate(A)
            assert await app.evaluate('nearLatest() && DeskSessionReading.follow()')
            assert await preparation() == saved
            await checkpoint('native-shaped-update-and-explicit-latest-survive-return')

            await open_evidence()
            cold_before = await reading()
            await reload_with({'freshMcp': True})
            await app.wait_for_function('id=>selected===id&&!opening', arg=A)
            await frames(app)
            cold_after = await reading()
            same_reading(cold_before, cold_after)
            assert 'FRESH SAMPLE MCP RESULT' in await app.locator(f'#activity [data-item-id="{MCP}"] pre').text_content()
            assert await preparation() == saved
            metadata = await app.evaluate('''() => {const raw=localStorage.getItem(DeskReadingCheckpoint.STORAGE_KEY);
                return {key:DeskReadingCheckpoint.STORAGE_KEY,raw,value:JSON.parse(raw),limits:DeskReadingCheckpoint.LIMITS};}''')
            metadata_only(metadata)
            await checkpoint('cold-pagehide-fresh-source-exact-reading-metadata-only', {'before': cold_before, 'after': cold_after, 'metadata': metadata})

            await reload_with({'namespaceHold': True})
            await app.wait_for_function("DeskBrowserPreview.fixture.entered.includes('/api/native/home')")
            await navigate(C, settle=False)
            await app.locator('#prompt').fill(C_DRAFT)
            await app.wait_for_function('text=>draftSaved.get(selected)?.text===text', arg=C_DRAFT)
            current = await app.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")
            await app.evaluate("DeskBrowserPreview.fixture.release('/api/native/home')")
            await frames(app)
            assert await app.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})") == current
            assert await preparation() == saved
            await navigate(A)
            await app.evaluate('''async ids => {await open(ids.a,{revealLatest:false,readingTarget:{turn_id:ids.turn,item_id:ids.item}});
                nodes.get(ids.item).scrollIntoView({block:'start'});DeskSessionReading.target();}''', {'a': A, 'turn': PRIOR, 'item': MCP})
            await frames(app)
            assert await app.locator(f'#activity [data-item-id="{COMMAND}"] details').get_attribute('open') is None
            assert not await app.evaluate('DeskSessionReading.follow()')
            await app.locator('#latest-output').click()
            await frames(app)
            await reload_with({})
            await app.wait_for_function('id=>selected===id&&!opening', arg=A)
            await frames(app)
            assert await app.evaluate('nearLatest() && DeskSessionReading.follow()')
            assert await preparation() == saved
            await checkpoint('cold-late-namespace-current-c-explicit-target-and-latest-win', current)

            await app.locator(f'#activity [data-item-id="{COMMAND}"] summary').click()
            await app.evaluate('''id=>{const node=nodes.get(id);node.querySelector('.activity-evidence').scrollTop=283;
                window.scrollTo({top:scrollY+node.getBoundingClientRect().top+30,behavior:'instant'});}''', COMMAND)
            await frames(app)
            captured = await app.evaluate('DeskSessionReading.capture()')
            assert captured['anchor']['turn_id'] == PRIOR and captured['anchor']['item_id'] == COMMAND
            await reload_with({'movedCommand': True})
            await app.wait_for_function('id=>selected===id&&!opening', arg=A)
            await frames(app)
            assert 'Previous reading place unavailable' in await app.locator('#latest-output').inner_text()
            assert not await app.evaluate('DeskSessionReading.follow()')
            assert await app.locator(f'#activity [data-item-id="{COMMAND}"]').get_attribute('data-turn-id') == LIVE
            assert await app.locator(f'#activity [data-item-id="{COMMAND}"] details').get_attribute('open') is None
            assert await app.locator(f'#activity [data-item-id="{COMMAND}"] pre').evaluate('node=>node.scrollTop') == 0
            assert await preparation() == saved
            await checkpoint('cold-missing-triple-id-does-not-borrow-later-turn-item', captured)

            requests.extend(await app.evaluate('DeskBrowserPreview.requests'))
            forbidden = {'/api/turn', '/api/followups/send', '/api/approval', '/api/answer', '/api/steer', '/api/stop'}
            assert not any(r['method'] == 'POST' and urlsplit(r['path']).path in forbidden for r in requests), requests
            await app.evaluate("localStorage.setItem('codex-desk-reading-checkpoints-v1','installed-marker');localStorage.setItem('codex-desk-session','installed-session')")
            await app.locator('#preview-reset').click()
            await page.wait_for_timeout(100)
            app = await (await page.locator('iframe').element_handle()).content_frame() if embedded else page.main_frame
            await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate("localStorage.getItem('codex-desk-browser-preview-reading-checkpoints-v1')") is None
            assert await app.evaluate("localStorage.getItem('codex-desk-reading-checkpoints-v1')") == 'installed-marker'
            assert await app.evaluate("localStorage.getItem('codex-desk-session')") == 'installed-session'
            assert await app.evaluate('DeskBrowserPreview.snapshot().sessions.length') == 0
            await checkpoint('sample-reset-clears-only-sample-reading-and-preparation')
            assert not errors and not escaped and not external, (errors, escaped, external)
            report.update(passed=True, javascript_errors=errors, escaped_api_requests=escaped, external_requests=external,
                          native_model_calls=0, native_response_calls=0, simulated_api_requests=requests, static_http_requests=received)
            return report
        except Exception as error:
            report['error'] = repr(error)
            await page.screenshot(path=str(evidence / f'{width}-{mode}-session-reading-failed.png'))
            raise
        finally:
            (evidence / f'{width}-{mode}-session-reading.json').write_text(json.dumps(report, indent=2) + '\n')
            await context.close()
            await browser.close()


async def main(args):
    from playwright.async_api import async_playwright
    args.evidence.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        results = [await check(p, args.site, args.evidence, args.chromium, args.embedded, int(width)) for width in args.widths.split(',')]
    print(json.dumps({'passed': True, 'groups': sum(len(result['checks']) for result in results)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--embedded', action='store_true')
    parser.add_argument('--widths', default='1250,390')
    parser.add_argument('--chromium', default=os.environ.get('DESK_CHROMIUM'))
    asyncio.run(main(parser.parse_args()))
