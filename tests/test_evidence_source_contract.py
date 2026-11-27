"""Focused malformed transport and nested-source evidence regressions."""
import copy
from unittest.mock import patch
from urllib.parse import urlencode

from codex_desk.evidence_reference import capture_reference, resolve_reference
from test_task_response_api import TaskResponseApiTests


class EvidenceSourceContractTests(TaskResponseApiTests):
    # Reuse the subprocess/HTTP/SQLite fixture, without rerunning its cases.
    for _name in TaskResponseApiTests.__dict__:
        if _name.startswith('test_'):
            locals()[_name] = None

    def source_path(self, thread='parent'):
        return '/api/native/evidence-source?' + urlencode({
            'home': self.desk.native_home_namespace(), 'thread': thread})

    def reference(self):
        return capture_reference(self.source,
            native_home=self.desk.native_home_namespace(), thread_id='parent',
            turn_id='captured', item_id='answer', quote_start=6, quote_end=12,
            expected_quote='native', text_for_item=lambda item: item['text'])

    def test_invalid_utf8_query_is_rejected_before_reader_creation(self):
        before = self.state()
        prefix = '/api/native/evidence-source?home=' + self.desk.native_home_namespace()
        with patch('codex_desk.server._NativeReader',
                   side_effect=AssertionError('Malformed query reached native reader')) as create:
            for encoded in ('%FF', '%C0%AF', '%ED%A0%80', '%F0%9F%99', 'parent%FE'):
                with self.subTest(encoded=encoded):
                    status, result, cache = self.request(path=prefix + '&thread=' + encoded)
                    self.assertEqual((status, cache), (400, 'no-store'))
                    self.assertIn('error', result)
            create.assert_not_called()
        self.assert_read_only(before, 0)

    def test_malformed_native_envelopes_fail_without_saved_state_changes(self):
        before = self.state()
        replies = [None, [], {}, {'thread': None}, {'thread': []},
                   {'thread': {'id': 'parent'}}, {'thread': {'id': 'parent', 'turns': {}}}]
        for reads, reply in enumerate(replies, 1):
            with self.subTest(reply=reply):
                self.set_reply(reply)
                status, body, cache = self.request(path=self.source_path())
                self.assertEqual((status, cache), (400, 'no-store'))
                self.assertIn('error', body)
                self.assertNotIn('thread', body)
                self.assert_read_only(before, reads)

    def test_nested_ambiguous_or_malformed_source_is_not_an_equal_quote_replacement(self):
        reference = self.reference()
        before = self.state()
        duplicate_turn = copy.deepcopy(self.source)
        duplicate_turn['turns'].append(copy.deepcopy(duplicate_turn['turns'][1]))
        duplicate_item = copy.deepcopy(self.source)
        duplicate_item['turns'][1]['items'].append(copy.deepcopy(duplicate_item['turns'][1]['items'][0]))
        malformed_items = copy.deepcopy(self.source)
        malformed_items['turns'][1]['items'] = 'Exact native answer'
        missing_item = copy.deepcopy(self.source)
        missing_item['turns'][1]['items'][0]['id'] = 'not-the-captured-item'
        for reads, thread in enumerate((duplicate_turn, duplicate_item, malformed_items, missing_item), 1):
            with self.subTest(reads=reads):
                self.set_reply({'thread': thread})
                status, result, cache = self.request(path=self.source_path())
                self.assertEqual((status, cache), (200, 'no-store'))
                self.assertEqual(result['thread'], thread)
                resolved = resolve_reference(reference, result['home_namespace'], result['thread'],
                                             text_for_item=lambda item: item['text'])
                self.assertEqual(resolved['status'], 'source_unavailable')
                self.assertFalse(resolved['available'])
                self.assertEqual(reference['quote'], 'native')
                self.assert_read_only(before, reads)

    def test_home_and_source_require_this_launch_capability_before_any_read(self):
        before = self.state()
        with patch('codex_desk.server._NativeReader',
                   side_effect=AssertionError('Unauthenticated source read')) as create:
            for path in ('/api/native/home', self.source_path()):
                for headers, expected in (({'X-Codex-Desk-Access': ''}, 403),
                                          ({'Origin': 'https://foreign.example'}, 400)):
                    with self.subTest(path=path, headers=headers):
                        self.assertEqual(self.request(path=path, headers=headers)[0], expected)
            create.assert_not_called()
        self.assert_read_only(before, 0)


del TaskResponseApiTests
