"""Actual Prepared DOM event binding and lifecycle presentation in Node."""
import subprocess
import unittest
from test_preparation_controller import HARNESS, NODE, ROOT

SETUP = HARNESS[:HARNESS.index('(async()=>{')]
SETUP = SETUP.replace("const ids=['preparation'", "const ids=['preparation-find-form','preparation-find-query','preparation-find-search','preparation-find','preparation-find-status','preparation-find-results','preparation-find-previous','preparation-find-next','preparation'")
SETUP = SETUP.replace("selector==='button'&&child.tagName==='BUTTON'", "child.tagName===selector.toUpperCase()")
SETUP = SETUP.replace("vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));", "vm.runInThisContext(fs.readFileSync(process.argv[2],'utf8'));\nvm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));")
SETUP = SETUP.replace("DeskPreparation.configure({api,", "let navigation='current-c:42';\nDeskPreparation.configure({navigationIdentity:()=>navigation,api:(path,data)=>api(path,data),")
SETUP += r'''
const token='12345678-1234-4234-8234-123456789abc';
world.c.archived=false;activeDraft.session='c';
world.a.draft.text='Duplicate remembered phrase';world.b.followups.entries[0].text='Duplicate remembered phrase';
world.d.followups.reservation.text='Remembered captured phrase';
world.a.turn_request={token,mode:'plan',status:'needs_review'};
const receipt=()=>({session:'a',token,request:{status:world.a.turn_request.status,payload:{session:'a',token,text:'Remembered original request',mode:'plan',revision:1,writer:'original-writer',sequence:2},
 binding:{session:'a',native_home:'/native',cwd:'/projects/a',profile:'default',thread_id:'thread-a'},
 current_binding:{session:'a',native_home:'/native',cwd:'/projects/a',profile:'default',thread_id:'thread-a'},binding_mismatch:false}});
const readers=[];
global.DeskHistoryReader={show:async(descriptor,callbacks)=>{readers.push({descriptor,callbacks});assert(callbacks.valid());return true;},close:()=>{}};
const initialApi=api;let requestGate=null,receiptGate=null;
api=async(path,data)=>{
 if(path.startsWith('/api/preparation?')){
  calls.push({path,data:null});const params=new URL(path,'http://local').searchParams;
  const result=snapshot(path);const q=params.get('q');
  if(q!==null){
   const needle=q.trim().toLowerCase();if(needle.length===1)throw Error('Use at least two characters');
   const hits=[];
   for(const row of result.sessions){
    const add=(kind,text,identity)=>{if(needle && text.toLowerCase().includes(needle))hits.push({session_id:row.id,name:row.name,cwd:row.cwd,profile:row.profile,archived:row.archived,kind,snippet:text,match_text:text,...identity});};
    add('session',row.name,{control:'review'});
    if(row.draft)add('draft',row.draft.text,{control:'draft',mode:row.draft.mode,revision:row.draft.revision});
    for(const e of row.followups.entries)add('followup',e.text,{control:'followup',followup_id:e.id,mode:e.mode,revision:e.revision,state:e.state});
    const r=row.followups.reservation;if(r)add('reservation',r.text,{control:'reservation',followup_id:r.entry_id,token:r.token,mode:r.mode,revision:r.revision,state:r.state});
    if(row.turn_request)add('turn_request',receipt().request.payload.text,{control:'turn_request',token:row.turn_request.token,mode:row.turn_request.mode,state:row.turn_request.status});
   }
   const offset=Number(params.get('offset'));result.lookup={q:q.trim(),offset,limit:30,total:hits.length,results:hits.slice(offset,offset+30),has_more:offset+30<hits.length};
  }
  if(control.overview)return control.overview(path,result);
  return result;
 }
 if(path.startsWith('/api/followups?session=')){calls.push({path,data:null});return clone(world[new URL(path,'http://local').searchParams.get('session')].followups);}
 if(path.startsWith('/api/turn/request?')){calls.push({path,data:null});assert.equal(new URL(path,'http://local').searchParams.get('session'),'a');assert.equal(new URL(path,'http://local').searchParams.get('token'),token);return receiptGate?receiptGate(clone(receipt())):clone(receipt());}
 if(path==='/api/turn/resolve'){calls.push({path,data:clone(data)});assert.equal(data.session,'a');assert.equal(data.token,token);world.a.turn_request.status=data.outcome;return clone(receipt());}
 return initialApi(path,data);
};
const query=value=>{n('find-query').value=value;n('find-query').oninput();};
const submit=()=>n('find-form').onsubmit({preventDefault(){}});
const lookupButtons=()=>n('find-results').querySelectorAll('button');
const hit=(owner,control)=>lookupButtons().find(e=>e.dataset.session===owner && e.dataset.control===control);
const queueControl=(id,key)=>all(n('followups')).find(e=>e.dataset.followup===id&&e.dataset.control===key);
const savedPanel=()=>all(n('editor')).find(e=>e.id==='preparation-saved-match');
const readOnly=()=>calls.filter(c=>c.data===null).length===calls.length;
const keepB=async()=>{
 await review('b');fill('B unsaved draft stays here','plan');
 await queueControl('b-one','queue-edit').click();const text=queueControl('b-one','queue-text');text.value='B unsaved queue stays here';text.oninput();text.focus();text.setSelectionRange(2,9,'backward');text.scrollTop=31;
};
'''

@unittest.skipUnless(NODE, 'Node required')
class PreparationFindBindingTests(unittest.TestCase):
    def check(self, body):
        script = SETUP + '\n(async()=>{await DeskPreparation.show();\n' + body + r'''
assert.equal(opened.length,0);assert.equal(activeDraft.session,'c');assert.equal(activeDraft.text,'ACTIVE UNSENT PLAN — do not alter');assert.equal(activeDraft.mode,'plan');
console.log('PASS actual Prepared lookup binding');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run([NODE, '-e', script, str(ROOT/'codex_desk/static/preparation.js'), str(ROOT/'codex_desk/static/preparation-find.js')], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_static_controls_and_dependency_order(self):
        html=(ROOT/'codex_desk/static/index.html').read_text()
        for suffix in ('form','query','search','status','results','previous','next'):
            self.assertIn('id="preparation-find-'+suffix+'"',html)
        self.assertLess(html.index('/preparation-find.js'), html.index('/preparation.js'))
        self.assertLess(html.index('/preparation.js'), html.index('/app.js'))

    def test_explicit_search_duplicate_draft_preserves_unsaved_queue_and_current_owner(self):
        self.check(r'''
await keepB();const initial=calls.length;query('Duplicate');assert.equal(calls.length,initial);
await submit();assert.deepEqual(sessions(),['a','d','b','c']);assert.equal(lookupButtons().length,2);assert.equal(n('text').value,'B unsaved draft stays here');
await hit('a','draft').click();assert.match(n('editor-title').textContent,/A decision/);assert.match(savedPanel().textContent,/Duplicate remembered phrase/);
assert(calls.slice(initial).filter(c=>c.path.startsWith('/api/preparation?')).length===2);
await review('b');assert.equal(n('text').value,'B unsaved draft stays here');const q=queueControl('b-one','queue-text');assert.equal(q.value,'B unsaved queue stays here');assert.equal(q.selectionStart,2);assert.equal(q.selectionDirection,'backward');assert.equal(q.scrollTop,31);assert(readOnly());
''')

    def test_exact_followup_and_reservation_use_existing_readonly_lifecycle(self):
        self.check(r'''
query('Duplicate');await submit();await hit('b','followup').click();assert.equal(document.activeElement.dataset.followup,'b-one');assert.equal(document.activeElement.dataset.session,'b');assert.equal(document.activeElement.dataset.control,'followup');assert(!queueControl('b-one','queue-text'));assert(readOnly());
query('captured');await submit();await hit('d','reservation').click();assert.equal(document.activeElement.dataset.token,'not-rendered');assert.equal(document.activeElement.dataset.session,'d');assert.match(document.activeElement.textContent,/Remembered captured phrase/);assert(!button(n('followups'),'Use in this session draft'));assert(readOnly());
''')

    def test_request_source_forward_return_and_exact_hit_focus(self):
        self.check(r'''
await keepB();query('original request');await submit();n('').scrollTop=127;const source=hit('a','turn_request');source.focus();await source.click();assert(n('request').open);assert.equal(n('request-captured-text').textContent,'Remembered original request');assert(!n('request-accepted').disabled);
n('request').scrollTop=94;n('request-captured-text').scrollTop=23;n('request-captured').open=false;
await n('request-read-original').click();assert.equal(readers[0].descriptor.thread_id,'thread-a');assert.equal(readers[0].descriptor.cwd,'/projects/a');assert.equal(readers[0].callbacks.backLabel,'Return to task request');
readers[0].callbacks.onReturn();assert.equal(n('request').scrollTop,94);assert.equal(n('request-captured-text').scrollTop,23);assert.equal(n('request-captured').open,false);assert.equal(document.activeElement,n('request-read-original'));
await n('request-return').click();assert.equal(n('request').open,false);assert.equal(n('').scrollTop,127);assert.equal(document.activeElement,source);
await review('b');assert.equal(n('text').value,'B unsaved draft stays here');assert.equal(queueControl('b-one','queue-text').value,'B unsaved queue stays here');assert(readOnly());
''')

    def test_cold_pending_lookup_reads_actual_needs_review_projection(self):
        self.check(r'''
await keepB();world.a.turn_request.status='pending';query('original request');await submit();
receiptGate=result=>({...result,request:{...result.request,status:'needs_review'}});
assert(await hit('a','turn_request').click());assert(n('request').open);
assert.match(n('request-captured-text').textContent,/Remembered original request/);assert(!n('request-accepted').disabled);
await n('request-return').click();await review('b');assert.equal(n('text').value,'B unsaved draft stays here');assert(readOnly());
''')

    def test_explicit_request_resolution_keeps_drafts_and_queue(self):
        self.check(r'''
const aDraft=clone(world.a.draft),queue=clone(world.b.followups);await keepB();query('original request');await submit();await hit('a','turn_request').click();await n('request-accepted').click();assert.equal(calls.filter(c=>c.data).length,1);assert.equal(calls.find(c=>c.data).path,'/api/turn/resolve');assert.deepEqual(world.a.draft,aDraft);assert.deepEqual(world.b.followups,queue);await n('request-return').click();await review('b');assert.equal(n('text').value,'B unsaved draft stays here');assert.equal(queueControl('b-one','queue-text').value,'B unsaved queue stays here');
''')

    def test_paging_is_explicit_and_keeps_unfiltered_owners(self):
        self.check(r'''
world.b.followups.entries=Array.from({length:35},(_,i)=>({id:'page-'+i,text:'Paged instruction '+i,mode:'plan',revision:1,state:'queued',order:i+1}));query('Paged');await submit();assert.equal(lookupButtons().length,30);assert(n('find-previous').disabled);assert(!n('find-next').disabled);assert.deepEqual(sessions(),['a','d','b','c']);
await n('find-next').click();assert.equal(lookupButtons().length,5);assert(n('find-next').disabled);assert(!n('find-previous').disabled);assert(calls.at(-1).path.includes('offset=30'));await n('find-previous').click();assert.equal(lookupButtons().length,30);assert(calls.at(-1).path.includes('offset=0'));assert(readOnly());
''')

    def test_held_query_scope_archive_and_closed_modal_are_inert(self):
        self.check(r'''
await keepB();let held=deferred();control.overview=(path,result)=>path.includes('q=')?held.promise:result;query('Duplicate');const old=submit();query('other');held.resolve({sessions:[]});assert.equal(await old,false);assert.equal(lookupButtons().length,0);assert.equal(n('text').value,'B unsaved draft stays here');
held=deferred();query('Duplicate');const scoped=submit();n('project').value='/projects/a';n('archived').checked=true;await n('archived').onchange();held.resolve({sessions:[]});assert.equal(await scoped,false);assert.deepEqual(sessions(),['a','d']);assert.equal(n('text').value,'B unsaved draft stays here');
held=deferred();const closed=submit();await n('close').click();n('project').value='';control.overview=null;await DeskPreparation.show();query('Duplicate');await submit();held.resolve({sessions:[]});assert.equal(await closed,false);assert.equal(lookupButtons().length,2);assert.equal(queueControl('b-one','queue-text').value,'B unsaved queue stays here');assert(readOnly());
''')

    def test_held_activation_cannot_change_newer_prepared_or_workbench_owner(self):
        self.check(r'''
query('Duplicate');await submit();let held=deferred();control.overview=(path,result)=>path.includes('q=')?result:held.promise;const activation=hit('a','draft').click();await settle();control.overview=null;await review('b');fill('Newer B editor','plan');held.resolve(snapshot('/api/preparation?archived=false'));assert.equal(await activation,false);assert.equal(n('text').value,'Newer B editor');
held=deferred();control.overview=(path,result)=>path.includes('q=')?result:held.promise;const activation2=hit('a','draft').click();await settle();navigation='current-c:43';held.resolve(snapshot('/api/preparation?archived=false'));assert.equal(await activation2,false);assert.equal(n('text').value,'Newer B editor');assert(readOnly());
''')

    def test_revised_source_or_mode_state_token_never_exposes_old_match(self):
        self.check(r'''
await keepB();query('Duplicate');await submit();world.a.draft.revision++;world.a.draft.text='Changed saved draft';assert.equal(await hit('a','draft').click(),false);assert.equal(n('text').value,'B unsaved draft stays here');assert.match(n('error').textContent,/changed/);
world.b.followups.entries[0].mode='plan';assert.equal(await hit('b','followup').click(),false);assert.equal(n('text').value,'B unsaved draft stays here');
query('captured');await submit();world.d.followups.reservation.state='pending';assert.equal(await hit('d','reservation').click(),false);world.d.followups.reservation.state='unknown';world.d.followups.reservation.token='new-token';assert.equal(await hit('d','reservation').click(),false);
query('original request');await submit();receiptGate=result=>({...result,request:{...result.request,status:'accepted'}});assert.equal(await hit('a','turn_request').click(),false);assert(n('request-accepted').disabled);assert.match(n('request-error').textContent,/match changed/);assert(readOnly());
''')
