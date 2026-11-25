import unittest
from codex_desk.handoff import build_handoff

class HandoffTests(unittest.TestCase):
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
