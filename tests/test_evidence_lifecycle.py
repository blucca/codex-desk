"""Exact evidence text through ordinary drafts, queues and Run request receipts.

HTTP, SQLite, request capture and Runtime reduction use product code. Only the
native turn transport is supplied by the maintained integration fixture.
"""
import copy
from pathlib import Path

from codex_desk.drafts import load_draft, save_draft
from codex_desk.evidence_reference import (
    append_evidence_block, capture_reference, format_evidence_block,
    parse_evidence_blocks, resolve_reference,
)
from codex_desk.followups import (
    edit_followup, followup_snapshot, record_followup_receipt, reserve_followup,
)
from codex_desk.preparation import preparation_snapshot
from codex_desk.runtime import Store
from codex_desk.server import Desk
from native_request_fixture import NativeRequestFixture

QUOTE = 'Retry budget: café\u0301🙂 — 2 attempts.'

class EvidenceLifecycleTests(NativeRequestFixture):
    def setUp(self):
        super().setUp()
        folder = self.path / 'removed-source-A'
        folder.mkdir(); folder.rmdir()
        text = 'Before🙂 ' + QUOTE + '\nLater decision: ' + QUOTE + '\nAfter'
        self.source = {'id': 'native-source-A', 'name': 'Checkout retry decision',
                       'cwd': str(folder), 'turns': [{'id': 'source-turn', 'status': 'failed',
                       'items': [{'id': 'source-item', 'type': 'agentMessage',
                                  'phase': 'commentary', 'text': text}]}]}
        projection = 'Codex\n' + text
        start = projection.rfind(QUOTE)
        self.reference = capture_reference(self.source,
            native_home=self.desk.native_home_namespace(), thread_id='native-source-A',
            turn_id='source-turn', item_id='source-item', quote_start=start,
            quote_end=start + len(QUOTE), expected_quote=QUOTE,
            text_for_item=self.item_text)
        self.block = format_evidence_block(self.reference)
        self.text = append_evidence_block('Existing Plan stays unsent.  保留\n  ', self.block)
        self.payload = self.capture(self.text, 'plan')

    @staticmethod
    def item_text(item):
        return 'Codex\n' + item['text']

    def assert_reference(self, text):
        rows = parse_evidence_blocks(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['reference'], self.reference)
        self.assertEqual(text[rows[0]['start']:rows[0]['end']], self.block)

    def assert_source_unattached(self):
        self.assertIsNone(self.desk.store.get('native-source-A'))
        self.assertFalse(Path(self.source['cwd']).exists())
        self.assertEqual(self.desk.store.get(self.identifier)['thread_id'], 'native-original')

    def test_prepared_queue_reservation_reopen_keeps_exact_original_revision(self):
        before = list(self.desk.store.db.iterdump())
        status, prepared = self.request('/api/preparation')
        self.assertEqual(status, 200)
        row = next(row for row in prepared['sessions'] if row['id'] == self.identifier)
        self.assert_reference(row['draft']['text'])
        self.assertEqual(row['draft']['mode'], 'plan')
        self.assertEqual(list(self.desk.store.db.iterdump()), before)
        self.assertEqual(self.requests, [])
        status, added = self.request('/api/followups', {
            'session': self.identifier, 'text': self.text, 'mode': 'plan'})
        self.assertEqual(status, 200)
        self.assertEqual(added['entries'][:2], self.preparation['entries'])
        entry = added['entries'][-1]
        self.assert_reference(entry['text'])
        reservation = reserve_followup(self.desk.store, self.identifier, entry['id'], entry['revision'])
        edited = edit_followup(self.desk.store, self.identifier, entry['id'],
                               self.text + '\nA separate newer next-step note.', 'native', entry['revision'])
        cold = Store(self.path / 'state' / 'desk.sqlite3')
        try:
            before = list(cold.db.iterdump())
            row = next(row for row in preparation_snapshot(cold)['sessions'] if row['id'] == self.identifier)
            self.assertEqual(list(cold.db.iterdump()), before)
            self.assert_reference(row['followups']['reservation']['text'])
            self.assertEqual(row['followups']['reservation'], reservation)
            self.assert_reference(row['followups']['entries'][-1]['text'])
            self.assertEqual(row['followups']['entries'][-1]['mode'], 'native')
        finally:
            cold.db.close()
        receipt = record_followup_receipt(self.desk.store, self.identifier,
            reservation['token'], reservation['entry_id'], reservation['revision'], 'accepted')
        self.assertFalse(receipt['consumed'])
        retained = followup_snapshot(self.desk.store, self.identifier)
        self.assertEqual(retained['entries'][-1], {**edited, 'state': 'queued'})
        self.assertEqual(retained['entries'][:2], self.preparation['entries'])
        self.assert_reference(load_draft(self.desk.store, self.identifier)['text'])
        self.assertEqual(self.requests, [])
        self.assert_source_unattached()

    def test_accepted_run_keeps_reference_in_captured_and_native_sent_instruction(self):
        status, receipt = self.request('/api/turn', self.payload)
        self.assertEqual((status, receipt['request']['status']), (200, 'accepted'))
        self.assert_reference(receipt['request']['payload']['text'])
        self.assertEqual(receipt['request']['binding']['thread_id'], 'native-original')
        self.assertEqual(receipt['request']['payload']['mode'], 'plan')
        native = self.requests[0]['params']
        self.assertEqual(native['threadId'], 'native-original')
        self.assertEqual(native['input'][0]['text'], self.text)
        self.assert_reference(native['input'][0]['text'])
        self.assertEqual(native['collaborationMode']['mode'], 'plan')
        self.assertEqual(load_draft(self.desk.store, self.identifier)['text'], '')
        user_items = [record['event']['params']['item'] for record in self.desk.store.events(self.identifier)
                      if record['event'].get('method') == 'item/completed'
                      and record['event']['params'].get('item', {}).get('type') == 'userMessage']
        self.assertEqual(user_items[-1]['content'][0]['text'], self.text)
        self.assert_reference(user_items[-1]['content'][0]['text'])
        before = list(self.desk.store.db.iterdump())
        self.assertEqual(self.read_request(self.payload), (200, receipt))
        self.assertEqual(self.request('/api/turn', self.payload), (200, receipt))
        self.assertEqual(list(self.desk.store.db.iterdump()), before)
        self.assertEqual(len(self.requests), 1)
        self.assert_preparation()
        self.assert_source_unattached()

    def test_unknown_cold_request_only_then_resolution_keeps_newer_preparation(self):
        self.native_mode = 'unknown'
        status, receipt = self.request('/api/turn', self.payload)
        self.assertEqual((status, receipt['request']['status']), (200, 'needs_review'))
        current = load_draft(self.desk.store, self.identifier)
        save_draft(self.desk.store, self.identifier, '', 'plan', current['revision'], 'new-page', 1)
        # Keep only the captured request as preparation; restore the independent
        # two queues after verifying request-only overview/authoritative body.
        queue_before = followup_snapshot(self.desk.store, self.identifier)
        status, cleared = self.request('/api/followups/clear', {
            'session': self.identifier, 'order': [entry['id'] for entry in queue_before['entries']]})
        self.assertEqual(status, 200)
        self.assertEqual(cleared['entries'], [])
        self.close_server()
        cold = Desk('must-not-execute', self.path, self.path / 'state')
        self.addCleanup(cold.close); self.addCleanup(cold.store.db.close)
        self.desk = cold
        cold.open = lambda identifier: self.fail('Request review opened native work')
        cold.runtime = lambda identifier: self.fail('Request review dispatched native work')
        self.start_server()
        before = list(cold.store.db.iterdump())
        status, prepared = self.request('/api/preparation')
        row = next(row for row in prepared['sessions'] if row['id'] == self.identifier)
        self.assertIsNone(row['draft'])
        self.assertEqual(row['followups'], {'entries': [], 'reservation': None})
        self.assertEqual(row['turn_request']['token'], self.payload['token'])
        self.assertNotIn('text', row['turn_request'])
        self.assert_reference(self.read_request(self.payload)[1]['request']['payload']['text'])
        self.assertEqual(list(cold.store.db.iterdump()), before)
        for entry in queue_before['entries']:
            self.request('/api/followups', {'session': self.identifier, 'text': entry['text'], 'mode': entry['mode']})
        queues = followup_snapshot(cold.store, self.identifier)
        current = load_draft(cold.store, self.identifier)
        newer = save_draft(cold.store, self.identifier, self.text + '\nA newer unsent edit.',
                           'native', current['revision'], 'new-page', 2)
        status, resolved = self.request('/api/turn/resolve', {
            'session': self.identifier, 'token': self.payload['token'], 'outcome': 'accepted'})
        self.assertEqual((status, resolved['request']['status']), (200, 'accepted'))
        self.assert_reference(resolved['request']['payload']['text'])
        self.assertEqual(load_draft(cold.store, self.identifier), newer)
        self.assertEqual(followup_snapshot(cold.store, self.identifier), queues)
        self.assertEqual(len(self.requests), 1)
        self.assert_source_unattached()

    def test_rejected_retry_sends_original_evidence_not_later_draft_or_changed_source(self):
        self.native_mode = 'rejected'
        self.assertEqual(self.request('/api/turn', self.payload)[1]['request']['status'], 'rejected')
        current = load_draft(self.desk.store, self.identifier)
        newer = save_draft(self.desk.store, self.identifier, self.text + '\nNewer task remains unsent.',
                           'native', current['revision'], 'later-page', 1)
        changed = copy.deepcopy(self.source)
        changed['turns'][0]['items'][0]['text'] = changed['turns'][0]['items'][0]['text'].replace(
            'Later decision: ' + QUOTE, 'Later decision: ' + 'X' + QUOTE[1:])
        self.assertEqual(resolve_reference(self.reference, self.reference['native_home'], changed,
                         text_for_item=self.item_text)['status'], 'quote_changed')
        self.native_mode = 'completed'
        status, accepted = self.request('/api/turn', {**self.payload, 'retry': True})
        self.assertEqual((status, accepted['request']['status']), (200, 'accepted'))
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(request['params']['input'][0]['text'] == self.text for request in self.requests))
        self.assert_reference(accepted['request']['payload']['text'])
        self.assertEqual(load_draft(self.desk.store, self.identifier), newer)
        self.assert_preparation()
        self.assert_source_unattached()

del NativeRequestFixture
