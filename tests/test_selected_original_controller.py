"""Selected original reads keep the mounted task, native binding and keyboard owner."""
import json
import subprocess
import unittest

from test_navigation_controllers import APP, DOM, NODE

SETUP = DOM[:DOM.index('const DeskHistoryReader=')] + r'''
let generation=7,opening=false,nativeThreadId='native-parent',after=0;
state={profiles:[],sessions:[{id:'active',thread_id:'native-parent',cwd:'/retained/project',status:'running'}]};
const main=new Element('main');document.body.append(main);
for(const id of ['read-original','prompt','turn-mode','activity','latest-output'])main.append($(id));
const closest=Element.prototype.closest;
Element.prototype.closest=function(selector){
  if(selector==='main' || selector==='dialog'){
    for(let n=this;n;n=n.parentElement)if(n.tagName===selector.toUpperCase())return n;
    return null;
  }
  if(selector==='input, textarea, select, [contenteditable]'){
    for(let n=this;n;n=n.parentElement)if(['INPUT','TEXTAREA','SELECT'].includes(n.tagName) || n.attributes.contenteditable!==undefined)return n;
    return null;
  }
  return closest.call(this,selector);
};
const handlers=new Map();document.addEventListener=(event,handler)=>handlers.set(event,handler);
document.querySelector=selector=>selector==='dialog[open]'?[...elements.values()].find(e=>e.tagName==='DIALOG' && e.open) || null:null;
const reader=$('history-reader');reader.tagName='DIALOG';reader.append($('history-reader-find-query'));
const draft={text:'Exact unsent Plan — 保留  ',mode:'plan'},queues=[{id:'first',mode:'native',text:'Prepared Work'},{id:'second',mode:'plan',text:'Prepared Plan'}];
$('prompt').tagName='TEXTAREA';$('prompt').value=draft.text;$('turn-mode').tagName='SELECT';$('turn-mode').value=draft.mode;
const activity=$('activity'),calls=[],frames=[],items=new Map(),rendered=[];
let hold=null,eventRows=[],latestUpdates=0,statePollAt=Date.now(),latestMoves=0,closes=0,refreshes=0;
let api=async(path,data)=>{
  calls.push({path,data});
  if(path.startsWith('/api/native/thread?id=')){if(hold)await hold.promise;return {id:decodeURIComponent(path.split('=')[1]),turns:[]};}
  if(path.startsWith('/api/events?'))return eventRows;
  throw Error('Unexpected read path '+path);
};
const DeskHistoryReader={
  async show(result,callbacks){
    if(!callbacks.valid())return false;reads.push({result,callbacks});reader.open=true;$('history-reader-find-query').disabled=true;
    await api('/api/native/thread?id='+encodeURIComponent(result.thread_id));
    if(!reader.open || !callbacks.valid())return false;$('history-reader-find-query').disabled=false;return true;
  },
  close(){++closes;reader.open=false;reads.at(-1)?.callbacks.onReturn();}
};
async function refresh(){++refreshes;syncSelectedOriginal();}
function nearLatest(){return true;}function goLatest(){++latestMoves;latestUpdates=0;}function latestLabel(){}
const requestAnimationFrame=callback=>frames.push(callback);
let currentTurn=null;const requests=new Map();function approvals(){}
function renderItem(item){items.set(item.id,item);rendered.push(item);}
function makeNativeFailure(){throw Error('No native failure rendering expected');}
const DeskNativeState={card:makeNativeFailure};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=async()=>{await Promise.resolve();await Promise.resolve();};
function key(target,key='F3',extra={}){const event={key,target,prevented:false,preventDefault(){this.prevented=true;},...extra};handlers.get('keydown')(event);return event;}
function unchanged(){
  assert.strictEqual($('prompt').value,draft.text);assert.strictEqual($('turn-mode').value,draft.mode);
  assert.deepStrictEqual(queues,[{id:'first',mode:'native',text:'Prepared Work'},{id:'second',mode:'plan',text:'Prepared Plan'}]);
  assert.strictEqual($('activity'),activity);assert(calls.every(c=>c.data===undefined));
}
'''


@unittest.skipUnless(NODE, 'Node is required for selected-original controller contracts')
class SelectedOriginalControllerTests(unittest.TestCase):
    def check(self, body):
        source = APP.read_text()
        fragments = [source[source.index('let selectedOriginalReview='):source.index('function draw()')],
                     source[source.index("$('read-original').onclick="):source.index('DeskRecall.configure(')],
                     source[source.index('function consume(m)'):source.index('async function refresh()')],
                     source[source.index('async function pollActivity()'):source.index('async function tick()')]]
        code = SETUP + '\n' + '\n'.join(fragments) + '\n(async()=>{\n' + body + r'''
unchanged();process.stdout.write(JSON.stringify({passed:true}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''
        result = subprocess.run([NODE, '-e', code], text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': True})

    def test_availability_uses_retained_parent_id_not_run_task_admission(self):
        self.check(r'''
for(const status of ['running','approval','completed','failed','starting']){
  state.sessions[0].status=status;$('task').hidden=true;$('send').disabled=true;nativeThreadId=null;
  syncSelectedOriginal();assert(!$('read-original').hidden);assert(!$('read-original').disabled);
}
opening=true;syncSelectedOriginal();assert($('read-original').disabled);assert.match($('read-original').title,/binding/);
await $('read-original').onclick();assert.strictEqual(reads.length,0);
opening=false;state.sessions[0].thread_id=null;syncSelectedOriginal();assert($('read-original').disabled);assert.match($('read-original').title,/not available/);
selected=null;syncSelectedOriginal();assert($('read-original').hidden);assert.strictEqual(calls.length,0);
''')

    def test_failed_open_retained_id_reads_without_reopening_or_mutating_task(self):
        self.check(r'''
nativeThreadId=null;$('task').hidden=true;state.sessions[0].status='failed';$('read-original').focus();
await $('read-original').onclick();assert.deepStrictEqual(reads[0].result,{thread_id:'native-parent',cwd:'/retained/project'});
assert.deepStrictEqual(calls,[{path:'/api/native/thread?id=native-parent',data:undefined}]);assert.strictEqual(selected,'active');assert.strictEqual(generation,7);
assert.strictEqual(reads[0].callbacks.backLabel,'Return to selected task');assert.strictEqual(reads[0].callbacks.startAtEnd,true);DeskHistoryReader.close();
assert.strictEqual(document.activeElement,$('read-original'));assert.deepStrictEqual(document.activeElement.focusOptions,{preventScroll:true});
''')

    def test_opaque_native_id_is_encoded_without_title_or_catalog_lookup(self):
        self.check(r'''
state.sessions[0].thread_id='native ID + / quoted ]';await $('read-original').onclick();
assert.strictEqual(calls[0].path,'/api/native/thread?id='+encodeURIComponent(state.sessions[0].thread_id));assert.strictEqual(calls.length,1);
''')

    def test_child_or_prebinding_notifications_cannot_supply_a_read_binding(self):
        self.check(r'''
state.sessions[0].thread_id=null;nativeThreadId=null;
consume({method:'thread/started',params:{thread:{id:'child-native'}}});syncSelectedOriginal();assert($('read-original').disabled);
await $('read-original').onclick();assert.strictEqual(calls.length,0);assert.strictEqual(nativeThreadId,null);
state.sessions[0].thread_id='native-parent';nativeThreadId='native-parent';
consume({method:'thread/started',params:{thread:{id:'child-native'}}});consume({method:'turn/started',params:{threadId:'child-native',turn:{id:'child-turn'}}});
await $('read-original').onclick();assert.strictEqual(reads[0].result.thread_id,'native-parent');assert.strictEqual(currentTurn,null);
''')

    def test_f3_from_selected_activity_opens_existing_find_and_returns_keyboard_origin(self):
        self.check(r'''
const origin=new Element('button');$('activity').append(origin);origin.focus();const event=key(origin);assert(event.prevented);await settle();await settle();
assert.strictEqual(reads.length,1);assert.strictEqual(document.activeElement,$('history-reader-find-query'));assert.strictEqual(selected,'active');assert.strictEqual(generation,7);
DeskHistoryReader.close();assert.strictEqual(document.activeElement,origin);assert.deepStrictEqual(origin.focusOptions,{preventScroll:true});
const fromBody=key(document.body);assert(fromBody.prevented);await settle();await settle();DeskHistoryReader.close();assert.strictEqual(document.activeElement,$('read-original'));
''')

    def test_f3_leaves_inputs_aside_unrelated_dialogs_and_modifiers_alone(self):
        self.check(r'''
const editable=new Element();editable.isContentEditable=true;main.append(editable);
const aside=new Element('aside'),asideButton=new Element('button');document.body.append(aside);aside.append(asideButton);
for(const target of [$('prompt'),$('turn-mode'),editable,asideButton])assert(!key(target).prevented);
const input=new Element('input');main.append(input);assert(!key(input).prevented);
const dialog=$('profiles-dialog');dialog.tagName='DIALOG';dialog.open=true;assert(!key(document.body).prevented);dialog.open=false;
for(const extra of [{ctrlKey:true},{altKey:true},{metaKey:true},{defaultPrevented:true}])assert(!key(document.body,'F3',extra).prevented);
opening=true;assert(!key(document.body).prevented);opening=false;state.sessions[0].thread_id=null;assert(!key(document.body).prevented);assert.strictEqual(calls.length,0);
''')

    def test_repeated_activation_and_cancel_do_not_reopen_after_held_read(self):
        self.check(r'''
hold=deferred();const pending=$('read-original').onclick();await $('read-original').onclick();key(document.body);assert.strictEqual(reads.length,1);assert.strictEqual(calls.length,1);
DeskHistoryReader.close();$('prompt').focus();hold.resolve();await pending;assert(!reader.open);assert.strictEqual(document.activeElement,$('prompt'));assert.strictEqual(selectedOriginalReview,null);
''')

    def test_newer_selected_task_invalidates_held_read_without_old_focus(self):
        self.check(r'''
hold=deferred();const pending=$('read-original').onclick();const old=reads[0].callbacks;
state.sessions.push({id:'new-task',thread_id:'native-new',cwd:'/new/project'});selected='new-task';++generation;syncSelectedOriginal();$('prompt').focus();
assert(!old.valid());assert(!reader.open);old.onReturn();assert.strictEqual(document.activeElement,$('prompt'));
hold.resolve();await pending;assert.strictEqual(document.activeElement,$('prompt'));assert(!reader.open);assert.strictEqual(closes,1);
''')

    def test_same_selection_new_native_binding_invalidates_old_original(self):
        self.check(r'''
await $('read-original').onclick();const old=reads[0].callbacks;state.sessions[0].thread_id='replacement-blank';syncSelectedOriginal();$('prompt').focus();
assert(!old.valid());assert(!reader.open);old.onReturn();assert.strictEqual(document.activeElement,$('prompt'));assert.strictEqual(nativeThreadId,'native-parent');
await $('read-original').onclick();assert.strictEqual(reads[1].result.thread_id,'replacement-blank');assert.strictEqual(generation,7);
''')

    def test_live_activity_continues_without_background_latest_scroll(self):
        self.check(r'''
await $('read-original').onclick();$('history-reader-find-query').focus();eventRows=[{seq:1,event:{method:'item/agentMessage/delta',params:{threadId:'native-parent',itemId:'answer',delta:'New live result'}}}];
await pollActivity();assert.strictEqual(rendered[0].text,'New live result');assert.strictEqual(latestUpdates,1);assert.strictEqual(latestMoves,0);assert.strictEqual(frames.length,0);
assert.strictEqual(document.activeElement,$('history-reader-find-query'));assert.strictEqual(refreshes,1);assert.strictEqual(calls.filter(c=>c.path.startsWith('/api/native/thread')).length,1);
''')

    def test_late_preopen_latest_frame_cannot_scroll_behind_original(self):
        self.check(r'''
eventRows=[{seq:1,event:{method:'item/agentMessage/delta',params:{threadId:'native-parent',itemId:'answer',delta:'Live before read'}}}];await pollActivity();assert.strictEqual(frames.length,1);
await $('read-original').onclick();$('history-reader-find-query').focus();frames.shift()();assert.strictEqual(latestMoves,0);assert.strictEqual(latestUpdates,1);assert.strictEqual(document.activeElement,$('history-reader-find-query'));
''')


if __name__ == '__main__':
    unittest.main()
