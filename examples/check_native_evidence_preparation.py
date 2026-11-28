#!/usr/bin/env python3
"""Installed A→existing unsent B→exact A evidence workflow at 1250/390.

Uses the maintained synthetic native transport/SQLite fixture from task-response
acceptance. No native executable, source import or model task is admitted.
"""
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import traceback
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

SPEC = importlib.util.spec_from_file_location('native_response_fixture', Path(__file__).with_name('check_native_task_response.py'))
base = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(base)
from codex_desk.drafts import load_draft
from codex_desk.followups import followup_snapshot, edit_followup, reserve_followup
from playwright.async_api import async_playwright

SOURCE, TURN, ITEM = 'source-A', 'source-command-turn', 'source-long-command'
QUOTE = 'DECISIVE retry budget — café🙂 retained exactly.'
OUTPUT = 'ORIGINAL OUTPUT START\n' + '\n'.join(
    f'Original command line {i:04d}: retained source reasoning and retry evidence.' +
    (' ' + QUOTE if i in (50, 1300) else '') for i in range(1800)) + '\nORIGINAL OUTPUT END'


def source_thread(folder):
    return {'id': SOURCE, 'cwd': str(folder), 'name': 'Source A retry budget', 'source': 'cli',
            'modelProvider': 'fixture-provider', 'updatedAt': 1795800000,
            'turns': [{'id': TURN, 'status': 'failed', 'items': [
                {'id': 'source-proposed-plan', 'type': 'plan', 'text': 'Clarify the proposed retry policy before changing the queue.'},
                {'id': ITEM, 'type': 'commandExecution', 'command': 'fixture inspect retry budget', 'cwd': str(folder),
                 'reason': 'Read the native retry evidence', 'status': 'completed', 'exitCode': 1, 'aggregatedOutput': OUTPUT},
                {'id': 'source-commentary', 'type': 'agentMessage', 'phase': 'commentary',
                 'text': 'Commentary keeps the failed check visible; this is not an accepted plan.'}]}]}


async def one(browser, width, root, evidence):
    r = {'width': width, 'passed': False, 'checks': []}; http, errors, external = [], [], []
    with tempfile.TemporaryDirectory(dir=root, prefix=f'evidence-preparation-{width}-') as temporary:
        f = base.Fixture(Path(temporary)); context = None
        folder = Path(temporary) / 'removed-source-A'; folder.mkdir(); f.threads[SOURCE] = source_thread(folder); folder.rmdir()
        original = copy.deepcopy(f.threads[SOURCE]); namespace = hashlib.sha256(str(f.home.resolve()).encode()).hexdigest()

        class Catalog:
            def request(self, method, params, timeout=30):
                if method == 'thread/read':
                    return f.reader_type('never-executed', f.home, f.state).request(method, params, timeout)
                assert method == 'thread/list', method
                f.calls.append({'method': method, 'params': copy.deepcopy(params)})
                row = {k: v for k, v in original.items() if k != 'turns'}
                search = params.get('searchTerm', '').casefold()
                return {'data': [row] if search in row['name'].casefold() else [], 'nextCursor': None}

        f.catalog_type = Catalog
        preparation = f.prepared(); source_sql = None
        with patch.object(base.product, '_NativeReader', f.reader_type), patch.object(
                base.product, 'Runtime', side_effect=AssertionError('Task runtime forbidden')):
            try:
                context = await browser.new_context(viewport={'width': width, 'height': 900 if width > 390 else 844})
                page = await context.new_page(); page.set_default_timeout(12000)
                page.on('pageerror', lambda e: errors.append(str(e)))

                async def isolated(route):
                    if urlsplit(route.request.url).hostname != '127.0.0.1':
                        external.append(route.request.url); await route.abort()
                    else:
                        await route.continue_()

                await context.route('**/*', isolated)
                page.on('request', lambda q: http.append({'method': q.method, 'path': urlsplit(q.url).path, 'query': parse_qs(urlsplit(q.url).query)}))

                async def ready():
                    await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
                    await base.frames(page)

                def target():
                    return page.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"]')

                async def checkpoint(name):
                    assert not errors and not external, (errors, external)
                    assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)"), name + ' overflow'
                    assert f.desk.runtimes == {} and not f.desk.store.get(SOURCE)
                    assert followup_snapshot(f.desk.store, base.ORIGINAL) == preparation[base.ORIGINAL]['queue']
                    assert f.prepared()[base.OTHER] == preparation[base.OTHER]
                    assert await page.evaluate('selected') == base.ORIGINAL
                    assert await page.locator('#turn-mode').input_value() == 'plan'
                    r['checks'].append(name); await page.screenshot(path=str(evidence / f'{width}-{name}.png'))

                async def close_reader():
                    await page.locator('#history-reader-back').click()
                    await page.wait_for_function("!$('history-reader').open")
                    if await page.locator('#history').evaluate('n=>n.open'):
                        await page.locator('#history-close').click()
                    await base.frames(page)

                await page.goto(f'http://127.0.0.1:{f.server.server_port}/')
                await page.locator(f'.session-row[data-session="{base.ORIGINAL}"] .session').click()
                await page.wait_for_function('id=>selected===id&&!opening', arg=base.ORIGINAL)
                initial_view = await page.evaluate("({selected,nativeThreadId,generation,text:$('prompt').value,mode:$('turn-mode').value})")
                source_sql = f.sql(); calls_before = len(f.calls)
                await page.locator('#browse').click()
                await page.wait_for_function("$('history').open && $('native-list').querySelector('.native-read')")
                await page.locator('#native-list .native-read').click(); await ready()
                assert f.sql() == source_sql
                assert await page.evaluate("({selected,nativeThreadId,generation,text:$('prompt').value,mode:$('turn-mode').value})") == initial_view
                assert any(x['method'] == 'thread/read' and x['params']['threadId'] == SOURCE for x in f.calls[calls_before:])
                await checkpoint('read-removed-source-A-with-existing-B-unchanged')

                await page.locator('#history-reader-find-query').fill(QUOTE)
                await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')")
                await page.keyboard.press('F3')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
                await base.frames(page)
                assert int(await target().get_attribute('data-window-start')) > 20000
                await target().locator('mark').evaluate("n=>{const r=document.createRange();r.selectNodeContents(n);const s=getSelection();s.removeAllRanges();s.addRange(r)}")
                assert await page.evaluate('getSelection().toString()') == QUOTE
                source_view = await target().evaluate("n=>({start:n.dataset.windowStart,scroll:n.querySelector('pre').scrollTop,selection:getSelection().toString()})")
                calls_before, boundary = len(f.calls), len(http)
                await target().locator('.history-reader-review-evidence').click()
                await page.wait_for_function("$('evidence-preparation').open && !DeskEvidencePreparation.state().pending")
                reviewed = await page.evaluate('DeskEvidencePreparation.state()')
                assert reviewed['reference']['quote'] == QUOTE and reviewed['reference']['native_home'] == namespace
                assert reviewed['reference']['thread_id'] == SOURCE and reviewed['reference']['turn_id'] == TURN and reviewed['reference']['item_id'] == ITEM
                projection = 'Command\nfixture inspect retry budget\nStatus: completed\nExit: 1\n' + OUTPUT
                expected_start = OUTPUT.rfind(QUOTE)
                assert reviewed['reference']['projection'] == 'history-reader-command-output/v1'
                assert reviewed['reference']['quote_start'] == expected_start
                assert reviewed['reference']['quote_end'] == expected_start + len(QUOTE)
                assert 'commandExecution' in await page.locator('#evidence-preparation-source').inner_text()
                assert 'fixture inspect retry budget' in await page.locator('#evidence-preparation-source').inner_text()
                assert 'Reported exit code: 1' in await page.locator('#evidence-preparation-source').inner_text()
                assert reviewed['destination']['session'] == base.ORIGINAL and reviewed['destination']['mode'] == 'plan'
                assert await page.locator('#evidence-preparation-quote').text_content() == QUOTE
                assert f.calls[calls_before:] == [] and f.sql() == source_sql
                assert [x for x in http[boundary:] if x['path'] == '/api/native/home']
                await checkpoint('exact-later-window-quote-source-facts-destination-review')

                # Cancel restores source selection/window and cannot save anything.
                await page.locator('#evidence-preparation-cancel').click()
                await page.wait_for_function("!$('evidence-preparation').open")
                assert await target().evaluate("n=>({start:n.dataset.windowStart,scroll:n.querySelector('pre').scrollTop,selection:getSelection().toString()})") == source_view
                assert f.sql() == source_sql
                await target().locator('.history-reader-review-evidence').click()
                await page.wait_for_function("$('evidence-preparation').open && !DeskEvidencePreparation.state().pending")
                await page.locator('#evidence-preparation-note').fill('Inspect the retry budget before the next edit.')
                native_boundary, boundary = len(f.calls), len(http)
                await page.locator('#evidence-preparation-append').click()
                await page.wait_for_function("!$('evidence-preparation').open")
                await page.wait_for_function("$('draft-status').textContent.includes('saved') || $('draft-status').textContent.includes('Saved')")
                saved = load_draft(f.desk.store, base.ORIGINAL)
                assert saved['text'].startswith(preparation[base.ORIGINAL]['draft']['text'] + '\n\nNext-step note:')
                assert saved['mode'] == 'plan' and saved['revision'] == preparation[base.ORIGINAL]['draft']['revision'] + 1
                assert saved['text'].count('<!-- codex-desk-evidence:v1 ') == 1
                parsed = await page.evaluate('DeskEvidencePreparation.parse($("prompt").value)')
                assert len(parsed) == 1 and parsed[0]['reference'] == reviewed['reference']
                assert f.calls[native_boundary:] == []
                assert [x['path'] for x in http[boundary:] if x['method'] == 'POST'] == ['/api/draft']
                for table, rows in source_sql.items():
                    if table != 'drafts':
                        assert f.sql()[table] == rows, table
                await close_reader(); await checkpoint('reviewed-source-appended-once-existing-plan-two-queues-intact')

                # Actual stored-draft action reveals the second identical phrase,
                # not its earlier equal occurrence, then returns exact editor view.
                if not await page.locator('#draft-evidence').evaluate('n=>n.open'):
                    await page.locator('#draft-evidence > summary').click()
                await page.locator('#draft-evidence-list button').scroll_into_view_if_needed()
                await page.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(12,30,'backward');n.scrollTop=45}")
                await base.frames(page)
                owner_view = await page.evaluate("({text:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,window:scrollY})")
                before, boundary, native_boundary = f.sql(), len(http), len(f.calls)
                await page.locator('#draft-evidence-list button').focus()
                await page.locator('#draft-evidence-list button').press('Enter'); await ready()
                assert await target().locator('mark').text_content() == QUOTE
                target_start = int(await target().get_attribute('data-window-start'))
                expected_utf16 = len(projection[:projection.rfind(QUOTE)].encode('utf-16-le')) // 2
                assert expected_utf16 - 11000 <= target_start <= expected_utf16
                assert await page.locator('#history-reader-saved-evidence-quote').text_content() == QUOTE
                assert 'still at this exact' in await page.locator('#history-reader-response').inner_text()
                assert f.sql() == before
                assert f.calls[native_boundary:] == [{'method': 'thread/read', 'params': {'threadId': SOURCE, 'includeTurns': True}}]
                assert not [x for x in http[boundary:] if x['path'] in ('/api/native/thread', '/api/open') or x['method'] != 'GET']
                await checkpoint('saved-preparation-reopens-exact-second-occurrence-read-only')
                await close_reader()
                after_view = await page.evaluate("({text:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,window:scrollY})")
                assert after_view == owner_view, (owner_view, after_view)
                assert await page.evaluate('document.activeElement.id') == 'prompt'
                await checkpoint('source-return-exact-unsent-editor-caret-scroll-mode')

                # Lost/changed original never consumes an equal phrase as replacement.
                for unavailable in ('changed', 'missing'):
                    f.threads[SOURCE] = copy.deepcopy(original)
                    if unavailable == 'changed':
                        command = f.threads[SOURCE]['turns'][0]['items'][1]
                        at = command['aggregatedOutput'].rfind(QUOTE)
                        command['aggregatedOutput'] = command['aggregatedOutput'][:at] + 'X' + command['aggregatedOutput'][at + 1:]
                    else:
                        f.threads[SOURCE]['turns'][0]['items'].pop(1)
                    before = f.sql(); await page.locator('#draft-evidence-list button').click(); await ready()
                    expected = 'quote_changed' if unavailable == 'changed' else 'source_unavailable'
                    assert expected in await page.locator('#history-reader-response').inner_text()
                    assert 'No other item or occurrence' in await page.locator('#history-reader-response').inner_text()
                    assert await page.locator('#history-reader-saved-evidence-quote').text_content() == QUOTE
                    assert await page.locator('#history-reader-body mark').count() == 0
                    assert f.sql() == before and load_draft(f.desk.store, base.ORIGINAL) == saved
                    await checkpoint(unavailable + '-source-saved-excerpt-kept-no-substitution')
                    await close_reader()
                f.threads[SOURCE] = copy.deepcopy(original)

                # Explicit retry preserves target; different native home rejects
                # before any read without altering its retained preparation.
                f.failures.add(SOURCE); before, boundary = f.sql(), len(http)
                await page.locator('#draft-evidence-list button').click()
                await page.wait_for_function("!$('draft-evidence-list').querySelector('button').disabled && $('draft-evidence-status').textContent.includes('unavailable')")
                assert not await page.locator('#history-reader').evaluate('n=>n.open')
                f.failures.clear(); await page.locator('#draft-evidence-list button').click(); await ready()
                assert len([x for x in http[boundary:] if x['path'] == '/api/native/evidence-source']) == 2
                assert f.sql() == before; await close_reader()
                old_home = f.desk.home; other_home = Path(temporary) / 'different-native-home'; other_home.mkdir(); f.desk.home = other_home
                before, native_boundary = f.sql(), len(f.calls)
                await page.locator('#draft-evidence-list button').click()
                await page.wait_for_function("!$('draft-evidence-list').querySelector('button').disabled && $('draft-evidence-status').textContent.toLowerCase().includes('home')")
                assert not await page.locator('#history-reader').evaluate('n=>n.open')
                assert f.calls[native_boundary:] == [] and f.sql() == before
                f.desk.home = old_home
                await checkpoint('source-failure-exact-retry-native-home-mismatch-keeps-preparation')

                # Ordinary same browser/server/SQLite restart retains the artifact;
                # startup performs no referenced-source read or source task action.
                port, before = f.server.server_port, f.sql()
                f.stop(); f.start(port); f.emitter.store = f.desk.store
                assert f.sql() == before
                boundary = len(http); await page.reload()
                await page.wait_for_function('id=>selected===id&&!opening&&!$("draft-evidence").hidden', arg=base.ORIGINAL)
                assert load_draft(f.desk.store, base.ORIGINAL) == saved
                assert await page.locator('#prompt').input_value() == saved['text']
                assert not [x for x in http[boundary:] if x['path'] == '/api/native/evidence-source']
                if not await page.locator('#draft-evidence').evaluate('n=>n.open'):
                    await page.locator('#draft-evidence > summary').click()
                await page.locator('#draft-evidence-list button').click(); await ready()
                assert await target().locator('mark').text_content() == QUOTE
                await close_reader(); await checkpoint('same-state-cold-return-retains-artifact-no-auto-source-read')
                assert all(x['method'] in ('thread/list', 'thread/read') for x in f.calls)
                assert not [x for x in http if x['method'] == 'POST' and x['path'] not in ('/api/open', '/api/draft')]
                assert f.opens == [base.ORIGINAL, base.ORIGINAL], f.opens
                assert {p: p.read_bytes() for p in f.protected} == f.protected
                # Prepared-only B keeps the independently selected task in place.
                task_before = await page.evaluate("({selected,nativeThreadId,generation,text:$('prompt').value,mode:$('turn-mode').value})")
                prepared_before = f.prepared()
                await page.locator('#show-preparation').click()
                review_b = page.locator(f'#preparation-list button[data-session="{base.OTHER}"][data-control="review"]')
                await review_b.click()
                await page.wait_for_function("!$('preparation-text').disabled")
                await page.locator('#preparation-mode').select_option('plan')
                await page.locator('#preparation-save').click()
                await page.wait_for_function("$('preparation-draft-status').textContent.includes('saved locally')")
                prepared_saved = load_draft(f.desk.store, base.OTHER)
                before = f.sql(); boundary = len(http)
                await page.locator('#preparation-browse-evidence').click()
                await page.wait_for_function("$('history').open && $('native-list').querySelector('.native-read')")
                await page.locator('#native-list .native-read').click(); await ready()
                assert f.sql() == before
                item = page.locator('.history-reader-item[data-item-id="source-proposed-plan"]')
                if not await item.evaluate('n=>n.open'):
                    await item.locator('summary').click()
                await item.locator('.history-reader-review-evidence').click()
                await page.wait_for_function("DeskEvidencePreparation.state()?.status==='review'")
                captured_b = await page.evaluate('DeskEvidencePreparation.state()')
                assert captured_b['destination']['session'] == base.OTHER
                assert captured_b['destination']['kind'] == 'prepared'
                assert captured_b['destination']['text'] == prepared_saved['text']
                assert captured_b['destination']['mode'] == 'plan'
                assert captured_b['reference']['source_kind'] == 'plan'
                await page.locator('#evidence-preparation-append').click()
                await page.wait_for_function("!$('evidence-preparation').open")
                await close_reader()
                b_saved = load_draft(f.desk.store, base.OTHER)
                assert b_saved['text'].startswith(prepared_saved['text']+'\n\n')
                assert b_saved['mode'] == 'plan' and b_saved['revision'] == prepared_saved['revision']+1
                assert f.prepared()[base.ORIGINAL] == prepared_before[base.ORIGINAL]
                assert followup_snapshot(f.desk.store, base.OTHER) == prepared_before[base.OTHER]['queue']
                assert await page.evaluate("({selected,nativeThreadId,generation,text:$('prompt').value,mode:$('turn-mode').value})") == task_before
                assert not [q for q in http[boundary:] if q['method']=='POST' and q['path']!='/api/draft']
                assert not errors and not external
                r['checks'].append('prepared-only-existing-B-plan-append-keeps-different-current-task')
                await page.screenshot(path=str(evidence / f'{width}-prepared-only-append.png'))
                # This saved row's source return preserves its exact independent editor.
                await page.locator('#preparation-text').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(4,18,'backward');n.scrollTop=25}")
                pview = await page.evaluate("({text:$('preparation-text').value,mode:$('preparation-mode').value,start:$('preparation-text').selectionStart,end:$('preparation-text').selectionEnd,direction:$('preparation-text').selectionDirection,scroll:$('preparation-text').scrollTop})")
                before = f.sql()
                await page.locator('#preparation-evidence-list button').click(); await ready()
                assert await page.locator('.history-reader-target').get_attribute('data-item-id') == 'source-proposed-plan'
                assert await page.locator('#history-reader-saved-evidence-quote').text_content() == captured_b['reference']['quote']
                assert f.sql() == before
                await page.locator('#history-reader-back').click(); await base.frames(page)
                assert await page.evaluate("({text:$('preparation-text').value,mode:$('preparation-mode').value,start:$('preparation-text').selectionStart,end:$('preparation-text').selectionEnd,direction:$('preparation-text').selectionDirection,scroll:$('preparation-text').scrollTop})") == pview
                assert await page.evaluate("({selected,nativeThreadId,generation,text:$('prompt').value,mode:$('turn-mode').value})") == task_before
                r['checks'].append('prepared-row-source-return-exact-editor-keeps-current-task')
                await page.screenshot(path=str(evidence / f'{width}-prepared-only-return.png'))
                # Existing queue and captured reservation carry the same readable
                # artifact; actual source controls do not send either instruction.
                entries = followup_snapshot(f.desk.store, base.OTHER)['entries']
                entry = entries[0]
                edit_followup(f.desk.store, base.OTHER, entry['id'], b_saved['text'], 'plan', entry['revision'])
                await page.locator('#preparation-refresh').click()
                await page.wait_for_function("!$('preparation-list').hasAttribute('data-unused') && !$('preparation-browse-evidence').disabled")
                before = f.sql()
                await page.locator('#preparation-followups button[data-control="read-evidence"]').first.click(); await ready()
                assert await page.locator('#history-reader-saved-evidence-quote').text_content() == captured_b['reference']['quote']
                assert f.sql() == before
                await page.locator('#history-reader-back').click(); await base.frames(page)
                r['checks'].append('saved-queued-instruction-source-read-does-not-send-or-alter-B')
                entry = followup_snapshot(f.desk.store, base.OTHER)['entries'][0]
                reserve_followup(f.desk.store, base.OTHER, entry['id'], entry['revision'])
                await page.locator('#preparation-refresh').click()
                await page.wait_for_function("!$('preparation-browse-evidence').disabled")
                before = f.sql()
                await page.locator('#preparation-followups button[data-control="read-evidence"]').first.click(); await ready()
                assert await page.locator('#history-reader-saved-evidence-quote').text_content() == captured_b['reference']['quote']
                assert f.sql() == before
                await page.locator('#history-reader-back').click(); await base.frames(page)
                assert load_draft(f.desk.store, base.OTHER) == b_saved
                r['checks'].append('captured-reservation-reference-read-keeps-exact-instruction')
                await page.locator('#preparation-close').click()
                # The subsequently supplied native instruction keeps the same
                # reference; follow it and Back without losing that source view.
                sent_item = {'id':'fixture-sent-evidence-instruction','type':'userMessage',
                             'content':[{'type':'text','text':b_saved['text']}]}
                f.threads[base.PARENT]['turns'].append({'id':'fixture-sent-evidence-turn','status':'completed','items':[sent_item]})
                await page.locator('#read-original').click(); await ready()
                # Ordinary initial reader starts at the latest supplied native turn.
                sent = page.locator('.history-reader-item[data-item-id="fixture-sent-evidence-instruction"]')
                if not await sent.evaluate('n=>n.open'):
                    await sent.locator('summary').click()
                before = f.sql()
                await sent.locator('.history-reader-read-reference').click(); await ready()
                assert await page.locator('#history-reader-saved-evidence-quote').text_content() == captured_b['reference']['quote']
                assert await page.locator('.history-reader-target').get_attribute('data-item-id') == 'source-proposed-plan'
                assert f.sql() == before
                await page.locator('#history-reader-back').click(); await base.frames(page)
                await page.wait_for_function("$('history-reader').open && $('history-reader-binding').textContent.includes('native-parent') && $('history-reader-body').getAttribute('aria-busy')==='false'")
                assert await page.locator('.history-reader-item[data-item-id="fixture-sent-evidence-instruction"]').locator('.history-reader-text').text_content() == 'User\n'+b_saved['text']
                assert await page.evaluate("({selected,nativeThreadId,generation,text:$('prompt').value,mode:$('turn-mode').value})") == task_before
                await page.locator('#history-reader-back').click(); await base.frames(page)
                r['checks'].append('native-sent-instruction-reference-returns-to-its-own-original-view')
                assert not errors and not external
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                r.update(passed=True, http=http, native_calls=f.calls, javascript_errors=errors, namespace=namespace,
                         reviewed_reference=reviewed['reference'], native_admissions=0, owned_task_runtimes=0,
                         source_imports=0, two_queues_unchanged=True, existing_unsent_mode='plan')
            except Exception as error:
                r.update(error=str(error), traceback=traceback.format_exc(), http=http, native_calls=f.calls, javascript_errors=errors)
                if 'page' in locals():
                    try:
                        r['observed'] = await page.evaluate("({selected,opening,error:$('error').textContent,review:DeskEvidencePreparation.state(),status:$('draft-status').textContent,sourceStatus:$('draft-evidence-status').textContent,reader:$('history-reader').open,readerStatus:$('history-reader-status').textContent})")
                        await page.screenshot(path=str(evidence / f'{width}-failed.png'))
                    except Exception as diagnostic:
                        r['diagnostic_error'] = str(diagnostic)
            finally:
                if context:
                    await context.close()
                f.stop()
    (evidence / f'case-{width}.json').write_text(json.dumps(r, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: r[key] for key in ('width', 'passed', 'checks', 'error') if key in r}), flush=True)
    return r


async def main():
    root = Path(os.environ['DESK_TEST_TEMP']).resolve(); root.mkdir(parents=True, exist_ok=True)
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']).resolve(); evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                                          args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            rows = [await one(browser, width, root, evidence) for width in (1250, 390)]
        finally:
            await browser.close()
    summary = {'result': 'PASS' if all(x['passed'] for x in rows) else 'FAIL', 'package': str(base.PACKAGE),
               'version': base.codex_desk.__version__, 'installed': os.environ.get('DESK_USE_INSTALLED') == '1',
               'widths': [1250, 390], 'results': rows}
    (evidence / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: summary[key] for key in ('result', 'version', 'package', 'installed', 'widths')}), flush=True)
    for row in rows:
        if not row['passed']:
            print(row.get('traceback'), flush=True)
    if summary['result'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
