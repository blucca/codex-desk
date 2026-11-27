"""Run the shipped queued-entry editor through held saves and live refreshes."""
import json
import subprocess
import unittest
from test_navigation_controllers import APP, DOM, NODE

HARNESS = DOM[:DOM.index('let state=')] + r'''
document.getElementById=$;
Element.prototype.remove=function(){
  if(this.contains(document.activeElement))document.activeElement=document.body;
  if(this.parentElement){const siblings=this.parentElement.children;siblings.splice(siblings.indexOf(this),1);}
  this.parentElement=null;this.connect(false);
};
Element.prototype.insertBefore=function(node,reference){
  assert(this.children.includes(reference));if(node.parentElement)node.remove();
  node.parentElement=this;node.connect(this.isConnected);this.children.splice(this.children.indexOf(reference),0,node);return node;
};
const clone=value=>JSON.parse(JSON.stringify(value));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const entry=(id,order,text,mode='native')=>({id,order,text,mode,revision:1,state:'queued'});
const world={a:{entries:[entry('one',1,'Original Work — exact  '),entry('two',2,'Second Plan 保留','plan'),entry('three',3,'Third Work')],reservation:null},
  b:{entries:[entry('b-one',1,'Other session Plan','plan')],reservation:null}};
let selected='a';const calls=[],control={};
async function api(path,data){
  calls.push({path,data:data===undefined?null:clone(data)});
  if(data===undefined){const id=new URL(path,'http://local').searchParams.get('session');return clone(world[id]);}
  const snapshot=world[data.session];
  if(path==='/api/followups/edit'){
    const target=snapshot.entries.find(e=>e.id===data.id);
    if(target.revision!==data.revision)throw Object.assign(Error('This follow-up changed. Review its current version.'),{status:409,current:clone(snapshot)});
    Object.assign(target,{text:data.text,mode:data.mode,revision:target.revision+1});
  }else if(path==='/api/followups/remove')snapshot.entries=snapshot.entries.filter(e=>e.id!==data.id);
  else if(path==='/api/followups/reorder')snapshot.entries=data.ids.map((id,index)=>({...snapshot.entries.find(e=>e.id===id),order:index+1}));
  else throw Error('Editor must not submit a task: '+path);
  const captured=clone(snapshot);return control.post?control.post(captured):captured;
}
const rows=()=>$('followup-list').children;
const row=id=>rows().find(n=>n.dataset.followup===id);
const byTag=(n,tag)=>n.children.find(c=>c.tagName===tag.toUpperCase());
const button=(n,label)=>n.querySelectorAll('button').find(b=>b.textContent===label);
const text=id=>byTag(row(id),'textarea'),mode=id=>byTag(row(id),'select');
function edit(id,value,choice='native'){text(id).value=value;text(id).oninput();mode(id).value=choice;mode(id).onchange();}
const posts=()=>calls.filter(c=>c.data!==null);
function caret(id){const n=text(id);n.selectionStart=4;n.selectionEnd=12;n.selectionDirection='backward';n.scrollTop=89;n.scrollLeft=3;n.focus();}
function sameReader(id,n){
  assert.strictEqual(text(id),n);assert.strictEqual(document.activeElement,n);
  assert.deepStrictEqual([n.selectionStart,n.selectionEnd,n.selectionDirection,n.scrollTop,n.scrollLeft],[4,12,'backward',89,3]);
}
'''


@unittest.skipUnless(NODE, 'Node is required for queued-entry editor controller checks')
class FollowupEditorControllerTests(unittest.TestCase):
    def check(self, body):
        script=HARNESS+'\n'+(APP.parent/'followups.js').read_text()+r'''
(async()=>{
DeskFollowups.configure({api,make,selected:()=>selected,refresh:async()=>{throw Error('Editing must not start or refresh native activity');}});
DeskFollowups.select('a');await settle();DeskFollowups.status('a',false);
button(row('one'),'Edit').onclick();
'''+body+r'''
assert(!posts().some(c=>!/\/api\/followups\/(edit|remove|reorder)$/.test(c.path)));
process.stdout.write(JSON.stringify({passed:true}));
})().catch(e=>{process.stderr.write(e.stack);process.exit(1);});
'''
        result=subprocess.run([NODE,'-e',script],text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout),{'passed':True})

    def test_other_entry_refresh_reorder_preserves_live_composition_caret_and_scroll(self):
        self.check(r'''
edit('one','Unsent local Work 保留  ');const originalRow=row('one'),reader=text('one');caret('one');
$('followup-list').scrollTop=127;$('followup-list').scrollLeft=5;
// IME DOM text may be ahead of its committed input event; a refresh must not overwrite it.
reader.value+=' composing';
world.a.entries[1].text='Other tab saved second';world.a.entries.reverse();world.a.entries.forEach((e,i)=>e.order=i+1);
await DeskFollowups.refresh();sameReader('one',reader);assert.strictEqual(row('one'),originalRow);
assert.equal(reader.value,'Unsent local Work 保留   composing');
assert.deepStrictEqual(rows().map(n=>n.dataset.followup),['three','two','one']);
assert.equal(row('one').children[0].textContent,'3. Work · prepared');
assert.equal($('followup-list').scrollTop,127);assert.equal($('followup-list').scrollLeft,5);
assert(button(row('two'),'Edit').disabled);assert.equal(posts().length,0);
''')

    def test_held_save_keeps_live_editor_and_newer_text_mode_and_revision(self):
        self.check(r'''
edit('one','Captured save Work','native');const reader=text('one');caret('one');const held=deferred();control.post=()=>held.promise;
const saving=button(row('one'),'Save changes').onclick();await settle();sameReader('one',reader);
assert(button(row('one'),'Save changes').disabled);assert(!reader.disabled);assert(button(row('two'),'Edit').disabled);
assert.deepStrictEqual(posts()[0].data,{session:'a',id:'one',text:'Captured save Work',mode:'native',revision:1});
edit('one','Newer unsent Plan — 保留  ','plan');caret('one');
held.resolve(clone(world.a));await saving;sameReader('one',reader);assert.equal(mode('one').value,'plan');
assert.equal(reader.value,'Newer unsent Plan — 保留  ');assert.equal(world.a.entries[0].text,'Captured save Work');
assert(!row('one').textContent.includes('This entry changed'));control.post=null;
await button(row('one'),'Save changes').onclick();assert.equal(posts()[1].data.revision,2);
assert.equal(world.a.entries[0].text,'Newer unsent Plan — 保留  ');assert.equal(world.a.entries[0].mode,'plan');assert(!text('one'));
''')

    def test_newer_edit_back_to_captured_words_does_not_retire_editor(self):
        self.check(r'''
edit('one','Same words','plan');const held=deferred();control.post=()=>held.promise;
const saving=button(row('one'),'Save changes').onclick();await settle();edit('one','Changed away','native');edit('one','Same words','plan');
const reader=text('one');caret('one');held.resolve(clone(world.a));await saving;sameReader('one',reader);
assert.equal(reader.value,'Same words');assert.equal(mode('one').value,'plan');assert.equal(posts().length,1);
''')

    def test_revision_conflict_keeps_local_edit_and_original_write_revision_until_cancel(self):
        self.check(r'''
edit('one','My local conflicting Plan','plan');const reader=text('one');caret('one');
world.a.entries[0]={...world.a.entries[0],text:'Other tab Work',mode:'native',revision:2};
await button(row('one'),'Save changes').onclick();sameReader('one',reader);
assert.equal(reader.value,'My local conflicting Plan');assert.equal(mode('one').value,'plan');
assert(row('one').textContent.includes('This entry changed in another tab'));assert.equal($('followup-error').hidden,false);
await button(row('one'),'Save changes').onclick();assert.equal(posts()[1].data.revision,1);
assert.equal(world.a.entries[0].text,'Other tab Work');button(row('one'),'Cancel edit').onclick();
assert(!text('one'));assert(row('one').textContent.includes('Other tab Work'));assert(!button(row('two'),'Edit').disabled);
''')

    def test_late_save_cannot_replace_or_focus_new_session_editor(self):
        self.check(r'''
edit('one','A captured','native');const held=deferred();control.post=()=>held.promise;
const saving=button(row('one'),'Save changes').onclick();await settle();edit('one','A newer unsent','plan');
selected='b';DeskFollowups.select('b');await settle();button(row('b-one'),'Edit').onclick();
edit('b-one','B retained unsent','plan');const reader=text('b-one');caret('b-one');
held.resolve(clone(world.a));await saving;sameReader('b-one',reader);assert.equal(reader.value,'B retained unsent');assert.equal(selected,'b');
selected='a';DeskFollowups.select('a');await settle();assert.equal(text('one').value,'A newer unsent');assert.equal(mode('one').value,'plan');
assert.notStrictEqual(document.activeElement,text('one'));assert.equal(posts().length,1);
''')

    def test_other_entry_removal_and_busy_updates_preserve_editor_without_stealing_main_focus(self):
        self.check(r'''
edit('one','Unsent Plan','plan');const reader=text('one');caret('one');
await button(row('two'),'Remove').onclick();sameReader('one',reader);assert(!row('two'));
$('prompt').focus();DeskFollowups.status('a',true);world.a.entries[1].text='New third';await DeskFollowups.refresh();
assert.strictEqual(document.activeElement,$('prompt'));assert.strictEqual(text('one'),reader);assert.equal(reader.value,'Unsent Plan');
''')

    def test_cancel_reopen_during_save_keeps_new_editor_identity(self):
        self.check(r'''
edit('one','Captured old editor','native');const held=deferred();control.post=()=>held.promise;
const saving=button(row('one'),'Save changes').onclick();await settle();button(row('one'),'Cancel edit').onclick();
held.resolve(clone(world.a));await settle();button(row('one'),'Edit').onclick();edit('one','New editor unsent','plan');
const reader=text('one');caret('one');await saving;sameReader('one',reader);assert.equal(reader.value,'New editor unsent');
assert(button(row('two'),'Edit').disabled);assert.equal(posts().length,1);
''')


if __name__=='__main__':
    unittest.main()
