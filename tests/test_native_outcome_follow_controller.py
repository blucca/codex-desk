"""Expanded native outcomes keep reading; deliberate Latest output still works."""
import json,subprocess,unittest
from pathlib import Path
APP=(Path(__file__).resolve().parents[1]/'codex_desk/static/app.js').read_text()
POLL=APP[APP.index('async function pollActivity()'):APP.index('async function tick()')]
class NativeOutcomeFollow(unittest.TestCase):
 def run_case(self,opened,hidden=False,late=False):
  script=r'''
let selected='task',opening=false,generation=1,after=0,latestUpdates=0,statePollAt=Date.now();
const document={activeElement:null},elements=new Map();
function $(id){if(!elements.has(id))elements.set(id,{hidden:true,open:false});return elements.get(id);}
const params=JSON.parse(process.argv[1]);$('native-outcome').hidden=params.hidden;$('native-outcome').open=params.open;
const DeskSteering={reading:()=>false},DeskStopTask={reading:()=>false};
const frames=[];const requestAnimationFrame=f=>frames.push(f);let followed=0;
function nearLatest(){return true;}function goLatest(){followed++;latestUpdates=0;}function latestLabel(){}
function consume(){return false;}async function refresh(){}function turnRequest(){return null;}
async function api(){return [{seq:1,event:{method:'item/agentMessage/delta',params:{threadId:'parent',turnId:'active',itemId:'reply',delta:'More native output'}}}];}
''' + POLL + r'''
(async()=>{await pollActivity();if(params.late)$('native-outcome').open=true;for(const f of frames)f();const automatic={followed,latestUpdates};goLatest();process.stdout.write(JSON.stringify({automatic,deliberate:followed}));})().catch(e=>{console.error(e);process.exitCode=1});
'''
  r=subprocess.run(['node','-e',script,json.dumps({'open':opened,'hidden':hidden,'late':late})],capture_output=True,text=True,timeout=20)
  self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
 def test_expanded_visible_preserves_reader(self):self.assertEqual(self.run_case(True),{'automatic':{'followed':0,'latestUpdates':1},'deliberate':1})
 def test_disclosure_expanded_before_animation_frame(self):self.assertEqual(self.run_case(False,late=True),{'automatic':{'followed':0,'latestUpdates':1},'deliberate':1})
 def test_closed_visible_can_follow(self):self.assertEqual(self.run_case(False)['automatic'],{'followed':1,'latestUpdates':0})
 def test_hidden_open_does_not_block(self):self.assertEqual(self.run_case(True,hidden=True)['automatic'],{'followed':1,'latestUpdates':0})
if __name__=='__main__':unittest.main()
