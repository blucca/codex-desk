#!/usr/bin/env python3
"""Check literal Prepared lookup and queued original-source return in the sample.

Runs the maintained UI against its browser-only API. --embedded places the
embedded build in an actual same-origin iframe, not a top-level approximation.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from check_browser_preview import static_server, normalized_request

SOURCE = 'sample-checkout-thread'
TURN = 'sample-checkout-turn'
ITEM = 'sample-checkout-answer'
DOCS = 'desk-sample-docs-thread'
CHECKOUT = 'desk-' + SOURCE
MOBILE = 'desk-sample-mobile-thread'
QUOTE = 'Retry only transient failures; preserve the original timeout result.'
LITERAL = 'Straße café🙂 ＦＩＸ .*[retry]'
QUERY = 'strasse café🙂 fix .*[retry]'
DOC_DRAFT = 'Plan the installation check; keep this task unsent.'
MOBILE_DRAFT = 'Current mobile task remains separate and unsent.'


async def check(playwright, site, evidence, width, chromium, embedded, public_url=None):
    errors, console, external, failed, phases, requests = [], [], [], [], [], []
    with static_server(site) as (url, received, escaped):
        url = public_url or url
        browser = await playwright.chromium.launch(executable_path=chromium,
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(viewport={'width': width, 'height': 900 if width > 390 else 844})
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
        try:
            if embedded:
                host = url + 'lookup-frame-host.html'
                await context.route(host, lambda route: route.fulfill(content_type='text/html', body=(
                    '<!doctype html><html><head><title>Embedded sample lookup</title>'
                    '<style>html,body{margin:0;height:100%;overflow:hidden}iframe{display:block;width:100%;height:100%;border:0}</style>'
                    '</head><body><iframe title="Codex Desk sample" src="' + url + '"></iframe></body></html>')))
                await page.goto(host)
                element = await page.locator('iframe').element_handle()
                app = await element.content_frame()
            else:
                await page.goto(url)
                app = page.main_frame
            await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate("document.documentElement.dataset.previewEmbedded==='true'") == embedded

            async def snapshot():
                return await app.evaluate('DeskBrowserPreview.snapshot()')

            async def log():
                return [normalized_request(row) for row in await app.evaluate('DeskBrowserPreview.requests')]

            async def saved(session, text):
                await app.wait_for_function("v=>DeskBrowserPreview.snapshot().drafts[v.id]?.text===v.text && DeskBrowserPreview.snapshot().drafts[v.id]?.mode==='plan'", arg={'id': session, 'text': text})

            async def select(session):
                await app.locator(f'.session-row[data-session="{session}"] .session').click()
                await app.wait_for_function('id=>selected===id&&!opening', arg=session)

            async def checkpoint(name):
                assert not errors and not console, (errors, console)
                assert not external and not failed and not escaped, (external, failed, escaped)
                assert await app.evaluate("document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)"), name + ' sample overflow'
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), name + ' host overflow'
                phases.append(name)
                await page.screenshot(path=str(evidence / f'{width}-{name}.png'))

            async def search(query):
                await app.locator('#preparation-find-query').fill(query)
                await app.locator('#preparation-find-query').press('Enter')
                await app.wait_for_function("$('preparation-find-results').getAttribute('aria-busy')==='false' && !$('preparation-find-search').disabled")
                assert not await app.locator('#preparation-error').is_visible(), await app.locator('#preparation-error').inner_text()

            # Use only visible import/draft/preparation actions for all three owners.
            for title, session, text in (
                ('Sample checkout retry decision', CHECKOUT, 'Checkout preparation: ' + LITERAL),
                ('Sample mobile layout check', MOBILE, MOBILE_DRAFT),
                ('Sample documentation review', DOCS, DOC_DRAFT)):
                await app.locator('#browse').click()
                await app.locator('#native-list .native-row').filter(has_text=title).get_by_role('button', name='Resume with current settings', exact=True).click()
                await app.wait_for_function('id=>selected===id&&!opening', arg=session)
                await app.locator('#prompt').fill(text)
                await app.locator('#turn-mode').select_option('plan')
                await saved(session, text)
            await checkpoint('three-project-prepared-owners')

            # Original A -> reviewed quote -> unsent documentation B, then a saved queue instruction.
            before_forward = await snapshot()
            await app.locator('#browse').click()
            await app.locator('#native-list .native-row').filter(has_text='Sample checkout retry decision').locator('.native-read').click()
            await app.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            original = app.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"]')
            await original.locator('pre').evaluate("""(n,quote)=>{
                const walker=document.createTreeWalker(n,NodeFilter.SHOW_TEXT);let node;
                while(node=walker.nextNode()){const at=node.textContent.indexOf(quote);if(at<0)continue;
                    const range=document.createRange();range.setStart(node,at);range.setEnd(node,at+quote.length);
                    const selection=getSelection();selection.removeAllRanges();selection.addRange(range);return;}
                throw Error('Sample quote missing');
            }""", QUOTE)
            await original.locator('.history-reader-review-evidence').click()
            await app.wait_for_function("$('evidence-preparation').open && !DeskEvidencePreparation.state().pending")
            reviewed = await app.evaluate('DeskEvidencePreparation.state()')
            reference = reviewed['reference']
            assert reference['quote'] == QUOTE and reference['thread_id'] == SOURCE
            assert reference['turn_id'] == TURN and reference['item_id'] == ITEM
            assert reviewed['destination']['session'] == DOCS and reviewed['destination']['mode'] == 'plan'
            assert await snapshot() == before_forward
            await app.locator('#evidence-preparation-note').fill('Retain this literal preparation phrase: ' + LITERAL)
            await app.locator('#evidence-preparation-append').click()
            await app.wait_for_function("!$('evidence-preparation').open && DeskEvidencePreparation.parse($('prompt').value).length===1")
            await app.locator('#history-reader-back').click()
            await app.locator('#history-close').click()
            forwarded = (await snapshot())['drafts'][DOCS]['text']
            assert forwarded.startswith(DOC_DRAFT + '\n\nNext-step note:')
            assert LITERAL in forwarded
            await app.locator('#prepare-followup').click()
            await app.wait_for_function("$('followup-count').textContent==='1' && !$('prepare-followup').disabled")
            await app.locator('#prompt').fill(forwarded)
            await saved(DOCS, forwarded)
            prepared = await snapshot()
            entry = prepared['followups'][DOCS]['entries'][0]
            assert entry['text'] == forwarded and entry['mode'] == 'plan' and entry['state'] == 'queued'
            assert prepared['drafts'][CHECKOUT] == before_forward['drafts'][CHECKOUT]
            assert prepared['drafts'][MOBILE] == before_forward['drafts'][MOBILE]
            await checkpoint('review-exact-original-forward-unsent-plan-and-queue')

            # Reload proves persisted source metadata; C remains independent while reviewing B.
            requests.extend(await log())
            await page.reload()
            if embedded:
                app = await (await page.locator('iframe').element_handle()).content_frame()
            else:
                app = page.main_frame
            await app.wait_for_function('id=>selected===id&&!opening', arg=DOCS)
            await app.wait_for_function("$('followup-count').textContent==='1'")
            assert await snapshot() == prepared
            await select(MOBILE)
            main = await app.evaluate("({selected,text:$('prompt').value,mode:$('turn-mode').value,nativeThreadId,generation})")
            baseline = await snapshot()
            boundary = len(await log())
            await app.locator('#show-preparation').click()
            await app.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            await app.locator(f'.preparation-session[data-session="{DOCS}"]').locator('button[aria-label^="Review preparation in "]').click()
            await app.wait_for_function("!$('preparation-save').disabled")
            unsaved = 'Local unsaved documentation review stays separate.\n' + forwarded
            await app.locator('#preparation-text').fill(unsaved)
            await app.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(5,29,'backward');n.scrollTop=45}")
            async def editor():
                return await app.locator('#preparation-text').evaluate("n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})")
            pending = await editor()
            await search(QUERY)
            assert await app.locator('.preparation-find-match').count() == 3
            assert await app.locator('.preparation-session').count() == 3, 'Lookup hid unmatched scoped owners'
            assert all(LITERAL in text for text in await app.locator('.preparation-find-match pre').all_text_contents())
            assert set(await app.locator('.preparation-find-match').evaluate_all('nodes=>nodes.map(n=>n.dataset.session)')) == {CHECKOUT, DOCS}
            await app.locator(f'.preparation-find-match[data-session="{DOCS}"]').filter(has=app.locator('h3', has_text='Saved draft')).locator('button').first.click()
            await app.wait_for_function("!$('preparation-saved-match').hidden")
            assert await editor() == pending
            assert LITERAL in await app.locator('#preparation-saved-match').inner_text()
            await checkpoint('literal-unicode-duplicate-owners-preserve-unsaved-B-and-current-C')

            # Read saved original, never treat the pending local edit as evidence.
            await app.locator('#preparation-evidence-list button').first.click()
            await app.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            assert await app.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"] mark').text_content() == QUOTE
            assert await app.locator('#history-reader-saved-evidence-quote').text_content() == QUOTE
            await app.locator('#history-reader-back').click()
            await app.wait_for_function("!$('history-reader').open")
            assert await editor() == pending
            await checkpoint('located-saved-B-read-exact-A-and-local-editor-return')

            await app.locator('#preparation-project').select_option('/sample/projects/docs')
            await app.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            await search(QUERY)
            assert await app.locator('.preparation-find-match').count() == 2
            assert await app.locator('.preparation-session').count() == 1
            assert await app.locator('.preparation-session').get_attribute('data-session') == DOCS
            await search('.*[retry]')
            assert await app.locator('.preparation-find-match').count() == 2
            assert all('.*[retry]' in text for text in await app.locator('.preparation-find-match pre').all_text_contents())
            await search('.*[missing]')
            assert await app.locator('.preparation-find-match').count() == 0
            assert await app.locator('.preparation-session').count() == 1
            await app.locator('#preparation-project').select_option('')
            await app.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            await search(QUERY)
            await app.locator(f'.preparation-find-match[data-session="{DOCS}"]').filter(has=app.locator('h3', has_text='Saved follow-up')).locator('button').first.click()
            await app.wait_for_function('id=>document.activeElement.tagName===\'ARTICLE\' && document.activeElement.dataset.followup===id', arg=entry['id'])
            assert await editor() == pending
            assert await snapshot() == baseline
            assert await app.evaluate("({selected,text:$('prompt').value,mode:$('turn-mode').value,nativeThreadId,generation})") == main
            read_only = (await log())[boundary:]
            assert all(row['method'] == 'GET' for row in read_only), read_only
            assert any(row['path'] == '/api/preparation' and row['query'].get('cwd') == ['/sample/projects/docs'] for row in read_only)
            await checkpoint('project-scoped-literal-miss-and-exact-queued-owner-no-writes')
            await app.locator('#preparation-close').click()

            # Ordinary saved follow-up retains its original when the unsent edit removes the reference.
            await select(DOCS)
            if not await app.locator('#followups').evaluate('n=>n.open'):
                await app.locator('#followups summary').click()
            ordinary = app.locator(f'#followup-list .followup-entry[data-followup="{entry["id"]}"]')
            await ordinary.get_by_role('button', name='Edit', exact=True).click()
            field = ordinary.locator('textarea')
            await field.fill('Ordinary current unsent instruction remains exact.\n' + ('Keep the pending line separate.\n' * 12))
            await field.evaluate("n=>{n.focus();n.setSelectionRange(8,25,'backward');n.scrollTop=35}")
            view = await field.evaluate("n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})")
            baseline = await snapshot()
            boundary = len(await log())
            await ordinary.locator('.followup-evidence-references button').first.click()
            await app.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            assert await app.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"] mark').text_content() == QUOTE
            assert await app.locator('#history-reader-back').text_content() == 'Return to saved follow-up'
            await app.locator('#history-reader-back').click()
            await app.wait_for_function("!$('history-reader').open")
            assert await field.evaluate("n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})") == view
            assert await snapshot() == baseline
            source_reads = (await log())[boundary:]
            assert all(row['method'] == 'GET' for row in source_reads)
            exact_reads = [row for row in source_reads if row['path'] == '/api/native/evidence-source']
            assert len(exact_reads) == 1 and exact_reads[0]['query'] == {'home': [reference['native_home']], 'thread': [SOURCE]}
            await checkpoint('ordinary-saved-followup-exact-A-return-unsent-range-and-scroll')
            requests.extend(await log())
            assert not any(row['method'] == 'POST' and row['path'] in {'/api/turn', '/api/followups/send', '/api/steer', '/api/stop'} for row in requests)
            receipt = {'passed': True, 'embedded': embedded, 'actual_iframe': embedded, 'viewport': width,
                'phases': phases, 'source': str(site), 'public_url': public_url, 'source_reference': reference, 'literal_query': QUERY,
                'literal_match': LITERAL, 'prepared_owners': [CHECKOUT, DOCS, MOBILE],
                'project_scope': '/sample/projects/docs', 'saved_followup': entry['id'],
                'read_only_lookup_and_source_return': True, 'unsaved_prepared_editor_preserved': True,
                'ordinary_unsent_editor_preserved': view, 'reload_preserved': True,
                'simulated_api_requests': requests, 'static_http_requests': received, 'escaped_api_requests': escaped,
                'native_model_calls': 0, 'external_requests': external, 'javascript_errors': errors,
                'console_errors': console, 'failed_requests': failed, 'horizontal_overflow': False}
            (evidence / f'receipt-{width}.json').write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
            print(json.dumps({'passed': True, 'embedded': embedded, 'viewport': width, 'phases': phases}), flush=True)
            return receipt
        except Exception:
            await page.screenshot(path=str(evidence / f'failure-{width}.png'))
            diagnostic = {'phases': phases, 'errors': errors, 'console': console, 'external': external,
                'failed': failed, 'escaped_api': escaped, 'body': await page.locator('body').inner_text()}
            if 'app' in locals() and app:
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
    parser.add_argument('--url', help='Verify lookup at an already-deployed sample URL')
    parser.add_argument('--embedded', action='store_true', help='Check an embedded build in a real iframe')
    parser.add_argument('--widths', default='1250,390')
    parser.add_argument('--chromium', default=os.environ.get('DESK_CHROMIUM'))
    asyncio.run(main(parser.parse_args()))
