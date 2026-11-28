'use strict';
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm'),path=require('path');
const staticRoot=path.join(__dirname,'../codex_desk/static');for(const f of ['evidence.js','evidence-preparation.js'])vm.runInThisContext(fs.readFileSync(path.join(staticRoot,f),'utf8'));
const E=DeskEvidencePreparation,D=DeskEvidence,quote='Result café🙂\r\n exact second occurrence',body='before🙂\n'+quote+'\nafter\n'+quote+'\nend',fixtures=[],home='a'.repeat(64);
for(const type of ['mcpToolCall','dynamicToolCall']){
 const item={id:'tool',type,server:'fixture',namespace:'fixture',tool:'read',status:'inProgress',arguments:{text:quote,_meta:'private'},...(type==='mcpToolCall'?{result:{content:[{type:'text',text:body}],structuredContent:{text:'structured',_meta:'private'}}}:{contentItems:[{type:'text',text:body}]})};
 const before={id:'A',turns:[{id:'t',status:'inProgress',items:[item]}]},text=E.textForItem(item),parts=D.toolParts(item),start=text.lastIndexOf(quote);
 assert.equal(parts.text,D.tool(item));assert.equal(parts.text,[parts.prefix,parts.result,parts.suffix].filter(Boolean).join('\n'));assert.equal(parts.text.slice(parts.start,parts.end),parts.result);
 const ref=E.capture(before,{native_home:home,thread_id:'A',turn_id:'t',item_id:'tool',start_utf16:start,end_utf16:start+quote.length});
 assert.equal(ref.projection,E.TOOL_RESULT_PROJECTION);assert.equal(ref.quote_start,Array.from(parts.result.slice(0,parts.result.lastIndexOf(quote))).length);
 const fresh=structuredClone(before),after=fresh.turns[0].items[0];Object.assign(after,{status:'completed',durationMs:1537,success:true,error:{message:'Retained error fact'},progress:['later progress'],arguments:{changed:'longer arguments',_meta:'private'}});fresh.turns[0].status='completed';
 const resolved=E.resolve(ref,home,fresh);assert(resolved.available);assert(resolved.state_changed);assert.equal(E.textForItem(after).slice(resolved.start_utf16,resolved.end_utf16),quote);
 assert.deepEqual(E.parse(E.format(ref))[0].reference,ref);assert(!E.format(ref).includes('private'));
 const changed=structuredClone(fresh),target=type==='mcpToolCall'?changed.turns[0].items[0].result.content[0]:changed.turns[0].items[0].contentItems[0];const at=target.text.lastIndexOf(quote);target.text=target.text.slice(0,at)+'X'+target.text.slice(at+1);assert.equal(E.resolve(ref,home,changed).status,'quote_changed');
 const missing=structuredClone(fresh);if(type==='mcpToolCall')delete missing.turns[0].items[0].result;else delete missing.turns[0].items[0].contentItems;assert.equal(E.resolve(ref,home,missing).status,'quote_unavailable');
 for(const [a,b] of [[0,8],[parts.start-2,parts.start+2],[parts.prefix.indexOf('Arguments'),parts.prefix.indexOf('Arguments')+9]])assert.equal(E.capture(before,{native_home:home,thread_id:'A',turn_id:'t',item_id:'tool',start_utf16:a,end_utf16:b}).projection,E.PROJECTION);
 assert.throws(()=>E.validate({...ref,source_kind:'agentMessage'}),/tool result/);
 const plain={...resolved};delete plain.start_utf16;delete plain.end_utf16;
 fixtures.push({before,fresh,reference:ref,block:E.format(ref),resolved:plain,before_parts:parts,fresh_parts:D.toolParts(after),start_codepoint:Array.from(text.slice(0,start)).length,end_codepoint:Array.from(text.slice(0,start+quote.length)).length});
}
// Execute actual shipped fresh result remapping against exact old/new item identities.
const reader=fs.readFileSync(path.join(staticRoot,'history_reader.js'),'utf8'),helpers=reader.slice(reader.indexOf('  function commandOutputStart('),reader.indexOf('  function saveOriginalReading('));
const root={DeskEvidencePreparation:E,DeskEvidence:D},str=x=>typeof x==='string'?x:'',textFor=E.textForItem,rowKey=r=>r?.item?JSON.stringify([r.turn.id,r.item.id]):null;
eval(helpers+`\nfor(const f of fixtures){const old=f.before.turns[0].items[0],next=f.fresh.turns[0].items[0],key=JSON.stringify(['t','tool']),start=E.resolve(f.reference,home,f.before).start_utf16,end=start+f.reference.quote.length;
 const view={items:new Map([[key,{start:start-12,character:{offset:start,top:-3}}]]),selection:{key,start,end,text:f.reference.quote,backward:true}},anchor={key,start,end};
 const mapped=mapSavedToolResult(view,anchor,[{turn:{id:'t'},item:next}],f.reference,[{turn:{id:'t'},item:old}]),at=E.resolve(f.reference,home,f.fresh).start_utf16;
 assert.equal(mapped.view.selection.start,at);assert.equal(mapped.view.selection.end,at+f.reference.quote.length);assert(mapped.view.selection.backward);assert.equal(mapped.anchor.start,at);
 assert.equal(mapped.view.items.get(key).character.offset,at);assert.equal(view.selection.start,start);
 assert.deepEqual(mapSavedToolResult(view,anchor,[],f.reference,[{turn:{id:'t'},item:old}]),{view,anchor});
}`);
console.log(JSON.stringify({passed:true,fixtures}));
