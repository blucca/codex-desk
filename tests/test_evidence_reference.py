import copy
import json
from pathlib import Path
import unittest

from codex_desk.evidence_reference import (
    MAX_DRAFT_CHARS, MAX_QUOTE_CHARS, CLOSE, OPEN,
    append_evidence_block, capture_reference, format_evidence_block,
    make_evidence_block, parse_evidence_blocks, reference_target, resolve_reference as _resolve_reference,
)


HOME = 'a' * 64


def primary_item_text(item):
    # These unit fixtures inject a common body projection. The shared JS/Python
    # parity fixture separately uses the production history_reader projection.
    if item['type'] in ('agentMessage', 'plan'):
        return item['text']
    if item['type'] == 'commandExecution':
        return item['aggregatedOutput']
    if item['type'] == 'userMessage':
        return '\n'.join(c['text'] for c in item['content'] if c.get('type') == 'text')
    raise ValueError('Explicit structured-tool projection needed')


def resolve_reference(reference, home, thread, *, text_for_item=primary_item_text):
    return _resolve_reference(reference, home, thread, text_for_item=text_for_item)


def original(text='First answer. Retry budget: 2 attempts. Later answer.', **item_fields):
    item = {'id': 'item-2', 'type': 'agentMessage', 'text': text,
            'phase': 'final_answer', **item_fields}
    return {'id': 'thread-A', 'name': 'Checkout decision', 'cwd': '/removed/project-A',
            'url': 'http://127.0.0.1:8787/#access=ignored-native-extra',
            'turns': [{'id': 'turn-1', 'items': [{'id': 'older', 'type': 'agentMessage',
                    'text': 'Retry budget: 2 attempts.'}]},
                {'id': 'turn-2', 'status': 'completed', 'items': [item]},
                {'id': 'turn-3', 'items': [{'id': 'newer', 'type': 'agentMessage',
                    'text': 'Retry budget: 2 attempts.'}]}]}


_UNSET = object()


def capture(thread=_UNSET, quote='Retry budget: 2 attempts.', start=None, **kwargs):
    thread = original() if thread is _UNSET else thread
    if not isinstance(thread, dict):
        return capture_reference(thread, native_home=HOME, thread_id='thread-A',
            turn_id='turn-2', item_id='item-2', quote_start=0, quote_end=1,
            text_for_item=primary_item_text)
    item = thread['turns'][1]['items'][0]
    text = kwargs.pop('text_for_item', lambda item: item['text'])
    body = text(item)
    start = body.index(quote) if start is None else start
    return capture_reference(thread, native_home=HOME, thread_id='thread-A',
        turn_id='turn-2', item_id='item-2', quote_start=start,
        quote_end=start + len(quote), expected_quote=quote,
        text_for_item=text, **kwargs)


class EvidenceReferenceTests(unittest.TestCase):
    def test_shared_history_reader_projection_parity_fixture(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/evidence_reference_v1.json').read_text())

        def reader_text(item):
            if item['type'] == 'agentMessage':
                return 'Codex\n' + item['text']
            if item['type'] == 'plan':
                return 'Proposed plan\n' + item['text']
            if item['type'] == 'commandExecution':
                return ('Command\n' + item['command'] + '\nStatus: ' + item['status']
                    + '\nExit: ' + str(item['exitCode']) + '\n' + item['aggregatedOutput'])
            raise ValueError('This parity fixture has no other projection kinds')

        for case in fixture['cases']:
            with self.subTest(case=case['name']):
                reference = capture_reference(case['thread'], native_home=case['native_home'],
                    thread_id='thread-A', turn_id='turn-A', item_id='item-A',
                    quote_start=case['codepoint_start'], quote_end=case['codepoint_end'],
                    expected_quote=case['quote'], text_for_item=reader_text)
                if case['name'] == 'native_command':
                    self.assertEqual(reference['projection'], 'history-reader-command-output/v1')
                    self.assertEqual(reference['quote_start'], case['thread']['turns'][0]['items'][0]['aggregatedOutput'].index(case['quote']))
                    # Frozen v1 artifact remains a literal, independently supported contract.
                    reference = case['reference']
                self.assertEqual(reference, case['reference'])
                self.assertEqual(format_evidence_block(reference), case['block'])
                self.assertEqual(parse_evidence_blocks(case['draft']), case['parsed'])
                self.assertEqual(resolve_reference(reference, case['native_home'], case['thread'],
                    text_for_item=reader_text), case['resolved'])
        first = fixture['cases'][0]
        self.assertEqual((first['utf16_start'], first['utf16_end']), (27, 41))
        self.assertEqual((first['codepoint_start'], first['codepoint_end']), (25, 38))
        for invalid in fixture['invalid_cases']:
            with self.subTest(case=invalid['name']):
                self.assertEqual(parse_evidence_blocks(invalid['text']), [])

    def test_readable_round_trip_and_exact_capture(self):
        reference = capture()
        block = format_evidence_block(reference)
        self.assertIn('> Retry budget: 2 attempts.', block)
        self.assertIn('Thread: thread-A\nTurn: turn-2\nItem: item-2', block)
        self.assertIn('Kind: agentMessage\nPhase: final_answer', block)
        self.assertNotIn('http://', block)
        self.assertNotIn('#access=', block)
        found = parse_evidence_blocks(block)
        self.assertEqual(found, [{'reference': reference, 'start': 0, 'end': len(block)}])
        self.assertEqual(reference_target(found[0]['reference'], HOME),
                         {'thread_id': 'thread-A', 'turn_id': 'turn-2', 'item_id': 'item-2'})

    def test_append_preserves_other_draft_text_and_locations(self):
        block = format_evidence_block(capture())
        draft = 'Existing unsent Plan\n  retain this whitespace  '
        text = append_evidence_block(draft, block)
        self.assertEqual(text, draft + '\n\n' + block)
        found = parse_evidence_blocks(text)
        self.assertEqual(text[found[0]['start']:found[0]['end']], block)
        self.assertEqual(append_evidence_block('', block), block)

    def test_unknown_phase_and_status_are_not_inferred(self):
        thread = original(phase='future_native_phase', status='future_status')
        thread['turns'][1]['status'] = 'future_turn_status'
        reference = capture(thread)
        parsed = parse_evidence_blocks(format_evidence_block(reference))[0]['reference']
        self.assertEqual((parsed['phase'], parsed['status'], parsed['turn_status']),
            ('future_native_phase', 'future_status', 'future_turn_status'))
        legacy = original()
        legacy['turns'][1]['items'][0].pop('phase')
        self.assertIsNone(capture(legacy)['phase'])

    def test_title_and_cwd_strip_only_readable_labels(self):
        thread = original()
        thread['name'] = '  Checkout\n decision\x00\u202e  '
        thread['cwd'] = '  /removed/\tproject-A\x01  '
        reference = capture(thread)
        self.assertEqual(reference['title'], 'Checkout decision')
        self.assertEqual(reference['cwd'], '/removed/ project-A')
        self.assertEqual(reference['native_home'], HOME)

    def test_unicode_codepoint_selection_is_literal(self):
        text = '前🙂 words ＡＩ café\u0301 retry🙂後'
        quote = 'ＡＩ café\u0301 retry🙂'
        reference = capture(original(text), quote)
        self.assertEqual(reference['quote'], quote)
        self.assertEqual(reference['quote_start'], len('前🙂 words '))
        self.assertEqual(reference['quote_end'] - reference['quote_start'], len(quote))
        self.assertEqual(parse_evidence_blocks(format_evidence_block(reference))[0]['reference'], reference)
        self.assertTrue(resolve_reference(reference, HOME, original(text))['available'])
        self.assertEqual(resolve_reference(reference, HOME, original(text.replace('ＡＩ', 'AI')))['status'], 'quote_changed')

    def test_codepoint_spans_keep_astral_characters_whole(self):
        thread = original('🙂x')
        for start, end, quote in ((0, 1, '🙂'), (1, 2, 'x')):
            reference = capture_reference(thread, native_home=HOME, thread_id='thread-A',
                turn_id='turn-2', item_id='item-2', quote_start=start, quote_end=end,
                text_for_item=primary_item_text)
            self.assertEqual(reference['quote'], quote)
        with self.assertRaises(ValueError):
            capture_reference(original('\ud800x'), native_home=HOME, thread_id='thread-A',
                turn_id='turn-2', item_id='item-2', quote_start=0, quote_end=1,
                text_for_item=primary_item_text)

    def test_repeated_quote_keeps_exact_second_span(self):
        text = 'repeat / repeat / repeat'
        reference = capture(original(text), 'repeat', start=9)
        self.assertEqual((reference['quote_start'], reference['quote_end']), (9, 15))
        self.assertTrue(resolve_reference(reference, HOME, original(text))['available'])
        changed = original('repeat / CHANGE / repeat')
        self.assertEqual(resolve_reference(reference, HOME, changed)['status'], 'quote_changed')

    def test_crlf_quote_is_exact_in_metadata_and_readable_in_text(self):
        quote = 'first\r\nsecond\rthird\n'
        reference = capture(original(quote), quote, start=0)
        block = format_evidence_block(reference)
        self.assertIn('> first\n> second\n> third\n> ', block)
        self.assertEqual(parse_evidence_blocks(block)[0]['reference']['quote'], quote)
        crlf = block.replace('\n', '\r\n')
        parsed = parse_evidence_blocks(crlf)
        self.assertEqual(parsed[0]['reference'], reference)
        self.assertEqual(crlf[parsed[0]['start']:parsed[0]['end']], crlf)

    def test_comment_delimiters_inside_quote_stay_quoted_data(self):
        quote = 'Before\n' + OPEN + '{} -->\n' + CLOSE + '\nAfter'
        reference = capture(original(quote), quote, start=0)
        block = format_evidence_block(reference)
        self.assertIn('> ' + CLOSE, block)
        parsed = parse_evidence_blocks(block)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['reference']['quote'], quote)

    def test_readable_quote_reference_or_metadata_edits_disable_action(self):
        block = format_evidence_block(capture())
        edits = [block.replace('> Retry budget: 2 attempts.', '> Retry budget: 3 attempts.'),
            block.replace('Thread: thread-A', 'Thread: thread-B'),
            block.replace('"thread_id":"thread-A"', '"thread_id":"thread-B"'),
            block.replace('"quote_start":14', '"quote_start":15'),
            block.replace('Codex source: Checkout decision', 'Codex source: edited title'),
            block.replace('Quote span: 14..39', 'Quote span: 15..40')]
        for text in edits:
            with self.subTest(text=text[:120]):
                self.assertNotEqual(text, block)
                before = text
                self.assertEqual(parse_evidence_blocks(text), [])
                self.assertEqual(text, before)

    def test_unknown_duplicate_or_extra_metadata_is_not_actionable(self):
        block = format_evidence_block(capture())
        edits = [block.replace('"version":1', '"version":2'),
            block.replace('"version":1', '"version":1,"version":1'),
            block.replace('"version":1', '"version":1,"url":"http://127.0.0.1/"'),
            block.replace('"version":1', '"version":NaN'),
            block.replace('codex-desk-evidence:v1', 'codex-desk-evidence:v2'),
            block.replace('"phase":"final_answer"', '"phase":[]')]
        for text in edits:
            with self.subTest(text=text[:120]):
                self.assertEqual(parse_evidence_blocks(text), [])

    def test_fenced_examples_and_quoted_blocks_are_plain_text(self):
        block = format_evidence_block(capture())
        for text in ('```markdown\n' + block + '\n```', '~~~~\n' + block + '\n~~~~',
                     '```\n' + block, '\n'.join('> ' + line for line in block.splitlines())):
            with self.subTest(text=text[:40]):
                self.assertEqual(parse_evidence_blocks(text), [])
        draft = '```\n' + block + '\n```\n\n' + block
        self.assertEqual(len(parse_evidence_blocks(draft)), 1)

    def test_multiple_blocks_and_unrelated_text_are_retained(self):
        first = format_evidence_block(capture())
        second = format_evidence_block(capture(original('Other answer.'), 'Other answer.'))
        draft = first + '\n\n<!-- unrelated metadata -->\nOther draft text\n\n' + second
        before = draft
        parsed = parse_evidence_blocks(draft)
        self.assertEqual([row['reference']['quote'] for row in parsed],
                         ['Retry budget: 2 attempts.', 'Other answer.'])
        self.assertEqual(draft, before)

    def test_quote_and_total_draft_limits_are_exact(self):
        text = 'x' * MAX_QUOTE_CHARS
        reference = capture(original(text), text, start=0)
        block = format_evidence_block(reference)
        self.assertEqual(len(parse_evidence_blocks(block)), 1)
        with self.assertRaises(ValueError):
            capture(original(text + 'x'), text + 'x', start=0)
        prefix = 'x' * (MAX_DRAFT_CHARS - len(block) - 2)
        exact = append_evidence_block(prefix, block)
        self.assertEqual(len(exact), MAX_DRAFT_CHARS)
        self.assertEqual(len(parse_evidence_blocks(exact)), 1)
        with self.assertRaises(ValueError):
            append_evidence_block(prefix + 'x', block)
        over = 'x' + exact
        self.assertEqual(parse_evidence_blocks(over), [])
        self.assertEqual(over, 'x' + exact)

    def test_append_requires_one_unedited_block_only(self):
        block = format_evidence_block(capture())
        for malformed in (block + '\n', 'Extra\n' + block, block + '\n\n' + block, block[:-5]):
            with self.subTest(text=malformed[:40]), self.assertRaises(ValueError):
                append_evidence_block('Keep original draft', malformed)

    def test_namespace_is_exact_and_checked_before_read(self):
        reference = capture()
        with self.assertRaises(ValueError):
            reference_target(reference, 'b' * 64)
        self.assertEqual(resolve_reference(reference, 'b' * 64, None)['status'], 'home_mismatch')
        for home in ('relative/.codex', 'https://example.com', '/home\nother', '', 'A' * 64, 'a' * 63):
            with self.subTest(home=home), self.assertRaises(ValueError):
                format_evidence_block({**reference, 'native_home': home})

    def test_wrong_native_identity_never_substitutes_adjacent_quote(self):
        reference = capture()
        wrong = original()
        wrong['id'] = 'thread-B'
        missing_turn = original()
        missing_turn['turns'].pop(1)
        missing_item = original()
        missing_item['turns'][1]['items'][0]['id'] = 'another-item'
        duplicate = original()
        duplicate['turns'][1]['items'].append(copy.deepcopy(duplicate['turns'][1]['items'][0]))
        for thread in (wrong, missing_turn, missing_item, duplicate, None):
            with self.subTest(thread=thread), self.assertRaises(ValueError):
                capture(thread)
            self.assertEqual(resolve_reference(reference, HOME, thread)['status'], 'source_unavailable')

    def test_fresh_native_state_change_is_reported_separately_from_quote(self):
        reference = capture()
        fresh = original(phase='commentary', status='inProgress')
        fresh['turns'][1]['status'] = 'inProgress'
        result = resolve_reference(reference, HOME, fresh)
        self.assertTrue(result['available'])
        self.assertTrue(result['state_changed'])
        self.assertEqual(result['current'], {'phase': 'commentary', 'status': 'inProgress',
                                           'turn_status': 'inProgress'})
        changed_kind = original(type='plan')
        self.assertEqual(resolve_reference(reference, HOME, changed_kind)['status'], 'source_kind_changed')

    def test_explicit_command_and_structured_tool_projection(self):
        thread = original('command body', type='commandExecution', aggregatedOutput='command body', phase=None,
                          status='completed', exitCode=0)
        reference = capture_reference(thread, native_home=HOME, thread_id='thread-A', turn_id='turn-2',
            item_id='item-2', quote_start=0, quote_end=12, expected_quote='command body',
            text_for_item=primary_item_text)
        self.assertTrue(resolve_reference(reference, HOME, thread)['available'])
        tool = original(type='mcpToolCall', phase=None, result={'content': [{'type': 'text', 'text': 'Exact result'}]})
        projection = lambda item: item['result']['content'][0]['text']
        reference = capture(tool, 'Exact result', text_for_item=projection)
        self.assertTrue(resolve_reference(reference, HOME, tool, text_for_item=projection)['available'])
        self.assertEqual(resolve_reference(reference, HOME, tool)['status'], 'quote_unavailable')

    def test_invalid_capture_and_boolean_offsets_are_rejected(self):
        for start, end in ((False, 1), (0, True), (0, 0), (-1, 1), (0, 1000)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                capture_reference(original(), native_home=HOME, thread_id='thread-A', turn_id='turn-2',
                    item_id='item-2', quote_start=start, quote_end=end, text_for_item=primary_item_text)
        with self.assertRaises(ValueError):
            capture_reference(original(), native_home=HOME, thread_id='thread-A', turn_id='turn-2',
                item_id='item-2', quote_start=0, quote_end=5, expected_quote='wrong',
                text_for_item=primary_item_text)
        for key, value in (('source_kind', 'unknown_kind'), ('phase', '\n'), ('title', '\x00'),
                           ('quote_start', True), ('quote', ''), ('version', True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                format_evidence_block({**capture(), key: value})

    def test_capture_parse_resolve_do_not_mutate_inputs(self):
        thread = original()
        before_thread = copy.deepcopy(thread)
        reference = capture(thread)
        before_reference = copy.deepcopy(reference)
        block = format_evidence_block(reference)
        before_block = block
        parsed = parse_evidence_blocks(block)
        reference_target(reference, HOME)
        resolve_reference(reference, HOME, thread)
        self.assertEqual(thread, before_thread)
        self.assertEqual(reference, before_reference)
        self.assertEqual(block, before_block)
        parsed[0]['reference']['quote'] = 'Changed parsed copy'
        self.assertEqual(reference, before_reference)

    def test_make_wrapper_and_user_plan_explicit_projection(self):
        for item in ({'type': 'plan', 'text': 'Exact plan', 'phase': None},
                     {'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Exact user'},
                         {'type': 'image', 'data': 'ignored media'}], 'phase': None}):
            thread = original(**item)
            block = make_evidence_block(thread, native_home=HOME, thread_id='thread-A', turn_id='turn-2',
                item_id='item-2', quote_start=0, quote_end=10, text_for_item=primary_item_text)
            reference = parse_evidence_blocks(block)[0]['reference']
            self.assertEqual(reference['source_kind'], item['type'])
            self.assertTrue(resolve_reference(reference, HOME, thread)['available'])


if __name__ == '__main__':
    unittest.main()
