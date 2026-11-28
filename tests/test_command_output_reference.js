'use strict';
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm'),path=require('path');
vm.runInThisContext(fs.readFileSync(path.join(__dirname,'../codex_desk/static/evidence-preparation.js'),'utf8'));
const E=DeskEvidencePreparation,x=JSON.parse(fs.readFileSync(0,'utf8')),home=x.reference.native_home;
const text=E.textForItem(x.before.turns[0].items[0]),start=text.lastIndexOf(x.reference.quote);
const reference=E.capture(x.before,{native_home:home,thread_id:'A',turn_id:'t',item_id:'c',start_utf16:start,end_utf16:start+x.reference.quote.length,expected_quote:x.reference.quote});
assert.deepEqual(reference,x.reference);assert.equal(E.format(reference),x.block);assert.deepEqual(E.parse(x.block)[0].reference,reference);
const resolved=E.resolve(reference,home,x.after),parity={...resolved};delete parity.start_utf16;delete parity.end_utf16;assert.deepEqual(parity,x.resolved);
const fresh=E.textForItem(x.after.turns[0].items[0]);assert.equal(fresh.slice(resolved.start_utf16,resolved.end_utf16),reference.quote);assert.equal(resolved.start_utf16,fresh.lastIndexOf(reference.quote));
const appended=structuredClone(x.after);appended.turns[0].items[0].aggregatedOutput+='\nlater🙂';assert(E.resolve(reference,home,appended).available);
const changed=structuredClone(x.after),item=changed.turns[0].items[0];const points=Array.from(item.aggregatedOutput);points[reference.quote_start]='X';item.aggregatedOutput=points.join('');assert.equal(E.resolve(reference,home,changed).status,'quote_changed');
assert.throws(()=>E.validate({...reference,source_kind:'agentMessage'}),/command/);
const prefix=E.textForItem({...x.before.turns[0].items[0],aggregatedOutput:''});
for(const [a,b] of [[0,7],[prefix.length-2,prefix.length+2]]){const legacy=E.capture(x.before,{native_home:home,thread_id:'A',turn_id:'t',item_id:'c',start_utf16:a,end_utf16:b});assert.equal(legacy.projection,E.PROJECTION);}
console.log(JSON.stringify({passed:true,checks:7}));
