import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from codex_desk.evidence import collaboration_text
from codex_desk.handoff import build_handoff, visible_text


NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')


def activity(kind='started', **fields):
    return dict(id='activity-1', type='subAgentActivity', kind=kind,
                agentPath='/root/drill', agentThreadId='drill-thread', **fields)


def call(status='completed', tool='spawnAgent', **fields):
    return dict(id='call-1', type='collabAgentToolCall', tool=tool, status=status,
                senderThreadId='parent-thread', receiverThreadIds=['drill-thread'],
                agentsStates={'drill-thread': {'status': 'running', 'message': None}}, **fields)


def handoff(*items, **options):
    return build_handoff({'id': 'parent-thread', 'cwd': '/project', 'modelProvider': 'relay',
                          'turns': [{'items': list(items)}]}, **options)


class CollaborationEvidenceTests(unittest.TestCase):
    def test_native_activity_kinds_have_path_and_thread_without_invented_tool_status(self):
        for kind in ('started', 'interacted', 'interrupted', 'completed'):
            with self.subTest(kind=kind):
                expected = ('Subagent activity\nKind: ' + kind + '\nAgent path: /root/drill'
                            '\nAgent thread: drill-thread')
                self.assertEqual(collaboration_text(activity(kind)), expected)
                self.assertEqual(visible_text(activity(kind)), expected)
                self.assertNotIn('Status:', expected)

    def test_native_creation_model_is_resolved_not_a_request(self):
        text = collaboration_text(activity(model='reported-model', reasoningEffort='medium'))
        self.assertIn('Resolved model: reported-model', text)
        self.assertIn('Resolved effort: medium', text)
        self.assertNotIn('Requested', text)
        self.assertNotIn('Output:', text)
        self.assertNotIn('Prompt sent:', text)

    def test_legacy_tool_request_preserves_prompt_and_last_known_receiver_state(self):
        item = call(model='requested-model', reasoningEffort='high', prompt='Open preset\nascii.printable.short.2.yz')
        item['receiverThreadIds'] = ['drill-thread', 'power-thread']
        item['agentsStates'] = {'power-thread': {'status': 'completed', 'message': 'Low power enabled'},
                               'drill-thread': {'status': 'running', 'message': None}}
        text = handoff(item)
        for value in ('Item call-1', 'Collaboration tool: spawnAgent', 'Status: completed',
                      'Source thread: parent-thread', 'Requested model: requested-model',
                      'Requested effort: high', 'Prompt sent:\nOpen preset\nascii.printable.short.2.yz',
                      'Receiver thread: drill-thread\nLast known status: running',
                      'Receiver thread: power-thread\nLast known status: completed\nOutput:\nLow power enabled'):
            self.assertIn(value, text)
        self.assertLess(text.index('Receiver thread: drill-thread'), text.index('Receiver thread: power-thread'))
        self.assertNotIn('Resolved', text)
        self.assertNotIn('Success:', text)

    def test_legacy_tool_and_status_enums_remain_distinct_from_agent_status(self):
        tools = ('spawnAgent', 'sendInput', 'resumeAgent', 'wait', 'closeAgent', 'sendMessage',
                 'followupTask', 'interruptAgent', 'listAgents')
        for tool in tools:
            for status in ('inProgress', 'completed', 'failed', 'interrupted'):
                with self.subTest(tool=tool, status=status):
                    item = call(status, tool)
                    item['agentsStates']['drill-thread'] = {'status': 'errored', 'message': 'Preset unavailable'}
                    text = collaboration_text(item)
                    self.assertIn('Collaboration tool: ' + tool + '\nStatus: ' + status, text)
                    self.assertIn('Last known status: errored\nOutput:\nPreset unavailable', text)
                    self.assertNotIn('Success:', text)

    def test_public_receiver_statuses_and_empty_output_are_retained(self):
        for status in ('pendingInit', 'running', 'interrupted', 'completed', 'errored', 'shutdown', 'notFound'):
            with self.subTest(status=status):
                item = call()
                item['agentsStates']['drill-thread'] = {'status': status, 'message': ''}
                text = collaboration_text(item)
                self.assertIn('Last known status: ' + status + '\nOutput:\n', text)

    def test_null_and_missing_fields_do_not_claim_prompt_output_or_model(self):
        for metadata in ({}, {'model': None, 'reasoningEffort': None, 'prompt': None}):
            text = collaboration_text(call(**metadata))
            for value in ('model:', 'effort:', 'Prompt sent:', 'Output:'):
                self.assertNotIn(value, text)
        item = {'id': 'old', 'type': 'collabAgentToolCall'}
        self.assertEqual(collaboration_text(item), 'Collaboration tool: unknown\nStatus: unknown'
                         '\nSource thread: unavailable\nReceiver threads: none reported')
        item = {'type': 'subAgentActivity', 'kind': None, 'agentPath': None, 'agentThreadId': None,
                'model': None, 'reasoningEffort': None}
        self.assertEqual(collaboration_text(item), 'Subagent activity\nKind: unknown'
                         '\nAgent path: unavailable\nAgent thread: unavailable')

    def test_missing_receivers_and_states_have_explicit_unavailable_status(self):
        item = call()
        item['agentsStates'] = {'other-thread': {'status': 'shutdown', 'message': 'Closed'}}
        text = collaboration_text(item)
        self.assertIn('Receiver thread: drill-thread\nLast known status: unavailable', text)
        self.assertIn('Receiver thread: other-thread\nLast known status: shutdown\nOutput:\nClosed', text)
        self.assertLess(text.index('drill-thread'), text.index('other-thread'))
        for states in (None, [], False):
            item['agentsStates'] = states
            self.assertIn('Receiver thread: drill-thread\nLast known status: unavailable', collaboration_text(item))

    def test_only_public_native_fields_are_formatted_without_mutation(self):
        item = call(prompt='Inspect drill')
        item.update(_meta={'secret': 'ITEM-SECRET'}, encryptedContent='CIPHER-SECRET',
                    reasoning={'text': 'REASONING-SECRET'}, source={'private': 'SOURCE-SECRET'},
                    result={'private': 'RESULT-SECRET'})
        item['agentsStates']['drill-thread'].update(_meta='STATE-SECRET',
                                                   encryptedContent='STATE-CIPHER-SECRET',
                                                   private='STATE-EXTRA-SECRET')
        item['agentsStates']['_meta'] = {'status': 'running', 'message': 'MAP-SECRET'}
        before = copy.deepcopy(item)
        text = collaboration_text(item)
        self.assertNotIn('-SECRET', text)
        self.assertNotIn('_meta', text)
        self.assertEqual(item, before)
        newer = activity()
        newer.update(prompt='ACTIVITY-PROMPT-SECRET', agentsStates=item['agentsStates'], tool='ACTIVITY-TOOL-SECRET')
        self.assertNotIn('-SECRET', collaboration_text(newer))

    def test_shaped_public_output_uses_existing_review_sanitation(self):
        item = call()
        item['agentsStates']['drill-thread'] = {'status': 'completed', 'message': {
            'records': [{'count': 42, '_meta': 'NESTED-SECRET'}], 'ok': True, 'empty': None,
            'image': {'type': 'image', 'mimeType': 'image/png', 'data': 'IMAGE-SECRET'},
            'audio': {'type': 'audio', 'data': 'AUDIO-SECRET'},
            'resource': {'blob': 'BLOB-SECRET', 'uri': 'https://user:pass@docs.example/chart?key=URI-SECRET#auth'},
            'imageUrl': 'data:image/png;base64,QklOQVJZ', '_meta': 'OUTPUT-SECRET'}}
        text = collaboration_text(item)
        for value in ('Output:\n{', '"records": [', '"count": 42', '"ok": true', '"empty": null',
                      'Image: inline payload 12 characters', 'Audio: inline payload 12 characters',
                      'Resource blob: inline payload 11 characters', 'https://docs.example/chart',
                      'Media: image/png; inline payload 8 characters'):
            self.assertIn(value, text)
        for value in ('-SECRET', '_meta', 'user:pass', '?key=', '#auth', 'QklOQVJZ'):
            self.assertNotIn(value, text)

    def test_native_text_is_verbatim_even_when_it_mentions_a_data_uri(self):
        native_text = 'data:audio/wav;base64,QVVESU8=\nThis is a task text example.'
        item = call(prompt=native_text)
        item['agentsStates']['drill-thread']['message'] = native_text
        self.assertEqual(collaboration_text(item).count(native_text), 2)

    def test_malformed_fields_use_plain_fallbacks_not_raw_json(self):
        item = call()
        item.update(tool={'private': 'TOOL-SECRET'}, status=['STATUS-SECRET'], senderThreadId={'id': 'SENDER-SECRET'},
                    model={'name': 'MODEL-SECRET'}, reasoningEffort=['EFFORT-SECRET'], prompt={'text': 'PROMPT-SECRET'},
                    receiverThreadIds=[None, {'private': 'RECEIVER-SECRET'}, 'drill-thread'])
        item['agentsStates']['drill-thread'] = {'status': {'private': 'STATE-SECRET'}, 'message': False}
        text = collaboration_text(item)
        self.assertNotIn('-SECRET', text)
        self.assertIn('Status: unknown', text)
        self.assertIn('Prompt sent:\n[Unavailable text content]', text)
        self.assertIn('Last known status: unavailable\nOutput:\n[Unavailable output]', text)
        for item in (None, False, [], {'type': 'reasoning', 'encryptedContent': 'PRIVATE'}):
            self.assertEqual(collaboration_text(item), '[Unsupported collaboration item]')

    def test_plain_text_preserves_user_html_without_escaping_or_markup_generation(self):
        html = '<img src=x onerror="alert(1)"> & <script>task()</script>'
        item = call(prompt=html)
        item['agentsStates']['drill-thread'] = {'status': 'completed', 'message': html}
        text = collaboration_text(item)
        self.assertEqual(text.count(html), 2)
        self.assertNotIn('&lt;', text)
        self.assertIn(html, handoff(item))

    def test_handoff_keeps_native_order_and_shared_formatter_with_default_budget(self):
        goal = {'id': 'goal', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Open the familiar drill'}]}
        command = {'id': 'command', 'type': 'commandExecution', 'command': 'inspect-preset',
                   'aggregatedOutput': 'Ready', 'exitCode': 0}
        hidden = {'id': 'hidden', 'type': 'reasoning', 'encryptedContent': 'CIPHER-SECRET', 'summary': ['PRIVATE-SECRET']}
        answer = {'id': 'answer', 'type': 'agentMessage', 'text': 'Drill opened'}
        start, done, legacy = activity(), activity('completed'), call(prompt='Use Y Z preset')
        start['id'], done['id'] = 'start', 'done'
        thread = {'id': 'parent-thread', 'cwd': '/project', 'modelProvider': 'relay',
                  'turns': [{'items': [goal, legacy, start]}, {'items': [hidden, command, done, answer]}]}
        text = build_handoff(thread)
        ids = ['goal', 'call-1', 'start', 'command', 'done', 'answer']
        positions = [text.index('Item ' + value + '\n') for value in ids]
        self.assertEqual(positions, sorted(positions))
        for item in (legacy, start, done):
            self.assertIn(collaboration_text(item), text)
        self.assertNotIn('-SECRET', text)
        self.assertLess(len(text), 24000)
        legacy['prompt'] = 'large request ' * 5000
        shorter = build_handoff(thread)
        self.assertLess(len(shorter), 24000)
        self.assertIn('shortened at the handoff character limit', shorter)
        self.assertIn('Drill opened', shorter)
        self.assertLess(shorter.index('Item start\n'), shorter.index('Item done\n'))

    def test_large_binary_output_does_not_displace_other_handoff_items(self):
        item = call()
        item['agentsStates']['drill-thread'] = {'status': 'completed', 'message': [
            {'type': 'image', 'data': 'BINARY-SECRET' * 10000}, {'count': 42}]}
        text = handoff(activity(), item, activity('completed'), max_chars=2000)
        self.assertIn('Kind: started', text)
        self.assertIn('Kind: completed', text)
        self.assertIn('"count": 42', text)
        self.assertIn('inline payload 130000 characters', text)
        self.assertNotIn('BINARY-SECRET', text)
        self.assertIn('Earlier visible items omitted: 0', text)
        self.assertLess(len(text), 2000)

    @unittest.skipUnless(NODE, 'Node is needed for JavaScript formatter parity')
    def test_python_and_javascript_formatters_match_native_and_sanitized_content(self):
        items = [activity(kind, model='reported-model', reasoningEffort='medium')
                 for kind in ('started', 'interacted', 'interrupted', 'completed')]
        items += [call(status, tool, prompt='<b>Task 😀</b>\nNext line', model='requested-model', reasoningEffort='high')
                  for tool in ('spawnAgent', 'sendInput', 'resumeAgent', 'wait', 'closeAgent', 'sendMessage',
                               'followupTask', 'interruptAgent', 'listAgents')
                  for status in ('inProgress', 'completed', 'failed', 'interrupted')]
        shaped = call()
        shaped['agentsStates']['drill-thread'] = {'status': 'completed', 'message': {
            'count': 42, 'done': False, 'empty': None, '_meta': 'PRIVATE',
            'nested': [{'blob': 'BINARY😀', 'uri': 'https://user:pass@docs.example/report?key=secret#auth'},
                       {'type': 'image', 'data': 'data:image/png;base64,QklOQVJZ'},
                       {'type': 'audio', 'data': 'BINARY'}, {'imageUrl': 'data:image/png;base64,QklOQVJZ'},
                       {'uri': 'file:///project/report.txt?key=secret'}, {'uri': 'https://[invalid'}]}}
        items += [shaped, call(model=None, reasoningEffort=None, prompt=None),
                  {'type': 'collabAgentToolCall'}, {'type': 'subAgentActivity'}, None, []]
        script = ('const evidence=require(process.argv[1]);let input="";'
                  'process.stdin.on("data",chunk=>input+=chunk);'
                  'process.stdin.on("end",()=>process.stdout.write(JSON.stringify('
                  'JSON.parse(input).map(item=>evidence.collaboration(item)))));')
        source = Path(__file__).resolve().parents[1] / 'codex_desk/static/evidence.js'
        result = subprocess.run([NODE, '-e', script, str(source)], input=json.dumps(items),
                                text=True, capture_output=True, timeout=15, check=True)
        self.assertEqual(json.loads(result.stdout), [collaboration_text(item) for item in items])


if __name__ == '__main__':
    unittest.main()
