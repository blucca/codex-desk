"""Saved native output quotes keep their own coordinates through header changes."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from codex_desk import evidence_reference as E

HOME='a'*64
QUOTE='Command\n exact café🙂\r\n quote'
OUTPUT='before🙂\n'+QUOTE+'\nafter\n'+QUOTE

def projection(item):
    return 'Command\n'+item['command']+'\nStatus: '+item['status']+'\nExit: '+str(item.get('exitCode','not reported'))+'\n'+item.get('aggregatedOutput','[No command output reported.]')

def original():
    return {'id':'A','turns':[{'id':'t','status':'inProgress','items':[{'id':'c','type':'commandExecution','command':'printf fixture','status':'inProgress','aggregatedOutput':OUTPUT}]}]}

def capture(thread,start=None,end=None):
    text=projection(thread['turns'][0]['items'][0]);start=text.rfind(QUOTE) if start is None else start;end=start+len(QUOTE) if end is None else end
    return E.capture_reference(thread,native_home=HOME,thread_id='A',turn_id='t',item_id='c',quote_start=start,quote_end=end,text_for_item=projection)

class CommandOutputReferenceTests(unittest.TestCase):
    def test_output_coordinate_roundtrip_header_completion_and_append(self):
        before=original();ref=capture(before);at=OUTPUT.rfind(QUOTE)
        self.assertEqual((ref['projection'],ref['quote_start'],ref['quote_end']),('history-reader-command-output/v1',at,at+len(QUOTE)))
        block=E.format_evidence_block(ref);self.assertEqual(E.parse_evidence_blocks('Plan B\n\n'+block)[0]['reference'],ref)
        for status,exit in [('completed',0),('failed',-12),('inProgress',None)]:
            after=copy.deepcopy(before);command=after['turns'][0]['items'][0];command['status']=status;command['exitCode']=exit;command['aggregatedOutput']+='\nnormal later output'
            resolved=E.resolve_reference(ref,HOME,after,text_for_item=projection)
            self.assertTrue(resolved['available']);self.assertEqual(resolved['quote_start'],at)
            self.assertEqual(ref['status'],'inProgress');self.assertEqual(ref['quote'],QUOTE)

    def test_changed_or_missing_exact_span_does_not_borrow_duplicate(self):
        ref=capture(original())
        for output in [OUTPUT[:OUTPUT.rfind(QUOTE)]+'X'+QUOTE[1:], 'X'+OUTPUT, OUTPUT[:OUTPUT.rfind(QUOTE)], None]:
            after=original();after['turns'][0]['items'][0]['aggregatedOutput']=output
            result=E.resolve_reference(ref,HOME,after,text_for_item=projection)
            self.assertFalse(result['available']);self.assertIn(result['status'],('quote_changed','quote_unavailable'))
        after=original();after['turns'][0]['items'].append(copy.deepcopy(after['turns'][0]['items'][0]));self.assertEqual(E.resolve_reference(ref,HOME,after,text_for_item=projection)['status'],'source_unavailable')

    def test_header_cross_header_and_legacy_spans_stay_literal(self):
        before=original();prefix=projection({**before['turns'][0]['items'][0],'aggregatedOutput':''})
        for start,end in [(0,7),(len(prefix)-2,len(prefix)+2)]:
            ref=capture(before,start,end);self.assertEqual(ref['projection'],E.PROJECTION)
        new=capture(before);legacy={**new,'projection':E.PROJECTION,'quote_start':len(prefix)+new['quote_start'],'quote_end':len(prefix)+new['quote_end']}
        self.assertTrue(E.resolve_reference(legacy,HOME,before,text_for_item=projection)['available'])
        after=copy.deepcopy(before);after['turns'][0]['items'][0].update(status='completed',exitCode=0)
        self.assertFalse(E.resolve_reference(legacy,HOME,after,text_for_item=projection)['available'])
        self.assertEqual(E.parse_evidence_blocks(E.format_evidence_block(legacy))[0]['reference'],legacy)
        with self.assertRaises(ValueError):E.format_evidence_block({**new,'source_kind':'agentMessage'})

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_shared_python_javascript_command_projection(self):
        before=original();ref=capture(before);after=copy.deepcopy(before);after['turns'][0]['items'][0].update(status='completed',exitCode=0)
        fixture={'before':before,'after':after,'reference':ref,'block':E.format_evidence_block(ref),'resolved':E.resolve_reference(ref,HOME,after,text_for_item=projection)}
        result=subprocess.run([shutil.which('node'),str(Path(__file__).with_suffix('.js'))],input=json.dumps(fixture),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
