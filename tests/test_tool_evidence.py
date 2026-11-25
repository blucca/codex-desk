import copy
import unittest
from codex_desk.evidence import content_text, public_uri, tool_text
from codex_desk.handoff import build_handoff


class ToolEvidenceTests(unittest.TestCase):
    def mcp(self, **fields):
        return dict(id='mcp-1', type='mcpToolCall', server='local', tool='lookup',
                    arguments={'name': 'apples'}, status='completed', **fields)

    def handoff(self, *items, **options):
        return build_handoff({'id': 'native-id', 'cwd': '/project', 'modelProvider': 'relay',
                              'turns': [{'items': list(items)}]}, **options)

    def test_mcp_text_structured_result_keeps_shape_not_private_metadata(self):
        item = self.mcp(durationMs=34, result={
            'content': [{'type': 'text', 'text': 'Found 3 records',
                         'annotations': {'audience': ['user'], 'priority': 0.8,
                                         'lastModified': '2026-11-25', 'private': 'annotation-secret'},
                         '_meta': {'token': 'content-secret'}}],
            'structuredContent': {'records': [{'name': 'one', 'count': 3}], 'ok': True,
                                  'empty': None, 'nested': {'_meta': 'nested-secret', 'count': 0}},
            '_meta': {'apiKey': 'result-secret'}, 'unrecognized': 'extra-secret'},
            appContext={'connectorId': 'connector-secret'}, pluginId='plugin-secret')
        before = copy.deepcopy(item)
        text = self.handoff(item)
        for value in ('Item mcp-1', 'MCP tool: local.lookup', 'Status: completed',
                      'Duration: 34 ms', 'Arguments:', '"name": "apples"',
                      'Content 1 — Text', 'Found 3 records', 'Structured content:',
                      '"records": [', '"count": 3', '"ok": true', '"empty": null',
                      'Annotations:', '"priority": 0.8', '2026-11-25'):
            self.assertIn(value, text)
        for value in ('_meta', 'annotation-secret', 'content-secret', 'nested-secret',
                      'result-secret', 'extra-secret', 'connector-secret', 'plugin-secret'):
            self.assertNotIn(value, text)
        self.assertEqual(item, before)

    def test_failure_stays_visible_alongside_partial_result(self):
        item = self.mcp(error={'message': 'Server rejected request'},
                        result={'content': [{'type': 'text', 'text': 'Partial evidence'}]})
        item['status'] = 'failed'
        text = self.handoff(item)
        self.assertIn('Status: failed', text)
        self.assertIn('Error: Server rejected request', text)
        self.assertIn('Partial evidence', text)
        self.assertLess(text.index('Error:'), text.index('Arguments:'))

    def test_in_progress_does_not_claim_completion_or_result(self):
        item = self.mcp(result=None, error=None)
        item['status'] = 'inProgress'
        text = tool_text(item)
        self.assertIn('Status: inProgress', text)
        self.assertNotIn('Content', text)
        self.assertNotIn('Success:', text)
        self.assertNotIn('Error:', text)

    def test_binary_does_not_crowd_other_evidence_out_of_handoff(self):
        image = 'BASE64-IMAGE-' * 10000
        audio = 'BASE64-AUDIO-' * 10000
        item = self.mcp(result={'content': [
            {'type': 'image', 'mimeType': 'image/png', 'data': image},
            {'type': 'audio', 'mimeType': 'audio/wav', 'data': audio},
            {'type': 'text', 'text': 'Pixels analyzed: 42'}]})
        goal = {'id': 'goal', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Check screenshot'}]}
        text = self.handoff(goal, item, max_chars=2000)
        self.assertIn('Check screenshot', text)
        self.assertIn('Image: image/png; inline payload 130000 characters', text)
        self.assertIn('Audio: audio/wav; inline payload 130000 characters', text)
        self.assertIn('Pixels analyzed: 42', text)
        self.assertIn('Earlier visible items omitted: 0', text)
        self.assertNotIn('BASE64-', text)
        self.assertLess(len(text), 2000)

    def test_embedded_resources_and_resource_links_keep_public_descriptors(self):
        item = self.mcp(result={'content': [
            {'type': 'resource', 'resource': {'uri': 'https://user:pass@docs.example/report?token=secret#auth',
                                            'mimeType': 'text/plain', 'text': 'Report totals: 7',
                                            '_meta': 'resource-secret'}},
            {'type': 'resource', 'resource': {'uri': 'file:///project/chart.png',
                                            'mimeType': 'image/png', 'blob': 'BINARY-SECRET'}},
            {'type': 'resource_link', 'uri': 'https://cdn.example/chart?key=secret', 'name': 'chart',
             'title': 'Totals chart', 'description': 'Seven records', 'mimeType': 'image/png',
             'size': 1200, '_meta': {'key': 'link-secret'}}]})
        text = self.handoff(item)
        for value in ('Embedded resource', 'URI: https://docs.example/report', 'MIME type: text/plain',
                      'Report totals: 7', 'file:///project/chart.png',
                      'Resource blob: inline payload 13 characters', 'Resource link',
                      'URI: https://cdn.example/chart', 'name: chart', 'title: Totals chart',
                      'description: Seven records', 'mimeType: image/png', 'size: 1200'):
            self.assertIn(value, text)
        for value in ('secret', 'user:pass', '?', '#auth', 'BINARY-SECRET', '_meta'):
            self.assertNotIn(value, text)

    def test_dynamic_tool_uses_content_items_and_reports_false_success(self):
        item = {'id': 'dyn-1', 'type': 'dynamicToolCall', 'namespace': 'desk', 'tool': 'inspect',
                'arguments': [None, False, 2], 'status': 'failed', 'success': False, 'durationMs': 8,
                'contentItems': [{'type': 'inputText', 'text': 'Could not inspect image'},
                                 {'type': 'inputImage', 'imageUrl': 'https://user:pass@img.example/a.png?token=secret#key'},
                                 {'type': 'inputAudio', 'audioUrl': 'data:audio/wav;base64,QVVESU8='}]}
        text = self.handoff(item)
        for value in ('Item dyn-1', 'Dynamic tool: desk.inspect', 'Status: failed', 'Success: false',
                      'Duration: 8 ms', 'Could not inspect image', '[Image: https://img.example/a.png]',
                      '[Audio: audio/wav; inline payload 8 characters]'):
            self.assertIn(value, text)
        self.assertNotIn('QVVESU8=', text)
        self.assertNotIn('secret', text)
        self.assertNotIn('user:pass', text)
        item['namespace'] = None
        self.assertIn('Dynamic tool: inspect', tool_text(item))

    def test_arbitrary_mcp_content_has_explicit_safe_fallback(self):
        blocks = [None, True, 42, 'SCALAR-SECRET', ['ARRAY-SECRET'],
                  {'type': 'custom', 'data': 'CUSTOM-SECRET'}, {'type': {'secret': 'TYPE-SECRET'}},
                  {'type': 'text', 'text': {'secret': 'TEXT-SECRET'}},
                  {'type': 'resource', 'resource': False},
                  {'type': 'resource_link', 'uri': None, 'name': {'key': 'NAME-SECRET'},
                   'size': {'key': 'SIZE-SECRET'},
                   'annotations': {'audience': [{'key': 'AUDIENCE-SECRET'}],
                                   'priority': {'key': 'PRIORITY-SECRET'}}}]
        text = self.handoff(self.mcp(result={'content': blocks}))
        self.assertIn('[Unsupported content block]', text)
        self.assertIn('[Unsupported content type: custom]', text)
        self.assertIn('[Unsupported content type: unknown]', text)
        self.assertIn('[Unavailable text content]', text)
        self.assertIn('[Unavailable embedded resource]', text)
        self.assertNotIn('-SECRET', text)
        text = tool_text(self.mcp(result={'content': {'data': 'LIST-SECRET'}}))
        self.assertIn('[Unsupported content list]', text)
        self.assertNotIn('LIST-SECRET', text)
        self.assertIn('Content: no content blocks', tool_text(self.mcp(result={'content': []})))

    def test_structured_json_excludes_embedded_payloads_and_credentials(self):
        item = self.mcp(result={'content': [], 'structuredContent': {
            'image': {'type': 'image', 'mimeType': 'image/png', 'data': 'BINARY-SECRET'},
            'url': 'https://user:pass@host.example/path?auth=secret#fragment',
            'nested': [{'imageUrl': 'data:image/png;base64,SU1BR0U=', '_meta': 'PRIVATE-SECRET'}],
            'text': 'Useful structured evidence'}})
        text = tool_text(item)
        self.assertIn('Useful structured evidence', text)
        self.assertIn('https://host.example/path', text)
        self.assertIn('inline payload 13 characters', text)
        self.assertIn('image/png; inline payload 8 characters', text)
        for value in ('-SECRET', 'user:pass', '?auth=', '#fragment', 'SU1BR0U=', '_meta'):
            self.assertNotIn(value, text)

    def test_public_uri_descriptor(self):
        cases = {'https://user:pass@[::1]:999/a?secret=b#token': 'https://[::1]:999/a',
                 'file:///project/report.txt?secret=b': 'file:///project/report.txt',
                 'mcp://server/item?secret=b': 'mcp://server/item',
                 './plot.png?secret=b': './plot.png', 'https://[invalid': '[Invalid URI]'}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(public_uri(value), expected)
        self.assertEqual(public_uri(None), '[Unavailable URI]')


if __name__ == '__main__':
    unittest.main()
