#!/usr/bin/env python3
"""Check Changed saved work using the maintained three saved conversations and linked original.

The ordinary build checks unknown baselines and exact saved-reading navigation.
The existing --session-reading-fixture build additionally checks background dots,
first-new original material and frozen review boundaries. --embedded uses a real
iframe. Every review and overview read is observed through the static transport.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from check_browser_preview import static_server
from check_browser_preview_links import open_app
from check_browser_preview_session_reading import (
    A, B, C, PRIOR, COMMAND, DRAFT, B_DRAFT, ANSWER, CHOICE, frames, metadata_only,
)


async def check(p, site, evidence, chromium, embedded, width, ordinary=False):
    mode = 'embedded' if embedded else 'direct'
    variant = 'normal' if ordinary else 'rich'
    prefix = f'{width}-{mode}-{variant}'
    report = {'passed': False, 'actual_iframe': embedded, 'width': width,
              'ordinary_distribution': ordinary, 'sample_tasks': 3, 'checks': []}
    errors, external = [], []
    with static_server(site) as (url, received, escaped):
        browser = await p.chromium.launch(executable_path=chromium, headless=True,
                                          args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(viewport={'width': width, 'height': 900 if width == 1250 else 844})
        page = await context.new_page()
        page.set_default_timeout(12000)
        page.on('pageerror', lambda error: errors.append(str(error)))

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
            await page.screenshot(path=str(evidence / f'{prefix}-{name}.png'))
            print(json.dumps({'passed': name, 'width': width, 'embedded': embedded,
                              'ordinary': ordinary}), flush=True)

        async def navigate(session):
            button = app.locator(f'.session-row[data-session="{session}"] .session')
            await button.evaluate('node => node.focus({preventScroll:true})')
            await button.press('Enter')
            await app.wait_for_function("id=>selected===id&&!opening&&!$('task').hidden", arg=session)
            await frames(app)

        async def preparation():
            return await app.evaluate('''() => {const saved=DeskBrowserPreview.snapshot();
                return {drafts:saved.drafts,followups:saved.followups};}''')

        async def reading():
            return await app.evaluate('''id=>{const row=nodes.get(id),detail=row.querySelector('.activity-tool'),pre=row.querySelector('pre');
                return {session:selected,thread:nativeThreadId,turn:row.dataset.turnId,item:row.dataset.itemId,
                    open:detail.open,top:pre.scrollTop,left:pre.scrollLeft,screenTop:row.getBoundingClientRect().top,documentTop:scrollY+row.getBoundingClientRect().top,
                    windowTop:scrollY,windowLeft:scrollX,bottomGap:document.documentElement.scrollHeight-innerHeight-scrollY,follow:DeskSessionReading.follow(),draft:$('prompt').value,mode:$('turn-mode').value};}''', COMMAND)

        async def review():
            return await app.evaluate('DeskNewActivityView.state()')

        async def scope():
            return await app.evaluate('''() => ({project:$('changed-work-project').value,mode:$('changed-work-mode').value,
                title:$('session-filter').value,archived:$('show-archived').checked,
                previous:$('changed-work-previous').disabled,next:$('changed-work-next').disabled})''')

        async def overview():
            await app.locator('#show-changed-work').click()
            await app.wait_for_function("$('changed-work').open")

        async def source_and_summary(expected_seq, received_seq):
            value = await app.evaluate('''async id=>{const home=(await api('/api/native/home')).home_namespace;
                const state=await api('/api/state'),source=await api('/api/native/evidence-source?home='+home+'&thread='+id);
                return {home,native:state.native_material,source,summary:state.native_material.summaries.find(row=>row.owner.thread_id===id)};}''', 'sample-checkout-thread')
            assert len(value['home']) == 64 and all(c in '0123456789abcdef' for c in value['home']), value
            assert set(value['native']) == {'native_home', 'summaries'}
            assert value['native']['native_home'] == value['home'] == value['source']['home_namespace']
            summary = value['summary']
            assert set(summary) == {'owner', 'status', 'received_seq', 'material_seq'}, summary
            assert summary == {'owner': {'native_home': value['home'], 'session': A, 'thread_id': 'sample-checkout-thread'},
                               'status': 'available', 'received_seq': received_seq, 'material_seq': expected_seq}, summary
            assert value['source']['thread']['id'] == 'sample-checkout-thread'
            assert next(item for turn in value['source']['thread']['turns'] if turn['id'] == PRIOR
                        for item in turn['items'] if item['id'] == COMMAND)['type'] == 'commandExecution'
            for text in (DRAFT, B_DRAFT, ANSWER, 'NEW SAMPLE COMMAND MATERIAL', '/sample/projects/'):
                assert text not in json.dumps(summary), summary
            return summary

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
                    await api('/api/followups',{session:id,text:id+' first instruction remains queued.',mode:'native'});
                    await api('/api/followups',{session:id,text:id+' second instruction remains Plan.',mode:'plan'});}
                await refresh();}''', {'a': A, 'b': B, 'draft': DRAFT, 'bDraft': B_DRAFT})
            saved = await preparation()
            requests_at = await app.evaluate('DeskBrowserPreview.requests.length')
            reviewed_before = await app.evaluate('JSON.stringify(DeskNewActivityView.reviewMetadata())')
            await overview()
            await app.locator('#changed-work-mode').select_option('all')
            assert await app.locator('#changed-work-list .changed-work-row').count() == 3
            assert await app.locator('#changed-work-list [data-native-activity="baseline_missing"]').count() == 3
            assert '3 without a review baseline' in await app.locator('#changed-work-status').inner_text()
            geometry = await app.locator('#changed-work').evaluate('node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:innerWidth,height:innerHeight};}')
            assert 0 <= geometry['left'] < geometry['right'] <= geometry['width']
            assert 0 <= geometry['top'] < geometry['bottom'] <= geometry['height']
            assert await app.evaluate('JSON.stringify(DeskNewActivityView.reviewMetadata())') == reviewed_before
            assert await preparation() == saved
            overview_requests = await app.evaluate('start=>DeskBrowserPreview.requests.slice(start)', requests_at)
            assert all(request['method'] == 'GET' for request in overview_requests), overview_requests
            await checkpoint('unknown-baselines-grouped-actual-assets-get-only-no-preparation-write', geometry)
            await app.locator('#changed-work-close').click()

            await navigate(A)
            initial = 0 if ordinary else 3
            assert (await review())['reviewed_seq'] == initial and (await review())['first'] is None
            await app.locator(f'#activity [data-item-id="{COMMAND}"] summary').click()
            await app.evaluate('''data=>{const row=nodes.get(data.item);row.querySelector('pre').scrollTop=283;
                window.scrollTo({top:scrollY+row.getBoundingClientRect().top-data.screenTop,behavior:'instant'});}''',
                {'item': COMMAND, 'screenTop': 145})
            await frames(app)
            anchor = await reading()
            assert anchor['open'] and anchor['turn'] == PRIOR, anchor
            if not ordinary:
                assert not anchor['follow'], anchor
            assert anchor['top'] == (0 if ordinary else 283), anchor
            await navigate(B)
            if not ordinary:
                await app.get_by_label('Sample B answer — What check should remain?').fill(ANSWER)
                await app.get_by_label('Sample B choice — Which scope?').select_option(CHOICE)
            await app.locator('#prompt').evaluate('node=>{node.focus({preventScroll:true});node.setSelectionRange(4,19,"backward");}')
            b_before = await app.evaluate('''() => ({selected,thread:nativeThreadId,text:$('prompt').value,mode:$('turn-mode').value,
                start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,top:scrollY})''')
            requests_at = await app.evaluate('DeskBrowserPreview.requests.length')
            first_seq, tail = initial, initial
            if not ordinary:
                first_seq = await app.evaluate('DeskBrowserPreview.fixture.updateCommand()')
                tail = await app.evaluate('DeskBrowserPreview.fixture.appendIgnored()')
            await app.evaluate('refresh()')
            await frames(app)
            b_after = await app.evaluate('''() => ({selected,thread:nativeThreadId,text:$('prompt').value,mode:$('turn-mode').value,
                start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,top:scrollY})''')
            assert b_after == b_before, (b_before, b_after)
            assert await app.locator(f'.session-row[data-session="{A}"] .native-material-dot').count() == (0 if ordinary else 1)
            for session in (B, C):
                assert await app.locator(f'.session-row[data-session="{session}"] .native-material-dot').count() == 0
            assert await preparation() == saved
            background_requests = await app.evaluate('start=>DeskBrowserPreview.requests.slice(start)', requests_at)
            assert all(request['method'] == 'GET' for request in background_requests), background_requests
            assert not any(urlsplit(request['path']).path in {'/api/open', '/api/native/thread',
                '/api/native/evidence-source', '/api/native/task-response'} for request in background_requests), background_requests
            report['background_dot_requests'] = background_requests
            # Read the fresh exact source deliberately, after proving that the
            # background compact update did not fetch an original body.
            summary = await source_and_summary(first_seq, tail)
            if not ordinary:
                assert await app.get_by_label('Sample B answer — What check should remain?').input_value() == ANSWER
                assert await app.get_by_label('Sample B choice — Which scope?').input_value() == CHOICE
            await checkpoint('compact-parent-material-only-dot-keeps-other-owner-draft-queues-answer-caret', summary)

            # The real overview captures the project, title, archive and first-page
            # scope. No fabricated sessions or controller-only opening is used.
            await app.locator('#session-filter').fill('Sample')
            await overview()
            await app.locator('#changed-work-mode').select_option('all' if ordinary else 'changed')
            project = await app.locator('#changed-work-project').evaluate('node=>Array.from(node.options).find(option=>option.textContent.includes("/sample/projects/checkout")).value')
            await app.locator('#changed-work-project').select_option(project)
            assert await app.locator('#changed-work-list .changed-work-row').count() == 1
            await app.evaluate('id=>globalThis.fixtureOverviewButton=document.querySelector(`#changed-work-list [data-session="${id}"] button`)', A)
            captured_scope = await scope()
            await app.locator(f'#changed-work-list [data-session="{A}"] button').click()
            await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending', arg=A)
            await frames(app)
            returned = await reading()
            for key in ('session', 'thread', 'turn', 'item', 'open', 'top', 'left', 'follow', 'draft', 'mode', 'windowLeft'):
                assert returned[key] == anchor[key], (key, anchor, returned)
            if anchor['follow']:
                # An ordinary short history can still be following Latest. Its
                # captured intent returns deliberately to the current bottom,
                # rather than manufacturing a manual older passage.
                assert ordinary and abs(returned['bottomGap']) <= 1, (anchor, returned)
            else:
                assert abs(returned['screenTop'] - anchor['screenTop']) <= 1, (anchor, returned)
                # Back to Changed work adds a control above activity; preserve
                # the same screen passage with exact layout compensation.
                assert abs((returned['windowTop'] - anchor['windowTop']) -
                           (returned['documentTop'] - anchor['documentTop'])) <= 1, (anchor, returned)
            assert (await review())['reviewed_seq'] == initial
            assert await preparation() == saved
            await checkpoint('overview-forward-restores-original-triple-disclosure-body-and-captured-reading-intent', {'anchor': anchor, 'returned': returned, 'scope': captured_scope})

            if not ordinary:
                pending = await review()
                assert (pending['first']['turn_id'], pending['first']['item_id'], pending['first']['first_seq']) == (PRIOR, COMMAND, first_seq), pending
                await app.locator('#native-activity-first').evaluate('node=>node.focus({preventScroll:true})')
                await app.locator('#native-activity-first').press('Enter')
                await frames(app)
                revealed = await reading()
                assert revealed['open'] and revealed['top'] == 283 and abs(revealed['screenTop']) <= 1, revealed
                assert await app.evaluate('id=>document.activeElement===nodes.get(id)', COMMAND)
                assert (await review())['reviewed_seq'] == initial
                await app.evaluate("DeskBrowserPreview.fixture.holdResponse('/api/events')")
                later = await app.evaluate('DeskBrowserPreview.fixture.appendOutput()')
                await app.wait_for_function("DeskBrowserPreview.fixture.responsesEntered.includes('/api/events')")
                assert (await review())['frontier'] == first_seq
                await app.locator('#native-activity-mark').evaluate('node=>node.focus({preventScroll:true})')
                await app.locator('#native-activity-mark').press('Enter')
                assert (await review())['reviewed_seq'] == first_seq
                assert await preparation() == saved
                await app.evaluate('refresh()')
                await checkpoint('read-first-original-item-separate-from-mark-frozen-displayed-frontier', {'revealed': revealed, 'frozen': first_seq, 'held_newer': later})
            else:
                assert await app.locator('#native-activity-first').is_disabled()
                assert await app.locator('#native-activity-mark').is_disabled()

            requests_at = await app.evaluate('DeskBrowserPreview.requests.length')
            reviewed_before = await app.evaluate('JSON.stringify(DeskNewActivityView.reviewMetadata())')
            await app.locator('#changed-work-back').click()
            await app.wait_for_function("$('changed-work').open")
            assert await scope() == captured_scope
            assert await app.evaluate('document.activeElement===fixtureOverviewButton && fixtureOverviewButton.isConnected')
            assert await app.locator('#changed-work-list .changed-work-row').count() == 1
            if not ordinary:
                assert await app.locator(f'#changed-work-list [data-session="{A}"] [data-native-activity="new_activity"]').count() == 1
                # The compact frontier can know about held native transport output;
                # it cannot advance this browser's displayed review boundary.
                await app.evaluate("DeskBrowserPreview.fixture.releaseResponse('/api/events')")
                await app.wait_for_function('seq=>after>=seq', arg=later)
                await frames(app)
                pending = await review()
                assert pending['reviewed_seq'] == first_seq and pending['first']['first_seq'] == later, pending
            assert await app.evaluate('JSON.stringify(DeskNewActivityView.reviewMetadata())') == reviewed_before
            assert await preparation() == saved
            return_requests = await app.evaluate('start=>DeskBrowserPreview.requests.slice(start)', requests_at)
            assert all(request['method'] == 'GET' for request in return_requests), return_requests
            await checkpoint('exact-overview-row-focus-project-title-archive-page-return-get-only', captured_scope)

            if not ordinary:
                await app.locator('#changed-work-close').click()
                await app.locator('#native-activity-mark').click()
                assert (await review())['reviewed_seq'] == later
                await app.locator('#changed-work-back').click()
                assert await scope() == captured_scope
                assert await app.evaluate('document.activeElement===fixtureOverviewButton && fixtureOverviewButton.isConnected')
                assert 'Opened from this overview' in await app.locator('#changed-work-list').inner_text()
                assert await app.locator(f'#changed-work-list [data-session="{A}"] [data-native-activity="up_to_date"]').count() == 1
                assert await app.locator(f'.session-row[data-session="{A}"] .native-material-dot').count() == 0
                assert await preparation() == saved
                await checkpoint('reviewed-row-retained-in-exact-changed-scope-without-new-dot', await review())

            reading_metadata = await app.evaluate('''() => {const raw=localStorage.getItem(DeskReadingCheckpoint.STORAGE_KEY);
                return {key:DeskReadingCheckpoint.STORAGE_KEY,raw,value:JSON.parse(raw),limits:DeskReadingCheckpoint.LIMITS};}''')
            metadata_only(reading_metadata)
            review_raw = await app.evaluate('localStorage.getItem(DeskNewActivity.STORAGE_KEY)')
            review_value = json.loads(review_raw)
            assert set(review_value) == {'version', 'reviews'} and review_value['version'] == 1
            for entry in review_value['reviews']:
                assert set(entry) == {'owner', 'reviewed_seq'}
                assert set(entry['owner']) == {'native_home', 'session', 'thread_id'}
            for text in (DRAFT, B_DRAFT, ANSWER, 'NEW SAMPLE COMMAND MATERIAL', '/sample/projects/'):
                assert text not in review_raw
            requests = await app.evaluate('DeskBrowserPreview.requests')
            forbidden = {'/api/turn', '/api/respond', '/api/followups/send', '/api/approval', '/api/answer', '/api/steer', '/api/stop'}
            assert not any(request['method'] == 'POST' and urlsplit(request['path']).path in forbidden for request in requests), requests
            assert not errors and not escaped and not external, (errors, escaped, external)
            report.update(passed=True, javascript_errors=errors, escaped_api_requests=escaped, external_requests=external,
                          native_model_calls=0, native_response_calls=0, simulated_api_requests=requests,
                          retained_preparation=saved, static_http_requests=received)
            return report
        except Exception as error:
            report.update(error=repr(error), javascript_errors=errors, external_requests=external)
            if app is not None:
                report['failure_state'] = await app.evaluate('''() => ({selected,opening,sessionReadingPending,after,
                    review:DeskNewActivityView.state(),bodyScroll:scrollY,scope:{project:$('changed-work-project').value,
                    mode:$('changed-work-mode').value,title:$('session-filter').value},requests:DeskBrowserPreview.requests})''')
            await page.screenshot(path=str(evidence / f'{prefix}-changed-work-failed.png'))
            raise
        finally:
            (evidence / f'{prefix}-changed-work.json').write_text(json.dumps(report, indent=2) + '\n')
            await context.close()
            await browser.close()


async def main(args):
    from playwright.async_api import async_playwright
    args.evidence.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        results = [await check(p, args.site, args.evidence, args.chromium, args.embedded, int(width), args.ordinary)
                   for width in args.widths.split(',')]
    print(json.dumps({'passed': True, 'groups': sum(len(result['checks']) for result in results)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--embedded', action='store_true')
    parser.add_argument('--ordinary', action='store_true', help='Check the default primary histories and linked original without transport fixtures')
    parser.add_argument('--widths', default='1250,390')
    parser.add_argument('--chromium', default=os.environ.get('DESK_CHROMIUM'))
    asyncio.run(main(parser.parse_args()))
