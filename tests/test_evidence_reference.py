import unittest

from codex_desk.evidence_reference import parse_evidence_blocks, append_evidence_block, capture_reference, format_evidence_block

HOME = 'a' * 64

def primary_item_text(item):
    if item['type'] in ('agentMessage', 'plan'):
        return item['text']
    if item['type'] == 'commandExecution':
        return item['aggregatedOutput']
    if item['type'] == 'userMessage':
        return '\n'.join(c['text'] for c in item['content'] if c.get('type') == 'text')
    raise ValueError('Explicit structured-tool projection needed')

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
    def test_combined_append_context_preserves_the_exact_new_reference_or_rejects(self):
        quote = 'Retry budget: café\u0301🙂 — 2 attempts.'
        reference = capture(original('Before🙂 ' + quote + '\nAfter'), quote)
        block = format_evidence_block(reference)
        draft = 'Inspect the failing check.\n```sh\npytest -q'
        before = draft
        with self.assertRaisesRegex(ValueError, 'Close the unfinished'):
            append_evidence_block(draft, block)
        self.assertEqual(draft, before)
        self.assertEqual(parse_evidence_blocks(block)[0]['reference'], reference)
        corrected = draft + '\n```'
        combined = append_evidence_block(corrected, block)
        self.assertEqual(combined, corrected + '\n\n' + block)
        parsed = parse_evidence_blocks(combined)
        self.assertEqual(parsed, [{'reference': reference, 'start': len(corrected) + 2, 'end': len(combined)}])
        self.assertEqual(reference['quote'], quote)


if __name__ == '__main__':
    unittest.main()
