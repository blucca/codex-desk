"""Saved native output quotes keep their own coordinates through header changes."""
import copy
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
        for status,exit in [('completed',0)]:
            after=copy.deepcopy(before);command=after['turns'][0]['items'][0];command['status']=status;command['exitCode']=exit;command['aggregatedOutput']+='\nnormal later output'
            resolved=E.resolve_reference(ref,HOME,after,text_for_item=projection)
            self.assertTrue(resolved['available']);self.assertEqual(resolved['quote_start'],at)
            self.assertEqual(ref['status'],'inProgress');self.assertEqual(ref['quote'],QUOTE)

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

if __name__=='__main__':unittest.main()
