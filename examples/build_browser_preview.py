#!/usr/bin/env python3
"""Build a static, sample-only preview from the maintained Desk browser assets."""
import argparse
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = 'https://blucca.github.io/codex-desk/demo/'
READING_KEY = 'codex-desk-browser-preview-reading-checkpoints-v1'
ORIGINAL_READING_KEY = 'codex-desk-browser-preview-original-reading-checkpoints-v1'
ORIGINAL_FRONTIER_KEY = 'codex-desk-browser-preview-original-frontiers-v1'
REVIEW_KEY = 'codex-desk-browser-preview-activity-review-v1'
CHILD = 'sample-child-thread'
CHILD_TURN = 'sample-child-turn'
CHILD_ITEM = 'sample-child-answer'
CHILD_QUOTE = 'Child decisive evidence — café🙂 项目 exact source.'


def linked_item():
    return {'id': 'sample-checkout-collaboration', 'type': 'collabAgentToolCall',
            'tool': 'spawnAgent', 'status': 'completed', 'senderThreadId': 'sample-checkout-thread',
            'receiverThreadIds': [CHILD], 'prompt': 'Inspect the sample retry result only.',
            'agentsStates': {CHILD: {'status': 'completed', 'message': 'Sample child result retained.'}}}


def child_original():
    text = 'CHILD START\n' + '\n'.join(
        f'Child source line {n:04d} — retain the captured retry instruction and independent original.'
        + (' ' + CHILD_QUOTE if n in (50, 900) else '') for n in range(1200)) + '\nCHILD END'
    return {'id': CHILD, 'name': 'Sample linked retry original', 'archived': True, 'cwd': '/sample/projects/checkout-child',
            'cwdExists': False, 'modelProvider': 'sample', 'updatedAt': 1795649999,
            'turns': [{'id': CHILD_TURN, 'status': 'completed', 'items': [
                {'id': 'sample-child-question', 'type': 'userMessage', 'content': [{'type': 'text',
                 'text': 'Inspect the reported retry result and retain the decisive original evidence.'}]},
                {'id': CHILD_ITEM, 'type': 'agentMessage', 'phase': 'final_answer', 'text': text},
                {'id': 'sample-child-evidence', 'type': 'commandExecution', 'command': 'printf sample-child',
                 'status': 'completed', 'exitCode': 0,
                 'aggregatedOutput': 'Sample child command evidence: independent original — café🙂.'}]}]}


def sample_threads():
    projects = [
        ('checkout', 'Sample checkout retry decision', 'Keep the retry budget at two attempts. Retry only transient failures; preserve the original timeout result.'),
        ('docs', 'Sample documentation review', 'The installation section should show the launch command before configuration details.'),
        ('mobile', 'Sample mobile layout check', 'At 390 pixels, keep the next-task buttons visible and let long paths wrap.')]
    result = []
    for name, title, answer in projects:
        result.append({'id': f'sample-{name}-thread', 'name': title, 'cwd': f'/sample/projects/{name}',
            'cwdExists': True, 'modelProvider': 'sample', 'updatedAt': 1795650000,
            'turns': [{'id': f'sample-{name}-turn', 'status': 'completed', 'items': [
                {'id': f'sample-{name}-question', 'type': 'userMessage', 'content': [{'type': 'text', 'text': f'Review the {name} decision and retain one useful next step.'}]},
                {'id': f'sample-{name}-answer', 'type': 'agentMessage', 'text': answer},
                {'id': f'sample-{name}-evidence', 'type': 'commandExecution', 'command': f'printf sample-{name}',
                 'status': 'completed', 'exitCode': 0,
                 'aggregatedOutput': f'Sample {name} command evidence: retained result — café🙂.'}]}]})
    result[0]['turns'][0]['items'].append(linked_item())
    result.append(child_original())
    return result


def reading_fixture():
    """Synthetic source-only inputs for the maintained session-reading checker."""
    threads = sample_threads()
    prior = threads[0]['turns'][0]
    prior['items'][2]['aggregatedOutput'] = '\n'.join(
        f'Sample command line {n:04d} — café 项目 🌱 retains its original result.' for n in range(950))
    prior['items'].insert(-1,
        {'id': 'sample-checkout-mcp', 'type': 'mcpToolCall', 'server': 'sample',
         'tool': 'read_saved_result', 'status': 'completed', 'arguments': {'project': 'checkout'},
         'result': {'content': [{'type': 'text', 'text': '\n'.join(
             f'Sample MCP line {n:04d} — original retained result.' for n in range(650))}]}})
    live = 'sample-checkout-live-turn'
    threads[0]['turns'].append({'id': live, 'status': 'inProgress', 'items': [
        {'id': 'sample-checkout-live-output', 'type': 'agentMessage', 'text': '\n'.join(
            f'Current sample output paragraph {n}' for n in range(60))}]})
    a, b = 'desk-' + threads[0]['id'], 'desk-' + threads[1]['id']
    pending = {'id': 801, 'method': 'item/tool/requestUserInput', 'params': {
        'threadId': threads[1]['id'], 'turnId': threads[1]['turns'][0]['id'], 'itemId': 'sample-docs-question',
        'questions': [
            {'id': 'sample-answer', 'header': 'Sample B answer', 'question': 'What check should remain?', 'isOther': True},
            {'id': 'sample-choice', 'header': 'Sample B choice', 'question': 'Which scope?', 'isOther': False,
             'options': [{'label': 'Keep existing scope', 'description': 'Retain the check'},
                         {'label': 'Different scope', 'description': 'Separate next work'}]}]}}
    events = [{'method': 'turn/started', 'params': {'threadId': threads[0]['id'], 'turn': {'id': live, 'status': 'inProgress'}}},
        {'method': 'turn/plan/updated', 'params': {'threadId': threads[0]['id'], 'turnId': live,
            'explanation': 'Reported sample steps remain separate from the unsent Plan.',
            'plan': [{'step': f'Sample verification step {n}', 'status': 'inProgress' if n == 3 else 'pending'} for n in range(55)]}},
        {'method': 'turn/diff/updated', 'params': {'threadId': threads[0]['id'], 'turnId': live,
            'diff': '\n'.join(f'+ Retained sample patch line {n}' for n in range(150))}}]
    return threads, {'pending': {b: [pending]}, 'events': {a: [{'seq': n + 1, 'event': event} for n, event in enumerate(events)]}}


def build(output, embedded=False, session_reading_fixture=False):
    output.mkdir(parents=True, exist_ok=True)
    assets = ROOT / 'codex_desk/static'
    for source in assets.iterdir():
        if source.is_file():
            shutil.copyfile(source, output / source.name)
    html = (assets / 'index.html').read_text()
    html = re.sub(r'(src|href)="/([^"/]+)"', r'\1="./\2"', html)
    html = html.replace('<title>Codex Desk</title>', '<title>Try Codex Desk — interactive browser sample</title><meta name="description" content="Find the sample retry decision, read its task response and own command result. Try the real interface without installing; preparation and return are optional."><link rel="canonical" href="'+PUBLIC+'">')
    banner = '''<section id="preview-banner" aria-label="Browser sample preview"><div><strong>Codex Desk · find an earlier investigation · sample preview</strong><p>First task: <b>Find the sample answer</b> → <b>Index existing Codex history</b> → <b>Search</b> → <b>Read original conversation</b>. Read the <b>retry budget</b> response, then <b>Read containing task</b> → <b>Read this task’s evidence</b> to inspect <code>printf sample-checkout</code> and its reported result.</p><p>For your own investigation, use its original evidence to decide which check to change or skip. Continuing, saving a draft and reloading to return are optional.</p><details><summary>Optional original-review rehearsals</summary><p>Have a source ID? In <b>Browse existing Codex sessions</b>, read <code>sample-child-thread</code> by ID. Open its task context and find <code>reported retry result</code> in supplied instructions.</p><p>Revisit: choose <b>Archived native conversations</b>, search <b>linked retry original</b>, read its later passage, close it, then explicitly reopen by title or known ID. Reload keeps the reading place, not an open original.</p><p>Follow this synthetic original: read <b>Sample linked retry original</b>, close it, choose <b>Add sample original items</b>, then deliberately read it again. <b>Read first newly supplied item</b> opens the exact new native item; <b>Return to original passage</b> returns to your prior place, including after a narrow/wide resize. “New” compares supplied identities with the previous fresh original read.</p><p>Skim a longer supplied task chain: choose <b>Prepare sample task review</b>, read <code>sample-child-thread</code>, open <b>Task overview</b>, page to supplied task 42, then <b>Read this task’s evidence</b>. Task-scoped Find finds its own tool result; choose <b>Whole original conversation</b> to compare the three exact occurrences.</p><p>Find which conversation contains the answer: choose <b>Prepare sample conversation search</b>, index explicitly, and search <code>Retry discovery Café 项目 😀</code>. Check <b>Group matches by conversation</b> to choose the distinct original before inspecting its exact matching item. Return keeps your selected task and preparation.</p></details><p>Sample conversations and preparation stay in this browser. The installed workbench uses your own Codex history and local database.</p></div><nav aria-label="Preview actions"><button id="preview-start" type="button">Find the sample answer</button><a href="https://github.com/blucca/codex-desk#install-the-preview">Install for your own work</a><a href="https://github.com/blucca/codex-desk/issues/new?template=browser-preview.yml">Share sample feedback</a><button id="preview-supply-original" type="button">Add sample original items</button><button id="preview-group-prepare" type="button">Prepare sample conversation search</button><button id="preview-tasks-prepare" type="button">Prepare sample task review</button><button id="preview-header-prepare" type="button">Prepare sample command output</button><button id="preview-header-toggle" type="button" hidden>Complete sample command</button><button id="preview-reset" type="button">Reset sample</button></nav><p id="preview-notice" role="status"></p></section>'''
    html = html.replace('<body>', '<body>'+banner)
    html = html.replace('id="history-reader-refresh"', 'id="preview-header-reader-toggle" hidden>Complete sample command</button><button type="button" id="history-reader-refresh"')
    if embedded:
        html = html.replace('<html lang="en">', '<html lang="en" data-preview-embedded="true">')
        html = html.replace('<a href="https://github.com/', '<a target="_blank" rel="noopener noreferrer" href="https://github.com/')
    html = html.replace('</head>', '<link rel="stylesheet" href="./preview.css"><script src="./sample-data.js"></script><script src="./preview-api.js"></script></head>')
    html = html.replace('◈ Codex Desk <span>LOCAL</span>', '◈ Codex Desk <span>SAMPLE</span>')
    html = html.replace('Your projects. Your providers.<br>Your actual Codex sessions.', 'Sample projects.<br>Try finding and preparing work.')
    html = html.replace('Native Codex does the work.<br>Settings stay local. Keys are handled by native Codex.', 'Interactive sample · preparation only.<br>Install Desk to run your own native tasks.')
    html = html.replace('Runs in the selected project with native Codex permissions.', 'Save preparation here; run native tasks in the installed workbench.')
    html = html.replace('id="send">Run task', 'id="send">Install to run tasks')
    html = html.replace('id="followup-send">Send next', 'id="followup-send">Install to send next')
    (output / 'index.html').write_text(html)
    # Namespace only the preview selection; remaining app behavior is maintained source.
    app = (output / 'app.js').read_text().replace("'codex-desk-session'", "'codex-desk-browser-preview-session-v1'")
    (output / 'app.js').write_text(app)
    checkpoint = output / 'reading_checkpoint.js'
    if checkpoint.exists():
        checkpoint.write_text(checkpoint.read_text().replace("'codex-desk-reading-checkpoints-v1'", repr(READING_KEY)).replace("'codex-desk-original-reading-checkpoints-v1'", repr(ORIGINAL_READING_KEY)))
    frontier = output / 'original_frontier.js'
    if frontier.exists():
        frontier.write_text(frontier.read_text().replace("'codex-desk-original-frontiers-v1'", repr(ORIGINAL_FRONTIER_KEY)))
    review = output / 'new-activity.js'
    if review.exists():
        review.write_text(review.read_text().replace("'codex-desk-activity-review-v1'", repr(REVIEW_KEY)))
    for name in ('preview-api.js', 'preview.css'):
        shutil.copyfile(ROOT / 'examples/browser-preview' / name, output / name)
    casefold = {chr(n): chr(n).casefold() for n in range(0x110000) if chr(n).casefold() != chr(n).lower()}
    threads, fixture = reading_fixture() if session_reading_fixture else (sample_threads(), None)
    data = 'window.DeskPreviewThreads = '+json.dumps(threads, ensure_ascii=False)+';\nwindow.DeskPreviewCasefold = '+json.dumps(casefold, ensure_ascii=False)+';\n'
    if fixture:
        data += 'window.DeskPreviewReadingFixture = '+json.dumps(fixture, ensure_ascii=False)+';\n'
        shutil.copyfile(ROOT / 'examples/browser-preview/session-reading-fixture.js', output / 'session-reading-fixture.js')
        html = html.replace('<script src="./preview-api.js">', '<script src="./session-reading-fixture.js"></script><script src="./preview-api.js">')
        (output / 'index.html').write_text(html)
    (output / 'sample-data.js').write_text(data)
    (output / 'preview-source.json').write_text(json.dumps({'source': 'blucca/codex-desk', 'runtime_version': re.search(r'__version__\s*=\s*[\"\']([^\"\']+)', (ROOT / 'codex_desk/__init__.py').read_text())[1], 'sample': True, 'assets': sorted(x.name for x in assets.iterdir() if x.is_file()), 'build': 'python3 examples/build_browser_preview.py --out OUTPUT'}, indent=2)+'\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path.cwd() / 'temp/browser-preview/demo')
    parser.add_argument('--embedded', action='store_true', help='Open installer links separately when hosted in an iframe')
    parser.add_argument('--session-reading-fixture', action='store_true', help='Build synthetic long sources and pending input for session-reading acceptance')
    args = parser.parse_args()
    print(build(args.out.resolve(), embedded=args.embedded, session_reading_fixture=args.session_reading_fixture))
