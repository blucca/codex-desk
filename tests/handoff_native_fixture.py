"""Controlled native boundary; real Desk admission, receipts and SQLite stay live."""
from types import SimpleNamespace
import threading
from codex_desk.runtime import NativeRequestRejected, NativeRequestUnknown


class HandoffNative:
    def __init__(self, desk, histories=None):
        self.desk = desk
        self.histories = histories or {}
        self.calls = []
        self.starts = []
        self.mode = 'accepted'
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        desk.runtime = self.runtime
        desk.open = self.open
        desk.history = lambda native: self.histories[native]

    def hold(self, mode='accepted'):
        self.mode = mode
        self.entered.clear()
        self.release.clear()

    def runtime(self, identifier):
        desk = self.desk
        if identifier not in desk.runtimes:
            self.calls.append({'operation': 'native-open', 'session': identifier})
            desk.store.update(identifier, thread_id='created-' + identifier,
                              status='ready', model='fixture', thread_saved=1)
            owner = self

            class Loaded:
                def __init__(self):
                    self.process = SimpleNamespace(poll=lambda: None)
                    self.approvals = {}

                def close(self):
                    self.process.poll = lambda: 0

                def turn(self, text, mode):
                    start = {'session': identifier, 'cwd': desk.store.get(identifier)['cwd'],
                             'text': text, 'mode': mode}
                    owner.starts.append(start)
                    owner.calls.append({'operation': 'native-start', **start})
                    selected_mode = owner.mode
                    owner.entered.set()
                    assert owner.release.wait(30), 'Held native admission not released'
                    if selected_mode == 'unknown':
                        raise NativeRequestUnknown('Native admission reply was not confirmed')
                    if selected_mode == 'rejected':
                        raise NativeRequestRejected('Native rejected the task before start')
                    turn = {'id': 'turn-' + identifier + '-' + str(len(owner.starts)),
                            'status': 'completed'}
                    owner.histories['created-' + identifier] = {
                        'id': 'created-' + identifier, 'cwd': start['cwd'], 'turns': [
                            {**turn, 'items': [{'id': 'answer-' + turn['id'],
                                              'type': 'agentMessage', 'text': 'Controlled accepted proof'}]}]}
                    desk.store.update(identifier, status='completed')
                    return {'turn': turn}

            desk.runtimes[identifier] = Loaded()
        return desk.runtimes[identifier]

    def open(self, identifier):
        row = self.desk.store.get(identifier)
        native = row['thread_id']
        return {'thread': self.histories.get(native, {'id': native, 'cwd': row['cwd'], 'turns': []}),
                'model': 'fixture', 'modelProvider': 'fixture'}
