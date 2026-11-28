"""Selected original/F3 and explicit live Refresh through real loopback routes.

Controlled native thread/read; real Desk.history, private SQLite, HTTP and
Chromium. DESK_TEST_TEMP and DESK_TEST_EVIDENCE isolate state and receipts.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, ThreadingHTTPServer, handler
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright


async def acceptance(browser, width, root, evidence):
    result = {'width': width, 'checks': [], 'javascriptErrors': []}
    with tempfile.TemporaryDirectory(dir=root, prefix='selected-original-') as temporary:
        folder = Path(temporary)
        home, state_dir = folder / 'home', folder / 'state'
        project = folder / 'active-project'
        project.mkdir()
        removed = folder / 'removed + 决策'
        removed.mkdir()
        removed.rmdir()
        threads = {}
        old_phrase = 'EXACT ORIGINAL décision beyond the first window'
        output = '\n'.join(f'Original command line {n:04d}: retained exact evidence.' for n in range(1800))
        output += '\n' + old_phrase + '\nORIGINAL LATEST'
        for key in ('active', 'newer', 'removed', 'failed-open'):
            cwd = removed if key == 'removed' else project
            items = [{'id': f'{key}-context-{n}', 'type': 'agentMessage',
                      'text': f'Original {key} neighbouring answer {n:02d}'} for n in range(85)]
            items[45] = {'id': key + '-command', 'type': 'commandExecution',
                         'command': 'inspect --original', 'status': 'completed', 'exitCode': 0,
                         'aggregatedOutput': output if key == 'active' else 'Retained command evidence ' + key}
            threads['native-' + key] = {'id': 'native-' + key, 'name': 'Selected ' + key,
                'cwd': str(cwd), 'modelProvider': 'fixture', 'turns': [
                    {'id': 'turn-' + key, 'status': 'completed', 'items': items}]}
        live = {'id': 'native-active', 'cwd': str(project), 'turns': [
            {'id': 'live-turn', 'status': 'inProgress', 'items': [
                {'id': 'live-command', 'type': 'commandExecution', 'command': 'tail --live',
                 'status': 'inProgress', 'aggregatedOutput': '\n'.join(f'Live line {i}' for i in range(250))},
                {'id': 'live-answer', 'type': 'agentMessage', 'text': 'Live selected answer remains separate.'}]}]}
        native, http, holds, failures, responses = [], [], {}, set(), []
        desk = Desk('not-executed', home, state_dir)
        plans = {key: '  Exact unsent ' + key + ' Plan — 保留\nNever send this reader review. 🔧\n'
                 for key in ('active', 'newer', 'removed', 'failed-open')}
        for key in plans:
            desk.store.create(str(removed if key == 'removed' else project), 'default', identifier=key,
                              name='Selected ' + key)
            desk.store.update(key, thread_id='native-' + key, status='saved', thread_saved=1, name_pending=0)
            save_draft(desk.store, key, plans[key], 'plan', 0)
            add_followup(desk.store, key, 'Paused Work for ' + key, 'native')
            add_followup(desk.store, key, 'Paused Plan for ' + key, 'plan')
        original_drafts = {key: load_draft(desk.store, key) for key in plans}
        original_queues = {key: followup_snapshot(desk.store, key) for key in plans}
        class Catalog:
            def request(self, method, params):
                native.append({'method': method, 'params': copy.deepcopy(params)})
                assert method in ('thread/list', 'thread/read'), 'Unexpected native mutation: ' + method
                if method == 'thread/list':
                    return {'data': [], 'nextCursor': None}
                identifier = params['threadId']
                assert params == {'threadId': identifier, 'includeTurns': True}
                if identifier in holds:
                    entered, release = holds[identifier]
                    entered.set()
                    assert release.wait(30), 'Held original read was not released'
                if identifier in failures:
                    raise OSError('Controlled original read unavailable')
                responses.append(identifier)
                return {'thread': copy.deepcopy(threads[identifier])}
        def mount():
            desk.catalog = lambda: Catalog()
            desk.runtime = lambda id: (_ for _ in ()).throw(AssertionError('Reader invoked native task runtime'))
            def opened(identifier):
                native.append({'method': 'explicit-open', 'session': identifier})
                if identifier == 'failed-open':
                    raise OSError('Controlled native attachment unavailable')
                desk.store.update(identifier, status='running' if identifier == 'active' else 'ready', model='fixture', provider='fixture')
                return {'thread': copy.deepcopy(live if identifier == 'active' else threads['native-' + identifier]),
                        'model': 'fixture', 'modelProvider': 'fixture'}
            desk.open = opened
        def start_server(port=0):
            mount()
            base = handler(desk, 'fixture-read-access')
            class Handler(base):
                def do_GET(self):
                    parsed = urlsplit(self.path)
                    http.append({'method': 'GET', 'path': parsed.path, 'query': parse_qs(parsed.query)})
                    return super().do_GET()
                def do_POST(self):
                    parsed = urlsplit(self.path)
                    http.append({'method': 'POST', 'path': parsed.path, 'query': parse_qs(parsed.query)})
                    return super().do_POST()
            server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            return server, worker
        def stop_server():
            server.shutdown()
            server.server_close()
            worker.join(5)
            desk.close()
            desk.store.db.close()
        server, worker = start_server()
        port = server.server_port
        context = await browser.new_context(viewport={'width': width, 'height': 900 if width > 390 else 844})
        page = await context.new_page()
        page.set_default_timeout(15000)
        page.on('pageerror', lambda error: result['javascriptErrors'].append(str(error)))
        async def ready():
            await page.wait_for_function('$("history-reader").open && $("history-reader-body").getAttribute("aria-busy")==="false"')
        async def refreshed():
            await page.wait_for_function('!$("history-reader-refresh").disabled && $("history-reader-find-form").getAttribute("aria-busy")!=="true"')
        async def select(key):
            if await page.locator('#history-reader').evaluate('node=>node.open'):
                await page.locator('#history-reader-close').click()
            await page.locator(f'.session-row[data-session="{key}"] .session').click()
            await page.wait_for_function('key=>selected===key && !opening', arg=key)
            await page.wait_for_function('!$("read-original").disabled')
        async def unchanged(key='active'):
            assert await page.evaluate('selected') == key
            assert await page.locator('#prompt').input_value() == plans[key]
            assert await page.locator('#turn-mode').input_value() == 'plan'
            assert load_draft(desk.store, key) == original_drafts[key]
            assert followup_snapshot(desk.store, key) == original_queues[key]
            assert await page.locator('#followup-count').inner_text() == '2'
        async def find(phrase):
            await page.locator('#history-reader-find-query').fill(phrase)
            await page.locator('#history-reader-find-query').press('Enter')
            await page.wait_for_function('!$("history-reader-find-submit").disabled')
        async def visible_match():
            await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            geometry = await page.evaluate('''() => {
                const mark=document.querySelector('.history-reader-target mark'),body=$('history-reader-body'),pre=mark.closest('pre');
                const bounds=node=>{const rect=node.getBoundingClientRect();return {top:rect.top,bottom:rect.bottom};};
                return {mark:bounds(mark),body:bounds(body),pre:bounds(pre),dialog:bounds($('history-reader')),viewport:{top:0,bottom:innerHeight}};
            }''')
            assert geometry['mark']['top'] >= max(value['top'] for value in geometry.values()) - 1, geometry
            assert geometry['mark']['bottom'] <= min(value['bottom'] for value in geometry.values()) + 1, geometry
            return geometry
        async def source_glyph():
            return await target.evaluate(r"""n=>{
              const p=n.querySelector('pre'),body=$('history-reader-body'),reader=$('history-reader'),text=p.textContent,start=Number(n.dataset.windowStart);
              const pr=p.getBoundingClientRect(),br=body.getBoundingClientRect(),rr=reader.getBoundingClientRect();
              const clip={left:Math.max(pr.left,br.left,rr.left,0),right:Math.min(pr.right,br.right,rr.right,innerWidth),top:Math.max(pr.top,br.top,rr.top,0),bottom:Math.min(pr.bottom,br.bottom,rr.bottom,innerHeight)};
              const walker=document.createTreeWalker(p,NodeFilter.SHOW_TEXT),nodes=[];let at=0,node;while(node=walker.nextNode()){nodes.push({node,start:at,end:at+node.data.length});at+=node.data.length;}
              function point(at,right=false){for(const q of nodes){if(at<q.end||!right&&at===q.end)return[q.node,at-q.start];}const q=nodes.at(-1);return q?[q.node,q.node.data.length]:null;}
              function glyph(at){const a=point(at,true),b=point(at+(text.codePointAt(at)>0xffff?2:1));if(!a||!b)return null;const r=document.createRange();r.setStart(...a);r.setEnd(...b);return [...r.getClientRects()].find(r=>r.width&&r.height);}
              let first=null;const offsets=[];for(let i=0;i<text.length;i+=text.codePointAt(i)>0xffff?2:1)if(!['\n','\r'].includes(text[i]))offsets.push(i);
              let low=0,high=offsets.length;while(low<high){const mid=(low+high)>>>1,r=glyph(offsets[mid]);if(!r||r.bottom<=clip.top)low=mid+1;else high=mid;}
              for(let i=low;i<offsets.length;i++){const at=offsets[i],r=glyph(at);if(!r)continue;if(r.top>=clip.bottom)break;if(r.bottom>clip.top&&r.right>clip.left&&r.left<clip.right){const lines=[...text.slice(0,at+30).matchAll(/Original command line (\d{4})/g)].filter(m=>m.index<=at);first={offset:start+at,char:String.fromCodePoint(text.codePointAt(at)),line:lines.length?Number(lines.at(-1)[1]):null,top:r.top,relative_top:r.top-clip.top,bottom:r.bottom};break;}}
              return {window_start:start,inner:p.scrollTop,body:body.scrollTop,outer:reader.scrollTop,clip,first_visible:first,pre:{top:pr.top,bottom:pr.bottom,height:pr.height,font:getComputedStyle(p).font,line_height:getComputedStyle(p).lineHeight},focus:document.activeElement.id,query:$('history-reader-find-query').value};
            }""")
        def read_only_since(http_before, native_before):
            routes = http[http_before:]
            assert not any(entry['path'] in ('/api/native', '/api/open', '/api/import', '/api/turn', '/api/handoff/start', '/api/followups/send') for entry in routes)
            assert not any(entry['method'] == 'POST' and entry['path'] != '/api/draft' for entry in routes)
            assert all(call['method'] == 'thread/read' for call in native[native_before:])
        async def bounded():
            assert await page.locator('.history-reader-item').count() <= 40
            assert await page.locator('.history-reader-text').evaluate_all('nodes=>nodes.every(node=>node.textContent.length<=20000)')
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth && $("history-reader").scrollWidth<=$("history-reader").clientWidth')
        def held(identifier='native-active'):
            entered, release = threading.Event(), threading.Event()
            holds[identifier] = entered, release
            return entered, release
        try:
            await page.goto(f'http://127.0.0.1:{port}/#access=fixture-read-access')
            await page.wait_for_function('state.sessions.length===4')
            await select('active')
            desk.store.event('active', {'method': 'turn/started', 'params': {
                'threadId': 'native-active', 'turn': {'id': 'live-turn'}}})
            await page.evaluate('pollActivity()')
            await unchanged()

            # Header entry reads the exact Store native ID, with no title search.
            h, n = len(http), len(native)
            await page.locator('#read-original').click()
            await ready()
            assert 'Thread native-active' in await page.locator('#history-reader-binding').inner_text()
            assert await page.locator('#history-reader-back').inner_text() == 'Return to selected task'
            assert 'Page 3 of 3' in await page.locator('#history-reader-coverage').inner_text()
            assert 'Original active neighbouring answer 84' in await page.locator('#history-reader-body').inner_text()
            await find(old_phrase)
            target = page.locator('.history-reader-target')
            assert await target.get_attribute('data-item-id') == 'active-command'
            assert await target.get_attribute('data-turn-id') == 'turn-active'
            assert await target.locator('mark').inner_text() == old_phrase
            assert int(await target.get_attribute('data-window-start')) > 20000
            mark_geometry = await visible_match()
            read_only_since(h, n)
            assert len(native) == n + 1
            await unchanged()
            await bounded()
            await page.screenshot(path=str(evidence / f'{width}-selected-complete-original-find.png'))
            result['checks'].append({'case': 'selected header complete original Find', 'nativeThread': 'native-active',
                                     'initialLatestPage': '3 of 3, 85 native items',
                                     'exactTurnItemAndUnclippedMatch': True, 'visibleMatchGeometry': mark_geometry,
                                     'listOpenTaskPosts': 0, 'nativeReads': 1})
            await page.locator('#history-reader-back').click()
            assert await page.evaluate('document.activeElement.id') == 'read-original'
            await page.locator('#prompt').focus()
            await page.keyboard.press('F3')
            assert not await page.locator('#history-reader').evaluate('node=>node.open')
            await unchanged()

            # Keyboard entry from live evidence owns Return focus and never Latest.
            summary = page.locator('[data-item-id="live-command"] summary')
            await summary.evaluate('node=>node.parentElement.open=true')
            await page.locator('[data-item-id="live-command"] pre').evaluate('node=>node.scrollTop=250')
            await summary.evaluate('node=>node.focus({preventScroll:true})')
            await page.evaluate('window.scrollTo(0,200)')
            activity_scroll = await page.locator('[data-item-id="live-command"] pre').evaluate('node=>node.scrollTop')
            document_scroll = await page.evaluate('window.scrollY')
            h, n = len(http), len(native)
            await page.keyboard.press('F3')
            await ready()
            assert await page.evaluate('document.activeElement.id') == 'history-reader-find-query'
            desk.store.event('active', {'method': 'item/commandExecution/outputDelta', 'params': {
                'threadId': 'native-active', 'turnId': 'live-turn', 'itemId': 'live-command', 'delta': '\nLIVE DURING ORIGINAL READING'}})
            await page.evaluate('pollActivity()')
            assert await page.evaluate('window.scrollY') == document_scroll
            await page.locator('#history-reader-back').click()
            assert await summary.evaluate('node=>node===document.activeElement')
            assert await page.evaluate('window.scrollY') == document_scroll
            assert await page.locator('[data-item-id="live-command"] pre').evaluate('node=>node.scrollTop') == activity_scroll
            assert await summary.evaluate('node=>node.parentElement.open')
            assert await page.evaluate('latestUpdates') > 0
            read_only_since(h, n)
            await unchanged()
            result['checks'].append({'case': 'F3 live activity Return focus and scroll', 'liveUpdatesRetainedNotAutoLatest': True})

            # Held Refresh commits the editor/window at response, not at click.
            await page.locator('#read-original').click()
            await ready()
            await find(old_phrase)
            target = page.locator('.history-reader-item[data-item-id="active-command"]')
            initial_window = await target.get_attribute('data-window-start')
            initial_scroll = await target.locator('pre').evaluate('node=>node.scrollTop')
            entered, release = held()
            h, n = len(http), len(native)
            await page.locator('#history-reader-refresh').click()
            assert await asyncio.to_thread(entered.wait, 10)
            await page.locator('#history-reader-refresh').press('Enter')
            assert len(native) == n + 1
            await page.locator('#history-reader-find-query').fill('Later unsent phrase')
            assert await target.get_attribute('data-window-start') == initial_window
            assert await target.locator('pre').evaluate('node=>node.scrollTop') == initial_scroll
            assert await target.evaluate('node=>node.open')
            await page.locator('#history-reader-find-query').fill(old_phrase)
            assert await target.get_attribute('data-window-start') == initial_window
            assert await target.locator('pre').evaluate('node=>node.scrollTop') == initial_scroll
            await target.get_by_role('button', name='Earlier text', exact=True).click()
            expected_window = await target.get_attribute('data-window-start')
            await target.locator('pre').evaluate('node=>node.scrollTop=100')
            await page.locator('#history-reader-find-query').focus()
            await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            glyph_before=await source_glyph()
            threads['native-active']['turns'][0]['items'].append({'id': 'fresh-native-evidence', 'type': 'agentMessage',
                'text': 'FRESH NATIVE ORIGINAL RESULT from explicit Refresh'})
            release.set()
            await refreshed()
            holds.pop('native-active')
            assert await page.locator('#history-reader-find-query').input_value() == old_phrase
            assert await page.evaluate('document.activeElement.id') == 'history-reader-find-query'
            assert await target.get_attribute('data-window-start') == expected_window
            await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            glyph_after=await source_glyph()
            result['held_glyph_probe']={'before':glyph_before,'after':glyph_after,'pixel100':glyph_after['inner']==100,'native_character_exact':glyph_before['first_visible'] and glyph_after['first_visible'] and glyph_before['first_visible']['offset']==glyph_after['first_visible']['offset']}
            (evidence/f'held-glyph-{width}.json').write_text(json.dumps(result['held_glyph_probe'],indent=2)+'\n')
            await page.screenshot(path=str(evidence/f'{width}-held-refreshed-glyph.png'))

            assert glyph_before['first_visible'] and glyph_after['first_visible'],result['held_glyph_probe']
            assert glyph_after['first_visible']['offset']==glyph_before['first_visible']['offset'],result['held_glyph_probe']
            assert glyph_after['first_visible']['char']==glyph_before['first_visible']['char'],result['held_glyph_probe']
            assert await page.locator('#history-reader-find-next').is_disabled()
            assert len(native) == n + 1
            await find('FRESH NATIVE ORIGINAL RESULT')
            assert await page.locator('.history-reader-target').get_attribute('data-item-id') == 'fresh-native-evidence'
            assert await page.locator('.history-reader-target mark').inner_text() == 'FRESH NATIVE ORIGINAL RESULT'
            await visible_match()
            read_only_since(h, n)
            await unchanged()
            result['checks'].append({'case': 'held Refresh latest A-B-A unsent query and text window', 'nativeReads': 1,
                                     'queryEditsKeepExactWindowDisclosureAndScroll': True, 'AtoBtoANotAutoSearched': True,
                                     'explicitNewOriginalEvidenceFindable': True})

            # Failed Refresh keeps the successful snapshot, exact query and match.
            before_text = await page.locator('#history-reader-body').inner_text()
            failures.add('native-active')
            await page.locator('#history-reader-refresh').click()
            await refreshed()
            assert await page.locator('#history-reader-error').is_visible()
            assert await page.locator('#history-reader-body').inner_text() == before_text
            assert await page.locator('#history-reader-find-query').input_value() == 'FRESH NATIVE ORIGINAL RESULT'
            assert await page.locator('.history-reader-target').get_attribute('data-item-id') == 'fresh-native-evidence'
            failures.remove('native-active')
            await page.locator('#history-reader-retry').click()
            await refreshed()
            assert await page.locator('#history-reader-error').is_hidden()
            assert await page.locator('.history-reader-target').get_attribute('data-item-id') == 'fresh-native-evidence'
            result['checks'].append({'case': 'failed Refresh retains original then explicit Retry', 'exactSnapshotQueryMatch': True})

            # A vanished visible native item must not become a different occurrence.
            threads['native-active']['turns'][0]['items'] = [{'id': 'replacement-evidence', 'type': 'agentMessage',
                'text': 'FRESH NATIVE ORIGINAL RESULT in a different item'}]
            await page.locator('#history-reader-refresh').click()
            await refreshed()
            assert await page.locator('.history-reader-target').count() == 0
            assert 'no longer' in await page.locator('#history-reader-status').inner_text()
            assert 'previous occurrence' in await page.locator('#history-reader-find-status').inner_text()
            await bounded()
            result['checks'].append({'case': 'vanished native item does not substitute a new match', 'explicitNavigationRequired': True})

            # Close and newer selection invalidate held native replies.
            for case in ('close', 'newer-selection'):
                entered, release = held()
                await page.locator('#history-reader-refresh').click()
                assert await asyncio.to_thread(entered.wait, 10)
                await page.locator('#history-reader-close').click()
                if case == 'newer-selection':
                    await select('newer')
                    await page.locator('#read-original').click()
                    await ready()
                    await page.locator('#history-reader-find-query').fill('Exact newer reader query')
                done = len(responses)
                release.set()
                if case == 'close':
                    await page.wait_for_function('!$("read-original").disabled')
                for _ in range(100):
                    if len(responses) > done:
                        break
                    await asyncio.sleep(.02)
                assert len(responses) > done
                await asyncio.sleep(.1)
                holds.pop('native-active')
                if case == 'close':
                    assert not await page.locator('#history-reader').evaluate('node=>node.open')
                    await page.locator('#read-original').click()
                    await ready()
                else:
                    assert 'native-newer' in await page.locator('#history-reader-binding').inner_text()
                    assert await page.locator('#history-reader-find-query').input_value() == 'Exact newer reader query'
                    await unchanged('newer')
                result['checks'].append({'case': case + ' ignores held Refresh reply', 'noOldReopenOrNewReaderReplacement': True})

            # Existing folder loss and failed native attachment retain direct read.
            for key in ('removed', 'failed-open'):
                await select(key)
                h, n = len(http), len(native)
                if key == 'removed':
                    assert not removed.exists()
                else:
                    assert await page.locator('#error').is_visible()
                failures.add('native-' + key)
                await page.locator('#read-original').click()
                await ready()
                assert await page.locator('#history-reader-retry').is_visible()
                failures.remove('native-' + key)
                await page.locator('#history-reader-retry').click()
                await ready()
                assert 'native-' + key in await page.locator('#history-reader-binding').inner_text()
                assert await page.locator('#history-reader-error').is_hidden()
                read_only_since(h, n)
                assert load_draft(desk.store, key) == original_drafts[key]
                assert followup_snapshot(desk.store, key) == original_queues[key]
                if key == 'removed':
                    await unchanged(key)
                result['checks'].append({'case': key + ' selected binding original Retry', 'readWithoutResumeOrFolderCreation': True})

            # Same origin/state cold return restores Plan/queues and direct original.
            await select('active')
            await unchanged()
            stop_server()
            desk = Desk('not-executed', home, state_dir)
            server, worker = start_server(port)
            await page.reload()
            await page.wait_for_function('selected==="active" && !opening && !$("read-original").disabled')
            await unchanged()
            h, n = len(http), len(native)
            await page.locator('#read-original').click()
            await ready()
            await find('FRESH NATIVE ORIGINAL RESULT')
            assert await page.locator('.history-reader-target').get_attribute('data-item-id') == 'replacement-evidence'
            await visible_match()
            read_only_since(h, n)
            await unchanged()
            await bounded()
            await page.screenshot(path=str(evidence / f'{width}-cold-selected-original.png'))
            result['checks'].append({'case': 'cold same-port state selected original', 'samePort': port,
                                     'exactPlanAndTwoPausedModes': True, 'nativeTaskPostsDuringRead': 0})
            assert not result['javascriptErrors'], result['javascriptErrors']
        finally:
            for entered, release in holds.values():
                release.set()
            await context.close()
            stop_server()
            result['nativeCalls'] = native
            result['http'] = http
            (evidence / f'result-{width}.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result), flush=True)
    return result


async def check():
    root, evidence = Path(os.environ['DESK_TEST_TEMP']), Path(os.environ['DESK_TEST_EVIDENCE'])
    root.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                                                  args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            results = [await acceptance(browser, width, root, evidence) for width in (390, 1250)]
            (evidence / 'result.json').write_text(json.dumps({'cases': results}, indent=2) + '\n')
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(check())
