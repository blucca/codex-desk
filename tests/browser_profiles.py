"""Actual loopback retained-profile edits and modal races, with no inference.

DESK_TEST_TEMP=/your/workspace/temp DESK_CHROMIUM=/path/to/chromium \
  python tests/browser_profiles.py
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import tomllib
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

if not os.environ.get('DESK_USE_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk import server as desk_server
from codex_desk.runtime import save_profile
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    result = {'checks': {}, 'javascriptErrors': [], 'externalRequests': [], 'nativeTurns': 0}
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-profile-edit-') as folder:
        folder = Path(folder)
        home, project = folder / 'home', folder / 'project'
        home.mkdir()
        project.mkdir()
        (home / 'config.toml').write_text('model = "current-model"\n')
        (home / 'auth.json').write_text('{"fixture": "not-used"}\n')
        (home / 'manual.config.toml').write_text(
            'model = "manual-model"\nmodel_provider = "manual"\n'
            '[model_providers.manual]\nbase_url = "https://manual.example/v1"\n'
            'env_key = "MANUAL_KEY"\n')
        save_profile(home, 'retained', 'https://original.example/v1', 'original-model',
                     'synthetic-original-key')
        save_profile(home, 'default', 'https://file-default.example/v1', 'file-default-model',
                     'synthetic-file-default-key')
        unchanged = {name: (home / name).read_bytes()
                     for name in ('config.toml', 'auth.json', 'manual.config.toml')}
        desk = desk_server.Desk('never-executed', home, folder / 'state')
        for identifier, profile in (('project-session', 'sidecar:retained'), ('legacy-session', 'retained'),
                                    ('current-session', 'default')):
            desk.store.create(str(project), profile, identifier, 'Saved ' + identifier)
            desk.store.update(identifier, thread_id='native-' + identifier, status='ready', thread_saved=1)
            desk.runtimes[identifier] = SimpleNamespace(
                process=SimpleNamespace(poll=lambda: None), approvals={}, close=lambda: None,
                thread_result={'thread': {'id': 'native-' + identifier, 'turns': []}})
        bindings = desk.store.sessions()
        calls, holds = [], {}
        original_update = desk_server.update_profile

        def controlled_update(native_home, identifier, endpoint, model, key=''):
            calls.append({'id': identifier, 'endpoint': endpoint, 'model': model, 'keySubmitted': bool(key)})
            if model in holds:
                entered, release = holds[model]
                entered.set()
                if not release.wait(20):
                    raise RuntimeError('Controlled profile request was not released')
            return original_update(native_home, identifier, endpoint, model, key)

        def saved():
            return tomllib.loads((home / 'retained.config.toml').read_text())

        def update_response(response):
            return urlsplit(response.url).path == '/api/profiles/update' and response.request.method == 'POST'

        server = desk_server.ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.object(desk_server, 'update_profile', controlled_update):
                async with async_playwright() as p:
                    browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                        headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                    try:
                        page = await browser.new_page(viewport={'width': 390, 'height': 844})
                        page.on('pageerror', lambda error: result['javascriptErrors'].append(str(error)))
                        http_calls = []

                        def requested(request):
                            route = urlsplit(request.url)
                            http_calls.append((request.method, route.path))
                            if route.hostname != '127.0.0.1':
                                result['externalRequests'].append(request.url)

                        page.on('request', requested)
                        await page.goto(f'http://127.0.0.1:{server.server_port}')
                        await page.wait_for_function('state.profiles.length === 4')
                        await page.locator('#sessions button').filter(has_text='Saved project-session').click()
                        await page.wait_for_function("!opening && !$('task').hidden")
                        await page.locator('#prompt').fill('Unsent project verification draft')

                        async def manage():
                            if not await page.locator('#profiles-dialog').evaluate('(d) => d.open'):
                                await page.locator('#manage-profiles').click()
                            await page.wait_for_function("$('profiles-dialog').open")

                        async def edit(profile='sidecar:retained'):
                            await manage()
                            await page.locator('[data-profile="' + profile + '"] button').click()
                            await page.wait_for_function("$('provider').open")

                        async def cancel():
                            await page.locator('#provider-close').click()
                            await page.wait_for_function(
                                "!$('provider').open && $('provider-key').value === '' && $('profiles-dialog').open")

                        async def form():
                            return await page.evaluate("""() => ({open:$('provider').open,
                                name:$('provider-name').value,nameReadOnly:$('provider-name').readOnly,
                                endpoint:$('provider-endpoint').value,model:$('provider-model').value,
                                key:$('provider-key').value,keyRequired:$('provider-key').required,
                                saveEnabled:!$('provider-save').disabled,error:$('provider-error').textContent,
                                errorVisible:!$('provider-error').hidden,globalErrorHidden:$('error').hidden,
                                draft:$('prompt').value})""")

                        async def layout(label):
                            check = await page.evaluate("""() => {
                                const d=document.querySelector('dialog[open]'),r=d?.getBoundingClientRect();
                                return {viewport:innerWidth,pageOverflow:document.documentElement.scrollWidth>innerWidth,
                                    dialogOverflow:!!d&&d.scrollWidth>d.clientWidth+1,
                                    dialogInViewport:!!r&&r.left>=0&&r.right<=innerWidth};
                            }""")
                            result['checks'][label] = check
                            assert not check['pageOverflow'] and not check['dialogOverflow'] \
                                and check['dialogInViewport'], check

                        await manage()
                        rows = await page.locator('#profiles-list .native-row').evaluate_all("""rows => rows.map(r => ({
                            id:r.dataset.profile,text:r.textContent,edits:r.querySelectorAll('button').length}))""")
                        result['checks']['profileCatalog'] = rows
                        by_id = {row['id']: row for row in rows}
                        assert by_id['default']['edits'] == 0 and by_id['sidecar:manual']['edits'] == 0, rows
                        assert '1 saved session' in by_id['default']['text'] \
                            and '0 saved sessions' in by_id['sidecar:default']['text'], rows
                        assert by_id['sidecar:retained']['edits'] == 1 \
                            and '2 saved sessions' in by_id['sidecar:retained']['text'], rows
                        await layout('manage390')
                        await edit('sidecar:default')
                        await page.locator('#provider-model').fill('file-default-edited')
                        async with page.expect_response(update_response) as response:
                            await page.locator('#provider-save').click()
                        default_result = await (await response.value).json()
                        await page.wait_for_function("!$('provider').open && $('profiles-dialog').open")
                        result['checks']['defaultFileDistinctFromCurrentSettings'] = \
                            default_result['id'] == 'sidecar:default' and default_result['restartRequired'] is False
                        assert result['checks']['defaultFileDistinctFromCurrentSettings'], default_result
                        assert tomllib.loads((home / 'default.config.toml').read_text()) \
                            ['model_providers']['desk_provider']['experimental_bearer_token'] == 'synthetic-file-default-key'
                        assert 'New native sessions' in await page.locator('#profiles-notice').inner_text()
                        await edit()
                        initial = await form()
                        result['checks']['initialEdit'] = initial
                        assert initial['name'] == 'retained' and initial['nameReadOnly'] \
                            and initial['key'] == '' and not initial['keyRequired'], initial
                        assert initial['endpoint'] == 'https://original.example/v1' \
                            and initial['model'] == 'original-model', initial
                        endpoint = 'https://updated.example/v1/' + 'long-task-path-' * 15
                        await page.locator('#provider-endpoint').fill(endpoint)
                        await page.locator('#provider-model').fill('updated-model')
                        await layout('edit390')
                        async with page.expect_response(update_response) as response:
                            await page.locator('#provider-save').click()
                        assert (await response.value).status == 200
                        await page.wait_for_function("!$('provider').open && $('profiles-dialog').open")
                        await page.wait_for_function("state.profiles.find(p=>p.id==='sidecar:retained').model==='updated-model'")
                        data = saved()
                        result['checks']['blankKeyPreservesSecret'] = \
                            data['model_providers']['desk_provider']['experimental_bearer_token'] == 'synthetic-original-key'
                        assert result['checks']['blankKeyPreservesSecret'] and data['model'] == 'updated-model', data
                        assert data['model_providers']['desk_provider']['base_url'] == endpoint, data
                        assert 'Stop Desk and relaunch' in await page.locator('#profiles-notice').inner_text()

                        await edit()
                        await page.locator('#provider-model').fill('rotated-model')
                        await page.locator('#provider-key').fill('synthetic-rotated-key')
                        async with page.expect_response(update_response) as response:
                            await page.locator('#provider-save').click()
                        assert (await response.value).status == 200
                        await page.wait_for_function("!$('provider').open && $('profiles-dialog').open")
                        await page.wait_for_function("state.profiles.find(p=>p.id==='sidecar:retained').model==='rotated-model'")
                        result['checks']['keyRotation'] = \
                            saved()['model_providers']['desk_provider']['experimental_bearer_token'] == 'synthetic-rotated-key'
                        assert result['checks']['keyRotation']

                        await edit()
                        before_failure = (home / 'retained.config.toml').read_bytes()
                        await page.locator('#provider-endpoint').fill('ftp://invalid.example/v1')
                        await page.locator('#provider-model').fill('retry-model')
                        await page.locator('#provider-key').fill('synthetic-rejected-key')
                        async with page.expect_response(update_response) as response:
                            await page.locator('#provider-save').click()
                        assert (await response.value).status == 400
                        await page.wait_for_function("!$('provider-save').disabled && !$('provider-error').hidden")
                        failed = await form()
                        result['checks']['invalidEndpoint'] = failed
                        assert failed['open'] and failed['errorVisible'] and failed['error'] \
                            and failed['globalErrorHidden'] and failed['saveEnabled'], failed
                        assert failed['endpoint'] == 'ftp://invalid.example/v1' \
                            and failed['model'] == 'retry-model' and failed['key'] == '', failed
                        assert (home / 'retained.config.toml').read_bytes() == before_failure
                        await page.locator('#provider-key').fill('synthetic-escape-key')
                        await page.locator('#provider-key').press('Escape')
                        await page.wait_for_function(
                            "!$('provider').open && $('provider-key').value === '' && $('profiles-dialog').open")
                        await edit()
                        reopened = await form()
                        result['checks']['escapeAndReopen'] = reopened
                        assert reopened['nameReadOnly'] and reopened['key'] == '' and not reopened['keyRequired'] \
                            and not reopened['errorVisible'] and reopened['endpoint'] == endpoint \
                            and reopened['model'] == 'rotated-model', reopened
                        await cancel()

                        for model, delayed_endpoint, status in (
                            ('held-success', 'https://held.example/v1', 200),
                            ('held-failure', 'ftp://held.example/v1', 400)):
                            entered, release = threading.Event(), threading.Event()
                            holds[model] = (entered, release)
                            await edit()
                            await page.locator('#provider-endpoint').fill(delayed_endpoint)
                            await page.locator('#provider-model').fill(model)
                            await page.locator('#provider-key').fill('synthetic-old-request-key')
                            await page.locator('#provider-save').click()
                            assert await asyncio.to_thread(entered.wait, 5), 'Update did not enter its controlled hold'
                            assert await page.locator('#provider-key').input_value() == ''
                            await cancel()
                            await page.locator('#profiles-add').click()
                            await page.wait_for_function("$('provider').open")
                            for name, value in (('name', 'new-profile-draft'),('endpoint', 'https://next.example/v1'),
                                                ('model', 'new-model-draft'),('key', 'synthetic-new-form-key')):
                                await page.locator('#provider-' + name).fill(value)
                            async with page.expect_response(update_response) as response:
                                release.set()
                            completed = await response.value
                            assert completed.status == status
                            await completed.body()
                            if status == 200:
                                await page.wait_for_function(
                                    "state.profiles.find(p=>p.id==='sidecar:retained').model==='held-success'")
                            await page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
                            newer = await form()
                            result['checks'][model + 'KeepsNewForm'] = newer
                            assert newer['open'] and newer['saveEnabled'] and not newer['nameReadOnly'] \
                                and newer['keyRequired'] and not newer['errorVisible'], newer
                            assert newer['name'] == 'new-profile-draft' and newer['model'] == 'new-model-draft' \
                                and newer['endpoint'] == 'https://next.example/v1' \
                                and newer['key'] == 'synthetic-new-form-key' \
                                and newer['draft'] == 'Unsent project verification draft', newer
                            await cancel()

                        await page.set_viewport_size({'width': 1280, 'height': 900})
                        await manage()
                        await layout('manage1280')
                        await edit()
                        await layout('edit1280')
                        await page.screenshot(path=str(root / 'profile-edit-1280.png'), full_page=True)
                        await page.set_viewport_size({'width': 390, 'height': 844})
                        await layout('finalEdit390')
                        await page.screenshot(path=str(root / 'profile-edit-390.png'), full_page=True)
                        await cancel()
                        result['checks']['savedBindingsUnchanged'] = desk.store.sessions() == bindings
                        result['checks']['currentAuthCustomUnchanged'] = \
                            all((home / name).read_bytes() == content for name, content in unchanged.items())
                        result['checks']['privateProfileMode'] = (home / 'retained.config.toml').stat().st_mode & 0o777 == 0o600
                        browser_data = await page.evaluate("""() => JSON.stringify({state,
                            localStorage:{...localStorage},sessionStorage:{...sessionStorage},
                            body:document.body.textContent,key:$('provider-key').value})""")
                        result['checks']['secretsAbsentFromBrowserState'] = \
                            not any(key in browser_data for key in ('synthetic-original-key', 'synthetic-rotated-key',
                                                                    'synthetic-file-default-key',
                                                                    'synthetic-old-request-key', 'synthetic-new-form-key'))
                        result['profileUpdates'] = calls
                        result['inferenceRequests'] = sum(path in ('/api/turn', '/api/handoff/start', '/api/sessions')
                                                          for method, path in http_calls)
                        assert result['checks']['savedBindingsUnchanged'] \
                            and result['checks']['currentAuthCustomUnchanged'] \
                            and result['checks']['privateProfileMode'] \
                            and result['checks']['secretsAbsentFromBrowserState'], result
                        assert result['inferenceRequests'] == 0 and not result['javascriptErrors'] \
                            and not result['externalRequests'], result
                    finally:
                        await browser.close()
        finally:
            for entered, release in holds.values():
                release.set()
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()
            desk.close()
            desk.store.db.close()
            print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    asyncio.run(check())
