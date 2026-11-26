"""Handoff next-task isolation across projects and failed-start recovery.

Real loopback routes and private SQLite; native history/start are controlled.
Run with DESK_TEST_TEMP=/path/to/workspace/temp python tests/browser_handoff.py.
DESK_USE_INSTALLED=1 uses the installed package; DESK_TEST_EVIDENCE saves receipts.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-handoff-') as folder:
        folder = Path(folder)
        evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(folder / 'evidence')))
        evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
        projects = {key: folder / key for key in ('a', 'b')}
        for path in projects.values():
            path.mkdir()
        histories = {
            key: {'id': 'native-' + key, 'name': 'Project ' + key.upper(),
                  'cwd': str(path), 'modelProvider': 'openai',
                  'turns': [{'id': 'prior-' + key, 'items': [
                      {'id': 'evidence-' + key, 'type': 'agentMessage',
                       'text': 'Verified project ' + key.upper() + ' evidence'}]}]}
            for key, path in projects.items()
        }
        # Native 0.171's owned command-start capture reports null output/exit.
        # Keep that shape in the ordinary review path, with a short read command.
        pending_command = {'id': 'pending-read-b', 'type': 'commandExecution',
                           'command': 'cat lines.txt', 'cwd': str(projects['b']),
                           'status': 'inProgress', 'aggregatedOutput': None,
                           'exitCode': None, 'durationMs': None}
        histories['b']['turns'][0]['items'].append(pending_command)
        # Native thread/read preserves the final error separately from items.
        histories['b']['turns'][0].update(status='failed', error={
            'message': 'Provider stream disconnected before build verification',
            'codexErrorInfo': {'responseStreamDisconnected': {
                'httpStatusCode': 503,
                'uri': 'https://native-user:native-key@relay.example/error?access=native-token#private',
                '_meta': {'key': 'private-native-metadata'}}},
            'additionalDetails': 'Retry limit reached; retain the partial command evidence',
            '_meta': {'key': 'private-root-error-metadata'}})
        desk = Desk('not-called', folder / 'home', folder / 'state')
        desk.history = lambda thread: next(t for t in histories.values() if t['id'] == thread)

        class Catalog:
            def request(self, method, params):
                assert method == 'thread/list'
                return {'data': list(histories.values()), 'nextCursor': None}

        desk.catalog = lambda: Catalog()
        desk.open = lambda identifier: {'thread': {'id': 'target-' + identifier, 'turns': []}}
        captured = []

        def capture_turn(identifier, text, mode='native'):
            captured.append({'session': identifier, 'cwd': desk.store.get(identifier)['cwd'],
                             'text': text, 'mode': mode})
            desk.store.update(identifier, status='completed', thread_id='target-' + identifier)
            return {'turn': {'id': 'captured-' + identifier, 'status': 'completed'}}

        desk.turn = capture_turn
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                    args=['--no-sandbox', '--disable-dev-shm-usage'])
                try:
                    results = []
                    for width in (390, 1250):
                        page = await browser.new_page(viewport={'width': width, 'height': 844})
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        await page.goto(f'http://127.0.0.1:{server.server_port}')
                        await page.wait_for_function('state.profiles.length > 0')

                        async def review(key):
                            await page.click('#browse')
                            row = page.locator('.native-row').filter(has_text='Project ' + key.upper())
                            await row.get_by_role('button', name='Review handoff').click()
                            await page.wait_for_function("$('preview').open")

                        await review('a')
                        await page.fill('#handoff-goal', 'Change only project A login')
                        edited_a_evidence = (await page.input_value('#handoff-text')) + '\nReviewed A: skip the completed login edit; verify remaining logout only.'
                        await page.fill('#handoff-text', edited_a_evidence)
                        await page.click('#preview-close')
                        await review('a')
                        same_source_goal = await page.input_value('#handoff-goal')
                        same_source_evidence = await page.input_value('#handoff-text')
                        await page.click('#preview-close')
                        await review('b')
                        cancelled_goal = await page.input_value('#handoff-goal')
                        b_evidence = await page.input_value('#handoff-text')
                        pending_evidence = {
                            'command': pending_command['command'] in b_evidence,
                            'status': 'Status: inProgress' in b_evidence,
                            'exit': 'Exit: not reported' in b_evidence,
                            'output': '[No command output reported.]' in b_evidence}
                        failure_evidence = {
                            'turn': 'Turn prior-b\nStatus: failed' in b_evidence,
                            'message': 'Provider stream disconnected before build verification' in b_evidence,
                            'code': 'responseStreamDisconnected' in b_evidence,
                            'http': '"httpStatusCode": 503' in b_evidence,
                            'details': 'Retry limit reached' in b_evidence,
                            'publicUri': 'https://relay.example/error' in b_evidence,
                            'noAccessPayload': not any(value in b_evidence for value in (
                                'native-user', 'native-key', 'native-token', '?access=',
                                '#private', 'private-native-metadata', 'private-root-error-metadata'))}
                        b_evidence += '\nReviewed remaining: run the project B build.'
                        await page.fill('#handoff-text', b_evidence)
                        await page.fill('#handoff-goal', 'Verify only project B build')
                        await page.fill('#handoff-cwd', str(folder / 'missing'))
                        await page.click('#handoff-start')
                        await page.wait_for_function("!$('handoff-start').disabled")
                        failure = await page.evaluate("""() => ({
                            open:$('preview').open,errorVisible:!$('handoff-error').hidden,
                            goal:$('handoff-goal').value,evidence:$('handoff-text').value,
                            profile:$('handoff-profile').value})""")
                        await page.screenshot(path=str(evidence / f'handoff-retry-{width}.png'), full_page=True)
                        await page.click('#preview-close')
                        await review('b')
                        failed_reopen_evidence = await page.input_value('#handoff-text')
                        failed_reopen_goal = await page.input_value('#handoff-goal')
                        await page.fill('#handoff-cwd', str(projects['b']))
                        await page.click('#handoff-start')
                        await page.wait_for_function("!$('preview').open && !$('task').hidden")
                        await review('b')
                        completed_goal = await page.input_value('#handoff-goal')
                        completed_evidence = await page.input_value('#handoff-text')
                        await page.click('#preview-close')
                        await review('a')
                        retained_source_goal = await page.input_value('#handoff-goal')
                        retained_source_evidence = await page.input_value('#handoff-text')
                        overflow = await page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        await page.click('#preview-close')
                        result = {'width': width, 'cancelledGoal': cancelled_goal,
                                  'sameSourceGoal': same_source_goal,
                                  'sameSourceEvidenceRetained': same_source_evidence == edited_a_evidence,
                                  'failedReopenEvidenceRetained': failed_reopen_evidence == b_evidence,
                                  'failedReopenGoal': failed_reopen_goal,
                                  'completedEvidenceFresh': completed_evidence != b_evidence and not completed_evidence.endswith('Reviewed remaining: run the project B build.'),
                                  'otherSourceEvidenceRetained': retained_source_evidence == edited_a_evidence,
                                  'completedGoal': completed_goal, 'failedStart': failure,
                                  'pendingCommandEvidence': pending_evidence,
                                  'nativeFailureEvidence': failure_evidence,
                                  'retainedSourceGoal': retained_source_goal,
                                  'target': captured[-1], 'mobileOverflow': overflow,
                                  'javascriptErrors': errors}
                        results.append(result)
                        await page.close()
                    receipt = {'cases': results, 'nativeModelTurns': 0}
                    (evidence / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
                    print(json.dumps(receipt, indent=2), flush=True)
                    for result in results:
                        assert result['sameSourceEvidenceRetained'] and result['failedReopenEvidenceRetained'], result
                        assert result['completedEvidenceFresh'] and result['otherSourceEvidenceRetained'], result
                        assert result['failedReopenGoal'] == 'Verify only project B build', result
                        assert result['cancelledGoal'] == '', result
                        assert result['sameSourceGoal'] == 'Change only project A login', result
                        assert result['completedGoal'] == '', result
                        assert result['retainedSourceGoal'] == 'Change only project A login', result
                        assert all(result['pendingCommandEvidence'].values()), result
                        assert all(result['nativeFailureEvidence'].values()), result
                        failure = result['failedStart']
                        assert failure['open'] and failure['errorVisible'], result
                        assert failure['goal'] == 'Verify only project B build', result
                        assert failure['profile'] == 'default' and 'Verified project B evidence' in failure['evidence'], result
                        assert failure['evidence'].endswith('Reviewed remaining: run the project B build.'), result
                        target = result['target']
                        assert target['cwd'] == str(projects['b']), result
                        assert target['text'].startswith('Next task: Verify only project B build\n\n'), result
                        assert 'Verified project B evidence' in target['text'] and 'project A login' not in target['text'], result
                        for value in ('Turn prior-b\nStatus: failed', 'responseStreamDisconnected',
                                      '"httpStatusCode": 503', 'https://relay.example/error'):
                            assert value in target['text'], result
                        for value in ('native-key', 'native-token', 'private-native-metadata',
                                      'private-root-error-metadata'):
                            assert value not in target['text'], result
                        assert not result['javascriptErrors'] and not result['mobileOverflow'], result
                    assert len(captured) == 2 and not desk.runtimes
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
