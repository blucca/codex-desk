"""Replay native-shaped activity through the shipped loopback HTTP UI.

DESK_TEST_TEMP=/workspace/temp DESK_CHROMIUM=/usr/bin/chromium \
  python tests/browser_activity.py
DESK_USE_INSTALLED=1 tests an installed wheel, without adding the source to sys.path.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk import server as desk_server
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ.get('DESK_TEST_TEMP', Path(__file__).resolve().parents[3] / 'temp'))
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-activity-') as folder:
        folder = Path(folder)
        project, home = folder / 'project', folder / 'native-home'
        project.mkdir()
        home.mkdir()
        (home / 'config.toml').write_text('model = "fixture"\n')
        code = 'const html = "<img src=https://activity-fetch.invalid/code>";\n' + 'x' * 260
        message = '\n'.join([
            '# Work log', '', 'A **clear result** with *emphasis* and `inline code`.', '',
            '## Next steps', '', '3. Keep the existing project', '4. Verify the output', '',
            '- First check', '- Second check', '  - Nested check', '',
            '[Docs](https://example.com/docs) and [HTTP](http://example.com/).',
            '[script](javascript:alert(1)) [data](data:text/html,hello) [file](file:///etc/passwd)',
            '[relative](/api/turn) [protocol relative](//activity-fetch.invalid/payload)',
            '<script>globalThis.__activityXss = 1</script>',
            '<img src="https://activity-fetch.invalid/raw" onerror="globalThis.__activityXss = 2">',
            '![external](https://activity-fetch.invalid/picture.png)', '',
            'Inline raw <b title="**attribute**">__literal body__</b> stays text.', '',
            '<style>', '', '# Not a Markdown heading', '__not emphasis__', '', '</style>', '',
            '<!-- **not strong** -->', '', '```javascript', code, '```', '',
            '### Finished', 'The first turn is complete.'
        ])
        user_text = 'Read this as typed.\n\n  Keep two spaces.\n\tKeep a tab and <b>literal tags</b>.'
        saved = [
            {'id': 'u1', 'type': 'userMessage', 'content': [{'type': 'text', 'text': user_text}]},
            {'id': 'a1', 'type': 'agentMessage', 'text': message},
            {'id': 'c1', 'type': 'commandExecution', 'command': 'python -m unittest discover',
             'status': 'completed', 'aggregatedOutput': 'Saved output\nAll tests passed', 'exitCode': 0},
            {'id': 'f1', 'type': 'fileChange', 'status': 'completed', 'changes': [
                {'path': 'src/main.py', 'kind': {'type': 'update'}, 'diff': '@@\n-old\n+new'},
                {'path': 'tests/' + 'long-path-' * 30 + '.py', 'kind': {'type': 'add'}, 'diff': '+test'}]},
            {'id': 'm1', 'type': 'mcpToolCall', 'server': 'local', 'tool': 'inspect', 'status': 'completed',
             'arguments': {'path': 'src/main.py'}, 'result': {'content': [
                 {'type': 'text', 'text': 'Complete MCP text\nsecond line'},
                 {'type': 'image', 'mimeType': 'image/png', 'data': 'never-expand-binary'},
                 {'type': 'resource_link', 'name': 'Report', 'uri': 'https://activity-fetch.invalid/report'}],
                 'structuredContent': {'answer': 42, '_meta': {'secret': 'private-native-meta'}}}},
            {'id': 'd1', 'type': 'dynamicToolCall', 'namespace': 'project', 'tool': 'verify',
             'status': 'completed', 'success': False, 'contentItems': [{'type': 'text', 'text': 'Complete dynamic evidence'}]},
            {'id': 'u2', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Follow up on the same project.'}]},
            {'id': 'a2', 'type': 'agentMessage', 'text': '## Follow-up\n\nA separate second turn.'},
        ]
        thread = {'id': 'fixture-thread', 'cwd': str(project), 'name': 'Activity replay',
                  'turns': [{'id': 't1', 'items': saved[:6]}, {'id': 't2', 'items': saved[6:]}]}
        native_calls = []

        class ControlledRuntime:
            def __init__(self, store, identifier, binary, native_home):
                assert binary == 'never-executed'
                self.store, self.id = store, identifier
                self.process = SimpleNamespace(poll=lambda: None)
                self.approvals = {}

            def attach(self):
                native_calls.append('thread/resume')
                self.thread_result = {'thread': thread, 'model': 'fixture', 'modelProvider': 'fixture'}
                self.store.update(self.id, status='ready', thread_id=thread['id'], model='fixture', provider='fixture')
                return self.thread_result

            def close(self):
                pass

        with patch.object(desk_server, 'Runtime', ControlledRuntime):
            desk = desk_server.Desk('never-executed', home, folder / 'state')
            identifier = desk.store.create(str(project), 'default', name='Activity replay')
            desk.store.update(identifier, status='saved', thread_id=thread['id'])

            def emit(method, **params):
                desk.store.event(identifier, {'method': method, 'params': params})

            # Reopening first renders the authoritative two-turn native snapshot,
            # then replays the stored started/delta/completed stream by the same IDs.
            for item in saved:
                if item['type'] == 'agentMessage':
                    emit('item/started', item={'id': item['id'], 'type': 'agentMessage', 'text': ''})
                    for delta in (item['text'][:40], item['text'][40:]):
                        emit('item/agentMessage/delta', itemId=item['id'], delta=delta)
                elif item['type'] == 'commandExecution':
                    emit('item/started', item={**item, 'status': 'inProgress', 'aggregatedOutput': '', 'exitCode': None})
                    emit('item/commandExecution/outputDelta', itemId=item['id'], delta='Transient replay output')
                else:
                    emit('item/started', item=item)
                emit('item/completed', item=item)
            replay_seq = desk.store.events(identifier)[-1]['seq']
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            url = f'http://127.0.0.1:{server.server_port}'
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                        headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                    try:
                        page = await browser.new_page(viewport={'width': 390, 'height': 844})
                        errors, requests = [], []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.on('request', lambda r: requests.append(r.url))
                        await page.goto(url)
                        await page.locator('#sessions .session').click()
                        await page.wait_for_function('!opening && after >= ' + str(replay_seq))

                        def row(item_id):
                            return page.locator('[data-item-id="' + item_id + '"]')

                        expected_order = [item['id'] for item in saved]
                        assert await page.locator('#activity .item').evaluate_all('(rows) => rows.map(r => r.dataset.itemId)') == expected_order
                        assert await row('a1').locator('h1').inner_text() == 'Work log'
                        assert await row('a1').locator('h2').inner_text() == 'Next steps'
                        assert await row('a1').locator('h3').inner_text() == 'Finished'
                        assert await row('a1').locator('strong').inner_text() == 'clear result'
                        assert await row('a1').locator('em').inner_text() == 'emphasis'
                        assert await row('a1').locator('ol').get_attribute('start') == '3'
                        assert await row('a1').locator('ul ul li').inner_text() == 'Nested check'
                        assert await row('a1').locator('pre code').count() == 1
                        assert await row('a1').locator('pre code').text_content() == code
                        assert await row('u1').locator('.activity-plain').text_content() == user_text
                        assert await row('u1').locator('.activity-plain').evaluate('(n) => getComputedStyle(n).whiteSpace') == 'pre-wrap'
                        assert await row('a1').locator('script,style,img,iframe,video,audio,svg,object,embed,link').count() == 0
                        assert not await page.evaluate('globalThis.__activityXss')
                        links = await row('a1').locator('a').evaluate_all('(nodes) => nodes.map(n => ({href:n.href, rel:n.rel, target:n.target}))')
                        assert [link['href'] for link in links] == ['https://example.com/docs', 'http://example.com/'], links
                        assert all(link['target'] == '_blank' and 'noopener' in link['rel'] for link in links)
                        assert '<img src=' in await row('a1').inner_text()
                        assert '<b title="**attribute**">__literal body__</b>' in await row('a1').inner_text()
                        assert '<!-- **not strong** -->' in await row('a1').inner_text()
                        assert '[script](javascript:alert(1))' in await row('a1').inner_text()
                        assert await page.locator('#activity details').count() == 4
                        assert await page.locator('#activity details[open]').count() == 0
                        assert 'exit 0' in await row('c1').locator('summary').inner_text()
                        assert '2 changes' in await row('f1').locator('summary').inner_text()
                        assert 'src/main.py' in await row('f1').locator('summary').inner_text()
                        assert 'MCP · local / inspect · Completed' == await row('m1').locator('summary').inner_text()
                        assert 'project / verify' in await row('d1').locator('summary').inner_text()
                        for item_id in ('c1', 'f1', 'm1', 'd1'):
                            assert await row(item_id).locator('pre').text_content() == await page.evaluate('(id) => itemText(items.get(id))', item_id)
                        assert 'private-native-meta' not in await row('m1').text_content()
                        assert 'Transient replay output' not in await row('c1').text_content()

                        # Real button action with controlled clipboard success and rejection.
                        await page.evaluate("Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{writeText:async (text) => {globalThis.copiedCode=text;}}})")
                        copy = row('a1').get_by_role('button', name='Copy javascript code')
                        await copy.click()
                        await page.wait_for_function("document.querySelector('.activity-copy-feedback').textContent === 'Copied'")
                        assert await page.evaluate('globalThis.copiedCode') == code
                        await page.evaluate("() => {navigator.clipboard.writeText=async () => {throw new Error('Permission rejected')};}")
                        await copy.click()
                        await page.wait_for_function("document.querySelector('.activity-copy-feedback').textContent.includes('Copy failed')")
                        assert await copy.is_enabled()

                        async def sync():
                            seq = desk.store.events(identifier)[-1]['seq']
                            await page.wait_for_function('after >= ' + str(seq))

                        # New live output is visible by default, without replacing its details node.
                        command = {'id': 'c-live', 'type': 'commandExecution', 'command': 'echo live',
                                   'status': 'inProgress', 'aggregatedOutput': '', 'exitCode': None}
                        emit('item/started', item=command)
                        await sync()
                        details = row('c-live').locator('details')
                        handle = await details.element_handle()
                        assert await details.get_attribute('open') is not None
                        emit('item/commandExecution/outputDelta', itemId='c-live', delta='live one\n')
                        await sync()
                        assert 'live one' in await row('c-live').inner_text()
                        await row('c-live').locator('summary').focus()
                        await page.keyboard.press('Enter')
                        assert await details.get_attribute('open') is None
                        emit('item/commandExecution/outputDelta', itemId='c-live', delta='live two\n')
                        await sync()
                        assert await details.get_attribute('open') is None
                        assert await handle.evaluate('(n) => n.isConnected')
                        await row('c-live').locator('summary').click()
                        emit('item/completed', item={**command, 'status': 'completed', 'aggregatedOutput': 'authoritative final\n', 'exitCode': 7})
                        await sync()
                        assert await details.get_attribute('open') is not None
                        assert 'exit 7' in await row('c-live').locator('summary').inner_text()
                        assert 'authoritative final' in await row('c-live').inner_text()
                        assert 'live one' not in await row('c-live').text_content()
                        assert 'live two' not in await row('c-live').text_content()
                        assert await handle.evaluate('(n) => n.isConnected')

                        # An untouched in-progress call collapses on completion; an explicit
                        # saved-tool expansion survives progress and full evidence replacement.
                        mcp = {'id': 'm-live', 'type': 'mcpToolCall', 'server': 'local', 'tool': 'scan', 'status': 'inProgress'}
                        emit('item/started', item=mcp)
                        await sync()
                        assert await row('m-live').locator('details').get_attribute('open') is not None
                        emit('item/mcpToolCall/progress', itemId='m-live', message='Scanning project')
                        await sync()
                        assert 'Scanning project' in await row('m-live').inner_text()
                        emit('item/completed', item={**mcp, 'status': 'completed', 'result': {'content': [{'type': 'text', 'text': 'Final scan'}]}})
                        await sync()
                        assert await row('m-live').locator('details').get_attribute('open') is None
                        assert 'Final scan' in await row('m-live').text_content()
                        await row('m1').locator('summary').click()
                        emit('item/completed', item={**saved[4], 'result': {'content': [{'type': 'text', 'text': 'Replaced complete evidence'}]}})
                        await sync()
                        assert await row('m1').locator('details').get_attribute('open') is not None
                        assert 'Replaced complete evidence' in await row('m1').inner_text()
                        assert 'Complete MCP text' not in await row('m1').text_content()

                        # A third streamed turn extends the existing timeline, not another copy.
                        emit('item/started', item={'id': 'u3', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Continue'}]})
                        emit('item/started', item={'id': 'a3', 'type': 'agentMessage', 'text': ''})
                        emit('item/agentMessage/delta', itemId='a3', delta='# Streaming\n\nPartial')
                        await sync()
                        assert 'Partial' in await row('a3').inner_text()
                        emit('item/completed', item={'id': 'a3', 'type': 'agentMessage', 'text': '# Final third turn\n\nFinal only'})
                        await sync()
                        assert 'Partial' not in await row('a3').text_content()
                        assert await row('a3').locator('h1').inner_text() == 'Final third turn'
                        assert await page.locator('#activity .item').evaluate_all('(rows) => rows.map(r => r.dataset.itemId)') == expected_order + ['c-live', 'm-live', 'u3', 'a3']
                        await row('f1').locator('summary').click()
                        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth && $('activity').scrollWidth <= $('activity').clientWidth")
                        assert await row('a1').locator('pre').evaluate('(n) => n.scrollWidth > n.clientWidth')
                        external = [request for request in requests if not request.startswith(url + '/')]
                        assert not external, external
                        assert native_calls == ['thread/resume'], native_calls
                        assert not errors, errors
                        receipt = {'httpSource': str(Path(desk_server.__file__).resolve()), 'nativeSnapshotAndReplay': True,
                            'messageMarkdownAndWhitespace': True, 'rawHTMLAndUnsafeLinksTextOnly': True,
                            'clipboardSuccessAndRejectionFeedback': True, 'compactToolSummariesAndCompleteEvidence': True,
                            'liveDefaultVisibilityAndKeyboardCollapse': True, 'expansionSurvivesOutputAndCompletion': True,
                            'authoritativeReplacementRemovesStaleContent': True, 'threeTurnOrderWithoutDuplicates': True,
                            'viewportWidth': 390, 'pageOverflow': False, 'externalRequests': external, 'javascriptErrors': errors}
                        if os.environ.get('DESK_ACTIVITY_RECEIPT'):
                            destination = Path(os.environ['DESK_ACTIVITY_RECEIPT'])
                            destination.mkdir(parents=True, exist_ok=True)
                            (destination / 'browser-activity.json').write_text(json.dumps(receipt, indent=2) + '\n')
                            await page.screenshot(path=str(destination / 'activity-390.png'), full_page=True)
                        print(json.dumps(receipt, indent=2), flush=True)
                    finally:
                        await browser.close()
            finally:
                server.shutdown()
                worker.join(timeout=5)
                server.server_close()
                desk.close()
                desk.store.db.close()


if __name__ == '__main__':
    asyncio.run(check())
