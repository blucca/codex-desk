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
                        await page.click('#preview-close')
                        await review('a')
                        same_source_goal = await page.input_value('#handoff-goal')
                        await page.click('#preview-close')
                        await review('b')
                        cancelled_goal = await page.input_value('#handoff-goal')
                        b_evidence = await page.input_value('#handoff-text')
                        pending_evidence = {
                            'command': pending_command['command'] in b_evidence,
                            'status': 'Status: inProgress' in b_evidence,
                            'exit': 'Exit: not reported' in b_evidence,
                            'output': '[No command output reported.]' in b_evidence}
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
                        await page.fill('#handoff-cwd', str(projects['b']))
                        await page.click('#handoff-start')
                        await page.wait_for_function("!$('preview').open && !$('task').hidden")
                        await review('b')
                        completed_goal = await page.input_value('#handoff-goal')
                        await page.click('#preview-close')
                        await review('a')
                        retained_source_goal = await page.input_value('#handoff-goal')
                        overflow = await page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        await page.click('#preview-close')
                        result = {'width': width, 'cancelledGoal': cancelled_goal,
                                  'sameSourceGoal': same_source_goal,
                                  'completedGoal': completed_goal, 'failedStart': failure,
                                  'pendingCommandEvidence': pending_evidence,
                                  'retainedSourceGoal': retained_source_goal,
                                  'target': captured[-1], 'mobileOverflow': overflow,
                                  'javascriptErrors': errors}
                        results.append(result)
                        await page.close()
                    receipt = {'cases': results, 'nativeModelTurns': 0}
                    (evidence / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
                    print(json.dumps(receipt, indent=2), flush=True)
                    for result in results:
                        assert result['cancelledGoal'] == '', result
                        assert result['sameSourceGoal'] == 'Change only project A login', result
                        assert result['completedGoal'] == '', result
                        assert result['retainedSourceGoal'] == 'Change only project A login', result
                        assert all(result['pendingCommandEvidence'].values()), result
                        failure = result['failedStart']
                        assert failure['open'] and failure['errorVisible'], result
                        assert failure['goal'] == 'Verify only project B build', result
                        assert failure['profile'] == 'default' and 'Verified project B evidence' in failure['evidence'], result
                        assert failure['evidence'].endswith('Reviewed remaining: run the project B build.'), result
                        target = result['target']
                        assert target['cwd'] == str(projects['b']), result
                        assert target['text'].startswith('Next task: Verify only project B build\n\n'), result
                        assert 'Verified project B evidence' in target['text'] and 'project A login' not in target['text'], result
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
