#!/usr/bin/env python3
"""Literal instruction matches → own supplied task/response → exact original passage at1250/390."""
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

SPEC = importlib.util.spec_from_file_location('task_context_fixture', Path(__file__).with_name('check_native_task_response.py'))
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
from codex_desk.drafts import load_draft, save_draft
from codex_desk.evidence_reference import make_evidence_block
from codex_desk.followups import add_followup, edit_followup, followup_snapshot, reserve_followup
from codex_desk.handoff import visible_text
from playwright.async_api import async_playwright

SOURCE, TURN, ITEM = 'task-source-A', 'historical-failed-task', 'historical-long-command'
CURRENT, CURRENT_THREAD = 'current-C', 'native-current-C'
FIRST, SECOND, FINAL = 'first-supplied-instruction', 'second-supplied-instruction', 'last-historical-final'
QUOTE = 'DECISIVE task context — Straße Café 项目 🚀 retained exactly.'
OUTPUT = 'ORIGINAL TOOL START\n' + '\n'.join(
    f'Native tool source line {i:04d}: exact supplied evidence — Café 项目 🚀' +
    (' ' + QUOTE if i in (100, 1450) else '') for i in range(1900)) + '\nORIGINAL TOOL END'
PROMPT = 'Inspect the retained retry policy without replacing the failed outcome.\n' + (
    'Full historical instruction: Café 项目 🚀 keep its exact wording.\n' * 16)
SECOND_PROMPT = 'Second supplied user instruction: read the command evidence before editing.\nRetain literal .*[retry] and Straße.\nCafé Straße .*[retry]'


def user(identifier, text):
    return {'id': identifier, 'type': 'userMessage', 'content': [{'type': 'text', 'text': text}]}


def source_thread(folder):
    items = [{'id': f'evidence-{i}', 'type': 'commandExecution', 'command': 'fixture inspect task',
              'status': 'completed', 'exitCode': 0, 'aggregatedOutput': f'Native historical evidence {i}'}
             for i in range(96)]
    items[0] = user(FIRST, PROMPT)
    items[1] = user(SECOND, SECOND_PROMPT)
    items[2] = {'id': 'image-only-user', 'type': 'userMessage', 'content': [{'type': 'image', 'url': 'retained-image'}]}
    items[3] = base.assistant('earlier-historical-final', 'EARLIER FINAL DOES NOT WIN', 'final_answer')
    items[45] = {'id': ITEM, 'type': 'commandExecution', 'command': 'fixture inspect task',
                 'status': 'completed', 'exitCode': 1, 'aggregatedOutput': OUTPUT}
    items[75] = base.assistant(FINAL, 'Same response text — exact historical final.', 'final_answer')
    items[80] = base.assistant('later-historical-commentary', 'LATER COMMENTARY DOES NOT WIN', 'commentary')
    jump_tasks = [{'id':f'jump-task-{i:02d}','status':'failed','error':{'message':f'Own jump-task-{i:02d} failure'},'items':[
        user(SECOND, ('Earlier supplied instruction line — Café 项目 🌱 exact.\n'*800)+'Café Straße .*[retry]'+f' own instruction {i:02d}'),
        base.assistant('jump-early-final', 'EARLY JUMP RESPONSE MUST NOT WIN', 'final_answer'),
        {'id':'jump-command','type':'commandExecution','command':'Café Straße .*[retry] ONLY TOOL NOT AN INSTRUCTION','aggregatedOutput':'Café Straße .*[retry]'},
        base.assistant(FINAL,f'OWN exact historical jump-task-{i:02d} final response.','final_answer'),
        base.assistant('jump-later-commentary','Café Straße .*[retry] ONLY RESPONSE NOT AN INSTRUCTION','commentary')]} for i in range(25)]
    duplicate = {'id': 'duplicate-turn', 'status': 'failed', 'items': [user('duplicate-prompt', 'Ambiguous instruction')]}
    return {'id': SOURCE, 'cwd': str(folder), 'name': 'Original task context A', 'modelProvider': 'fixture-provider',
            'turns': [
                {'id': 'earlier-historical-task', 'status': 'completed', 'items': [
                    user(FIRST, PROMPT), base.assistant(FINAL, 'Same response text — exact historical final.', 'final_answer')]},
                {'id': TURN, 'status': 'failed', 'error': {'message': 'Actual historical parser failure'}, 'items': items},
                {'id': 'outcome-only-task', 'status': 'interrupted', 'error': {'message': 'Actual native interruption'}, 'items': []},
                {'id': 'fallback-task', 'status': 'interrupted', 'items': [
                    user('fallback-instruction', SECOND_PROMPT),
                    base.assistant('fallback-first', 'Earlier fallback response', 'commentary'),
                    base.assistant('fallback-last', 'Actual last assistant text — unknown phase.', 'future_native_phase')]},
                duplicate, copy.deepcopy(duplicate),
                {'id': 'duplicate-item-task', 'status': 'completed', 'items': [
                    user('duplicate-item-instruction', 'Only same-turn supplied instruction'),
                    base.assistant('duplicate-response', 'Ambiguous response one', 'final_answer'),
                    base.assistant('duplicate-response', 'Ambiguous response two', 'final_answer')]},
                *jump_tasks,
                {'id': 'latest-source-task', 'status': 'completed', 'items': [
                    user('latest-instruction', 'LATEST INSTRUCTION MUST NOT REPLACE HISTORICAL'),
                    base.assistant('latest-final', 'LATEST SOURCE RESPONSE DOES NOT WIN', 'final_answer')]}]}


async def one(browser, width, root, evidence):
    report = {'width': width, 'passed': False, 'checks': []}
    http, errors, external = [], [], []
    with tempfile.TemporaryDirectory(dir=root, prefix=f'task-context-{width}-') as temporary:
        f = base.Fixture(Path(temporary))
        context = None
        f.threads[SOURCE] = source_thread(Path(temporary)/'removed-source-folder')
        source_before = copy.deepcopy(f.threads[SOURCE])
        f.threads[CURRENT_THREAD] = {'id': CURRENT_THREAD, 'cwd': str(f.project), 'name': 'Current C independent task',
            'turns': [{'id': 'current-C-completed', 'status': 'completed', 'items': [
                base.assistant('current-C-answer', 'Current C stays selected', 'final_answer')]}]}
        f.desk.store.create(str(f.project), 'default', identifier=CURRENT, name='Current C independent task')
        f.desk.store.update(CURRENT, thread_id=CURRENT_THREAD, status='ready', thread_saved=1,
                            name_pending=0, mode='plan', model='fixture-model', provider='fixture-provider')
        f.desk.store.recall_snapshot(CURRENT, f.threads[CURRENT_THREAD])
        save_draft(f.desk.store, CURRENT, 'Current C unsent Plan — separate from source A and saved B.\n保留 exactly.', 'plan', 0)
        add_followup(f.desk.store, CURRENT, 'Current C retained Work queue', 'native')
        add_followup(f.desk.store, CURRENT, 'Current C retained Plan queue', 'plan')
        projection = visible_text(f.threads[SOURCE]['turns'][1]['items'][45])
        at = projection.rfind(QUOTE)
        block = make_evidence_block(f.threads[SOURCE],
            native_home=hashlib.sha256(str(f.home.resolve()).encode()).hexdigest(),
            thread_id=SOURCE, turn_id=TURN, item_id=ITEM, quote_start=at, quote_end=at+len(QUOTE),
            text_for_item=visible_text, expected_quote=QUOTE)
        entries = followup_snapshot(f.desk.store, base.ORIGINAL)['entries']
        saved = edit_followup(f.desk.store, base.ORIGINAL, entries[0]['id'], 'Captured B instruction\n\n'+block,
                              'plan', entries[0]['revision'])
        reserve_followup(f.desk.store, base.ORIGINAL, saved['id'], saved['revision'])
        queued = edit_followup(f.desk.store, base.ORIGINAL, entries[1]['id'], 'Queued B original source\n\n'+block,
                               'plan', entries[1]['revision'])
        preparation = {sid: {'draft': load_draft(f.desk.store, sid), 'queue': followup_snapshot(f.desk.store, sid)}
                       for sid in (base.ORIGINAL, base.OTHER, CURRENT)}
        with patch.object(base.product, '_NativeReader', f.reader_type), patch.object(
                base.product, 'Runtime', side_effect=AssertionError('Unexpected task admission')):
            try:
                context = await browser.new_context(viewport={'width': width, 'height': 900 if width > 390 else 844})
                # Exercise intentional Refresh and explicit activity polling independently.
                await context.add_init_script("""(()=>{const later=window.setTimeout;window.setTimeout=function(callback,...args){
                    if(callback?.name==='tick')return 0;return later.call(this,callback,...args);};})();""")
                page = await context.new_page()
                page.set_default_timeout(12000)
                page.on('pageerror', lambda error: errors.append(str(error)))

                async def isolated(route):
                    if urlsplit(route.request.url).hostname != '127.0.0.1':
                        external.append(route.request.url)
                        await route.abort()
                    else:
                        await route.continue_()

                await context.route('**/*', isolated)
                page.on('request', lambda request: http.append({'path': urlsplit(request.url).path,
                    'method': request.method, 'query': parse_qs(urlsplit(request.url).query)}))
                await page.goto(f'http://127.0.0.1:{f.server.server_port}/')
                await page.locator(f'.session-row[data-session="{CURRENT}"] .session').click()
                await page.wait_for_function('id=>selected===id&&!opening', arg=CURRENT)
                await page.wait_for_function("!$('home-list').getAttribute('aria-busy') || $('home-list').getAttribute('aria-busy')==='false'")
                main = await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
                baseline = f.sql()

                def target(turn=TURN, item=ITEM):
                    return page.locator(f'.history-reader-item[data-turn-id="{turn}"][data-item-id="{item}"]')

                def action(name):
                    return page.locator(f'#history-reader-body [data-task-action="{name}"]')

                async def ready():
                    await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
                    await base.frames(page)

                async def checkpoint(name):
                    assert not errors and not external, (errors, external)
                    assert f.sql() == baseline, name+' changed SQL'
                    assert f.desk.runtimes == {}
                    assert await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})") == main
                    assert {sid: {'draft': load_draft(f.desk.store, sid), 'queue': followup_snapshot(f.desk.store, sid)}
                            for sid in preparation} == preparation
                    assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)"), name+' overflow'
                    assert await page.locator('.history-reader-text').evaluate_all('nodes=>nodes.every(n=>n.textContent.length<=20000)')
                    report['checks'].append(name)
                    await page.screenshot(path=str(evidence/f'{width}-{name}.png'))

                await page.locator('#show-preparation').click()
                await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
                await page.get_by_role('button', name='Review preparation in Saved '+base.ORIGINAL, exact=True).click()
                await page.wait_for_function("!$('preparation-save').disabled")
                unsaved = 'Unsent local B review remains separate.\n' + 'Retained unsaved café 项目.\n'*18
                await page.locator('#preparation-text').fill(unsaved)
                await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(12,38,'backward');n.scrollTop=70}")

                async def editor():
                    return await page.locator('#preparation-text').evaluate("n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})")

                pending = await editor()
                saved_control = page.locator(f'.preparation-followup[data-followup="{queued["id"]}"] button[data-control="read-evidence"]')
                native_before, boundary = len(f.calls), len(http)
                await saved_control.click()
                await ready()
                assert await target().locator('mark').text_content() == QUOTE
                assert await page.locator('#history-reader-back').inner_text() == 'Return to Prepared work'
                assert f.calls[native_before:] == [{'method': 'thread/read', 'params': {'threadId': SOURCE, 'includeTurns': True}}]
                assert [q['path'] for q in http[boundary:] if q['path'].startswith('/api/native/')] == ['/api/native/evidence-source']
                await page.locator('#history-reader-find-query').fill(QUOTE)
                await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')")
                await page.locator('#history-reader-find-next').click()
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
                await base.frames(page)
                assert int(await target().get_attribute('data-window-start')) > 20000
                assert await target().locator('mark').text_content() == QUOTE
                assert 'Page 2 of' in await page.locator('#history-reader-coverage').inner_text()
                rects=await target().locator('mark').evaluate("n=>[...n.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))")
                first,last=rects[0],rects[-1]
                await page.mouse.move(last['right']-.5,(last['top']+last['bottom'])/2);await page.mouse.down()
                await page.mouse.move(first['left']+.5,(first['top']+first['bottom'])/2,steps=12);await page.mouse.up()
                assert await page.evaluate('getSelection().toString()')==QUOTE
                await target().locator('pre').evaluate('n=>n.scrollTop+=35')
                await target().locator('.history-reader-task-open').evaluate('n=>n.focus({preventScroll:true})')
                await base.frames(page)

                async def passage():
                    return await target().evaluate("""n=>{const pre=n.querySelector('pre'),selection=getSelection(),r=selection.rangeCount?selection.getRangeAt(0):null;
                        return {item:n.dataset.itemId,turn:n.dataset.turnId,start:n.dataset.windowStart,open:n.open,
                            scroll:pre.scrollTop,selection:selection.toString(),backward:!!r&&selection.anchorNode===r.endContainer&&selection.anchorOffset===r.endOffset,
                            query:$('history-reader-find-query').value,status:$('history-reader-find-status').textContent,
                            page:$('history-reader-coverage').textContent,focus:document.activeElement.className,
                            window:scrollY,outer:$('history-reader').scrollTop,body:$('history-reader-body').scrollTop,
                            top:n.getBoundingClientRect().top,selectionTop:r?r.getBoundingClientRect().top:null};}""")

                original_view = await passage()
                assert original_view['selection'] == QUOTE and original_view['backward']
                native_boundary, local_boundary = len(f.calls), len(http)
                await target().locator('.history-reader-task-open').press('Enter')
                await page.wait_for_function("document.querySelector('.history-reader-task-context')")
                assert TURN in await page.locator('.history-reader-task-context').inner_text()
                assert 'Actual historical parser failure' in await page.locator('.history-reader-task-context').inner_text()
                assert await page.locator('.history-reader-task-instruction').count() == 3
                assert await action('instruction:image-only-user').is_disabled()
                assert 'No readable user text' in await page.locator('.history-reader-task-context').inner_text()
                async def context_position():
                    return await page.evaluate("""()=>({focus:document.activeElement?.dataset?.taskAction || null,
                        body:$('history-reader-body').scrollTop,outer:$('history-reader').scrollTop,
                        query:$('history-reader-find-query').value,findStatus:$('history-reader-find-status').textContent,
                        context:!!document.querySelector('.history-reader-task-context')})""")

                context_returns = []
                for selected_action in ('instruction:'+SECOND, 'response'):
                    await action(selected_action).evaluate("n=>{n.focus({preventScroll:true});$('history-reader-body').scrollTop=105;$('history-reader').scrollTop=115}")
                    await base.frames(page)
                    expected_position = await context_position()
                    assert expected_position['focus'] == selected_action
                    assert expected_position['body'] > 0 and expected_position['outer'] > 0
                    await action(selected_action).press('Enter')
                    await page.locator('#history-reader-task-return').click()
                    await base.frames(page)
                    actual_position = await context_position()
                    context_returns.append({'action':selected_action,'before':expected_position,'after':actual_position})
                    assert actual_position == expected_position, (expected_position, actual_position)
                report['context_returns'] = context_returns
                await checkpoint('context-instruction-response-return-exact-control-body-dialog-scroll')
                await page.locator('#history-reader-instruction-query').fill('CAFE\u0301 STRASSE .*[retry]')
                await page.locator('#history-reader-instruction-query').press('Enter')
                await page.wait_for_function("document.querySelector('.history-reader-instruction-matches')")
                assert await page.locator('.history-reader-instruction-match').count()==20
                assert '27 supplied instructions · 27 phrase occurrences' in await page.locator('.history-reader-instruction-match-status').inner_text()
                assert await page.locator('.history-reader-task-match-preview mark').evaluate_all("nodes=>nodes.every(n=>n.textContent==='Café Straße .*[retry]')")
                await action('instruction-matches-next').focus();await action('instruction-matches-next').press('Enter')
                assert await page.locator('.history-reader-instruction-match').count()==7
                chosen_turn='jump-task-23';key=json.dumps([SOURCE,chosen_turn,SECOND],separators=(',',':'))
                chosen=page.locator('.history-reader-instruction-match').filter(has=page.locator(f'[data-task-action=\'instruction-match:{key}\']')).locator('button')
                # The results status owns focus after paging. Six genuine Tab
                # keys visit rows jump18…jump23, bringing the chosen row onscreen.
                for _ in range(6):await page.keyboard.press('Tab')
                assert await chosen.evaluate('n=>n===document.activeElement')
                await base.frames(page)
                async def matches_position():
                    return await page.evaluate("""()=>({query:$('history-reader-instruction-query').value,page:$('history-reader-coverage').textContent,
                      row:document.activeElement.dataset.taskAction,body:$('history-reader-body').scrollTop,outer:$('history-reader').scrollTop})""")
                results_before=await matches_position()
                await chosen.press('Enter')
                assert chosen_turn in await page.locator('.history-reader-task-context').inner_text()
                assert await page.locator('.history-reader-task-instruction.history-reader-target').count()==1
                await action('instruction:'+SECOND).focus();await action('instruction:'+SECOND).press('Enter')
                assert await target(chosen_turn,SECOND).locator('mark').text_content()=='Café Straße .*[retry]'
                assert int(await target(chosen_turn,SECOND).get_attribute('data-window-start'))>20000
                await page.locator('#history-reader-task-return').click()
                await action('response').focus();await action('response').press('Enter')
                assert await target(chosen_turn,FINAL).locator('pre').text_content()==f'Codex\nOWN exact historical {chosen_turn} final response.'
                assert 'failed' in await page.locator('#history-reader-task-status').inner_text()
                await page.locator('#history-reader-task-instructions-return').click();await base.frames(page)
                results_after=await matches_position()
                assert results_after==results_before,(results_before,results_after)
                report['instruction_jump']={'matches':27,'page_limit':20,'selection_method':'six-native-Tab-keys-then-Enter','selected':{'thread':SOURCE,'turn':chosen_turn,'item':SECOND},'results_before':results_before,'results_after':results_after}
                await checkpoint('literal-NFKC-casefold-bounded-page-exact-late-user-instruction-own-response-return')
                native_boundary,local_boundary=len(f.calls),len(http)
                await action('instruction-matches-previous').focus();await action('instruction-matches-previous').press('Enter')
                historical_key=json.dumps([SOURCE,TURN,SECOND],separators=(',',':'))
                historical=page.locator(f"[data-task-action='instruction-match:{historical_key}']")
                await historical.focus();await historical.press('Enter')
                assert TURN in await page.locator('.history-reader-task-context').inner_text()
                await action('instruction:'+FIRST).click()
                assert await target(TURN, FIRST).locator('pre').text_content() == 'User\n'+PROMPT
                assert await target(TURN, FIRST).get_attribute('data-window-start') == '0'
                await page.locator('#history-reader-task-return').click()
                await action('instruction:'+SECOND).click()
                assert await target(TURN, SECOND).locator('pre').text_content() == 'User\n'+SECOND_PROMPT
                await page.locator('#history-reader-task-return').click()
                await action('response').click()
                assert await target(TURN, FINAL).count() == 1
                assert await target(TURN, FINAL).locator('pre').text_content() == 'Codex\nSame response text — exact historical final.'
                label = await page.locator('#history-reader-task-status').inner_text()
                assert 'Final answer' in label and 'final_answer' in label and 'failed' in label and TURN in label
                await checkpoint('same-turn-all-instructions-exact-historical-final')
                await page.locator('#history-reader-task-return').click()
                await action('next').click()
                assert 'outcome-only-task' in await page.locator('.history-reader-task-context').inner_text()
                assert await page.locator('.history-reader-task-instruction').count() == 0
                assert 'No user instruction was supplied' in await page.locator('.history-reader-task-context').inner_text()
                await action('response').click()
                assert 'No readable assistant response was supplied' in await page.locator('.history-reader-task-context').inner_text()
                await action('next').click()
                assert 'fallback-task' in await page.locator('.history-reader-task-context').inner_text()
                await action('response').click()
                assert await target('fallback-task', 'fallback-last').count() == 1
                label = await page.locator('#history-reader-task-status').inner_text()
                assert 'Last assistant message' in label and 'future_native_phase' in label and 'interrupted' in label
                await page.locator('#history-reader-task-return').click()
                assert await action('next').is_disabled(), 'Ambiguous adjacent turn became selectable'
                await checkpoint('supplied-adjacent-outcome-fallback-and-ambiguous-turn')
                await page.locator('#history-reader-task-passage').click()
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
                await base.frames(page)
                returned = await passage()
                report['passage_before'], report['passage_after'] = original_view, returned
                assert returned == original_view, (original_view, returned)
                assert http[local_boundary:] == [] and f.calls[native_boundary:] == []
                await checkpoint('exact-original-range-window-find-scroll-zero-navigation-requests')
                # A distinct explicit Refresh keeps the newer unsubmitted query.
                await target().locator('.history-reader-task-open').press('Enter')
                await page.locator('#history-reader-instruction-query').fill('CAFE\u0301 STRASSE .*[retry]')
                await page.locator('#history-reader-instruction-query').press('Enter')
                await action('instruction-matches-next').click()
                await page.locator('#history-reader-instruction-query').fill('Entered but not submitted correction — preserve this text.')
                expected_query=await page.locator('#history-reader-instruction-query').input_value()
                reads_before=len(f.calls);await page.locator('#history-reader-refresh').click()
                await page.wait_for_function("$('history-reader-status').textContent.includes('Original refreshed')")
                await base.frames(page)
                assert await page.locator('#history-reader-instruction-query').input_value()==expected_query
                assert '27 supplied instructions · 27 phrase occurrences' in await page.locator('.history-reader-instruction-match-status').inner_text()
                assert await page.locator('.history-reader-instruction-match').count()==7
                assert f.calls[reads_before:]==[{'method':'thread/read','params':{'threadId':SOURCE,'includeTurns':True}}]
                await checkpoint('explicit-refresh-preserves-entered-query-and-last-submitted-results-page')
                await page.locator('#history-reader-task-passage').click()
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
                await base.frames(page)
                refresh_return=await passage()
                # Fresh status chrome can change outer scroll while the exact
                # selected source and its absolute visible position stay fixed.
                assert {k:v for k,v in refresh_return.items() if k!='outer'}=={k:v for k,v in original_view.items() if k!='outer'},(original_view,refresh_return)
                report['query_refresh_return']={'before':original_view,'after':refresh_return}
                original_view=refresh_return
                await checkpoint('dirty-query-refresh-return-retains-exact-original-Range-Find-and-viewport')

                # A new selected-C outcome cannot redirect the captured historical task.
                f.emitter.id = CURRENT
                current_turn = {'id': 'current-C-newest-turn', 'status': 'completed', 'items': [
                    base.assistant('current-C-newest-answer', 'LATEST SELECTED C RESPONSE DOES NOT REPLACE A', 'final_answer')]}
                f.threads[CURRENT_THREAD]['turns'].append(copy.deepcopy(current_turn))
                f.event('turn/started', {'threadId': CURRENT_THREAD, 'turn': {**current_turn, 'status': 'inProgress'}})
                f.event('turn/completed', {'threadId': CURRENT_THREAD, 'turn': current_turn})
                await page.evaluate('pollActivity()')
                await base.frames(page)
                baseline = f.sql()
                assert await passage() == original_view
                assert 'current-C-newest-turn' in await page.locator('#native-outcome-identity').text_content()
                await target().locator('.history-reader-task-open').press('Enter')
                await action('response').click()
                assert await target(TURN, FINAL).count() == 1
                await checkpoint('newest-selected-native-outcome-never-redirects-historical-task')

                # Refresh keeps the response item chosen before a newer final arrives.
                f.threads[SOURCE]['turns'][1]['items'].append(base.assistant('added-after-selection', 'NEW FINAL DOES NOT RESELECT', 'final_answer'))
                native_boundary, local_boundary = len(f.calls), len(http)
                await page.locator('#history-reader-refresh').click()
                await page.wait_for_function("$('history-reader-status').textContent.includes('Original refreshed') && !$('history-reader-refresh').disabled")
                await base.frames(page)
                assert await target(TURN, FINAL).count() == 1
                assert await target(TURN, FINAL).evaluate('n=>n.classList.contains("history-reader-target")')
                assert f.calls[native_boundary:] == [{'method': 'thread/read', 'params': {'threadId': SOURCE, 'includeTurns': True}}]
                assert [q['path'] for q in http[local_boundary:]] == ['/api/native/evidence-source']
                await checkpoint('explicit-refresh-preserves-captured-response-item')
                f.threads[SOURCE]['turns'][1]['items'] = [item for item in f.threads[SOURCE]['turns'][1]['items'] if item['id'] != FINAL]
                await page.locator('#history-reader-refresh').click()
                await page.wait_for_function("$('history-reader-status').textContent.includes('Original refreshed') && !$('history-reader-refresh').disabled")
                await base.frames(page)
                assert await target(TURN, FINAL).count() == 0
                assert await page.locator('.history-reader-target').count() == 0
                assert 'not present' in await page.locator('#history-reader-match').inner_text()
                await checkpoint('explicit-refresh-reports-lost-item-without-other-response-substitution')
                await page.locator('#history-reader-task-passage').click()
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
                await base.frames(page)
                refreshed_view = await passage()
                assert refreshed_view['selection'] == QUOTE and refreshed_view['start'] == original_view['start']
                assert refreshed_view['query'] == original_view['query'] and refreshed_view['status'] == original_view['status']
                await page.locator('#history-reader-back').click()
                await page.wait_for_function("!$('history-reader').open")
                assert await editor() == pending
                assert await saved_control.evaluate('n=>n===document.activeElement')
                await checkpoint('saved-B-queue-outer-return-preserves-unsaved-editor-and-current-C')

                # A duplicated response ID cannot enter either a containing-task or response read.
                await saved_control.click()
                await ready()
                await page.locator('#history-reader-next').click()
                duplicated = target('duplicate-item-task', 'duplicate-response')
                assert await duplicated.count() == 2
                if not await duplicated.first.evaluate('n=>n.open'):
                    await duplicated.first.locator('summary').click()
                await duplicated.first.locator('.history-reader-task-open').click()
                assert await page.locator('.history-reader-task-context').count() == 0
                assert 'ambiguous' in await duplicated.first.locator('.history-reader-copy-status').inner_text()
                await page.locator('.history-reader-turn[data-turn-id="duplicate-item-task"] .history-reader-turn-task').click()
                await action('response').click()
                assert 'ambiguous response item' in await page.locator('.history-reader-task-context').inner_text()
                assert await page.locator('#history-reader-task-return').is_hidden()
                await checkpoint('duplicate-item-identity-suppresses-containing-task-and-response')
                await action('response').evaluate("n=>{n.focus({preventScroll:true});$('history-reader-body').scrollTop=35;$('history-reader').scrollTop=55}")
                await base.frames(page)
                report['context_f3_before'] = await context_position()
                f3_native, f3_http = len(f.calls), len(http)
                await page.keyboard.press('F3')
                await page.wait_for_timeout(600)
                await base.frames(page)
                report['context_f3_after'] = await context_position()
                report['context_f3_native_requests'] = len(f.calls)-f3_native
                report['context_f3_http_requests'] = len(http)-f3_http
                await page.screenshot(path=str(evidence/f'{width}-context-F3-observed.png'))
                assert report['context_f3_native_requests'] == 0 and report['context_f3_http_requests'] == 0
                assert report['context_f3_after'] == report['context_f3_before'], 'F3 changed context position or submitted hidden original Find'
                await checkpoint('context-F3-keeps-task-controls-and-does-not-submit-hidden-Find')
                await page.locator('#history-reader-back').click()
                await page.wait_for_function("!$('history-reader').open")
                assert await editor() == pending
                assert {path: path.read_bytes() for path in f.protected} == f.protected
                assert not [q for q in http if q['method'] == 'POST' and q['path'] != '/api/open']
                report.update(passed=True,package=str(base.PACKAGE),source=str(base.SOURCE),
                    native_calls=f.calls,http=http,javascript_errors=errors,sql_exact=True,
                    preparation_exact=True,outer_current_plan_exact=True,model_tasks=0,native_admissions=0,
                    navigation_requests=0,source_item_count=len(source_before['turns'][1]['items']))
            except Exception as error:
                report.update(error=str(error),traceback=traceback.format_exc(),native_calls=f.calls,http=http,javascript_errors=errors)
                if 'page' in locals():
                    try:
                        report['observed'] = await page.evaluate("({selected,opening,generation,nativeThreadId,status:$('history-reader-status').textContent,task:$('history-reader-task-status').textContent,match:$('history-reader-match').textContent,coverage:$('history-reader-coverage').textContent,body:$('history-reader-body').innerText})")
                        await page.screenshot(path=str(evidence/f'{width}-failed.png'))
                    except Exception as diagnostic:
                        report['diagnostic_error'] = str(diagnostic)
            finally:
                if context:
                    await context.close()
                f.stop()
    (evidence/f'case-{width}.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({key: report[key] for key in ('width','passed','checks','error') if key in report}),flush=True)
    return report


async def main():
    root=Path(os.environ['DESK_TEST_TEMP']).resolve();root.mkdir(parents=True,exist_ok=True)
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']).resolve();evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            records=[await one(browser,width,root,evidence) for width in (1250,390)]
        finally:
            await browser.close()
    summary={'result':'PASS' if all(row['passed'] for row in records) else 'FAIL','version':base.codex_desk.__version__,
        'package':str(base.PACKAGE),'source':str(base.SOURCE),'widths':[1250,390],'results':records}
    (evidence/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({key:summary[key] for key in ('result','version','package','source','widths')}),flush=True)
    if summary['result']!='PASS':
        for row in records:
            if not row['passed']:print(row.get('traceback',''),flush=True)
        raise SystemExit(1)


if __name__=='__main__':
    asyncio.run(main())
