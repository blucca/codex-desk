/* Exact reference parity and local preparation ownership; no browser or native process. */
'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const source=path.resolve(__dirname,'../codex_desk/static/evidence-preparation.js');
vm.runInThisContext(fs.readFileSync(source,'utf8'),{filename:source});
const E=DeskEvidencePreparation,clone=x=>JSON.parse(JSON.stringify(x)),checks=[];
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/evidence_reference_v1.json'),'utf8'));
const same=(a,b)=>assert.deepEqual(a,b),check=name=>checks.push(name);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=async()=>{await Promise.resolve();await Promise.resolve();};
for(const row of fixture.cases){
  const reference=E.capture(row.thread,{native_home:row.native_home,thread_id:row.reference.thread_id,
    turn_id:row.reference.turn_id,item_id:row.reference.item_id,start_utf16:row.utf16_start,
    end_utf16:row.utf16_end,expected_quote:row.quote,textFor:()=>row.item_text});
  same(reference,row.reference);assert.equal(E.format(reference),row.block,row.name);
  const parsed=E.parse(row.draft);
  same(parsed.map(x=>({reference:x.reference,start:Array.from(row.draft.slice(0,x.start)).length,
    end:Array.from(row.draft.slice(0,x.end)).length})),row.parsed);
  same(E.parse(row.block.replace(/\n/g,'\r\n'))[0].reference,row.reference);
  assert.equal(E.appendBlock('Existing Plan B 🙂',row.block),row.draft);
  const resolved=E.resolve(reference,row.native_home,row.thread,()=>row.item_text);
  const withoutUTF16={...resolved};delete withoutUTF16.start_utf16;delete withoutUTF16.end_utf16;
  same(withoutUTF16,row.resolved);
  assert.equal(resolved.start_utf16,row.utf16_start);assert.equal(resolved.end_utf16,row.utf16_end);
  check('Python/JS parity: '+row.name);
}
for(const row of fixture.invalid_cases){same(E.parse(row.text),[],row.name);check('Inert edited/example artifact: '+row.name);}
const first=fixture.cases[0],reference=clone(first.reference),thread=clone(first.thread);
const appendContexts=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/evidence_append_context.json'),'utf8'));
for(const row of appendContexts.cases){
  const block=E.format(reference),draft=row.draft.replaceAll('{{block}}',block),note=row.note;
  const prefix=draft+(draft?'\n\n':'')+(note?'Next-step note:\n'+note+'\n\n':'');
  if(!row.accepted)assert.throws(()=>E.appendBlock(draft,block,note),/Close the unfinished/,row.name);
  else{
    const combined=E.appendBlock(draft,block,note),parsed=E.parse(combined);
    assert.equal(combined,prefix+block);assert.equal(parsed.length,row.references,row.name);
    assert.equal(parsed.at(-1).start,combined.length-block.length);assert.equal(parsed.at(-1).end,combined.length);
    same(parsed.at(-1).reference,reference);
  }
  check('Combined append context parity: '+row.name);
}
assert.throws(()=>E.capture(thread,{native_home:reference.native_home,thread_id:reference.thread_id,
  turn_id:reference.turn_id,item_id:reference.item_id,start_utf16:8,end_utf16:9,textFor:()=>first.item_text}),/Unicode/);
assert.throws(()=>E.validate({...reference,quote:'\ud800',quote_end:reference.quote_start+1}),/readable/);
assert.throws(()=>E.selectionSpan('🙂'.repeat(8001),0,16002),/readable/);
assert.throws(()=>E.appendBlock('🙂'.repeat(200000),E.format(reference)),/smaller/);
assert.equal(E.resolve(reference,'b'.repeat(64),thread).status,'home_mismatch');
const wrong=clone(thread);wrong.id='not-this-source';assert.equal(E.resolve(reference,reference.native_home,wrong).status,'source_unavailable');
const repeated=clone(thread);repeated.turns[0].items.push({...repeated.turns[0].items[0]});
assert.equal(E.resolve(reference,reference.native_home,repeated).status,'source_unavailable');
const gone=clone(thread);gone.turns[0].items=[{id:'same-phrase-elsewhere',type:'agentMessage',text:first.item_text}];
assert.equal(E.resolve(reference,reference.native_home,gone).status,'source_unavailable');
assert.equal(E.resolve(reference,reference.native_home,thread,()=>first.item_text.replace(' / ',' / X')).status,'quote_changed');
assert.equal(E.resolve(reference,reference.native_home,thread,()=>first.item_text.normalize('NFD')).status,'quote_changed');
const phase=clone(thread);phase.turns[0].items[0].phase='commentary';phase.turns[0].status='interrupted';
assert(E.resolve(reference,reference.native_home,phase,()=>first.item_text).state_changed);
check('Exact quote identity/Unicode boundaries/limits; no equal-phrase substitution');

function world(extra={}){
  const b={session:'b',generation:4,revision:3,sequence:7,writer:'private-page-writer',
    text:'Retained unsent Plan B',mode:'plan',cwd:'/removed/destination-B',name:'Prepared B',busy:false,conflict:false};
  const c={...b,session:'c',generation:5,text:'Unrelated Work C',mode:'native'};
  const w={b,c,current:b,api:[],saves:[],applies:[],returned:[],read:[],errors:[],conflicts:[],...extra};
  const controller=E.createController({render:false,destination:()=>w.current,
    api:async url=>{w.api.push(url);if(url==='/api/native/home'){if(w.homeHold)await w.homeHold.promise;if(w.failHome)throw Error('Home unavailable');return {home_namespace:reference.native_home};}
      assert(url.startsWith('/api/native/evidence-source?home='+reference.native_home+'&thread='+reference.thread_id),url);
      if(w.readHold)await w.readHold.promise;if(w.failRead)throw Error('Native original unavailable');
      return {home_namespace:w.returnHome || reference.native_home,thread:clone(w.source || thread)};},
    save:async(payload,capture)=>{assert(E.sameDestination(capture,w.current));w.saves.push(clone(payload));
      const target=w.current;Object.assign(target,{text:payload.text,mode:payload.mode,sequence:payload.sequence});
      if(w.saveHold)await w.saveHold.promise;
      if(w.conflict){const error=Error('Changed in another tab');error.status=409;error.current={text:'Other tab saved',mode:'native',revision:4};throw error;}
      if(w.failSave)throw Error('Local save unavailable');return {text:payload.text,mode:payload.mode,revision:payload.revision+1};},
    apply:(receipt,capture,payload)=>{w.applies.push({receipt:clone(receipt),capture:clone(capture),payload:clone(payload)});
      if(w.current.session===capture.session && w.current.generation===capture.generation && w.current.sequence===payload.sequence && w.current.text===payload.text){w.current.revision=receipt.revision;return true;}return false;},
    onReturn:r=>w.returned.push(r),onError:e=>w.errors.push(e.message),onConflict:(capture,current)=>w.conflicts.push({capture,current}),
    showOriginal:async(target,callbacks)=>{w.read.push({target,callbacks});return true;},onReadError:e=>w.errors.push(e.message),
    textForItem:()=>w.projection || first.item_text});
  w.controller=controller;return w;
}
const loaded=()=>({thread:clone(thread),thread_id:reference.thread_id,turn_id:reference.turn_id,
  item_id:reference.item_id,start_utf16:first.utf16_start,end_utf16:first.utf16_end,expected_quote:first.quote});
(async()=>{
  {
    const w=world();assert(await w.controller.reviewLoaded(loaded()));
    w.controller.setNote('Check separately:\n~~~sh\npytest -q');
    const before=clone(w.b),reviewed=clone(w.controller.state().reference);
    assert.equal(await w.controller.append(),false);same(w.b,before);same(w.saves,[]);same(w.returned,[]);
    assert.equal(w.controller.state().status,'review');assert(!w.controller.state().pending);
    assert(w.controller.state().message.includes('Close the unfinished'));same(w.controller.state().reference,reviewed);
    w.controller.setNote('Check separately:\n~~~sh\npytest -q\n~~~');assert(await w.controller.append());
    assert.equal(w.saves.length,1);same(E.parse(w.b.text)[0].reference,reviewed);
    check('Unfinished note blocks all host writes, keeps exact reviewed quote, corrected note appends once');
  }
  {
    const w=world();w.b.text+='\n```sh\npytest -q';assert(await w.controller.reviewLoaded(loaded()));
    const before=clone(w.b);assert.equal(await w.controller.append(),false);same(w.b,before);
    same(w.saves,[]);same(w.returned,[]);assert.equal(w.controller.state().status,'review');
    w.controller.cancel();w.b.text+='\n```';w.b.sequence++;
    assert(await w.controller.reviewLoaded(loaded()));assert(await w.controller.append());
    assert.equal(w.saves.length,1);same(E.parse(w.b.text)[0].reference,reference);
    check('Unfinished destination keeps text/mode/revision/sequence; explicit close/review recovers');
  }
  {
    const w=world(),before=clone(w.b);assert(await w.controller.reviewLoaded(loaded()));
    same(w.b,before);same(w.api,['/api/native/home']);same(w.controller.state().reference,reference);
    w.controller.setNote('Inspect this proposed next step separately.');assert(await w.controller.append());
    assert.equal(w.saves.length,1);assert(w.b.text.startsWith(before.text+'\n\nNext-step note:'));
    assert(w.b.text.includes(E.format(reference)));assert.equal(w.b.mode,'plan');assert.equal(w.b.sequence,8);assert.equal(w.b.revision,4);
    assert.equal(w.applies[0].capture.sequence,7);assert.equal(w.applies[0].payload.sequence,8);
    assert.equal(w.controller.state(),null);assert.equal(w.returned[0].reason,'saved');
    assert.equal(await w.controller.append(),false);check('Explicit reviewed append once; host-reserved writer sequence/Plan mode/local receipt');
  }
  {
    const w=world();assert(await w.controller.reviewLoaded(loaded()));w.controller.cancel();
    assert.equal(w.saves.length,0);assert.equal(w.b.text,'Retained unsent Plan B');assert.equal(w.returned.length,1);
    w.b.busy=true;assert.equal(await w.controller.reviewLoaded(loaded()),false);assert.equal(w.api.length,1);
    w.b.busy=false;w.b.conflict=true;assert.equal(await w.controller.reviewLoaded(loaded()),false);assert.equal(w.api.length,1);
    check('Cancel/pending-save/conflict review leaves preparation and native source intact');
  }
  {
    const homeHold=deferred(),w=world({homeHold});const opening=w.controller.reviewLoaded(loaded());
    await settle();w.b.text+=' — newer';w.b.sequence++;homeHold.resolve();assert.equal(await opening,false);
    assert.equal(w.saves.length,0);assert(w.b.text.endsWith('newer'));
    const h=deferred(),next=world({homeHold:h}),pending=next.controller.reviewLoaded(loaded());await settle();next.controller.cancel();h.resolve();
    assert.equal(await pending,false);assert.equal(next.controller.state(),null);assert.equal(next.saves.length,0);
    check('Held source namespace newer-input/cancel ownership suppresses late review');
  }
  {
    const w=world();assert(await w.controller.reviewLoaded(loaded()));w.current=w.c;
    assert.equal(await w.controller.append(),false);assert.equal(w.saves.length,0);assert.equal(w.c.text,'Unrelated Work C');
    w.controller.invalidate();assert.equal(w.returned.length,0);check('Task switch during review cannot append/return into C');
  }
  {
    const hold=deferred(),w=world({saveHold:hold});assert(await w.controller.reviewLoaded(loaded()));
    const pending=w.controller.append();await settle();assert(w.b.text.includes(E.format(reference)));
    w.b.text+='\nNewer typed instruction';w.b.sequence++;hold.resolve();assert(await pending);
    assert(w.b.text.endsWith('Newer typed instruction'));assert(w.b.text.includes(E.format(reference)));assert.equal(w.b.sequence,9);
    assert.equal(w.applies.length,1);check('Held save/newer typing retains appended evidence and newer host edits');
  }
  {
    const hold=deferred(),w=world({saveHold:hold});assert(await w.controller.reviewLoaded(loaded()));
    const pending=w.controller.append();await settle();w.current=w.c;hold.resolve();assert(await pending);
    assert.equal(w.c.text,'Unrelated Work C');assert.equal(w.returned.length,0);check('Late accepted B save cannot mutate/restore newly selected C');
  }
  {
    const w=world({conflict:true});assert(await w.controller.reviewLoaded(loaded()));assert.equal(await w.controller.append(),false);
    assert.equal(w.conflicts.length,1);assert.equal(w.conflicts[0].capture.session,'b');
    assert.equal(w.controller.state().status,'conflict');assert.equal(await w.controller.append(),false);
    assert(w.b.text.includes(E.format(reference)));check('Another-tab 409 delegates ordinary keep/load; unsent append kept, no auto resend');
  }
  {
    const w=world({failSave:true});assert(await w.controller.reviewLoaded(loaded()));assert.equal(await w.controller.append(),false);
    assert.equal(w.controller.state().status,'failed');assert.equal(await w.controller.append(),false);assert.equal(w.saves.length,1);
    w.controller.cancel();assert(w.b.text.includes(E.format(reference)));check('Save failure leaves host unsent edit and reviewed quote; no false success/retry');
  }
  {
    const w=world();w.b.text='x'.repeat(199500);assert(await w.controller.reviewLoaded(loaded()));
    assert.equal(await w.controller.append(),false);assert.equal(w.saves.length,0);assert.equal(w.b.text.length,199500);
    w.controller.cancel();const tooLong=loaded();tooLong.start_utf16=0;tooLong.end_utf16=9000;
    assert.equal(await w.controller.reviewLoaded(tooLong),false);assert.equal(w.saves.length,0);
    check('Over-limit append/capture retains current preparation for a smaller reviewed excerpt');
  }
  {
    const w=world(),whole=loaded();delete whole.start_utf16;delete whole.end_utf16;delete whole.expected_quote;
    assert(await w.controller.reviewLoaded(whole));assert.equal(w.controller.state().reference.quote,first.item_text);w.controller.cancel();
    assert.equal(w.saves.length,0);check('Explicit item review with no selection captures readable whole item within limit');
  }
  {
    const row=fixture.cases.find(c=>c.name==='native_command'),w=world({projection:row.item_text});
    const native=clone(row.thread),item=native.turns[0].items[0];item.reason='Reported reason <literal>';item.cwd='/actual/reported';
    assert(await w.controller.reviewLoaded({thread:native,thread_id:row.reference.thread_id,turn_id:row.reference.turn_id,
      item_id:row.reference.item_id,start_utf16:row.utf16_start,end_utf16:row.utf16_end,expected_quote:row.quote}));
    const facts=w.controller.state().sourceFacts;assert(facts.includes('Command: '+item.command));assert(facts.includes('Reported exit code: '+item.exitCode));
    assert(facts.includes('Reported reason: Reported reason <literal>'));assert(facts.includes('/actual/reported'));
    assert(!Object.hasOwn(w.controller.state().reference,'sourceFacts'));w.controller.cancel();
    check('Immutable loaded command/reason/cwd/exit facts in review; canonical artifact remains exact');
  }
  {
    const w=world(),before=clone(w.b);assert(await w.controller.readReference(reference));
    same(w.b,before);assert.equal(w.saves.length,0);assert.equal(w.api.length,1);assert(!w.api.includes('/api/native/home'));
    same(w.read[0].callbacks.savedReference,reference);assert(w.read[0].callbacks.resolution.available);
    assert.equal(w.read[0].callbacks.resolution.start_utf16,first.utf16_start);assert.equal(w.read[0].callbacks.preloadedThread.id,reference.thread_id);
    assert.equal(w.read[0].target.item_id,reference.item_id);check('Saved artifact explicit GET/preloaded exact same source span; no discovery or task API');
  }
  {
    const w=world({source:{...clone(thread),turns:[{id:reference.turn_id,status:'failed',items:[]}]}});
    assert(await w.controller.readReference(reference));assert.equal(w.read[0].callbacks.resolution.status,'source_unavailable');
    same(w.read[0].callbacks.savedReference,reference);assert.equal(w.b.text,'Retained unsent Plan B');
    const foreign=world({returnHome:'b'.repeat(64)});assert.equal(await foreign.controller.readReference(reference),false);assert.equal(foreign.read.length,0);
    const failed=world({failRead:true});assert.equal(await failed.controller.readReference(reference),false);assert.equal(failed.read.length,0);assert.equal(failed.saves.length,0);
    check('Missing original/home mismatch/read failure preserve saved excerpt, never substitute or write');
  }
  {
    const hold=deferred(),w=world({readHold:hold});const pending=w.controller.readReference(reference);await settle();w.current=w.c;hold.resolve();
    assert.equal(await pending,false);assert.equal(w.read.length,0);assert.equal(w.c.text,'Unrelated Work C');
    const h=deferred(),next=world({readHold:h}),late=next.controller.readReference(reference);await settle();next.controller.invalidate();h.resolve();
    assert.equal(await late,false);assert.equal(next.read.length,0);
    check('Held referenced-original switch/close suppresses late source UI ownership');
  }
  {
    const nodes=[];
    class Node {
      constructor(tag){this.tag=tag;this.style={};this.children=[];this.events={};this.attributes={};this.open=false;nodes.push(this);}
      append(...values){this.children.push(...values);}
      setAttribute(key,value){this.attributes[key]=value;}
      addEventListener(event,fn){this.events[event]=fn;}
      showModal(){this.open=true;}
      close(){this.open=false;this.events.close?.();}
    }
    global.document={createElement:tag=>new Node(tag),body:new Node('body')};
    try{
      const w=world(),controller=E.createController({destination:()=>w.b,api:async()=>({home_namespace:reference.native_home}),
        save:async()=>{throw Error('No click admitted');},textForItem:()=>first.item_text});
      const dialog=nodes.find(n=>n.tag==='dialog');assert.equal(dialog.id,'evidence-preparation');
      assert.equal(dialog.attributes['aria-labelledby'],'evidence-preparation-title');
      assert(nodes.some(n=>n.id==='evidence-preparation-title'));
      assert(await controller.reviewLoaded(loaded()));assert(dialog.open);
      assert.equal(nodes.find(n=>n.id==='evidence-preparation-quote').textContent,first.quote);
      assert.equal(nodes.find(n=>n.id==='evidence-preparation-append').disabled,false);
      controller.cancel();assert(!dialog.open);
      check('Actual generated modal identity/ARIA/quote controls and cancel bootstrap');
    }finally{delete global.document;}
  }
  console.log(JSON.stringify({passed:true,groups:checks.length,checks,native_admissions:0,new_tables:0}));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
