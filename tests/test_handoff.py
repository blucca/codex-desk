import unittest
from codex_desk.handoff import build_handoff

class HandoffTests(unittest.TestCase):
    def test_recent_failed_turn_outcome_survives_large_earlier_evidence(self):
        thread = {'id': 'native-id', 'cwd': '/project', 'modelProvider': 'relay',
                  'turns': [{'id': 'failed-turn', 'status': 'failed',
                             'error': {'message': 'Account usage limit reached',
                                       'codexErrorInfo': 'usageLimitExceeded',
                                       'additionalDetails': None,
                                       '_meta': 'PRIVATE-ERROR-METADATA'},
                             'items': [{'id': 'large-command', 'type': 'commandExecution',
                                        'command': 'python verify.py', 'exitCode': 0,
                                        'aggregatedOutput': 'x' * 10000}]}]}
        text = build_handoff(thread, max_chars=2000)
        self.assertLess(len(text), 2000)
        for value in ('Turn failed-turn\nStatus: failed', 'Account usage limit reached',
                      'usageLimitExceeded', 'shortened'):
            self.assertIn(value, text)
        self.assertNotIn('PRIVATE-ERROR-METADATA', text)
        self.assertNotIn('additionalDetails', text)

    def test_interrupted_turn_without_error_is_not_presented_as_completed(self):
        thread = {'id': 'native-id', 'cwd': '/project', 'modelProvider': 'relay',
                  'turns': [{'id': 'stopped-turn', 'status': 'interrupted', 'error': None,
                             'items': [{'id': 'partial', 'type': 'agentMessage',
                                        'text': 'Verification still needs to run.'}]}]}
        text = build_handoff(thread)
        self.assertIn('Verification still needs to run.', text)
        self.assertIn('Turn stopped-turn\nStatus: interrupted', text)
        self.assertNotIn('Native error:', text)

    def test_native_command_without_output_keeps_reviewable_pending_evidence(self):
        thread = {'id': 'native-id', 'cwd': '/project', 'modelProvider': 'relay',
                  'turns': [{'items': [
                      {'id': 'earlier', 'type': 'agentMessage', 'text': 'Earlier verified evidence'},
                      {'id': 'pending-command', 'type': 'commandExecution',
                       'command': 'python verify.py', 'status': 'inProgress',
                       'aggregatedOutput': None, 'exitCode': None, 'durationMs': None}]}]}
        text = build_handoff(thread)
        for value in ('Earlier verified evidence', 'python verify.py', 'Status: inProgress',
                      'Exit: not reported', '[No command output reported.]'):
            self.assertIn(value, text)
        self.assertNotIn('Exit: 0', text)
        self.assertNotIn('None', text)

    def test_quiet_completed_command_retains_reported_exit_and_empty_output(self):
        thread = {'id': 'native-id', 'cwd': '/project', 'modelProvider': 'relay',
                  'turns': [{'items': [{'id': 'quiet-command', 'type': 'commandExecution',
                                      'command': 'true', 'status': 'completed',
                                      'aggregatedOutput': '', 'exitCode': 0}]}]}
        text = build_handoff(thread)
        self.assertIn('Status: completed\nExit: 0\n', text)
        self.assertNotIn('[No command output reported.]', text)

    def test_visible_command_evidence_and_cutoff(self):
        thread={'id':'native-id','cwd':'/project','modelProvider':'relay','turns':[{'items':[
            {'id':'goal','type':'userMessage','content':[{'type':'text','text':'Check totals'}]},
            {'id':'hidden','type':'reasoning','encryptedContent':'secret-cipher','summary':['private reasoning']},
            {'id':'cmd','type':'commandExecution','command':'python check.py','exitCode':0,'aggregatedOutput':'TOTAL=42'},
            {'id':'answer','type':'agentMessage','text':'Totals pass'}]}]}
        text=build_handoff(thread)
        for value in ('native-id','/project','Check totals','python check.py','Exit: 0','TOTAL=42','Totals pass'):
            self.assertIn(value,text)
        self.assertNotIn('secret-cipher',text);self.assertNotIn('private reasoning',text)
        thread['turns'][0]['items'][-1]['text']='x'*10000
        shortened=build_handoff(thread,max_chars=2000)
        self.assertLess(len(shortened),2000);self.assertIn('shortened',shortened);self.assertIn('omitted:',shortened)

if __name__=='__main__':unittest.main()
