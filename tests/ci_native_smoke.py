"""Installed native launcher/profile smoke on actual runner OS; no model turns."""
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from codex_desk.runtime import Runtime, save_profile
from codex_desk.server import Desk, resolve_codex

root = Path(os.environ.get('DESK_TEST_TEMP', 'temp')).resolve()
root.mkdir(parents=True, exist_ok=True)
methods = []
original = Runtime.request


def metadata_only(self, method, params, *args, **kwargs):
    if method not in ('initialize', 'thread/start'):
        raise AssertionError('Unexpected native operation: ' + method)
    methods.append(method)
    return original(self, method, params, *args, **kwargs)


with tempfile.TemporaryDirectory(dir=root, prefix='desk-native-runner-') as folder:
    base = Path(folder)
    home, project = base / 'native home', base / 'project with spaces'
    home.mkdir(); project.mkdir()
    config, auth = home / 'config.toml', home / 'auth.json'
    config.write_text('model = "gpt-6.2"\n', encoding='utf-8')
    auth.write_text('{"OPENAI_API_KEY":"synthetic-smoke-key"}', encoding='utf-8')
    before = (config.read_bytes(), auth.read_bytes())
    save_profile(home, 'default', 'https://example.invalid/v1', 'gpt-6.2', 'synthetic-profile-key')
    binary = resolve_codex(os.environ.get('DESK_CODEX', 'codex'))
    desk = Desk(binary, home, base / 'state')
    try:
        with patch.object(Runtime, 'request', metadata_only):
            current = desk.create(str(project), 'default')['id']
            retained = desk.create(str(project), 'sidecar:default')['id']
        current_row, retained_row = desk.store.get(current), desk.store.get(retained)
        assert current_row['provider'] == 'openai', current_row['provider']
        assert retained_row['provider'] == 'desk_provider', retained_row['provider']
        assert retained_row['model'] == 'gpt-6.2'
        assert current_row['thread_id'] != retained_row['thread_id']
        assert Path(retained_row['cwd']).resolve() == project.resolve()
        assert (config.read_bytes(), auth.read_bytes()) == before
        for runtime in desk.runtimes.values():
            assert 'synthetic-profile-key' not in repr(runtime.process.args)
        receipt = {'platform': sys.platform, 'python': sys.version.split()[0],
                   'version': importlib.metadata.version('codex-desk'),
                   'launcher': binary, 'nativeMethods': methods,
                   'currentAndSidecarDefaultDistinct': True,
                   'projectWithSpaces': True, 'configAndAuthUnchanged': True,
                   'providerInference': 0}
        print(json.dumps(receipt, indent=2))
    finally:
        desk.close(); desk.store.db.close()
