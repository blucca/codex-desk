#!/usr/bin/env python3
"""Build a static, sample-only preview from the maintained Desk browser assets."""
import argparse
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = 'https://blucca.github.io/codex-desk/demo/'


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
    return result


def build(output, embedded=False):
    output.mkdir(parents=True, exist_ok=True)
    assets = ROOT / 'codex_desk/static'
    for source in assets.iterdir():
        if source.is_file():
            shutil.copyfile(source, output / source.name)
    html = (assets / 'index.html').read_text()
    html = re.sub(r'(src|href)="/([^"/]+)"', r'\1="./\2"', html)
    html = html.replace('<title>Codex Desk</title>', '<title>Try Codex Desk — interactive browser sample</title><meta name="description" content="Find a sample Codex answer, read its original context, prepare the next task and reload to return. Try the real interface without installing."><link rel="canonical" href="'+PUBLIC+'">')
    banner = '''<section id="preview-banner" aria-label="Browser sample preview"><div><strong>Codex Desk · interactive sample preview</strong><p>Try: Find a decision → search <b>retry budget</b> → Index history → Read original → Continue → save a Plan draft → reload.</p><p>Sample conversations and preparation stay in this browser. The installed workbench uses your own Codex history and local database.</p></div><nav aria-label="Preview actions"><button id="preview-start" type="button">Find the sample answer</button><a href="https://github.com/blucca/codex-desk#install-the-preview">Install for your own work</a><a href="https://github.com/blucca/codex-desk/issues/new?template=browser-preview.yml">Share sample feedback</a><button id="preview-reset" type="button">Reset sample</button></nav><p id="preview-notice" role="status"></p></section>'''
    html = html.replace('<body>', '<body>'+banner)
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
    for name in ('preview-api.js', 'preview.css'):
        shutil.copyfile(ROOT / 'examples/browser-preview' / name, output / name)
    casefold = {chr(n): chr(n).casefold() for n in range(0x110000) if chr(n).casefold() != chr(n).lower()}
    (output / 'sample-data.js').write_text('window.DeskPreviewThreads = '+json.dumps(sample_threads(), ensure_ascii=False)+';\nwindow.DeskPreviewCasefold = '+json.dumps(casefold, ensure_ascii=False)+';\n')
    (output / 'preview-source.json').write_text(json.dumps({'source': 'blucca/codex-desk', 'runtime_version': re.search(r'__version__\s*=\s*[\"\']([^\"\']+)', (ROOT / 'codex_desk/__init__.py').read_text())[1], 'sample': True, 'assets': sorted(x.name for x in assets.iterdir() if x.is_file()), 'build': 'python3 examples/build_browser_preview.py --out OUTPUT'}, indent=2)+'\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT.parents[1] / 'temp/round122-preview/site/demo')
    parser.add_argument('--embedded', action='store_true', help='Open installer links separately when hosted in an iframe')
    args = parser.parse_args()
    print(build(args.out.resolve(), embedded=args.embedded))
