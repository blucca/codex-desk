#!/usr/bin/env python3
"""Check first-new review in the opt-in maintained sample, direct or actual iframe.

Build with --session-reading-fixture. Source updates, cached replay, transport
holds and deliberate review frames use synthetic data and the maintained app.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from check_browser_preview import static_server
from check_browser_preview_links import open_app, reload_app, reset_app
from check_browser_preview_session_reading import A, B, C, PRIOR, LIVE, COMMAND, DRAFT, B_DRAFT, ANSWER, CHOICE, frames

REVIEW_KEY = 'codex-desk-browser-preview-activity-review-v1'


async def check(p, site, evidence, chromium, embedded, width):
    mode = 'embedded' if embedded else 'direct'
    report = {'passed': False, 'actual_iframe': embedded, 'width': width, 'checks': []}
    errors, external, requests = [], [], []
    with static_server(site) as (url, received, escaped):
        browser = await p.chromium.launch(executable_path=chromium, headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(viewport={'width': width, 'height': 900 if width == 1250 else 844})
        page = await context.new_page()
        page.set_default_timeout(12000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        await context.add_init_script('''window.DeskPreviewReadingOverrides=JSON.parse(sessionStorage.getItem('reading-fixture-overrides') || '{}');
            const fixtureRequestFrame=globalThis.requestAnimationFrame;
            globalThis.requestAnimationFrame=callback=>{if(globalThis.fixtureCaptureNextFrame){globalThis.fixtureCaptureNextFrame=false;globalThis.fixtureLatestFrame=callback;return -1;}
                return fixtureRequestFrame.call(globalThis,callback);};''')

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

        async def navigate(session):
            button = app.locator(f'.session-row[data-session="{session}"] .session')
            await button.evaluate('node => node.focus({preventScroll:true})')
            await button.press('Enter')
            await app.wait_for_function("id=>selected===id&&!opening&&!$('task').hidden", arg=session)
            await frames(app)

        async def consume(sequence):
            await app.wait_for_function('seq=>after>=seq', arg=sequence)
            await frames(app)

        async def review():
            return await app.evaluate('''() => ({...DeskNewActivityView.state(),intent:DeskSessionReading.intent(),follow:DeskSessionReading.follow(),near:nearLatest(),
                statusText:$('native-activity-status').textContent,metadata:DeskNewActivityView.reviewMetadata(),raw:localStorage.getItem(DeskNewActivity.STORAGE_KEY)})''')

        async def reading():
            return await app.evaluate('''id=>{const row=nodes.get(id),detail=row.querySelector('details'),pre=row.querySelector('pre');
                return {session:selected,thread:nativeThreadId,turn:row.dataset.turnId,item:row.dataset.itemId,open:detail.open,top:pre.scrollTop,
                    screenTop:row.getBoundingClientRect().top,windowTop:scrollY,draft:$('prompt').value,mode:$('turn-mode').value};}''', COMMAND)

        async def preparation():
            return await app.evaluate('''ids=>{const saved=DeskBrowserPreview.snapshot();return {
                drafts:Object.fromEntries(ids.map(id=>[id,saved.drafts[id]])),followups:saved.followups};}''', [A, B])

        async def reload_with(overrides=None):
            nonlocal app
            requests.extend(await app.evaluate('DeskBrowserPreview.requests'))
            await app.evaluate('''extra=>sessionStorage.setItem('reading-fixture-overrides',JSON.stringify({activityRows:DeskBrowserPreview.fixture.activityRows(),...(extra || {})}))''', overrides)
            app = await reload_app(page, embedded)
            await app.wait_for_function('id=>selected===id&&!opening', arg=A)
            await frames(app)

        async def held_latest():
            await app.evaluate('''() => {const original=DeskNewActivityView.reviewLatest;
                globalThis.fixtureLatestOriginal=original;
                DeskNewActivityView.reviewLatest=capture=>{globalThis.fixtureLatestFrame=null;globalThis.fixtureCaptureNextFrame=true;return original(capture);};}''')
            await app.locator('#latest-output').click()
            assert await app.evaluate('typeof fixtureLatestFrame === "function"')
            await app.evaluate('DeskNewActivityView.reviewLatest=fixtureLatestOriginal')

        async def release_latest():
            await app.evaluate('''() => {const callback=fixtureLatestFrame;fixtureLatestFrame=null;callback(performance.now());}''')
            await frames(app)

        try:
            app = await open_app(page, context, url, embedded)
            await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate('!!DeskBrowserPreview.fixture && !!DeskNewActivityView && DeskNewActivity.STORAGE_KEY') == REVIEW_KEY
            assert await app.evaluate("document.documentElement.dataset.previewEmbedded==='true'") == embedded
            await app.evaluate('''async data=>{
                for(const name of ['checkout','docs','mobile']){const id=(await api('/api/import',{thread:'sample-'+name+'-thread'})).id;await api('/api/followups?session='+encodeURIComponent(id));}
                for(const [id,text] of [[data.a,data.draft],[data.b,data.bDraft]]){
                    await api('/api/draft',{session:id,text,mode:'plan',revision:0});
                    await api('/api/followups',{session:id,text:id+' first instruction remains queued.',mode:'native'});
                    await api('/api/followups',{session:id,text:id+' second instruction remains Plan.',mode:'plan'});}
                await refresh();}''', {'a': A, 'b': B, 'draft': DRAFT, 'bDraft': B_DRAFT})
            await navigate(A)
            seeded = await review()
            assert seeded['reviewed_seq'] == 3 and seeded['first'] is None and seeded['status'] == 'up_to_date', seeded
            saved = await preparation()
            await checkpoint('first-owned-attach-seeds-once', seeded)

            await app.locator(f'#activity [data-item-id="{COMMAND}"] summary').click()
            await app.evaluate('''id=>{const row=nodes.get(id);row.querySelector('pre').scrollTop=283;window.scrollTo({top:scrollY+row.getBoundingClientRect().top-145,behavior:'instant'});}''', COMMAND)
            await frames(app)
            before = await reading()
            seq = await app.evaluate('DeskBrowserPreview.fixture.updateCommand()')
            tail = await app.evaluate('DeskBrowserPreview.fixture.appendIgnored()')
            await consume(tail)
            pending = await review()
            assert pending['reviewed_seq'] == 3 and pending['frontier'] == seq and pending['received_seq'] == tail, pending
            assert (pending['first']['turn_id'], pending['first']['item_id']) == (PRIOR, COMMAND)
            assert await reading() == before and await preparation() == saved
            await checkpoint('earlier-item-update-keeps-manual-reading-status-child-plan-ignored', pending)

            await navigate(B)
            await app.get_by_label('Sample B answer — What check should remain?').fill(ANSWER)
            await app.get_by_label('Sample B choice — Which scope?').select_option(CHOICE)
            await navigate(A)
            assert await reading() == before
            await app.locator('#native-activity-first').evaluate('node=>node.focus({preventScroll:true})')
            await app.locator('#native-activity-first').press('Enter')
            await frames(app)
            revealed = await reading()
            assert revealed['turn'] == PRIOR and revealed['open'] and revealed['top'] == 283 and abs(revealed['screenTop']) <= 1, revealed
            assert await app.evaluate('id=>document.activeElement===nodes.get(id)', COMMAND)
            assert (await review())['reviewed_seq'] == 3 and await preparation() == saved
            geometry = await app.evaluate('''()=>Object.fromEntries(['activity-controls','native-activity-status','latest-output','native-activity-first','native-activity-mark'].map(id=>{
                const node=$(id),r=node.getBoundingClientRect();return [id,{left:r.left,right:r.right,top:r.top,bottom:r.bottom,background:getComputedStyle(node).backgroundColor}];}))''')
            panel = geometry['activity-controls']
            assert 0 <= panel['left'] < panel['right'] <= width and panel['background'] not in ('transparent', 'rgba(0, 0, 0, 0)'), geometry
            assert geometry['native-activity-status']['bottom'] <= geometry['native-activity-first']['top'], geometry
            await checkpoint('keyboard-read-first-exact-disclosure-no-review-opaque-bounded-panel', geometry)

            await reload_with()
            cold = await reading()
            for key in ('session', 'thread', 'turn', 'item', 'open', 'top', 'draft', 'mode'):
                assert cold[key] == revealed[key], (key, cold, revealed)
            assert abs(cold['screenTop']-revealed['screenTop']) <= 1
            pending = await review()
            assert pending['reviewed_seq'] == 3 and pending['first']['item_id'] == COMMAND
            value = json.loads(pending['raw'])
            assert set(value) == {'version', 'reviews'} and value['version'] == 1
            for row in value['reviews']:
                assert set(row) == {'owner', 'reviewed_seq'} and set(row['owner']) == {'native_home', 'session', 'thread_id'}
            for text in (DRAFT, B_DRAFT, ANSWER, '/sample/projects/', 'NEW SAMPLE COMMAND MATERIAL'):
                assert text not in pending['raw']
            assert await preparation() == saved
            await checkpoint('cold-fresh-source-retains-review-and-reading-separately-metadata-only', pending)

            # Freeze the real rendered frontier while an actual transport response is held.
            await app.evaluate("DeskBrowserPreview.fixture.holdResponse('/api/events')")
            later = await app.evaluate('DeskBrowserPreview.fixture.appendOutput()')
            await app.wait_for_function("DeskBrowserPreview.fixture.responsesEntered.includes('/api/events')")
            assert (await review())['frontier'] == seq
            await app.locator('#native-activity-mark').evaluate('node=>node.focus({preventScroll:true})')
            await app.locator('#native-activity-mark').press('Enter')
            assert (await review())['reviewed_seq'] == seq
            await app.evaluate("DeskBrowserPreview.fixture.releaseResponse('/api/events')")
            await consume(later)
            assert (await review())['first']['first_seq'] == later
            await checkpoint('held-response-after-mark-remains-beyond-frozen-frontier', await review())

            await held_latest()
            intent = (await review())['intent']
            newer = await app.evaluate('DeskBrowserPreview.fixture.updateCommand()')
            await consume(newer)
            assert (await review())['intent'] == intent
            await release_latest()
            exact = await review()
            assert exact['reviewed_seq'] == later and exact['first']['first_seq'] == newer, exact
            await app.locator('#native-activity-mark').click()
            auto = await app.evaluate('DeskBrowserPreview.fixture.updateCommand()')
            await consume(auto)
            assert (await review())['reviewed_seq'] == newer
            await checkpoint('held-explicit-latest-survives-auto-follow-reviews-only-captured-frontier', exact)

            await held_latest()
            await app.locator('#prompt').fill(DRAFT)
            await release_latest()
            assert (await review())['reviewed_seq'] == newer
            await held_latest()
            await app.evaluate("DeskSessionReading.target();window.scrollTo({top:350,behavior:'instant'})")
            await release_latest()
            assert (await review())['reviewed_seq'] == newer
            await held_latest()
            await navigate(C)
            await release_latest()
            assert await app.evaluate('selected') == C
            await navigate(A)
            assert (await review())['reviewed_seq'] == newer and await preparation() == saved
            await checkpoint('manual-and-new-owner-intents-cancel-late-latest', await review())

            await reload_with({'movedCommand': True})
            missing = await review()
            assert missing['reviewed_seq'] == newer and missing['first']['turn_id'] == PRIOR and missing['source'] == 'item_unavailable', missing
            await app.locator('#native-activity-first').click()
            assert 'item_unavailable' in await app.locator('#native-activity-status').inner_text()
            await app.locator('#native-activity-mark').click()
            assert (await review())['reviewed_seq'] == newer
            fresh_turns = await app.evaluate('''async()=>{const home=(await api('/api/native/home')).home_namespace;
                const source=await api('/api/native/evidence-source?home='+home+'&thread='+nativeThreadId);
                return source.thread.turns.map(turn=>({id:turn.id,items:turn.items.map(item=>item.id)}));}''')
            assert COMMAND not in next(turn['items'] for turn in fresh_turns if turn['id'] == PRIOR)
            assert COMMAND in next(turn['items'] for turn in fresh_turns if turn['id'] == LIVE)
            assert await preparation() == saved
            await checkpoint('fresh-missing-triple-cached-replay-cannot-resurrect-or-review', missing)

            requests.extend(await app.evaluate('DeskBrowserPreview.requests'))
            forbidden = {'/api/turn', '/api/followups/send', '/api/approval', '/api/answer', '/api/steer', '/api/stop'}
            assert not any(r['method'] == 'POST' and urlsplit(r['path']).path in forbidden for r in requests)
            await app.evaluate("localStorage.setItem('codex-desk-activity-review-v1','installed-review-marker');localStorage.setItem('codex-desk-reading-checkpoints-v1','installed-reading-marker')")
            app = await reset_app(page, app, embedded)
            assert await app.evaluate('key=>localStorage.getItem(key)', REVIEW_KEY) is None
            assert await app.evaluate("localStorage.getItem('codex-desk-activity-review-v1')") == 'installed-review-marker'
            assert await app.evaluate("localStorage.getItem('codex-desk-reading-checkpoints-v1')") == 'installed-reading-marker'
            assert await app.evaluate('DeskBrowserPreview.snapshot().sessions.length') == 0
            await checkpoint('reset-clears-only-sample-review-reading-and-preparation')
            assert not errors and not escaped and not external, (errors, escaped, external)
            report.update(passed=True, javascript_errors=errors, escaped_api_requests=escaped, external_requests=external,
                          native_model_calls=0, native_response_calls=0, simulated_api_requests=requests, static_http_requests=received)
            return report
        except Exception as error:
            report['error'] = repr(error)
            await page.screenshot(path=str(evidence / f'{width}-{mode}-new-activity-failed.png'))
            raise
        finally:
            (evidence / f'{width}-{mode}-new-activity.json').write_text(json.dumps(report, indent=2)+'\n')
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
